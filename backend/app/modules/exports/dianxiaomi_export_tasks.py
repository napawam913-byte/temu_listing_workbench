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
EXPORT_TASK_STATUSES = (
    EXPORT_TASK_STATUS_QUEUED,
    EXPORT_TASK_STATUS_RUNNING,
    EXPORT_TASK_STATUS_COMPLETED,
    EXPORT_TASK_STATUS_FAILED,
)

_EXPORT_TASK_SLOT_LOCK = threading.Lock()
_EXPORT_TASK_POLL_SECONDS = 3


class DianxiaomiExportTaskError(ValueError):
    pass


def ensure_dianxiaomi_export_task_schema(conn) -> None:
    return


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
                records_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                resolved_mode,
                EXPORT_TASK_STATUS_QUEUED,
                len(normalized_records),
                json.dumps(record_ids, ensure_ascii=False),
                json.dumps(normalized_records, ensure_ascii=False),
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
    wait_for_export_task_slot(task_id=task_id, user_id=user_id)
    task = get_dianxiaomi_export_task(task_id=task_id, user_id=user_id)
    records = task.get("records") or []
    try:
        export_path = export_dianxiaomi_temu_template(
            records,
            export_mode=clean_text(task.get("exportMode")) or EXPORT_MODE_CURATED,
            user_id=user_id,
        )
        mark_export_task_completed(task_id=task_id, user_id=user_id, export_path=export_path)
    except Exception as exc:
        mark_export_task_failed(task_id=task_id, user_id=user_id, error_message=str(exc))
        raise


def wait_for_export_task_slot(*, task_id: str, user_id: str) -> None:
    while True:
        with _EXPORT_TASK_SLOT_LOCK:
            running_count = count_running_export_tasks_for_user(user_id=user_id, exclude_task_id=task_id)
            if running_count <= 0:
                update_export_task_status(task_id=task_id, user_id=user_id, status=EXPORT_TASK_STATUS_RUNNING)
                return
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
            SET status = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (status, utc_now_text(), task_id, user_id),
        )


def mark_export_task_completed(*, task_id: str, user_id: str, export_path: Path) -> None:
    with get_connection() as conn:
        ensure_dianxiaomi_export_task_schema(conn)
        conn.execute(
            """
            UPDATE dianxiaomi_export_tasks
            SET status = ?, file_path = ?, filename = ?, error_message = NULL,
                updated_at = ?, completed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                EXPORT_TASK_STATUS_COMPLETED,
                str(export_path),
                export_path.name,
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
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (EXPORT_TASK_STATUS_FAILED, error_message[:2000], utc_now_text(), task_id, user_id),
        )


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
