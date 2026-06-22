from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.config import STORAGE_DIR
from app.core.database import (
    clean_text,
    utc_now_text,
)
from app.modules.admin_config.postgres_store import assert_user_api_usage_allowed, record_api_usage_safe
from app.modules.exports.postgres_store import get_export_connection as get_connection
from app.modules.image_storage.aliyun_oss import ImageStorageError, read_image_ref, upload_image_bytes
from app.modules.link_records.postgres_store import list_link_list_records, upsert_link_list_record
from app.modules.shared_concurrency import running_runtime_slot_count
from app.modules.visual_generation.clients import (
    VisualGenerationError,
    build_api_url,
    bounded_image_request_timeout,
    classify_ai_error,
    get_ai_stage_settings,
    image_gateway_max_attempt_timeout_seconds,
    get_runtime_setting,
    is_rate_limit_error,
    is_request_too_large_error,
    request_generated_image,
    should_switch_ai_candidate,
)
from app.modules.ai_gateway import scheduler as ai_gateway_scheduler
from app.modules.visual_generation.queue import get_visual_progress, set_visual_progress
from app.modules.visual_generation.planner import (
    build_compact_mother_prompt_from_plan,
    build_mother_prompt_from_plan,
    compact_json_value,
    request_product_analysis,
    request_prompt_plan,
)
from app.modules.visual_generation.splitter import GridSplitError, split_grid_file


VISUAL_STORAGE_DIR = STORAGE_DIR / "visual_generation"
TASK_STATUS_DRAFT = "draft"
TASK_STATUS_QUEUED = "queued"
TASK_STATUS_PLANNED = "planned"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_RETRY_WAITING = "retry_waiting"
_visual_generation_schema_ready = False
_visual_generation_schema_lock = Lock()
TASK_STATUS_SPLIT = "split"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"
ACTIVE_VISUAL_TASK_STATUSES = (TASK_STATUS_QUEUED, TASK_STATUS_RUNNING, TASK_STATUS_RETRY_WAITING)
RUNNING_VISUAL_TASK_STATUSES = (TASK_STATUS_RUNNING,)

BOOL_TRUE_VALUES = {"1", "true", "yes", "on"}
IMAGE_PAYLOAD_RETRY_PROFILES = [
    {"max_side": None, "quality": 86, "label": "original"},
    {"max_side": 1280, "quality": 82, "label": "compressed-1280"},
    {"max_side": 960, "quality": 78, "label": "compressed-960"},
    {"max_side": 768, "quality": 74, "label": "compressed-768"},
]
IMAGE_RATE_LIMIT_RETRY_DELAYS_SECONDS = (0, 8, 16, 30)
CHUFAN_AI_HOST_MARKER = "aicoming.top"
CHUFAN_AI_DEFAULT_IMAGE_MODEL = "gpt-image-2-1k"
VISUAL_PROMPT_LOGIC_VERSION = "analysis-generates-final-title-image-material-100-2026-06-18"


class VisualTaskError(ValueError):
    pass


class VisualTaskNonRetryableError(VisualTaskError):
    pass


class VisualTaskCancelled(VisualTaskError):
    pass


def visual_prompt_logic_version_from_task(task: dict[str, Any]) -> str:
    analysis = task.get("analysis") if isinstance(task.get("analysis"), dict) else {}
    return clean_text(analysis.get("visualPromptLogicVersion") or analysis.get("promptLogicVersion"))


def visual_task_has_persisted_generation(task: dict[str, Any]) -> bool:
    if clean_text(task.get("promptText")):
        return True
    if clean_text(task.get("motherImagePath")) or clean_text(task.get("motherImageUrl")):
        return True
    manifest = task.get("manifest") if isinstance(task.get("manifest"), dict) else {}
    if isinstance(manifest.get("panels"), list) and manifest.get("panels"):
        return True
    modules = task.get("modules") if isinstance(task.get("modules"), list) else []
    return any(
        clean_text(module.get("prompt"))
        or clean_text(module.get("outputPath"))
        or clean_text(module.get("outputUrl"))
        for module in modules
    )


def visual_task_prompt_is_stale(task: dict[str, Any]) -> bool:
    if not visual_task_has_persisted_generation(task):
        return False
    return visual_prompt_logic_version_from_task(task) != VISUAL_PROMPT_LOGIC_VERSION


def is_chufan_ai_image_target(settings: dict[str, str], model: str) -> bool:
    channel_id = clean_text(settings.get("channel_id")).lower()
    base_url = clean_text(settings.get("base_url")).lower()
    model_name = clean_text(model).lower()
    return (channel_id == "chufan_ai" or CHUFAN_AI_HOST_MARKER in base_url) and model_name.startswith("gpt-image-2")


def normalize_image_model_for_channel(settings: dict[str, str], model: str) -> str:
    clean_model = clean_text(model)
    if is_chufan_ai_image_target(settings, clean_model) and clean_model == "gpt-image-2":
        return CHUFAN_AI_DEFAULT_IMAGE_MODEL
    return clean_model


def record_visual_api_usage(
    settings: dict[str, str],
    *,
    user_id: str,
    stage: str,
    api_type: str,
    model: str,
    status: str,
    error_message: str | None = None,
    task_id: str | None = None,
) -> None:
    record_api_usage_safe(
        provider="openai-compatible",
        api_type=api_type,
        stage=stage,
        model=model,
        user_id=user_id,
        channel_id=settings.get("channel_id"),
        credential_id=settings.get("credential_id"),
        credential_name=settings.get("credential_name"),
        status=status,
        related_id=task_id,
        error_message=error_message,
    )


def visual_setting(key: str, default: str) -> str:
    value = get_runtime_setting(key, default).strip()
    return value or default


def visual_bool_setting(key: str, default: bool) -> bool:
    default_text = "1" if default else "0"
    return visual_setting(key, default_text).lower() in BOOL_TRUE_VALUES


def visual_int_setting(key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(float(visual_setting(key, str(default))))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def visual_float_setting(key: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(visual_setting(key, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def assert_visual_concurrency_available(user_id: str, *, exclude_task_id: str | None = None) -> None:
    user_limit = visual_int_setting("VISUAL_USER_CONCURRENCY_LIMIT", 5, minimum=0, maximum=100)
    if user_limit <= 0:
        return

    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        user_count = count_running_visual_tasks_for_user(conn, user_id, exclude_task_id=exclude_task_id)
    user_count += running_runtime_slot_count(user_id)

    if user_limit > 0 and user_count >= user_limit:
        raise VisualTaskError(f"当前成员已有 {user_count} 个生图任务正在运行，成员并发上限为 {user_limit}")


def count_visual_tasks_for_user(
    conn,
    user_id: str,
    statuses: tuple[str, ...],
    *,
    exclude_task_id: str | None = None,
) -> int:
    if not statuses:
        return 0
    params: list[Any] = [user_id, *statuses]
    placeholders = ", ".join("?" for _ in statuses)
    where = f"user_id = ? AND status IN ({placeholders})"
    if exclude_task_id:
        where += " AND id != ?"
        params.append(exclude_task_id)
    return int(conn.execute(f"SELECT COUNT(*) FROM visual_generation_tasks WHERE {where}", params).fetchone()[0] or 0)


def count_active_visual_tasks_for_user(conn, user_id: str, *, exclude_task_id: str | None = None) -> int:
    return count_visual_tasks_for_user(
        conn,
        user_id,
        ACTIVE_VISUAL_TASK_STATUSES,
        exclude_task_id=exclude_task_id,
    )


def count_running_visual_tasks_for_user(conn, user_id: str, *, exclude_task_id: str | None = None) -> int:
    return count_visual_tasks_for_user(
        conn,
        user_id,
        RUNNING_VISUAL_TASK_STATUSES,
        exclude_task_id=exclude_task_id,
    )


def count_running_visual_tasks_global() -> int:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        placeholders = ", ".join("?" for _ in RUNNING_VISUAL_TASK_STATUSES)
        return int(
            conn.execute(
                f"SELECT COUNT(*) FROM visual_generation_tasks WHERE status IN ({placeholders})",
                RUNNING_VISUAL_TASK_STATUSES,
            ).fetchone()[0]
            or 0
        )


def get_visual_task_status_summary(*, user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM visual_generation_tasks
            WHERE user_id = ?
            GROUP BY status
            """,
            (user_id,),
        ).fetchall()
        counts = {clean_text(row["status"]) or TASK_STATUS_DRAFT: int(row["count"] or 0) for row in rows}
        active_count = sum(counts.get(status, 0) for status in ACTIVE_VISUAL_TASK_STATUSES)
        running_count = counts.get(TASK_STATUS_RUNNING, 0)
        queued_count = counts.get(TASK_STATUS_QUEUED, 0)
    user_limit = visual_int_setting("VISUAL_USER_CONCURRENCY_LIMIT", 5, minimum=0, maximum=100)
    return {
        "counts": counts,
        "activeCount": active_count,
        "runningCount": running_count,
        "queuedCount": queued_count,
        "userConcurrencyLimit": user_limit,
    }


def ensure_visual_generation_schema(conn) -> None:
    global _visual_generation_schema_ready
    if _visual_generation_schema_ready:
        return
    with _visual_generation_schema_lock:
        if _visual_generation_schema_ready:
            return
        ensure_visual_generation_schema_on_connection(conn)
        _visual_generation_schema_ready = True


def ensure_visual_generation_schema_on_connection(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS visual_generation_tasks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            link_record_id TEXT,
            product_id TEXT,
            mode TEXT NOT NULL DEFAULT 'main-gallery',
            layout TEXT NOT NULL DEFAULT '3x3',
            requested_count INTEGER NOT NULL DEFAULT 9,
            status TEXT NOT NULL DEFAULT 'draft',
            source_image_ref TEXT,
            record_json TEXT NOT NULL DEFAULT '{}',
            analysis_json TEXT NOT NULL DEFAULT '{}',
            prompt_text TEXT NOT NULL DEFAULT '',
            mother_image_path TEXT,
            mother_image_url TEXT,
            manifest_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_visual_tasks_user_status
            ON visual_generation_tasks(user_id, status, created_at);
        CREATE INDEX IF NOT EXISTS idx_visual_tasks_link_record
            ON visual_generation_tasks(user_id, link_record_id, created_at);

        CREATE TABLE IF NOT EXISTS visual_generation_modules (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            panel_index INTEGER NOT NULL,
            position TEXT,
            slot_type TEXT,
            title TEXT,
            purpose TEXT,
            prompt TEXT NOT NULL DEFAULT '',
            output_path TEXT,
            output_url TEXT,
            target_slot_id TEXT,
            target_sku_entry_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, panel_index),
            FOREIGN KEY(task_id) REFERENCES visual_generation_tasks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_visual_modules_task
            ON visual_generation_modules(task_id, panel_index);
        DELETE FROM visual_generation_modules
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY task_id, panel_index
                        ORDER BY updated_at DESC, created_at DESC, id DESC
                    ) AS duplicate_rank
                FROM visual_generation_modules
            ) ranked_modules
            WHERE duplicate_rank > 1
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_visual_modules_task_panel_unique
            ON visual_generation_modules(task_id, panel_index);
        """
    )


def create_visual_task(
    *,
    user_id: str,
    record: dict[str, Any] | None = None,
    link_record_id: str | None = None,
    product_id: str | None = None,
    run_batch_id: str | None = None,
    mode: str | None = None,
    layout: str | None = None,
    requested_count: int | None = None,
    source_image_ref: str | None = None,
    reference_image_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record = dict(record or {})
    now = utc_now_text()
    task_id = f"visual_{uuid.uuid4().hex}"
    reference_refs = normalize_reference_image_refs(reference_image_refs or record.get("visualReferenceImages"))
    clean_link_record_id = clean_text(link_record_id) or clean_text(record.get("id"))
    clean_product_id = clean_text(product_id) or clean_text(record.get("productId"))
    clean_run_batch_id = clean_text(run_batch_id) or clean_text((record.get("visualQueueMeta") or {}).get("runBatchId") if isinstance(record.get("visualQueueMeta"), dict) else "")
    if clean_run_batch_id:
        queue_meta = record.get("visualQueueMeta") if isinstance(record.get("visualQueueMeta"), dict) else {}
        record["visualQueueMeta"] = {**queue_meta, "runBatchId": clean_run_batch_id}
    clean_source_image_ref = clean_text(source_image_ref) or (reference_refs[0]["url"] if reference_refs else "") or pick_record_image(record)
    if reference_refs:
        record["visualReferenceImages"] = reference_refs
        record["visualReferenceImageCount"] = len(reference_refs)
    resolved_mode = clean_text(mode) or visual_setting("VISUAL_DEFAULT_MODE", "main-gallery")
    resolved_layout = clean_text(layout) or visual_setting("VISUAL_DEFAULT_LAYOUT", "3x3")
    resolved_count = requested_count or visual_int_setting("VISUAL_DEFAULT_REQUESTED_COUNT", 9, minimum=1, maximum=9)
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            INSERT INTO visual_generation_tasks (
                id, user_id, link_record_id, product_id, mode, layout, requested_count,
                status, source_image_ref, record_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                clean_link_record_id,
                clean_product_id,
                resolved_mode,
                resolved_layout,
                max(1, min(int(resolved_count or 1), 9)),
                TASK_STATUS_DRAFT,
                clean_source_image_ref,
                json.dumps(record, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM visual_generation_tasks WHERE id = ?", (task_id,)).fetchone()
    return task_row_to_api(row, modules=[])


def list_visual_tasks(*, user_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        params: list[Any] = [user_id]
        where = ["user_id = ?"]
        if status:
            where.append("status = ?")
            params.append(status)
        params.append(max(1, min(int(limit or 100), 500)))
        rows = conn.execute(
            f"""
            SELECT *
            FROM visual_generation_tasks
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        task_ids = [row["id"] for row in rows]
        modules_by_task = fetch_modules_by_task_ids(conn, task_ids)
    return [task_row_to_api(row, modules=modules_by_task.get(row["id"], [])) for row in rows]


def get_visual_task(*, task_id: str, user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        row = conn.execute(
            "SELECT * FROM visual_generation_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise VisualTaskError("visual task not found")
        modules = fetch_modules(conn, task_id)
    return task_row_to_api(row, modules=modules)


def update_visual_task_run_batch_id(*, task_id: str, user_id: str, run_batch_id: str | None) -> None:
    clean_run_batch_id = clean_text(run_batch_id)
    if not clean_run_batch_id:
        return
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        row = conn.execute(
            "SELECT record_json FROM visual_generation_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise VisualTaskError("visual task not found")
        record = parse_json(row["record_json"], {})
        queue_meta = record.get("visualQueueMeta") if isinstance(record.get("visualQueueMeta"), dict) else {}
        if clean_text(queue_meta.get("runBatchId")) == clean_run_batch_id:
            return
        record["visualQueueMeta"] = {**queue_meta, "runBatchId": clean_run_batch_id}
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET record_json = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (json.dumps(record, ensure_ascii=False), utc_now_text(), task_id, user_id),
        )


def assert_visual_task_not_cancelled(task_id: str, user_id: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        row = conn.execute(
            "SELECT status FROM visual_generation_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
    if row is None:
        raise VisualTaskCancelled("visual task was removed")
    if clean_text(row["status"]) == TASK_STATUS_CANCELLED:
        raise VisualTaskCancelled("visual task was cancelled")


def delete_visual_task(*, task_id: str, user_id: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            DELETE FROM visual_generation_modules
            WHERE task_id = ?
              AND EXISTS (
                  SELECT 1
                  FROM visual_generation_tasks
                  WHERE id = ? AND user_id = ?
              )
            """,
            (task_id, task_id, user_id),
        )
        result = conn.execute("DELETE FROM visual_generation_tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        if result.rowcount <= 0:
            raise VisualTaskError("visual task not found")


def delete_visual_tasks(*, task_ids: list[str], user_id: str) -> dict[str, Any]:
    clean_ids = []
    seen_ids = set()
    for task_id in task_ids:
        clean_id = clean_text(task_id)
        if clean_id and clean_id not in seen_ids:
            clean_ids.append(clean_id)
            seen_ids.add(clean_id)
    if not clean_ids:
        return {"deletedCount": 0, "missingIds": []}
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        placeholders = ", ".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"SELECT id FROM visual_generation_tasks WHERE user_id = ? AND id IN ({placeholders})",
            (user_id, *clean_ids),
        ).fetchall()
        found_ids = {row["id"] for row in rows}
        deleting_ids = [task_id for task_id in clean_ids if task_id in found_ids]
        if deleting_ids:
            delete_placeholders = ", ".join("?" for _ in deleting_ids)
            conn.execute(f"DELETE FROM visual_generation_modules WHERE task_id IN ({delete_placeholders})", deleting_ids)
            conn.execute(
                f"DELETE FROM visual_generation_tasks WHERE user_id = ? AND id IN ({delete_placeholders})",
                (user_id, *deleting_ids),
            )
    return {
        "deletedCount": len(deleting_ids),
        "missingIds": [task_id for task_id in clean_ids if task_id not in found_ids],
    }


def reset_stale_visual_task_outputs(*, task_id: str, user_id: str) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        row = conn.execute(
            "SELECT id FROM visual_generation_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise VisualTaskError("visual task not found")
        conn.execute("DELETE FROM visual_generation_modules WHERE task_id = ?", (task_id,))
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET analysis_json = '{}',
                prompt_text = '',
                mother_image_path = NULL,
                mother_image_url = NULL,
                manifest_json = '{}',
                status = ?,
                error_message = NULL,
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (TASK_STATUS_DRAFT, now, task_id, user_id),
        )

def request_product_analysis_with_payload_retry(
    *,
    api_url: str,
    api_key: str,
    model: str,
    product_image_path: Path | None,
    product_image_paths: list[Path],
    context: dict[str, Any],
) -> dict[str, Any]:
    last_error: Exception | None = None
    for index, profile in enumerate(IMAGE_PAYLOAD_RETRY_PROFILES):
        try:
            return request_product_analysis(
                api_url=api_url,
                api_key=api_key,
                model=model,
                product_image_path=product_image_path,
                product_image_paths=product_image_paths,
                context=context,
                image_max_side=profile["max_side"],
                image_quality=profile["quality"],
            )
        except Exception as exc:
            if not is_request_too_large_error(exc) or index == len(IMAGE_PAYLOAD_RETRY_PROFILES) - 1:
                raise
            last_error = exc
    raise last_error or VisualTaskError("product analysis failed")


def request_generated_image_with_payload_retry(
    *,
    api_url: str,
    api_key: str,
    model: str,
    size: str,
    prompt: str,
    compact_prompt: str,
    reference_image_path: Path | None,
    reference_image_paths: list[Path],
    gateway_stage: str = "",
    used_settings: dict[str, str] | None = None,
    task_id: str = "",
) -> bytes:
    if gateway_stage:
        attempt_limit = ai_gateway_scheduler.resolve_attempt_limit(gateway_stage)
        excluded_credential_ids: set[str] = set()
        last_error: Exception | None = None
        last_error_type = ""
        last_switch_progress: dict[str, str] = {}
        for _attempt in range(attempt_limit):
            candidate = ai_gateway_scheduler.acquire_candidate(
                gateway_stage,
                task_type="image",
                excluded_credential_ids=excluded_credential_ids,
            )
            if not candidate:
                break
            excluded_credential_ids.add(clean_text(candidate.get("credentialId")))
            started = time.monotonic()
            candidate_settings = {
                "api_key": clean_text(candidate.get("apiKey")),
                "base_url": clean_text(candidate.get("baseUrl")),
                "model": clean_text(candidate.get("model")) or model,
                "channel_id": clean_text(candidate.get("channelId")),
                "credential_id": clean_text(candidate.get("credentialId")),
                "credential_name": clean_text(candidate.get("credentialName")) or clean_text(candidate.get("credentialId")),
                "gateway_stage": gateway_stage,
            }
            candidate_model = normalize_image_model_for_channel(candidate_settings, candidate_settings["model"])
            candidate_settings["model"] = candidate_model
            candidate_size = "" if is_chufan_ai_image_target(candidate_settings, candidate_model) else size
            candidate_timeout = min(
                bounded_image_request_timeout(candidate.get("readTimeoutSeconds")),
                image_gateway_max_attempt_timeout_seconds(),
            )
            candidate_api_url = build_api_url(
                candidate_settings["base_url"],
                "/images/edits" if reference_image_paths or reference_image_path else "/images/generations",
            )
            if used_settings is not None:
                used_settings.clear()
                used_settings.update(candidate_settings)
            if task_id:
                set_visual_progress(
                    task_id,
                    {
                        "state": "waiting_upstream",
                        "stage": gateway_stage,
                        "channelId": candidate_settings["channel_id"],
                        "credentialId": candidate_settings["credential_id"],
                        "credentialName": candidate_settings["credential_name"],
                        "model": candidate_model,
                        "timeoutSeconds": candidate_timeout,
                        **last_switch_progress,
                    },
                )
            try:
                result = request_generated_image_for_candidate(
                    api_url=candidate_api_url,
                    api_key=candidate_settings["api_key"],
                    model=candidate_model,
                    size=candidate_size,
                    prompt=prompt,
                    compact_prompt=compact_prompt,
                    reference_image_path=reference_image_path,
                    reference_image_paths=reference_image_paths,
                    timeout=candidate_timeout,
                )
                ai_gateway_scheduler.finish_attempt(
                    candidate,
                    success=True,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                last_error_type = classify_ai_error(exc)
                ai_gateway_scheduler.finish_attempt(
                    candidate,
                    success=False,
                    error_message=str(exc),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                if not should_switch_ai_candidate(exc):
                    break
                if task_id:
                    last_switch_progress = {
                        "lastSwitchChannelId": candidate_settings["channel_id"],
                        "lastSwitchCredentialId": candidate_settings["credential_id"],
                        "lastSwitchCredentialName": candidate_settings["credential_name"],
                        "lastSwitchModel": candidate_model,
                        "lastSwitchErrorType": last_error_type,
                        "lastSwitchError": str(exc)[:2000],
                    }
                    set_visual_progress(
                        task_id,
                        {
                            "state": "switching_key",
                            "stage": gateway_stage,
                            "channelId": candidate_settings["channel_id"],
                            "credentialId": candidate_settings["credential_id"],
                            "credentialName": candidate_settings["credential_name"],
                            "model": candidate_model,
                            "errorType": last_error_type,
                            "lastError": str(exc)[:2000],
                            **last_switch_progress,
                        },
                    )
                continue
        if last_error_type == "bad_request" and last_error is not None:
            raise VisualTaskNonRetryableError(str(last_error)) from last_error
        if last_error is None:
            raise VisualTaskError(f"API 中枢没有可用生图渠道：{gateway_stage}")
        raise last_error or VisualTaskError(f"API 中枢没有可用生图渠道：{gateway_stage}")

    last_error: Exception | None = None
    for rate_attempt, delay_seconds in enumerate(IMAGE_RATE_LIMIT_RETRY_DELAYS_SECONDS):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            for active_prompt in (prompt, compact_prompt):
                for index, image_profile in enumerate(IMAGE_PAYLOAD_RETRY_PROFILES):
                    try:
                        return request_generated_image(
                            api_url=api_url,
                            api_key=api_key,
                            model=model,
                            size=size,
                            prompt=active_prompt,
                            reference_image_path=reference_image_path,
                            reference_image_paths=reference_image_paths,
                            reference_image_max_side=image_profile["max_side"],
                            reference_image_quality=image_profile["quality"],
                        )
                    except Exception as exc:
                        if not is_request_too_large_error(exc):
                            raise
                        last_error = exc
                        if index < len(IMAGE_PAYLOAD_RETRY_PROFILES) - 1:
                            continue
                        break
            if last_error:
                break
        except Exception as exc:
            if is_rate_limit_error(exc) and rate_attempt < len(IMAGE_RATE_LIMIT_RETRY_DELAYS_SECONDS) - 1:
                last_error = exc
                continue
            raise
    raise last_error or VisualTaskError("image generation failed")


def request_generated_image_for_candidate(
    *,
    api_url: str,
    api_key: str,
    model: str,
    size: str,
    prompt: str,
    compact_prompt: str,
    reference_image_path: Path | None,
    reference_image_paths: list[Path],
    timeout: int,
) -> bytes:
    last_error: Exception | None = None
    for active_prompt in (prompt, compact_prompt):
        for index, image_profile in enumerate(IMAGE_PAYLOAD_RETRY_PROFILES):
            try:
                return request_generated_image(
                    api_url=api_url,
                    api_key=api_key,
                    model=model,
                    size=size,
                    prompt=active_prompt,
                    reference_image_path=reference_image_path,
                    reference_image_paths=reference_image_paths,
                    reference_image_max_side=image_profile["max_side"],
                    reference_image_quality=image_profile["quality"],
                    timeout=timeout,
                    fail_fast_transient=True,
                )
            except Exception as exc:
                if not is_request_too_large_error(exc):
                    raise
                last_error = exc
                if index < len(IMAGE_PAYLOAD_RETRY_PROFILES) - 1:
                    continue
                break
    raise last_error or VisualTaskError("image generation failed")


def plan_visual_task(
    *,
    task_id: str,
    user_id: str,
    source_image_ref: str | None = None,
    reference_image_refs: list[dict[str, Any]] | None = None,
    allow_short_labels: bool | None = None,
    analysis_model: str | None = None,
    prompt_model: str | None = None,
) -> dict[str, Any]:
    assert_visual_task_not_cancelled(task_id, user_id)
    task = get_visual_task(task_id=task_id, user_id=user_id)
    record = task.get("record") or {}
    reference_refs = normalize_reference_image_refs(reference_image_refs or record.get("visualReferenceImages"))
    source_ref = clean_text(source_image_ref) or (reference_refs[0]["url"] if reference_refs else "") or clean_text(task.get("sourceImageRef"))
    reference_refs = normalize_reference_image_refs(reference_refs, fallback_ref=source_ref)
    if not source_ref:
        raise VisualTaskError("source image is required before planning")

    analysis_settings = get_ai_stage_settings("visual_analysis", user_id=user_id)
    prompt_settings = get_ai_stage_settings("visual_prompt", user_id=user_id)
    text_model = analysis_model or analysis_settings["model"]
    plan_model = prompt_model or prompt_settings["model"]
    resolved_allow_short_labels = (
        visual_bool_setting("VISUAL_ALLOW_SHORT_LABELS", True) if allow_short_labels is None else allow_short_labels
    )
    analysis_url = build_api_url(analysis_settings["base_url"], "/chat/completions")
    prompt_url = build_api_url(prompt_settings["base_url"], "/chat/completions")
    task_dir = task_output_dir(user_id, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    reference_paths = materialize_reference_image_refs(reference_refs, task_dir)
    source_path = reference_paths[0] if reference_paths else materialize_image_ref(source_ref, task_dir / "source_image")

    context = build_visual_prompt_context(task=task, record=record, reference_refs=reference_refs)
    requested_count = int(task.get("requestedCount") or task.get("requested_count") or layout_panel_count(task["layout"]))
    existing_analysis = task.get("analysis") if isinstance(task.get("analysis"), dict) else {}
    cached_product_analysis = (
        existing_analysis.get("productUnderstanding")
        if isinstance(existing_analysis.get("productUnderstanding"), dict)
        else existing_analysis.get("productAnalysis")
        if isinstance(existing_analysis.get("productAnalysis"), dict)
        else None
    )
    update_task_status(task_id, user_id, TASK_STATUS_RUNNING, clear_error=True)
    try:
        assert_visual_task_not_cancelled(task_id, user_id)
        if cached_product_analysis:
            product_analysis = dict(cached_product_analysis)
            product_analysis = normalize_visual_product_identity(
                record=record,
                product_analysis=product_analysis,
                context=context,
            )
        else:
            assert_user_api_usage_allowed(user_id)
            try:
                product_analysis = request_product_analysis_with_payload_retry(
                    api_url=analysis_url,
                    api_key=analysis_settings["api_key"],
                    model=text_model,
                    product_image_path=source_path,
                    product_image_paths=reference_paths,
                    context=context,
                )
                assert_visual_task_not_cancelled(task_id, user_id)
                product_analysis = normalize_visual_product_identity(
                    record=record,
                    product_analysis=product_analysis,
                    context=context,
                )
                persist_product_analysis(
                    task_id=task_id,
                    user_id=user_id,
                    source_image_ref=source_ref,
                    product_analysis=product_analysis,
                )
                existing_analysis = {
                    "stage": "product_analysis",
                    "productUnderstanding": product_analysis,
                    "productAnalysis": product_analysis,
                }
                record_visual_api_usage(
                    analysis_settings,
                    user_id=user_id,
                    stage="visual_analysis",
                    api_type="chat",
                    model=text_model,
                    status="success",
                    task_id=task_id,
                )
            except Exception as exc:
                record_visual_api_usage(
                    analysis_settings,
                    user_id=user_id,
                    stage="visual_analysis",
                    api_type="chat",
                    model=text_model,
                    status="failed",
                    error_message=str(exc),
                    task_id=task_id,
                )
                raise
        assert_user_api_usage_allowed(user_id)
        try:
            try:
                plan = request_prompt_plan(
                    api_url=prompt_url,
                    api_key=prompt_settings["api_key"],
                    model=plan_model,
                    product_analysis=product_analysis,
                    layout=task["layout"],
                    allow_short_labels=resolved_allow_short_labels,
                    requested_count=requested_count,
                    context=context,
                    cached_plan=existing_analysis,
                    on_partial_plan=lambda partial_plan: persist_partial_plan(
                        task_id=task_id,
                        user_id=user_id,
                        source_image_ref=source_ref,
                        plan=partial_plan,
                    ),
                )
                assert_visual_task_not_cancelled(task_id, user_id)
            except Exception as exc:
                if not is_request_too_large_error(exc):
                    raise
                compact_analysis = compact_json_value(product_analysis, max_items=6, max_chars=140)
                plan = request_prompt_plan(
                    api_url=prompt_url,
                    api_key=prompt_settings["api_key"],
                    model=plan_model,
                    product_analysis=compact_analysis if isinstance(compact_analysis, dict) else product_analysis,
                    layout=task["layout"],
                    allow_short_labels=resolved_allow_short_labels,
                    requested_count=requested_count,
                    context=context,
                    cached_plan=existing_analysis,
                    on_partial_plan=lambda partial_plan: persist_partial_plan(
                        task_id=task_id,
                        user_id=user_id,
                        source_image_ref=source_ref,
                        plan=partial_plan,
                    ),
                )
                assert_visual_task_not_cancelled(task_id, user_id)
            record_visual_api_usage(
                prompt_settings,
                user_id=user_id,
                stage="visual_prompt",
                api_type="chat",
                model=plan_model,
                status="success",
                task_id=task_id,
            )
        except Exception as exc:
            record_visual_api_usage(
                prompt_settings,
                user_id=user_id,
                stage="visual_prompt",
                api_type="chat",
                model=plan_model,
                status="failed",
                error_message=str(exc),
                task_id=task_id,
            )
            raise
        mother_prompt = build_mother_prompt_from_plan(plan, task["layout"], resolved_allow_short_labels)
        assert_visual_task_not_cancelled(task_id, user_id)
        persist_plan(task_id, user_id, source_ref, plan, mother_prompt)
    except VisualTaskCancelled:
        raise
    except Exception as exc:
        mark_task_failed(task_id, user_id, str(exc))
        raise

    assert_visual_task_not_cancelled(task_id, user_id)
    return get_visual_task(task_id=task_id, user_id=user_id)


def generate_visual_task(
    *,
    task_id: str,
    user_id: str,
    split_after: bool | None = None,
    upload_to_oss: bool | None = None,
    image_model: str | None = None,
    image_size: str | None = None,
    use_reference_image: bool | None = None,
) -> dict[str, Any]:
    assert_visual_task_not_cancelled(task_id, user_id)
    task = get_visual_task(task_id=task_id, user_id=user_id)
    if visual_task_prompt_is_stale(task):
        raise VisualTaskError("task prompt is stale; run plan first")
    prompt_text = clean_text(task.get("promptText"))
    if not prompt_text:
        raise VisualTaskError("task has no mother prompt; run plan first")

    settings = get_ai_stage_settings("image", user_id=user_id)
    source_ref = clean_text(task.get("sourceImageRef"))
    reference_refs = normalize_reference_image_refs((task.get("record") or {}).get("visualReferenceImages"), fallback_ref=source_ref)
    task_dir = task_output_dir(user_id, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    resolved_split_after = True if split_after is None else split_after
    resolved_upload_to_oss = (
        visual_bool_setting("VISUAL_UPLOAD_TO_OSS_DEFAULT", False) if upload_to_oss is None else upload_to_oss
    )
    resolved_image_size = clean_text(image_size) or visual_setting("VISUAL_IMAGE_SIZE", "1024x1024")
    resolved_use_reference_image = (
        visual_bool_setting("VISUAL_USE_REFERENCE_IMAGE", True) if use_reference_image is None else use_reference_image
    )
    resolved_image_model = normalize_image_model_for_channel(settings, image_model or settings["model"])
    use_chufan_image_target = is_chufan_ai_image_target(settings, resolved_image_model)
    reference_paths = materialize_reference_image_refs(reference_refs, task_dir) if resolved_use_reference_image else []
    reference_path = reference_paths[0] if reference_paths else None
    image_endpoint = "/images/edits" if reference_paths else "/images/generations"
    image_url = build_api_url(settings["base_url"], image_endpoint)
    compact_prompt_text = build_compact_mother_prompt_from_plan(
        task.get("analysis") if isinstance(task.get("analysis"), dict) else {},
        clean_text(task.get("layout")) or "3x3",
        visual_bool_setting("VISUAL_ALLOW_SHORT_LABELS", True),
    )
    request_image_size = resolved_image_size
    if not settings.get("gateway_stage") and use_chufan_image_target:
        request_image_size = ""

    update_task_status(task_id, user_id, TASK_STATUS_RUNNING, clear_error=True)
    try:
        assert_visual_task_not_cancelled(task_id, user_id)
        assert_user_api_usage_allowed(user_id)
        actual_image_settings = dict(settings)
        try:
            image_bytes = request_generated_image_with_payload_retry(
                api_url=image_url,
                api_key=settings["api_key"],
                model=resolved_image_model,
                size=request_image_size,
                prompt=prompt_text,
                compact_prompt=compact_prompt_text,
                reference_image_path=reference_path,
                reference_image_paths=reference_paths,
                gateway_stage=settings.get("gateway_stage", ""),
                used_settings=actual_image_settings,
                task_id=task_id,
            )
            assert_visual_task_not_cancelled(task_id, user_id)
        except Exception as exc:
            record_visual_api_usage(
                actual_image_settings,
                user_id=user_id,
                stage="visual_image",
                api_type="image",
                model=clean_text(actual_image_settings.get("model")) or resolved_image_model,
                status="failed",
                error_message=str(exc),
                task_id=task_id,
            )
            raise
        mother_path = task_dir / "generated_mother.png"
        mother_path.write_bytes(image_bytes)
        with get_connection() as conn:
            ensure_visual_generation_schema(conn)
            conn.execute(
                """
                UPDATE visual_generation_tasks
                SET mother_image_path = ?, status = ?, updated_at = ?, error_message = NULL
                WHERE id = ? AND user_id = ?
                """,
                (str(mother_path), TASK_STATUS_PLANNED, utc_now_text(), task_id, user_id),
            )
        record_visual_api_usage(
            actual_image_settings,
            user_id=user_id,
            stage="visual_image",
            api_type="image",
            model=clean_text(actual_image_settings.get("model")) or resolved_image_model,
            status="success",
            task_id=task_id,
        )
    except VisualTaskCancelled:
        raise
    except Exception as exc:
        mark_task_failed(task_id, user_id, str(exc))
        raise

    if resolved_split_after:
        assert_visual_task_not_cancelled(task_id, user_id)
        return split_visual_task(
            task_id=task_id,
            user_id=user_id,
            mother_image_ref=str(mother_path),
            upload_to_oss=resolved_upload_to_oss,
        )
    assert_visual_task_not_cancelled(task_id, user_id)
    return get_visual_task(task_id=task_id, user_id=user_id)


def split_visual_task(
    *,
    task_id: str,
    user_id: str,
    mother_image_ref: str | None = None,
    upload_to_oss: bool | None = None,
    target_size: int | None = None,
    safe_margin_ratio: float | None = None,
    output_format: str | None = None,
    quality: int | None = None,
    sharpen: float | None = None,
) -> dict[str, Any]:
    assert_visual_task_not_cancelled(task_id, user_id)
    task = get_visual_task(task_id=task_id, user_id=user_id)
    if visual_task_prompt_is_stale(task):
        raise VisualTaskError("task prompt is stale; run plan first")
    source_ref = clean_text(mother_image_ref) or clean_text(task.get("motherImagePath")) or clean_text(task.get("motherImageUrl"))
    if not source_ref:
        raise VisualTaskError("mother image is required for split")

    task_dir = task_output_dir(user_id, task_id)
    split_dir = task_dir / "split"
    split_dir.mkdir(parents=True, exist_ok=True)
    mother_path = materialize_image_ref(source_ref, task_dir / "mother_image")
    resolved_upload_to_oss = (
        visual_bool_setting("VISUAL_UPLOAD_TO_OSS_DEFAULT", False) if upload_to_oss is None else upload_to_oss
    )
    resolved_target_size = target_size or visual_int_setting("VISUAL_SPLIT_TARGET_SIZE", 800, minimum=256, maximum=2048)
    resolved_safe_margin_ratio = (
        safe_margin_ratio
        if safe_margin_ratio is not None
        else visual_float_setting("VISUAL_SPLIT_SAFE_MARGIN_RATIO", 0.03, minimum=0, maximum=0.24)
    )
    resolved_output_format = clean_text(output_format) or visual_setting("VISUAL_SPLIT_FORMAT", "webp")
    resolved_quality = quality or visual_int_setting("VISUAL_SPLIT_QUALITY", 92, minimum=1, maximum=100)
    resolved_sharpen = (
        sharpen if sharpen is not None else visual_float_setting("VISUAL_SPLIT_SHARPEN", 0.7, minimum=0, maximum=3)
    )
    update_task_status(task_id, user_id, TASK_STATUS_RUNNING, clear_error=True)
    try:
        assert_visual_task_not_cancelled(task_id, user_id)
        manifest = split_grid_file(
            input_path=mother_path,
            output_dir=split_dir,
            layout=task["layout"],
            target_size=resolved_target_size,
            safe_margin_ratio=resolved_safe_margin_ratio,
            output_format=resolved_output_format,
            quality=resolved_quality,
            sharpen=resolved_sharpen,
        )
        assert_visual_task_not_cancelled(task_id, user_id)
        modules = persist_split_result(
            task_id=task_id,
            user_id=user_id,
            mother_path=mother_path,
            split_dir=split_dir,
            manifest=manifest,
            upload_to_oss=resolved_upload_to_oss,
        )
    except VisualTaskCancelled:
        raise
    except Exception as exc:
        mark_task_failed(task_id, user_id, str(exc))
        raise

    assert_visual_task_not_cancelled(task_id, user_id)
    result = get_visual_task(task_id=task_id, user_id=user_id)
    result["modules"] = modules
    return result


def run_visual_task_pipeline(
    *,
    task_id: str,
    user_id: str,
    source_image_ref: str | None = None,
    reference_image_refs: list[dict[str, Any]] | None = None,
    allow_short_labels: bool | None = None,
    analysis_model: str | None = None,
    prompt_model: str | None = None,
    split_after: bool | None = True,
    upload_to_oss: bool | None = True,
    image_model: str | None = None,
    image_size: str | None = None,
    use_reference_image: bool | None = True,
    apply_to_link_record: bool = True,
    reuse_existing_outputs: bool = False,
) -> dict[str, Any]:
    """Run plan -> generate -> split.

    Persisted prompt/mother outputs are only reusable for explicit failure retries.
    A normal run against the same task/link should regenerate from fresh planning.
    """
    assert_visual_task_not_cancelled(task_id, user_id)
    task = get_visual_task(task_id=task_id, user_id=user_id)
    if visual_task_prompt_is_stale(task) or (
        not reuse_existing_outputs and visual_task_has_persisted_generation(task)
    ):
        reset_stale_visual_task_outputs(task_id=task_id, user_id=user_id)
        assert_visual_task_not_cancelled(task_id, user_id)
        task = get_visual_task(task_id=task_id, user_id=user_id)

    completed_status = completed_status_from_task(task)
    if completed_status:
        assert_visual_task_not_cancelled(task_id, user_id)
        update_task_status(task_id, user_id, completed_status, clear_error=True)
        if apply_to_link_record:
            assert_visual_task_not_cancelled(task_id, user_id)
            apply_visual_task_results_to_link_record(task_id=task_id, user_id=user_id)
            assert_visual_task_not_cancelled(task_id, user_id)
            update_task_status(task_id, user_id, TASK_STATUS_COMPLETED, clear_error=True)
        return get_visual_task(task_id=task_id, user_id=user_id)

    planned: dict[str, Any] | None = None
    if not clean_text(task.get("promptText")):
        assert_visual_task_not_cancelled(task_id, user_id)
        planned = plan_visual_task(
            task_id=task_id,
            user_id=user_id,
            source_image_ref=source_image_ref,
            reference_image_refs=reference_image_refs,
            allow_short_labels=allow_short_labels,
            analysis_model=analysis_model,
            prompt_model=prompt_model,
        )
        assert_visual_task_not_cancelled(task_id, user_id)
        task = planned

    generated: dict[str, Any] | None = None
    if split_after is not False and task_has_usable_mother_image(task):
        assert_visual_task_not_cancelled(task_id, user_id)
        generated = split_visual_task(
            task_id=task_id,
            user_id=user_id,
            mother_image_ref=clean_text(task.get("motherImagePath")) or clean_text(task.get("motherImageUrl")),
            upload_to_oss=upload_to_oss,
        )
    elif not task_has_usable_mother_image(task):
        assert_visual_task_not_cancelled(task_id, user_id)
        generated = generate_visual_task(
            task_id=task_id,
            user_id=user_id,
            split_after=split_after,
            upload_to_oss=upload_to_oss,
            image_model=image_model,
            image_size=image_size,
            use_reference_image=use_reference_image,
        )
    else:
        generated = task

    if apply_to_link_record:
        try:
            assert_visual_task_not_cancelled(task_id, user_id)
            update_task_status(task_id, user_id, TASK_STATUS_RUNNING, clear_error=True)
            apply_visual_task_results_to_link_record(task_id=task_id, user_id=user_id)
            assert_visual_task_not_cancelled(task_id, user_id)
            update_task_status(task_id, user_id, TASK_STATUS_COMPLETED, clear_error=True)
        except VisualTaskCancelled:
            raise
        except Exception as exc:
            # The generated assets should remain usable even if link-list persistence fails.
            mark_task_failed(task_id, user_id, f"generated, but link record update failed: {exc}")
            raise
    assert_visual_task_not_cancelled(task_id, user_id)
    return get_visual_task(task_id=task_id, user_id=user_id) if apply_to_link_record else generated or planned


def task_has_usable_mother_image(task: dict[str, Any]) -> bool:
    mother_url = clean_text(task.get("motherImageUrl"))
    if mother_url:
        return True
    mother_path = clean_text(task.get("motherImagePath"))
    if not mother_path:
        return False
    if mother_path.startswith("http://") or mother_path.startswith("https://"):
        return True
    return Path(mother_path).exists()


def completed_status_from_task(task: dict[str, Any]) -> str:
    expected_count = int(task.get("requestedCount") or 0)
    manifest = task.get("manifest") if isinstance(task.get("manifest"), dict) else {}
    manifest_panels = manifest.get("panels") if isinstance(manifest.get("panels"), list) else []
    if expected_count <= 0:
        expected_count = len(manifest_panels)
    if expected_count <= 0 or not task_has_usable_mother_image(task):
        return ""

    modules = task.get("modules") if isinstance(task.get("modules"), list) else []
    output_count = sum(
        1 for module in modules if clean_text(module.get("outputUrl")) or clean_text(module.get("outputPath"))
    )
    if output_count < expected_count:
        return ""
    url_count = sum(1 for module in modules if clean_text(module.get("outputUrl")))
    return TASK_STATUS_COMPLETED if url_count >= expected_count else TASK_STATUS_SPLIT


def apply_visual_task_results_to_link_record(*, task_id: str, user_id: str) -> dict[str, Any] | None:
    task = get_visual_task(task_id=task_id, user_id=user_id)
    link_record_id = clean_text(task.get("linkRecordId"))
    if not link_record_id:
        return None

    record = load_link_record_for_visual_task(link_record_id=link_record_id, user_id=user_id)
    if record is None:
        record = task.get("record") if isinstance(task.get("record"), dict) else {}
    if not isinstance(record, dict) or not record:
        return None

    modules = sorted(
        [module for module in task.get("modules") or [] if visual_module_result_ref(module)],
        key=lambda module: int(module.get("panelIndex") or 0),
    )
    if not modules:
        return record

    mode = clean_text(task.get("mode"))
    if mode == "sku-gallery":
        next_record = apply_visual_sku_gallery_result(record, task, modules)
    else:
        next_record = apply_visual_product_gallery_result(record, task, modules)
    next_record = apply_visual_sku_identity_rewrites(next_record, task)
    next_record = apply_visual_product_identity_to_record(next_record, task)

    now = utc_now_text()
    visual_history = next_record.get("visualGenerationTaskIds")
    if not isinstance(visual_history, list):
        visual_history = []
    if task_id not in visual_history:
        visual_history.append(task_id)
    next_record["visualGenerationTaskIds"] = visual_history[-20:]
    next_record["visualGenerationStatus"] = task.get("status") or TASK_STATUS_COMPLETED
    next_record["visualGeneratedAt"] = now
    next_record["updatedAt"] = now
    return upsert_link_list_record(next_record, user_id=user_id)


def load_link_record_for_visual_task(*, link_record_id: str, user_id: str) -> dict[str, Any] | None:
    records = list_link_list_records(user_id=user_id, include_deleted=False, limit=1000)
    for record in records:
        if clean_text(record.get("id")) == link_record_id:
            return record
    return None


def visual_module_result_ref(module: dict[str, Any]) -> str:
    return clean_text(module.get("outputUrl")) or clean_text(module.get("outputPath"))


def normalize_visual_product_identity(
    *,
    record: dict[str, Any],
    product_analysis: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize model product identity into a reusable JSON contract for image and Excel flows."""
    if not isinstance(product_analysis, dict):
        return {}

    identity = (
        product_analysis.get("productIdentity")
        if isinstance(product_analysis.get("productIdentity"), dict)
        else {}
    )
    context = context if isinstance(context, dict) else {}
    reference_by_index = visual_reference_analysis_by_index(product_analysis)
    sku_bindings = product_analysis.get("skuBindings") if isinstance(product_analysis.get("skuBindings"), list) else []
    if not sku_bindings:
        sku_bindings = context.get("skuBindings") if isinstance(context.get("skuBindings"), list) else []
    if not sku_bindings:
        sku_bindings = extract_record_sku_bindings(record, record.get("visualReferenceImages"))

    raw_identity_skus = identity.get("skus") if isinstance(identity.get("skus"), list) else []
    identity_by_index: dict[int, dict[str, Any]] = {}
    for item in raw_identity_skus:
        if not isinstance(item, dict):
            continue
        sku_index = safe_int(item.get("sku_index") or item.get("skuIndex"))
        if sku_index > 0:
            identity_by_index[sku_index] = item

    normalized_skus: list[dict[str, Any]] = []
    for binding in sku_bindings:
        if not isinstance(binding, dict):
            continue
        sku_index = safe_int(binding.get("skuIndex") or binding.get("sku_index"))
        if sku_index <= 0:
            continue
        raw_sku = identity_by_index.get(sku_index, {})
        raw_name = first_clean_text(
            raw_sku.get("raw_name"),
            raw_sku.get("rawName"),
            binding.get("skuName"),
            f"SKU {sku_index}",
        )
        components = [component for component in binding.get("components") or [] if isinstance(component, dict)]
        normalized_components: list[dict[str, Any]] = []
        for component_index, component in enumerate(components, start=1):
            raw_component = visual_identity_component_by_index(raw_sku, component_index)
            reference_index = safe_int(
                raw_component.get("reference_image_index")
                or raw_component.get("referenceImageIndex")
                or component.get("referenceImageIndex")
            )
            reference_analysis = reference_by_index.get(reference_index, {})
            component_label = first_clean_text(
                raw_component.get("standard_name"),
                raw_component.get("standardName"),
            )
            if not component_label:
                component_label = build_visual_component_sku_label(component, reference_analysis)
            product_name = first_clean_text(
                raw_component.get("product_name"),
                raw_component.get("productName"),
                strip_leading_quantity_label(component_label),
            )
            normalized_components.append(
                {
                    "component_index": component_index,
                    "raw_name": first_clean_text(
                        raw_component.get("raw_name"),
                        raw_component.get("rawName"),
                        component.get("componentName"),
                        component.get("specText"),
                    ),
                    "standard_name": component_label,
                    "product_name": product_name,
                    "quantity": first_clean_text(
                        raw_component.get("quantity"),
                        extract_visual_quantity_prefix(component_label),
                        extract_visual_quantity_prefix(component.get("componentName")),
                    ),
                    "shape": first_clean_text(raw_component.get("shape"), reference_analysis.get("shape"), reference_analysis.get("geometry")),
                    "material": first_clean_text(
                        raw_component.get("material"),
                        visual_identity_material_text(reference_analysis.get("materials")),
                    ),
                    "source_title": first_clean_text(raw_component.get("source_title"), raw_component.get("sourceTitle"), component.get("sourceTitle")),
                    "reference_image_index": reference_index,
                }
            )

        component_names = [clean_text(item.get("standard_name")) for item in normalized_components if clean_text(item.get("standard_name"))]
        standard_name = first_clean_text(
            raw_sku.get("standard_name"),
            raw_sku.get("standardName"),
            "+".join(component_names) if len(component_names) > 1 else (component_names[0] if component_names else ""),
        )
        standard_name = clamp_sku_identity_label(standard_name)
        reference_indexes = [
            int(item["reference_image_index"])
            for item in normalized_components
            if safe_int(item.get("reference_image_index")) > 0
        ]
        normalized_skus.append(
            {
                "sku_index": sku_index,
                "raw_name": raw_name,
                "standard_name": standard_name,
                "product_name": first_clean_text(
                    raw_sku.get("product_name"),
                    raw_sku.get("productName"),
                    strip_leading_quantity_label(standard_name),
                ),
                "quantity": first_clean_text(raw_sku.get("quantity"), extract_visual_quantity_prefix(standard_name)),
                "shape": first_clean_text(raw_sku.get("shape"), *(item.get("shape") for item in normalized_components)),
                "material": first_clean_text(raw_sku.get("material"), *(item.get("material") for item in normalized_components)),
                "reference_image_indexes": sorted({index for index in reference_indexes if index}),
                "components": normalized_components,
            }
        )

    if not normalized_skus and identity_by_index:
        for sku_index in sorted(identity_by_index):
            item = identity_by_index[sku_index]
            standard_name = clamp_sku_identity_label(
                first_clean_text(item.get("standard_name"), item.get("standardName"), item.get("product_name"), item.get("productName"))
            )
            if not standard_name:
                continue
            normalized_skus.append(
                {
                    "sku_index": sku_index,
                    "raw_name": first_clean_text(item.get("raw_name"), item.get("rawName"), standard_name),
                    "standard_name": standard_name,
                    "product_name": first_clean_text(item.get("product_name"), item.get("productName"), strip_leading_quantity_label(standard_name)),
                    "quantity": first_clean_text(item.get("quantity"), extract_visual_quantity_prefix(standard_name)),
                    "shape": clean_text(item.get("shape")),
                    "material": clean_text(item.get("material")),
                    "reference_image_indexes": item.get("reference_image_indexes")
                    if isinstance(item.get("reference_image_indexes"), list)
                    else [],
                    "components": item.get("components") if isinstance(item.get("components"), list) else [],
                }
            )

    combo_sku_name = first_clean_text(
        identity.get("combo_sku_name"),
        identity.get("comboSkuName"),
        "+".join(item["standard_name"] for item in normalized_skus if clean_text(item.get("standard_name"))),
    )
    product_type = first_clean_text(
        identity.get("product_type"),
        identity.get("productType"),
        product_analysis.get("overallCategory"),
        *(item.get("category") for item in reference_by_index.values()),
    )
    title_en = first_clean_text(
        identity.get("title_en"),
        identity.get("titleEn"),
        build_visual_identity_title_en(normalized_skus, product_type),
    )
    title_cn = first_clean_text(
        identity.get("title_cn"),
        identity.get("titleCn"),
        record.get("productTitle"),
        product_analysis.get("productTitle"),
    )

    normalized_identity = {
        "product_type": product_type,
        "product_type_cn": first_clean_text(identity.get("product_type_cn"), identity.get("productTypeCn")),
        "title_cn": title_cn,
        "title_en": title_en,
        "combo_sku_name": clamp_sku_identity_label(combo_sku_name, max_chars=140),
        "skus": normalized_skus,
    }
    next_analysis = dict(product_analysis)
    next_analysis["productIdentity"] = normalized_identity
    if title_cn:
        next_analysis["standardTitleCn"] = title_cn
    if title_en:
        next_analysis["standardTitleEn"] = title_en
    if normalized_skus:
        next_analysis["skuNames"] = [
            item["standard_name"]
            for item in normalized_skus
            if clean_text(item.get("standard_name"))
        ]
    return next_analysis


def visual_identity_component_by_index(raw_sku: dict[str, Any], component_index: int) -> dict[str, Any]:
    components = raw_sku.get("components") if isinstance(raw_sku.get("components"), list) else []
    for item in components:
        if not isinstance(item, dict):
            continue
        if safe_int(item.get("component_index") or item.get("componentIndex")) == component_index:
            return item
    return components[component_index - 1] if component_index <= len(components) and isinstance(components[component_index - 1], dict) else {}


def visual_identity_material_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(clean_text(item) for item in value if clean_text(item))
    return clean_text(value)


def build_visual_identity_title_en(skus: list[dict[str, Any]], product_type: str = "") -> str:
    names = [strip_leading_quantity_label(item.get("standard_name")) for item in skus if clean_text(item.get("standard_name"))]
    names = [name for name in names if name]
    if not names:
        return clean_text(product_type)
    if len(names) == 1:
        base = names[0]
    elif len(names) == 2:
        base = f"{names[0]} and {names[1]}"
    else:
        base = ", ".join(names[:-1]) + f", and {names[-1]}"
    suffix = clean_text(product_type)
    if suffix and suffix.lower() not in base.lower():
        return clamp_sku_identity_label(f"{base} {suffix}", max_chars=140)
    return clamp_sku_identity_label(base, max_chars=140)


def visual_product_identity_from_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    product_understanding = analysis.get("productUnderstanding") if isinstance(analysis.get("productUnderstanding"), dict) else analysis
    identity = product_understanding.get("productIdentity") if isinstance(product_understanding.get("productIdentity"), dict) else {}
    return identity if isinstance(identity, dict) else {}


def apply_visual_product_identity_to_record(record: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    analysis = task.get("analysis") if isinstance(task.get("analysis"), dict) else {}
    identity = visual_product_identity_from_analysis(analysis)
    if not identity:
        return record
    next_record = dict(record)
    next_record["visualProductIdentity"] = identity
    title_cn = first_clean_text(identity.get("title_cn"), identity.get("titleCn"))
    title_en = first_clean_text(identity.get("title_en"), identity.get("titleEn"))
    product_type = first_clean_text(identity.get("product_type"), identity.get("productType"))
    if title_cn:
        next_record["visualGeneratedTitleCn"] = title_cn
    if title_en:
        next_record["visualGeneratedTitleEn"] = title_en
    if product_type:
        next_record["visualGeneratedProductType"] = product_type
    task_id = clean_text(task.get("id"))
    if task_id:
        next_record["visualProductIdentityTaskId"] = task_id
    next_record["visualProductIdentityUpdatedAt"] = utc_now_text()
    return next_record


def apply_visual_sku_identity_rewrites(record: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """Use completed visual analysis to replace weak SKU labels with product-aware English names."""
    sku_entries = record.get("skuEntries") if isinstance(record.get("skuEntries"), list) else []
    if not sku_entries:
        return record

    analysis = task.get("analysis") if isinstance(task.get("analysis"), dict) else {}
    if not analysis:
        return record

    rewrites = build_visual_sku_identity_rewrites(record, analysis)
    if not rewrites:
        return record

    task_id = clean_text(task.get("id"))
    next_record = dict(record)
    next_skus: list[dict[str, Any]] = []
    changed = False
    for index, entry in enumerate(sku_entries, start=1):
        if not isinstance(entry, dict):
            continue
        rewrite = rewrites.get(index)
        if not rewrite:
            next_skus.append(entry)
            continue
        next_name = clean_text(rewrite.get("name"))
        if not next_name:
            next_skus.append(entry)
            continue

        next_entry = dict(entry)
        current_name = clean_text(next_entry.get("name"))
        if current_name and not clean_text(next_entry.get("originalName")):
            next_entry["originalName"] = current_name
        next_entry["name"] = next_name
        next_entry["visualGeneratedName"] = next_name
        next_entry["visualGeneratedNameSource"] = "visual_generation"
        if task_id:
            next_entry["visualGeneratedNameTaskId"] = task_id

        component_labels = rewrite.get("componentLabels") if isinstance(rewrite.get("componentLabels"), dict) else {}
        component_skus = next_entry.get("componentSkus") if isinstance(next_entry.get("componentSkus"), list) else []
        if component_skus and component_labels:
            next_components: list[dict[str, Any]] = []
            for component_index, component in enumerate(component_skus, start=1):
                if not isinstance(component, dict):
                    continue
                component_label = clean_text(component_labels.get(component_index))
                if not component_label:
                    next_components.append(component)
                    continue
                next_component = dict(component)
                component_name = clean_text(next_component.get("name"))
                if component_name and not clean_text(next_component.get("originalName")):
                    next_component["originalName"] = component_name
                next_component["name"] = component_label
                next_component["visualGeneratedName"] = component_label
                next_components.append(next_component)
            next_entry["componentSkus"] = next_components
            if next_components != component_skus:
                changed = True

        next_skus.append(next_entry)
        changed = changed or next_name != current_name

    if not changed:
        return record
    next_record["skuEntries"] = next_skus
    next_record["visualSkuNamesRewrittenAt"] = utc_now_text()
    if task_id:
        next_record["visualSkuNamesRewrittenTaskId"] = task_id
    return next_record


def build_visual_sku_identity_rewrites(record: dict[str, Any], analysis: dict[str, Any]) -> dict[int, dict[str, Any]]:
    product_identity = visual_product_identity_from_analysis(analysis)
    identity_skus = product_identity.get("skus") if isinstance(product_identity.get("skus"), list) else []
    identity_rewrites: dict[int, dict[str, Any]] = {}
    for item in identity_skus:
        if not isinstance(item, dict):
            continue
        sku_index = safe_int(item.get("sku_index") or item.get("skuIndex"))
        standard_name = clamp_sku_identity_label(
            first_clean_text(item.get("standard_name"), item.get("standardName"), item.get("combo_sku_name"), item.get("comboSkuName"))
        )
        if sku_index <= 0 or not standard_name:
            continue
        component_labels: dict[int, str] = {}
        components = item.get("components") if isinstance(item.get("components"), list) else []
        for component_index, component in enumerate(components, start=1):
            if not isinstance(component, dict):
                continue
            component_name = clamp_sku_identity_label(
                first_clean_text(component.get("standard_name"), component.get("standardName"), component.get("product_name"), component.get("productName"))
            )
            if component_name:
                component_labels[component_index] = component_name
        identity_rewrites[sku_index] = {"name": standard_name, "componentLabels": component_labels}
    if identity_rewrites:
        return identity_rewrites

    sku_bindings = analysis.get("skuBindings") if isinstance(analysis.get("skuBindings"), list) else []
    if not sku_bindings:
        product_understanding = analysis.get("productUnderstanding") if isinstance(analysis.get("productUnderstanding"), dict) else {}
        sku_bindings = product_understanding.get("skuBindings") if isinstance(product_understanding.get("skuBindings"), list) else []
    if not sku_bindings:
        return {}

    reference_by_index = visual_reference_analysis_by_index(analysis)
    rewrites: dict[int, dict[str, Any]] = {}
    for binding in sku_bindings:
        if not isinstance(binding, dict):
            continue
        try:
            sku_index = int(binding.get("skuIndex") or 0)
        except (TypeError, ValueError):
            sku_index = 0
        if sku_index <= 0:
            continue

        components = [component for component in binding.get("components") or [] if isinstance(component, dict)]
        component_labels: dict[int, str] = {}
        for component_position, component in enumerate(components, start=1):
            reference_index = safe_int(component.get("referenceImageIndex"))
            reference_analysis = reference_by_index.get(reference_index, {})
            label = build_visual_component_sku_label(component, reference_analysis)
            if label:
                component_labels[component_position] = label

        labels = [component_labels[key] for key in sorted(component_labels) if component_labels.get(key)]
        if not labels:
            continue
        rewrite_name = "+".join(labels) if len(labels) > 1 else labels[0]
        rewrite_name = clamp_sku_identity_label(rewrite_name)
        if rewrite_name:
            rewrites[sku_index] = {"name": rewrite_name, "componentLabels": component_labels}
    return rewrites


def visual_reference_analysis_by_index(analysis: dict[str, Any]) -> dict[int, dict[str, Any]]:
    product_understanding = analysis.get("productUnderstanding") if isinstance(analysis.get("productUnderstanding"), dict) else {}
    if not product_understanding:
        product_understanding = analysis.get("productAnalysis") if isinstance(analysis.get("productAnalysis"), dict) else {}
    items = product_understanding.get("referenceAnalyses") if isinstance(product_understanding.get("referenceAnalyses"), list) else []
    if not items and isinstance(analysis.get("referenceAnalyses"), list):
        items = analysis.get("referenceAnalyses")
    result: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        index = safe_int(item.get("index"))
        if index > 0:
            result[index] = item
    return result


def build_visual_component_sku_label(component: dict[str, Any], reference_analysis: dict[str, Any]) -> str:
    prefix = extract_visual_quantity_prefix(
        first_clean_text(
            component.get("componentName"),
            component.get("optionText"),
            component.get("specText"),
        )
    )
    descriptor = build_visual_product_descriptor(component, reference_analysis)
    if not descriptor:
        descriptor = strip_leading_quantity_label(
            clean_visual_sku_text(first_clean_text(component.get("sourceTitle"), component.get("componentName")))
        )
    if not descriptor:
        return prefix
    if prefix and sku_identity_key(descriptor).startswith(sku_identity_key(prefix)):
        return clamp_sku_identity_label(descriptor)
    return clamp_sku_identity_label(f"{prefix} {descriptor}".strip() if prefix else descriptor)


def build_visual_product_descriptor(component: dict[str, Any], reference_analysis: dict[str, Any]) -> str:
    text_parts = [
        reference_analysis.get("visualIdentity"),
        reference_analysis.get("subject"),
        reference_analysis.get("category"),
        reference_analysis.get("shape"),
        reference_analysis.get("geometry"),
        reference_analysis.get("facetOrSideCount"),
        reference_analysis.get("printedPattern"),
        component.get("sourceTitle"),
    ]
    combined = " ".join(clean_text(part) for part in text_parts if clean_text(part)).lower()
    colors = visual_words(reference_analysis.get("colors"))
    materials = visual_words(reference_analysis.get("materials"))
    pattern = clean_text(reference_analysis.get("printedPattern")).lower()

    is_dice = "dice" in combined or "die" in combined
    if is_dice:
        has_wood = "wood" in combined or any("wood" in item for item in materials)
        has_white = "white" in combined or "white" in colors
        has_printed = "print" in combined or "icon" in combined or "text" in combined or "print" in pattern
        is_d12 = "d12" in combined or "twelve" in combined or "12" in combined or "dodeca" in combined
        is_six = "six" in combined or "6" in combined or "cube" in combined
        if is_d12:
            return "Wooden D12 Die" if has_wood else "D12 Die"
        if is_six:
            adjectives = []
            if has_white:
                adjectives.append("White")
            if has_printed:
                adjectives.append("Printed")
            adjectives.append("Six-Sided Dice")
            return " ".join(adjectives)
        adjectives = []
        if has_white:
            adjectives.append("White")
        if has_wood:
            adjectives.append("Wooden")
        if has_printed:
            adjectives.append("Printed")
        adjectives.append("Dice")
        return " ".join(adjectives)

    for key in ("visualIdentity", "subject", "category"):
        descriptor = strip_leading_quantity_label(clean_visual_sku_text(reference_analysis.get(key)))
        if descriptor:
            return descriptor
    return ""


def visual_words(value: Any) -> set[str]:
    if isinstance(value, list):
        return {clean_text(item).lower() for item in value if clean_text(item)}
    text = clean_text(value).lower()
    return {text} if text else set()


def extract_visual_quantity_prefix(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(pc|pcs|piece|pieces)\b", text, re.I)
    if match:
        amount = match.group(1)
        return f"{amount}pc" if amount == "1" else f"{amount}pcs"
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(pack|packs)\b", text, re.I)
    if match:
        amount = match.group(1)
        unit = "Pack" if amount == "1" else "Packs"
        return f"{amount} {unit}"
    return text if is_weak_visual_sku_label(text) else ""


def is_weak_visual_sku_label(value: Any) -> bool:
    text = clean_text(value).lower()
    if not text:
        return True
    return bool(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:pc|pcs|piece|pieces|pack|packs)", text, re.I)) or text in {
        "mix",
        "mixed",
        "random",
        "assorted",
        "white",
        "black",
        "red",
        "blue",
        "green",
        "yellow",
        "pink",
        "purple",
        "orange",
        "gray",
        "grey",
    }


def strip_leading_quantity_label(value: str) -> str:
    text = clean_text(value)
    text = re.sub(r"^\s*\d+(?:\.\d+)?\s*(?:pc|pcs|piece|pieces|pack|packs)\.?\s*", "", text, flags=re.I)
    return text.strip(" -_/,.+")


def clean_visual_sku_text(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?i)\bno\s+import\s+charges\b", " ", text)
    text = re.sub(r"(?i)\b\d+(?:,\d+)*\s*sold(?:\s+from\s+this\s+store)?\b", " ", text)
    text = re.sub(r"(?i)\bbest\s+seller\b", " ", text)
    text = re.sub(r"(?i)\bsuitable\s+for\b.*?\s+-\s+", " ", text)
    text = re.sub(r"(?i)\bsuitable\s+for\b.*$", " ", text)
    text = re.sub(r"(?i)\b(?:valentines?|christmas|birthday|gift|gifts|party|date\s+night)\b", " ", text)
    text = re.sub(r"[^A-Za-z0-9+\-/().\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_/,.+")
    return text


def clamp_sku_identity_label(value: Any, max_chars: int = 48) -> str:
    text = clean_visual_sku_text(value)
    if len(text) <= max_chars:
        return text
    parts = text.split()
    while parts and len(" ".join(parts)) > max_chars:
        parts.pop()
    return " ".join(parts) or text[:max_chars].rstrip()


def sku_identity_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", clean_text(value).lower())


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_visual_result_asset(
    *,
    record: dict[str, Any],
    task: dict[str, Any],
    module: dict[str, Any],
    order: int,
    role: str,
) -> dict[str, Any]:
    result_ref = visual_module_result_ref(module)
    is_remote = result_ref.startswith("http://") or result_ref.startswith("https://")
    record_id = clean_text(record.get("id")) or clean_text(task.get("linkRecordId")) or "link"
    task_id = clean_text(task.get("id")) or "visual"
    module_id = clean_text(module.get("targetSkuEntryId")) or str(order)
    if role == "sales-sku":
        asset_id = f"{record_id}-visual-sku-{task_id}-{module_id}"
    elif role == "product-main":
        asset_id = f"{record_id}-visual-main-{task_id}"
    else:
        asset_id = f"{record_id}-visual-product-{task_id}-{order}"
    asset = {
        "id": asset_id,
        "role": role,
        "sourceUrl": clean_text(module.get("outputPath")) or result_ref,
        "displayUrl": result_ref,
        "editedUrl": result_ref,
        "alt": clean_text(module.get("title")) or clean_text(module.get("purpose")) or f"{record.get('productTitle') or 'Product'} {order}",
    }
    if is_remote:
        asset["displayCloudUrl"] = result_ref
        asset["editedCloudUrl"] = result_ref
    return asset


def apply_visual_product_gallery_result(
    record: dict[str, Any],
    task: dict[str, Any],
    modules: list[dict[str, Any]],
) -> dict[str, Any]:
    next_record = dict(record)
    slot_map: dict[str, dict[str, Any]] = {}
    for slot in record.get("imageSlots") or []:
        if isinstance(slot, dict) and clean_text(slot.get("id")):
            slot_map[clean_text(slot.get("id"))] = dict(slot)

    generated_assets: list[dict[str, Any]] = []
    main_image = record.get("mainImage") if isinstance(record.get("mainImage"), dict) else {}
    for index, module in enumerate(modules, start=1):
        order = int(module.get("panelIndex") or index)
        is_main = order == 1
        asset = build_visual_result_asset(
            record=record,
            task=task,
            module=module,
            order=order,
            role="product-main" if is_main else "product-material",
        )
        generated_assets.append(asset)
        if is_main:
            main_image = {**main_image, **asset, "role": "product-main"}
            asset_id = clean_text(main_image.get("id")) or asset["id"]
            main_image["id"] = asset_id
            slot_map[f"{record.get('id')}-slot-main"] = {
                "id": f"{record.get('id')}-slot-main",
                "type": "main",
                "order": 0,
                "assetId": asset_id,
            }
            slot_map[f"{record.get('id')}-slot-carousel-1"] = {
                "id": f"{record.get('id')}-slot-carousel-1",
                "type": "carousel",
                "order": 1,
                "assetId": asset_id,
            }
        else:
            slot_map[f"{record.get('id')}-slot-carousel-{order}"] = {
                "id": f"{record.get('id')}-slot-carousel-{order}",
                "type": "carousel",
                "order": order,
                "assetId": asset["id"],
            }

    existing_assets = [
        asset
        for asset in record.get("productMaterialImages") or []
        if isinstance(asset, dict) and not clean_text(asset.get("id")).startswith(f"{record.get('id')}-visual-product-")
    ]
    product_assets = [asset for asset in generated_assets if asset.get("role") == "product-material"]
    next_record["schemaVersion"] = 3
    next_record["mainImage"] = main_image
    next_record["productMaterialImages"] = product_assets + existing_assets
    next_record["productImageGenerationCount"] = max(
        int(record.get("productImageGenerationCount") or 0),
        len(generated_assets),
    )
    next_record["imageSlots"] = sorted(slot_map.values(), key=lambda slot: int(slot.get("order") or 0))
    return next_record


def apply_visual_sku_gallery_result(
    record: dict[str, Any],
    task: dict[str, Any],
    modules: list[dict[str, Any]],
) -> dict[str, Any]:
    next_record = dict(record)
    sku_entries = record.get("skuEntries") if isinstance(record.get("skuEntries"), list) else []
    module_by_sku: dict[str, dict[str, Any]] = {}
    for index, module in enumerate(modules):
        sku_id = clean_text(module.get("targetSkuEntryId"))
        if not sku_id and index < len(sku_entries) and isinstance(sku_entries[index], dict):
            sku_id = clean_text(sku_entries[index].get("id"))
        if sku_id:
            module_by_sku[sku_id] = module

    next_skus: list[dict[str, Any]] = []
    for index, entry in enumerate(sku_entries, start=1):
        if not isinstance(entry, dict):
            continue
        module = module_by_sku.get(clean_text(entry.get("id")))
        if not module:
            next_skus.append(entry)
            continue
        result_ref = visual_module_result_ref(module)
        asset = build_visual_result_asset(record=record, task=task, module=module, order=index, role="sales-sku")
        next_skus.append(
            {
                **entry,
                "imageUrl": result_ref or entry.get("imageUrl"),
                "imageAsset": {
                    **(entry.get("imageAsset") if isinstance(entry.get("imageAsset"), dict) else {}),
                    **asset,
                    "sourceUrl": clean_text((entry.get("imageAsset") or {}).get("sourceUrl") if isinstance(entry.get("imageAsset"), dict) else "")
                    or clean_text(entry.get("imageUrl"))
                    or asset.get("sourceUrl"),
                },
            }
        )
    next_record["schemaVersion"] = 3
    next_record["skuEntries"] = next_skus
    return next_record


def split_mother_image_stateless(
    *,
    user_id: str,
    mother_image_ref: str,
    layout: str | None = None,
    upload_to_oss: bool | None = None,
    target_size: int | None = None,
    safe_margin_ratio: float | None = None,
    output_format: str | None = None,
    quality: int | None = None,
    sharpen: float | None = None,
) -> dict[str, Any]:
    resolved_layout = clean_text(layout) or visual_setting("VISUAL_DEFAULT_LAYOUT", "3x3")
    task = create_visual_task(
        user_id=user_id,
        mode="manual-split",
        layout=resolved_layout,
        requested_count=layout_panel_count(resolved_layout),
        source_image_ref=mother_image_ref,
    )
    return split_visual_task(
        task_id=task["id"],
        user_id=user_id,
        mother_image_ref=mother_image_ref,
        upload_to_oss=upload_to_oss,
        target_size=target_size,
        safe_margin_ratio=safe_margin_ratio,
        output_format=output_format,
        quality=quality,
        sharpen=sharpen,
    )


def persist_plan(
    task_id: str,
    user_id: str,
    source_image_ref: str,
    plan: dict[str, Any],
    mother_prompt: str,
) -> None:
    now = utc_now_text()
    plan = dict(plan or {})
    plan["visualPromptLogicVersion"] = VISUAL_PROMPT_LOGIC_VERSION
    tasks = plan.get("panelTasks") or []
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET source_image_ref = ?, analysis_json = ?, prompt_text = ?, status = ?, updated_at = ?, error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (
                source_image_ref,
                json.dumps(plan, ensure_ascii=False),
                mother_prompt,
                TASK_STATUS_PLANNED,
                now,
                task_id,
                user_id,
            ),
        )
        for task in tasks:
            upsert_module(
                conn,
                task_id=task_id,
                panel_index=int(task["panelIndex"]),
                position=clean_text(task.get("position")),
                slot_type=clean_text(task.get("slotType")),
                title=clean_text(task.get("title")),
                purpose=clean_text(task.get("purpose")),
                prompt=clean_text(task.get("panelPrompt")),
                output_path="",
                output_url="",
                status=TASK_STATUS_PLANNED,
            )


def persist_partial_plan(
    *,
    task_id: str,
    user_id: str,
    source_image_ref: str,
    plan: dict[str, Any],
) -> None:
    now = utc_now_text()
    partial_plan = dict(plan or {})
    partial_plan["visualPromptLogicVersion"] = VISUAL_PROMPT_LOGIC_VERSION
    partial_plan["promptLogicVersion"] = VISUAL_PROMPT_LOGIC_VERSION
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET source_image_ref = ?, analysis_json = ?, status = ?, updated_at = ?, error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (
                source_image_ref,
                json.dumps(partial_plan, ensure_ascii=False),
                TASK_STATUS_RUNNING,
                now,
                task_id,
                user_id,
            ),
        )


def persist_split_result(
    *,
    task_id: str,
    user_id: str,
    mother_path: Path,
    split_dir: Path,
    manifest: dict[str, Any],
    upload_to_oss: bool,
) -> list[dict[str, Any]]:
    now = utc_now_text()
    module_results: list[dict[str, Any]] = []
    panels = manifest.get("panels") if isinstance(manifest.get("panels"), list) else []
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        for panel in panels:
            panel_index = int(panel.get("panelIndex") or 0)
            output_name = clean_text(panel.get("output"))
            output_path = split_dir / output_name
            output_url = ""
            if upload_to_oss and output_path.exists():
                try:
                    uploaded = upload_image_bytes(
                        output_path.read_bytes(),
                        f"image/{output_path.suffix.lower().lstrip('.') or 'webp'}",
                        f"visual/{user_id}/{task_id}/panel-{panel_index:02d}",
                    )
                    output_url = uploaded.get("url", "")
                except ImageStorageError as exc:
                    output_url = ""
                    manifest.setdefault("uploadErrors", []).append({"panelIndex": panel_index, "error": str(exc)})
            upsert_module(
                conn,
                task_id=task_id,
                panel_index=panel_index,
                position=clean_text(panel.get("position")),
                slot_type="",
                title="",
                purpose="",
                prompt="",
                output_path=str(output_path),
                output_url=output_url,
                status=TASK_STATUS_SPLIT,
            )
            module_results.append(
                {
                    "panelIndex": panel_index,
                    "position": clean_text(panel.get("position")),
                    "outputPath": str(output_path),
                    "outputUrl": output_url,
                    "status": TASK_STATUS_SPLIT,
                }
            )
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET mother_image_path = ?, manifest_json = ?, status = ?, updated_at = ?, error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (
                str(mother_path),
                json.dumps(manifest, ensure_ascii=False),
                TASK_STATUS_COMPLETED if upload_to_oss else TASK_STATUS_SPLIT,
                now,
                task_id,
                user_id,
            ),
        )
    return module_results


def persist_product_analysis(
    *,
    task_id: str,
    user_id: str,
    source_image_ref: str,
    product_analysis: dict[str, Any],
) -> None:
    now = utc_now_text()
    analysis_payload = {
        "stage": "product_analysis",
        "productUnderstanding": product_analysis,
        "productAnalysis": product_analysis,
        "visualPromptLogicVersion": VISUAL_PROMPT_LOGIC_VERSION,
        "promptLogicVersion": VISUAL_PROMPT_LOGIC_VERSION,
    }
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET source_image_ref = ?, analysis_json = ?, status = ?, updated_at = ?, error_message = NULL
            WHERE id = ? AND user_id = ?
            """,
            (
                source_image_ref,
                json.dumps(analysis_payload, ensure_ascii=False),
                TASK_STATUS_RUNNING,
                now,
                task_id,
                user_id,
            ),
        )


def upsert_module(
    conn,
    *,
    task_id: str,
    panel_index: int,
    position: str,
    slot_type: str,
    title: str,
    purpose: str,
    prompt: str,
    output_path: str,
    output_url: str,
    status: str,
) -> None:
    now = utc_now_text()
    module_id = f"{task_id}_panel_{panel_index:02d}"
    conn.execute(
        """
        INSERT INTO visual_generation_modules (
            id, task_id, panel_index, position, slot_type, title, purpose, prompt,
            output_path, output_url, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id, panel_index) DO UPDATE SET
            position = COALESCE(NULLIF(excluded.position, ''), visual_generation_modules.position),
            slot_type = COALESCE(NULLIF(excluded.slot_type, ''), visual_generation_modules.slot_type),
            title = COALESCE(NULLIF(excluded.title, ''), visual_generation_modules.title),
            purpose = COALESCE(NULLIF(excluded.purpose, ''), visual_generation_modules.purpose),
            prompt = COALESCE(NULLIF(excluded.prompt, ''), visual_generation_modules.prompt),
            output_path = COALESCE(NULLIF(excluded.output_path, ''), visual_generation_modules.output_path),
            output_url = COALESCE(NULLIF(excluded.output_url, ''), visual_generation_modules.output_url),
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (
            module_id,
            task_id,
            panel_index,
            position,
            slot_type,
            title,
            purpose,
            prompt,
            output_path,
            output_url,
            status,
            now,
            now,
        ),
    )


def update_task_status(task_id: str, user_id: str, status: str, *, clear_error: bool = False) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        if clear_error:
            conn.execute(
                """
                UPDATE visual_generation_tasks
                SET status = ?, error_message = NULL, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (status, utc_now_text(), task_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE visual_generation_tasks SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (status, utc_now_text(), task_id, user_id),
            )


def try_mark_visual_task_running(task_id: str, user_id: str, *, exclude_task_id: str | None = None) -> tuple[bool, str]:
    user_limit = visual_int_setting("VISUAL_USER_CONCURRENCY_LIMIT", 5, minimum=0, maximum=100)
    now = utc_now_text()
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(?)::bigint)", (f"visual-generation:user:{user_id}",))
        row = conn.execute(
            "SELECT status FROM visual_generation_tasks WHERE id = ? AND user_id = ? FOR UPDATE",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise VisualTaskCancelled("visual task was removed")
        if row["status"] == TASK_STATUS_CANCELLED:
            raise VisualTaskCancelled("visual task was cancelled")

        if user_limit > 0:
            running_count = count_running_visual_tasks_for_user(conn, user_id, exclude_task_id=exclude_task_id or task_id)
            running_count += running_runtime_slot_count(user_id)
            if running_count >= user_limit:
                return False, f"当前成员已有 {running_count} 个模型任务正在运行，成员并发上限为 {user_limit}"

        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET status = ?, error_message = NULL, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (TASK_STATUS_RUNNING, now, task_id, user_id),
        )
    return True, ""


def mark_task_failed(task_id: str, user_id: str, error_message: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        completed_status = resolve_completed_task_status(conn, task_id=task_id, user_id=user_id)
        if completed_status:
            conn.execute(
                """
                UPDATE visual_generation_tasks
                SET status = ?, error_message = NULL, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (completed_status, utc_now_text(), task_id, user_id),
            )
            return
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (TASK_STATUS_FAILED, error_message[:2000], utc_now_text(), task_id, user_id),
        )


def resolve_completed_task_status(conn, *, task_id: str, user_id: str) -> str:
    row = conn.execute(
        """
        SELECT requested_count, mother_image_path, mother_image_url, manifest_json
        FROM visual_generation_tasks
        WHERE id = ? AND user_id = ?
        """,
        (task_id, user_id),
    ).fetchone()
    if row is None:
        return ""

    manifest = parse_json(row["manifest_json"], {})
    manifest_panels = manifest.get("panels") if isinstance(manifest, dict) else []
    try:
        requested_count = int(row["requested_count"] or 0)
    except (TypeError, ValueError):
        requested_count = 0
    expected_count = requested_count or (len(manifest_panels) if isinstance(manifest_panels, list) else 0)
    if expected_count <= 0:
        return ""

    has_mother_image = bool(clean_text(row["mother_image_path"]) or clean_text(row["mother_image_url"]))
    if not has_mother_image:
        return ""

    module_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN COALESCE(output_url, '') != '' THEN 1 ELSE 0 END) AS url_count,
            SUM(CASE WHEN COALESCE(output_url, '') != '' OR COALESCE(output_path, '') != '' THEN 1 ELSE 0 END) AS output_count
        FROM visual_generation_modules
        WHERE task_id = ?
        """,
        (task_id,),
    ).fetchone()
    if module_row is None:
        return ""
    output_count = int(module_row["output_count"] or 0)
    if output_count < expected_count:
        return ""
    url_count = int(module_row["url_count"] or 0)
    return TASK_STATUS_COMPLETED if url_count >= expected_count else TASK_STATUS_SPLIT


def mark_task_retry_waiting(task_id: str, user_id: str, error_message: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (TASK_STATUS_RETRY_WAITING, error_message[:2000], utc_now_text(), task_id, user_id),
        )


def fetch_modules(conn, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM visual_generation_modules
        WHERE task_id = ?
        ORDER BY panel_index ASC
        """,
        (task_id,),
    ).fetchall()
    return [module_row_to_api(row) for row in rows]


def fetch_modules_by_task_ids(conn, task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not task_ids:
        return {}
    placeholders = ",".join("?" for _ in task_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM visual_generation_modules
        WHERE task_id IN ({placeholders})
        ORDER BY task_id ASC, panel_index ASC
        """,
        task_ids,
    ).fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row["task_id"], []).append(module_row_to_api(row))
    return result


def task_row_to_api(row, *, modules: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = parse_json(row["analysis_json"], {})
    manifest = parse_json(row["manifest_json"], {})
    record = parse_json(row["record_json"], {})
    queue_meta = record.get("visualQueueMeta") if isinstance(record.get("visualQueueMeta"), dict) else {}
    api_task = {
        "id": row["id"],
        "userId": row["user_id"],
        "linkRecordId": row["link_record_id"],
        "productId": row["product_id"],
        "runBatchId": clean_text(queue_meta.get("runBatchId")),
        "mode": row["mode"],
        "layout": row["layout"],
        "requestedCount": int(row["requested_count"] or 0),
        "status": row["status"],
        "sourceImageRef": row["source_image_ref"],
        "referenceImageRefs": record.get("visualReferenceImages") if isinstance(record.get("visualReferenceImages"), list) else [],
        "record": record,
        "analysis": analysis,
        "promptText": row["prompt_text"],
        "motherImagePath": row["mother_image_path"],
        "motherImageUrl": row["mother_image_url"],
        "manifest": manifest,
        "modules": modules,
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    progress = get_visual_progress(row["id"])
    if progress:
        api_task.update(
            {
                "progressState": progress.get("state"),
                "progressMessage": progress.get("message") or progress.get("waitReason"),
                "activeChannelId": progress.get("channelId"),
                "activeCredentialId": progress.get("credentialId"),
                "activeCredentialName": progress.get("credentialName"),
                "activeModel": progress.get("model"),
                "timeoutSeconds": progress.get("timeoutSeconds"),
                "switchingErrorType": progress.get("errorType"),
                "lastSwitchChannelId": progress.get("lastSwitchChannelId"),
                "lastSwitchCredentialId": progress.get("lastSwitchCredentialId"),
                "lastSwitchCredentialName": progress.get("lastSwitchCredentialName"),
                "lastSwitchModel": progress.get("lastSwitchModel"),
                "lastSwitchErrorType": progress.get("lastSwitchErrorType"),
                "lastSwitchError": progress.get("lastSwitchError"),
            }
        )
    if row["status"] == TASK_STATUS_RETRY_WAITING:
        retry_error = clean_text(progress.get("lastError") or progress.get("error") or row["error_message"])
        api_task.update(
            {
                "retryCount": safe_int(progress.get("retryCount")),
                "nextRetryAt": progress.get("nextRetryAt"),
                "retryErrorMessage": retry_error or row["error_message"],
            }
        )
    return api_task


def module_row_to_api(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "taskId": row["task_id"],
        "panelIndex": int(row["panel_index"] or 0),
        "position": row["position"],
        "slotType": row["slot_type"],
        "title": row["title"],
        "purpose": row["purpose"],
        "prompt": row["prompt"],
        "outputPath": row["output_path"],
        "outputUrl": row["output_url"],
        "targetSlotId": row["target_slot_id"],
        "targetSkuEntryId": row["target_sku_entry_id"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def normalize_reference_image_refs(value: Any, fallback_ref: str | None = None) -> list[dict[str, str]]:
    raw_items = value if isinstance(value, list) else []
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_ref(url_value: Any, label_value: Any = "", role_value: Any = "") -> None:
        url = clean_text(url_value)
        if not url or url in seen:
            return
        seen.add(url)
        refs.append(
            {
                "url": url,
                "label": clean_text(label_value) or f"Reference image {len(refs) + 1}",
                "role": clean_text(role_value) or "reference-image",
            }
        )

    for item in raw_items:
        if isinstance(item, dict):
            add_ref(
                item.get("url") or item.get("imageUrl") or item.get("sourceUrl"),
                item.get("label") or item.get("name"),
                item.get("role"),
            )
        else:
            add_ref(item)
    add_ref(fallback_ref, "Primary reference image", "primary-reference")

    limit = visual_int_setting("VISUAL_MAX_REFERENCE_IMAGES", 4, minimum=1, maximum=9)
    return refs[:limit]


def build_visual_prompt_context(*, task: dict[str, Any], record: dict[str, Any], reference_refs: list[dict[str, Any]]) -> dict[str, Any]:
    product_title = (
        clean_text(record.get("productTitle"))
        or clean_text(record.get("title"))
        or clean_text(record.get("productName"))
        or clean_text(task.get("productTitle"))
        or "Untitled product"
    )
    sku_bindings = extract_record_sku_bindings(record, reference_refs)
    sku_reference_bindings = build_sku_reference_bindings(sku_bindings)
    return {
        "linkRecordId": clean_text(task.get("linkRecordId")) or clean_text(record.get("id")),
        "productId": clean_text(task.get("productId")) or clean_text(record.get("productId")),
        "mode": clean_text(task.get("mode")),
        "requestedCount": task.get("requestedCount"),
        "productTitle": product_title,
        "skuNames": extract_record_sku_names(record),
        "skuBindingRule": (
            "SKU names may be quantity-like or repeated across source products. "
            "Always interpret each SKU/component through skuBindings and skuCombinationBindings, "
            "including sourceTitle, referenceImageIndex, and skuReferenceBindings. Do not merge 1pc/6pc labels across different products. "
            "When a SKU name is only a quantity/unit, the sourceTitle and bound reference image are the product identity. "
            "The visual identity of each SKU comes from its bound reference image, not from SKU text alone."
        ),
        "skuBindings": sku_bindings,
        "skuCombinationBindings": [
            binding
            for binding in sku_bindings
            if binding.get("skuKind") == "combo" or len(binding.get("components") or []) > 1
        ],
        "skuReferenceBindings": sku_reference_bindings,
        "referenceImageBindingRule": (
            "All reference images are equal product image parameters. Do not treat the first image as the only main product, "
            "and do not rank images as main/material. Use each image label and SKU binding to identify which product or SKU "
            "component it shows. Preserve the exact visible product subject appearance and do not replace selected SKU "
            "components with generic category items. For different-product bundles, keep every reference image tied to its "
            "own SKU name and source product title. Image facts override title text. Titles may support function/use/occasion only. "
            "For appearance, material, surface finish, tactile texture, wrinkles/folds, rigidity/flexibility, color, body shape, construction, "
            "quantity, and printed pattern, the bound reference image has 100% authority. Preserve silhouette, geometry, facet/side count, "
            "shape, visible color, material, surface texture, edge details, and printed pattern for every bound SKU."
        ),
        "referenceImages": [
            {
                "index": index + 1,
                "label": clean_text(ref.get("label") if isinstance(ref, dict) else ref) or f"Reference image {index + 1}",
                "role": clean_text(ref.get("role") if isinstance(ref, dict) else "") or "reference-image",
            }
            for index, ref in enumerate(reference_refs)
        ],
    }


def build_sku_reference_bindings(sku_bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for sku in sku_bindings:
        if not isinstance(sku, dict):
            continue
        sku_name = clean_text(sku.get("skuName"))
        sku_kind = clean_text(sku.get("skuKind"))
        for component in sku.get("components") or []:
            if not isinstance(component, dict):
                continue
            reference_index = component.get("referenceImageIndex")
            try:
                reference_index = int(reference_index)
            except (TypeError, ValueError):
                reference_index = 0
            if reference_index <= 0:
                continue
            component_name = clean_text(component.get("componentName"))
            source_title = clean_text(component.get("sourceTitle"))
            spec_text = clean_text(component.get("specText"))
            option_text = clean_text(component.get("optionText"))
            visual_lock = (
                f"Reference image {reference_index} is the visual source of truth for SKU {sku_name or component_name}. "
                "Preserve the exact visible silhouette, geometry, facet/side count, shape, color, material, surface finish, "
                "tactile texture, wrinkles/folds, rigidity/flexibility, quantity, edge/rim details, and printed pattern from that image. "
                "Titles and SKU names may support function/use/occasion only and must not override the visible product appearance or material texture."
            )
            bindings.append(
                {
                    "referenceImageIndex": reference_index,
                    "skuName": sku_name,
                    "skuKind": sku_kind,
                    "componentName": component_name,
                    "sourceProductTitle": source_title,
                    "specText": spec_text,
                    "optionText": option_text,
                    "visualLock": visual_lock,
                    "bindingText": " / ".join(
                        part
                        for part in (
                            f"SKU {sku_name}" if sku_name else "",
                            f"component {component_name}" if component_name else "",
                            f"product title {source_title}" if source_title else "",
                            f"visual source reference image {reference_index}" if reference_index else "",
                        )
                        if part
                    ),
                }
            )
    return sorted(bindings, key=lambda item: (int(item.get("referenceImageIndex") or 0), clean_text(item.get("skuName"))))[:80]


def extract_record_sku_bindings(record: dict[str, Any], reference_refs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    sku_entries = record.get("skuEntries")
    if not isinstance(sku_entries, list):
        return []
    reference_lookup = build_reference_lookup(reference_refs or [])
    source_lookup = build_record_source_lookup(record)
    bindings: list[dict[str, Any]] = []
    for index, entry in enumerate(sku_entries, start=1):
        if not isinstance(entry, dict):
            continue
        sku_name = clean_text(entry.get("name")) or f"SKU {index}"
        sku_kind = clean_text(entry.get("kind")) or ("combo" if len(entry.get("componentSkus") or []) > 1 else "single")
        components = extract_sku_component_bindings(entry, sku_name, reference_lookup, source_lookup)
        composition_text = " + ".join(format_component_binding(component) for component in components) or sku_name
        reference_indexes = sorted(
            {
                int(component["referenceImageIndex"])
                for component in components
                if isinstance(component.get("referenceImageIndex"), int) and component.get("referenceImageIndex")
            }
        )
        binding: dict[str, Any] = {
            "skuIndex": index,
            "skuName": sku_name,
            "skuKind": sku_kind,
            "compositionText": composition_text,
            "components": components,
        }
        if reference_indexes:
            binding["referenceIndexes"] = reference_indexes
        bindings.append(binding)
    return bindings[:50]


def extract_sku_component_bindings(
    sku_entry: dict[str, Any],
    sku_name: str,
    reference_lookup: dict[str, Any],
    source_lookup: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    raw_components = [item for item in sku_entry.get("componentSkus") or [] if isinstance(item, dict)]
    components = raw_components or source_links_as_components(sku_entry, source_lookup)
    if not components:
        components = [
            {
                "name": sku_name,
                "specText": sku_name,
                "optionText": "",
                "sourceTitle": "",
                "imageUrl": first_clean_text(
                    sku_entry.get("imageUrl"),
                    *asset_image_url_candidates(sku_entry.get("imageAsset")),
                ),
            }
        ]

    result: list[dict[str, Any]] = []
    for index, component in enumerate(components[:12], start=1):
        component_name = first_clean_text(
            component.get("name"),
            component.get("optionText"),
            component.get("specText"),
            component.get("sourceTitle"),
            sku_name,
        )
        source_title = resolve_component_source_title(component, source_lookup)
        spec_text = clean_text(component.get("specText"))
        option_text = clean_text(component.get("optionText"))
        url_candidates = [
            clean_text(component.get("imageUrl")),
            clean_text(component.get("sourceImageUrl")),
            clean_text(sku_entry.get("imageUrl")),
            *asset_image_url_candidates(sku_entry.get("imageAsset")),
        ]
        reference_index = match_reference_index(
            reference_lookup,
            url_candidates=url_candidates,
            label_candidates=[source_title, component_name, spec_text, option_text, sku_name],
            source_title=source_title,
            component_name=component_name,
        )
        result.append(
            {
                "componentIndex": index,
                "componentName": component_name,
                "sourceTitle": source_title,
                "specText": spec_text,
                "optionText": option_text,
                "referenceImageIndex": reference_index,
            }
        )
    return result


def source_links_as_components(sku_entry: dict[str, Any], source_lookup: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for link in sku_entry.get("sourceSkuLinks") or []:
        if not isinstance(link, dict):
            continue
        components.append(
            {
                "name": first_clean_text(link.get("optionText"), link.get("specText"), link.get("sourceTitle")),
                "specText": clean_text(link.get("specText")),
                "optionText": clean_text(link.get("optionText")),
                "sourceTitle": resolve_component_source_title(link, source_lookup),
                "imageUrl": clean_text(link.get("imageUrl")),
            }
        )
    return components


def build_record_source_lookup(record: dict[str, Any]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for source in record.get("sourceLinks") or []:
        if not isinstance(source, dict):
            continue
        meta = {
            "title": clean_text(source.get("title")),
            "shopName": clean_text(source.get("shopName")),
            "productUrl": clean_text(source.get("productUrl")),
            "imageUrl": clean_text(source.get("imageUrl")),
        }
        for key in (source.get("id"), source.get("productUrl")):
            clean_key = clean_text(key)
            if clean_key:
                lookup[clean_key] = meta
    return lookup


def resolve_component_source_title(component: dict[str, Any], source_lookup: dict[str, dict[str, str]]) -> str:
    source_meta = source_lookup.get(clean_text(component.get("sourceId"))) or source_lookup.get(
        clean_text(component.get("sourceUrl") or component.get("sourceProductUrl"))
    )
    if source_meta:
        title = clean_text(source_meta.get("title"))
        if title:
            return title
    return clean_text(component.get("sourceTitle"))


def build_reference_lookup(reference_refs: list[dict[str, Any]]) -> dict[str, Any]:
    by_url: dict[str, int] = {}
    labels: list[tuple[int, str]] = []
    for index, ref in enumerate(reference_refs, start=1):
        if not isinstance(ref, dict):
            continue
        url = clean_text(ref.get("url") or ref.get("imageUrl") or ref.get("sourceUrl"))
        if url and url not in by_url:
            by_url[url] = index
        label = clean_text(ref.get("label") or ref.get("name"))
        if label:
            labels.append((index, normalize_lookup_text(label)))
    return {"byUrl": by_url, "labels": labels}


def match_reference_index(
    reference_lookup: dict[str, Any],
    *,
    url_candidates: list[str],
    label_candidates: list[str],
    source_title: str,
    component_name: str,
) -> int | None:
    by_url = reference_lookup.get("byUrl") if isinstance(reference_lookup.get("byUrl"), dict) else {}
    for url in url_candidates:
        clean_url = clean_text(url)
        if clean_url and clean_url in by_url:
            return by_url[clean_url]

    labels = reference_lookup.get("labels") if isinstance(reference_lookup.get("labels"), list) else []
    source_key = normalize_lookup_text(source_title)
    component_key = normalize_lookup_text(component_name)
    if source_key and component_key:
        for index, label_key in labels:
            if source_key in label_key and component_key in label_key:
                return index

    for candidate in label_candidates:
        candidate_key = normalize_lookup_text(candidate)
        if not candidate_key:
            continue
        for index, label_key in labels:
            if candidate_key in label_key or label_key in candidate_key:
                return index
    return None


def format_component_binding(component: dict[str, Any]) -> str:
    component_name = clean_text(component.get("componentName")) or "component"
    source_title = clean_text(component.get("sourceTitle"))
    return f"{component_name} from {source_title}" if source_title else component_name


def first_clean_text(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def asset_image_url_candidates(asset: Any) -> list[str]:
    if not isinstance(asset, dict):
        return []
    return [
        clean_text(asset.get(key))
        for key in ("editedCloudUrl", "displayCloudUrl", "sourceCloudUrl", "editedUrl", "displayUrl", "sourceUrl")
        if clean_text(asset.get(key))
    ]


def normalize_lookup_text(value: Any) -> str:
    return "".join(char.lower() for char in clean_text(value) if char.isalnum())


def extract_record_sku_names(record: dict[str, Any]) -> list[str]:
    sku_entries = record.get("skuEntries")
    if not isinstance(sku_entries, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(sku_entries, start=1):
        if not isinstance(entry, dict):
            continue
        name = clean_text(entry.get("name")) or f"SKU {index}"
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names[:50]


def materialize_reference_image_refs(reference_refs: list[dict[str, Any]], task_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for index, ref in enumerate(reference_refs, start=1):
        url = clean_text(ref.get("url") if isinstance(ref, dict) else ref)
        if not url:
            continue
        try:
            paths.append(materialize_image_ref(url, task_dir / f"reference_{index:02d}"))
        except Exception as exc:
            label = clean_text(ref.get("label") if isinstance(ref, dict) else "") or f"Reference image {index}"
            raise VisualTaskError(f"reference image download failed ({label}): {exc}") from exc
    return paths

def materialize_image_ref(source_ref: str, target_without_suffix: Path) -> Path:
    clean_ref = clean_text(source_ref)
    if not clean_ref:
        raise VisualTaskError("image ref is empty")

    source_path = Path(clean_ref)
    if source_path.exists() and source_path.is_file():
        suffix = source_path.suffix.lower() or ".png"
        target_path = target_without_suffix.with_suffix(suffix)
        if source_path.resolve() != target_path.resolve():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
        return target_path

    image_bytes, content_type, source_name = read_image_ref(clean_ref)
    suffix = Path(source_name).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = content_type_to_suffix(content_type)
    target_path = target_without_suffix.with_suffix(suffix)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(image_bytes)
    return target_path


def task_output_dir(user_id: str, task_id: str) -> Path:
    return VISUAL_STORAGE_DIR / sanitize_path_part(user_id) / sanitize_path_part(task_id)


def content_type_to_suffix(content_type: str) -> str:
    clean = clean_text(content_type).lower()
    if "png" in clean:
        return ".png"
    if "webp" in clean:
        return ".webp"
    return ".jpg"


def layout_panel_count(layout: str) -> int:
    rows, cols = layout.split("x", 1) if "x" in layout else ("3", "3")
    try:
        return int(rows) * int(cols)
    except ValueError:
        return 9


def pick_record_image(record: dict[str, Any]) -> str:
    main_image = record.get("mainImage")
    if isinstance(main_image, dict):
        for key in ("editedCloudUrl", "displayCloudUrl", "sourceCloudUrl", "editedUrl", "displayUrl", "sourceUrl"):
            value = clean_text(main_image.get(key))
            if value:
                return value
    for key in ("productImageUrl", "mainImageUrl"):
        value = clean_text(record.get(key))
        if value:
            return value
    images = record.get("productMaterialImages")
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            for key in ("editedCloudUrl", "displayCloudUrl", "sourceCloudUrl", "editedUrl", "displayUrl", "sourceUrl"):
                value = clean_text(image.get(key))
                if value:
                    return value
    return ""


def parse_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def sanitize_path_part(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in clean_text(value))
    return clean.strip("-")[:80] or "default"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
