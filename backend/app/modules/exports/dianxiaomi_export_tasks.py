from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.database import clean_text, utc_now_text
from app.modules.exports.dianxiaomi_temu import (
    EXPORT_MODE_CURATED,
    DianxiaomiExportError,
    export_dianxiaomi_temu_template,
    normalize_export_mode,
)
from app.modules.exports.postgres_store import get_export_connection as get_connection

EXPORT_TASK_STATUS_QUEUED = "queued"
EXPORT_TASK_STATUS_RUNNING = "running"
EXPORT_TASK_STATUS_COMPLETED = "completed"
EXPORT_TASK_STATUS_FAILED = "failed"
EXPORT_TASK_STATUS_CANCELLED = "cancelled"
EXPORT_TASK_STATUSES = (
    EXPORT_TASK_STATUS_QUEUED,
    EXPORT_TASK_STATUS_RUNNING,
    EXPORT_TASK_STATUS_COMPLETED,
    EXPORT_TASK_STATUS_FAILED,
    EXPORT_TASK_STATUS_CANCELLED,
)

_EXPORT_TASK_SLOT_LOCK = threading.Lock()
_EXPORT_TASK_POLL_SECONDS = 3
_EXPORT_TASK_PROGRESS_COLUMNS = {
    "progress_percent": "INTEGER NOT NULL DEFAULT 0",
    "processed_count": "INTEGER NOT NULL DEFAULT 0",
    "total_count": "INTEGER NOT NULL DEFAULT 0",
    "current_stage": "TEXT NOT NULL DEFAULT ''",
    "current_record_title": "TEXT NOT NULL DEFAULT ''",
}


class DianxiaomiExportTaskError(ValueError):
    pass


def ensure_dianxiaomi_export_task_schema(conn) -> None:
    existing_columns = {
        row["column_name"]
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = ?
            """,
            ("dianxiaomi_export_tasks",),
        ).fetchall()
    }
    for column_name, column_ddl in _EXPORT_TASK_PROGRESS_COLUMNS.items():
        if column_name in existing_columns:
            continue
        conn.execute(f"ALTER TABLE dianxiaomi_export_tasks ADD COLUMN {column_name} {column_ddl}")


def create_dianxiaomi_export_task(
    records: list[dict[str, Any]],
    *,
    export_mode: str = EXPORT_MODE_CURATED,
    user_id: str,
) -> dict[str, Any]:
    normalized_records = [record for record in records if isinstance(record, dict) and record.get("skuEntries")]
    if not normalized_records:
        raise DianxiaomiExportTaskError("No exportable SKU link records")

    resolved_mode = normalize_export_mode(export_mode)
    task_id = f"dxm_export_{uuid.uuid4().hex}"
    now = utc_now_text()
    record_ids = [clean_text(record.get("id")) or clean_text(record.get("productId")) for record in normalized_records]
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            """
            INSERT INTO dianxiaomi_export_tasks (
                id, user_id, export_mode, status, record_count, record_ids_json,
                records_json, progress_percent, processed_count, total_count,
                current_stage, current_record_title, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                resolved_mode,
                EXPORT_TASK_STATUS_QUEUED,
                len(normalized_records),
                json.dumps(record_ids, ensure_ascii=False),
                json.dumps(normalized_records, ensure_ascii=False),
                0,
                0,
                len(normalized_records),
                "排队中",
                "",
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM dianxiaomi_export_tasks WHERE id = ?", (task_id,)).fetchone()
    return export_task_row_to_api(row)


def list_dianxiaomi_export_tasks(*, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM dianxiaomi_export_tasks
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, max(1, min(int(limit or 50), 200))),
        ).fetchall()
    return [export_task_row_to_api(row) for row in rows]


def get_dianxiaomi_export_task(*, task_id: str, user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        row = conn.execute(
            "SELECT * FROM dianxiaomi_export_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
    if row is None:
        raise DianxiaomiExportTaskError("export task not found")
    return export_task_row_to_api(row)


def run_dianxiaomi_export_task(*, task_id: str, user_id: str) -> None:
    if not wait_for_export_task_slot(task_id=task_id, user_id=user_id):
        return
    task = get_dianxiaomi_export_task(task_id=task_id, user_id=user_id)
    if task.get("status") == EXPORT_TASK_STATUS_CANCELLED:
        return
    records = task.get("records") or []

    def update_progress(event: dict[str, Any]) -> None:
        if is_export_task_cancelled_or_deleted(task_id=task_id, user_id=user_id):
            raise DianxiaomiExportError("Export task was cancelled")
        update_export_task_progress(
            task_id=task_id,
            user_id=user_id,
            progress_percent=event.get("progressPercent"),
            processed_count=event.get("processedCount"),
            total_count=event.get("totalCount"),
            current_stage=event.get("currentStage"),
            current_record_title=event.get("currentRecordTitle"),
        )

    try:
        failed_records: list[dict[str, Any]] = []
        update_export_task_progress(
            task_id=task_id,
            user_id=user_id,
            progress_percent=5,
            processed_count=0,
            total_count=len(records),
            current_stage="正在准备导出",
            current_record_title="",
        )
        export_path = export_dianxiaomi_temu_template(
            records,
            export_mode=clean_text(task.get("exportMode")) or EXPORT_MODE_CURATED,
            user_id=user_id,
            progress_callback=update_progress,
            skip_failed_records=True,
            failed_records=failed_records,
        )
        if is_export_task_cancelled_or_deleted(task_id=task_id, user_id=user_id):
            return
        mark_export_task_completed(
            task_id=task_id,
            user_id=user_id,
            export_path=export_path,
            warning_message=format_skipped_export_records_message(failed_records),
        )
    except Exception as exc:
        if is_export_task_cancelled_or_deleted(task_id=task_id, user_id=user_id):
            return
        mark_export_task_failed(task_id=task_id, user_id=user_id, error_message=str(exc))
        raise


def wait_for_export_task_slot(*, task_id: str, user_id: str) -> bool:
    while True:
        if is_export_task_cancelled_or_deleted(task_id=task_id, user_id=user_id):
            return False
        with _EXPORT_TASK_SLOT_LOCK:
            running_count = count_running_export_tasks_for_user(user_id=user_id, exclude_task_id=task_id)
            if running_count <= 0:
                update_export_task_status(task_id=task_id, user_id=user_id, status=EXPORT_TASK_STATUS_RUNNING)
                return True
        update_export_task_status(task_id=task_id, user_id=user_id, status=EXPORT_TASK_STATUS_QUEUED)
        time.sleep(_EXPORT_TASK_POLL_SECONDS)


def count_running_export_tasks_for_user(*, user_id: str, exclude_task_id: str | None = None) -> int:
    params: list[Any] = [user_id, EXPORT_TASK_STATUS_RUNNING]
    where = "user_id = ? AND status = ?"
    if exclude_task_id:
        where += " AND id != ?"
        params.append(exclude_task_id)
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        row = conn.execute(f"SELECT COUNT(*) FROM dianxiaomi_export_tasks WHERE {where}", params).fetchone()
    return int(row[0] or 0)


def update_export_task_status(*, task_id: str, user_id: str, status: str) -> None:
    if status not in EXPORT_TASK_STATUSES:
        raise DianxiaomiExportTaskError(f"unsupported export task status: {status}")
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            """
            UPDATE dianxiaomi_export_tasks
            SET status = ?,
                current_stage = CASE WHEN ? = ? THEN ? ELSE current_stage END,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                status,
                status,
                EXPORT_TASK_STATUS_QUEUED,
                "排队中",
                utc_now_text(),
                task_id,
                user_id,
            ),
        )


def update_export_task_progress(
    *,
    task_id: str,
    user_id: str,
    progress_percent: Any = None,
    processed_count: Any = None,
    total_count: Any = None,
    current_stage: Any = None,
    current_record_title: Any = None,
) -> None:
    assignments = ["updated_at = ?"]
    params: list[Any] = [utc_now_text()]
    if progress_percent is not None:
        assignments.append("progress_percent = ?")
        params.append(max(0, min(100, int(progress_percent or 0))))
    if processed_count is not None:
        assignments.append("processed_count = ?")
        params.append(max(0, int(processed_count or 0)))
    if total_count is not None:
        assignments.append("total_count = ?")
        params.append(max(0, int(total_count or 0)))
    if current_stage is not None:
        assignments.append("current_stage = ?")
        params.append(clean_text(current_stage))
    if current_record_title is not None:
        assignments.append("current_record_title = ?")
        params.append(clean_text(current_record_title)[:500])
    params.extend([task_id, user_id])
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            f"""
            UPDATE dianxiaomi_export_tasks
            SET {", ".join(assignments)}
            WHERE id = ? AND user_id = ?
            """,
            params,
        )


def mark_export_task_completed(
    *,
    task_id: str,
    user_id: str,
    export_path: Path,
    warning_message: str | None = None,
) -> None:
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            """
            UPDATE dianxiaomi_export_tasks
            SET status = ?, file_path = ?, filename = ?, error_message = ?,
                progress_percent = 100, processed_count = total_count,
                current_stage = ?, current_record_title = '',
                updated_at = ?, completed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                EXPORT_TASK_STATUS_COMPLETED,
                str(export_path),
                export_path.name,
                clean_text(warning_message)[:2000] or None,
                "已完成",
                utc_now_text(),
                utc_now_text(),
                task_id,
                user_id,
            ),
        )


def mark_export_task_failed(*, task_id: str, user_id: str, error_message: str) -> None:
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            """
            UPDATE dianxiaomi_export_tasks
            SET status = ?, error_message = ?, current_stage = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (EXPORT_TASK_STATUS_FAILED, error_message[:2000], "执行失败", utc_now_text(), task_id, user_id),
        )


def format_skipped_export_records_message(failed_records: list[dict[str, Any]]) -> str | None:
    if not failed_records:
        return None
    samples = []
    for item in failed_records[:3]:
        index = item.get("index")
        title = clean_text(item.get("title")) or "record"
        error = clean_text(item.get("error"))
        samples.append(f"#{index} {title}: {error}" if index else f"{title}: {error}")
    suffix = "" if len(failed_records) <= len(samples) else f"; and {len(failed_records) - len(samples)} more"
    return f"Skipped {len(failed_records)} failed export record(s): {'; '.join(samples)}{suffix}"


def cancel_dianxiaomi_export_task(*, task_id: str, user_id: str) -> dict[str, Any]:
    task = get_dianxiaomi_export_task(task_id=task_id, user_id=user_id)
    if task.get("status") in {EXPORT_TASK_STATUS_COMPLETED, EXPORT_TASK_STATUS_FAILED, EXPORT_TASK_STATUS_CANCELLED}:
        return task

    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            """
            UPDATE dianxiaomi_export_tasks
            SET status = ?, error_message = ?, current_stage = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                EXPORT_TASK_STATUS_CANCELLED,
                "Export task was cancelled by user",
                "已停止",
                utc_now_text(),
                task_id,
                user_id,
            ),
        )
    return get_dianxiaomi_export_task(task_id=task_id, user_id=user_id)


def delete_dianxiaomi_export_task(*, task_id: str, user_id: str) -> None:
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        cursor = conn.execute(
            "DELETE FROM dianxiaomi_export_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        )
    if cursor.rowcount <= 0:
        raise DianxiaomiExportTaskError("export task not found")


def is_export_task_cancelled_or_deleted(*, task_id: str, user_id: str) -> bool:
    try:
        task = get_dianxiaomi_export_task(task_id=task_id, user_id=user_id)
    except DianxiaomiExportTaskError:
        return True
    return task.get("status") == EXPORT_TASK_STATUS_CANCELLED


def get_completed_export_task_path(*, task_id: str, user_id: str) -> Path:
    task = get_dianxiaomi_export_task(task_id=task_id, user_id=user_id)
    if task.get("status") != EXPORT_TASK_STATUS_COMPLETED:
        raise DianxiaomiExportTaskError("export task is not completed")
    file_path = Path(clean_text(task.get("filePath")))
    if not file_path.exists() or not file_path.is_file():
        raise DianxiaomiExportTaskError("export file is missing")
    return file_path


def export_task_row_to_api(row) -> dict[str, Any]:
    if row is None:
        raise DianxiaomiExportTaskError("export task not found")
    records = parse_json_list(row["records_json"])
    record_ids = parse_json_list(row["record_ids_json"])
    file_path = clean_text(row["file_path"])
    filename = clean_text(row["filename"])
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "exportMode": row["export_mode"],
        "status": row["status"],
        "recordCount": int(row["record_count"] or 0),
        "progressPercent": int(row.get("progress_percent") or 0),
        "processedCount": int(row.get("processed_count") or 0),
        "totalCount": int(row.get("total_count") or row["record_count"] or 0),
        "currentStage": clean_text(row.get("current_stage")) or None,
        "currentRecordTitle": clean_text(row.get("current_record_title")) or None,
        "recordIds": record_ids,
        "records": records,
        "filePath": file_path or None,
        "filename": filename or None,
        "downloadUrl": f"/api/exports/dianxiaomi/temu-semi-managed/tasks/{row['id']}/download"
        if row["status"] == EXPORT_TASK_STATUS_COMPLETED and filename
        else None,
        "errorMessage": clean_text(row["error_message"]) or None,
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "completedAt": row["completed_at"],
    }


def parse_json_list(raw_value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(raw_value or "[]"))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
