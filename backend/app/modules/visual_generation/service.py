from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from app.core.config import STORAGE_DIR
from app.core.database import (
    assert_user_api_usage_allowed,
    clean_text,
    get_connection,
    list_link_list_records,
    record_api_usage_safe,
    upsert_link_list_record,
    utc_now_text,
)
from app.modules.image_storage.aliyun_oss import ImageStorageError, read_image_ref, upload_image_bytes
from app.modules.visual_generation.clients import (
    VisualGenerationError,
    build_api_url,
    get_ai_settings,
    get_ai_stage_settings,
    get_runtime_setting,
    is_rate_limit_error,
    is_request_too_large_error,
    request_generated_image,
)
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
TASK_STATUS_SPLIT = "split"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
ACTIVE_VISUAL_TASK_STATUSES = (TASK_STATUS_QUEUED, TASK_STATUS_RUNNING, TASK_STATUS_RETRY_WAITING)

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


class VisualTaskError(ValueError):
    pass


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
) -> None:
    record_api_usage_safe(
        provider="openai-compatible",
        api_type=api_type,
        stage=stage,
        model=model,
        user_id=user_id,
        channel_id=settings.get("channel_id"),
        status=status,
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
    user_limit = visual_int_setting("VISUAL_USER_CONCURRENCY_LIMIT", 1, minimum=0, maximum=100)
    team_limit = visual_int_setting("VISUAL_TEAM_CONCURRENCY_LIMIT", 3, minimum=0, maximum=500)
    if user_limit <= 0 and team_limit <= 0:
        return

    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        user_count = count_active_visual_tasks_for_user(conn, user_id, exclude_task_id=exclude_task_id)
        team_scope = resolve_visual_team_scope(conn, user_id)
        team_count = (
            count_active_visual_tasks_for_team(conn, team_scope["adminUserId"], exclude_task_id=exclude_task_id)
            if team_scope["adminUserId"]
            else user_count
        )

    if user_limit > 0 and user_count >= user_limit:
        raise VisualTaskError(f"当前成员已有 {user_count} 个生图任务在排队或运行，成员并发上限为 {user_limit}")
    if team_limit > 0 and team_count >= team_limit:
        team_name = team_scope.get("teamName") or "当前团队"
        raise VisualTaskError(f"{team_name} 已有 {team_count} 个生图任务在排队或运行，团队并发上限为 {team_limit}")


def resolve_visual_team_scope(conn, user_id: str) -> dict[str, str]:
    row = conn.execute(
        """
        SELECT
            users.id,
            users.role,
            users.manager_user_id,
            teams.id AS team_id,
            teams.name AS team_name
        FROM users
        LEFT JOIN teams ON teams.admin_user_id = CASE
            WHEN users.role = 'admin' THEN users.id
            ELSE users.manager_user_id
        END
        WHERE users.id = ?
        """,
        (user_id,),
    ).fetchone()
    if not row:
        return {"adminUserId": "", "teamId": "", "teamName": ""}
    admin_user_id = row["id"] if row["role"] == "admin" else row["manager_user_id"]
    return {
        "adminUserId": clean_text(admin_user_id),
        "teamId": clean_text(row["team_id"]),
        "teamName": clean_text(row["team_name"]),
    }


def count_active_visual_tasks_for_user(conn, user_id: str, *, exclude_task_id: str | None = None) -> int:
    params: list[Any] = [user_id, *ACTIVE_VISUAL_TASK_STATUSES]
    placeholders = ", ".join("?" for _ in ACTIVE_VISUAL_TASK_STATUSES)
    where = f"user_id = ? AND status IN ({placeholders})"
    if exclude_task_id:
        where += " AND id != ?"
        params.append(exclude_task_id)
    return int(conn.execute(f"SELECT COUNT(*) FROM visual_generation_tasks WHERE {where}", params).fetchone()[0] or 0)


def count_active_visual_tasks_for_team(conn, admin_user_id: str, *, exclude_task_id: str | None = None) -> int:
    params: list[Any] = [admin_user_id, admin_user_id, *ACTIVE_VISUAL_TASK_STATUSES]
    placeholders = ", ".join("?" for _ in ACTIVE_VISUAL_TASK_STATUSES)
    task_filter = ""
    if exclude_task_id:
        task_filter = "AND visual_generation_tasks.id != ?"
        params.append(exclude_task_id)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM visual_generation_tasks
            JOIN users ON users.id = visual_generation_tasks.user_id
            WHERE (users.id = ? OR users.manager_user_id = ?)
              AND visual_generation_tasks.status IN ({placeholders})
              {task_filter}
            """,
            params,
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
        team_scope = resolve_visual_team_scope(conn, user_id)
        team_active_count = (
            count_active_visual_tasks_for_team(conn, team_scope["adminUserId"])
            if team_scope.get("adminUserId")
            else active_count
        )
    user_limit = visual_int_setting("VISUAL_USER_CONCURRENCY_LIMIT", 1, minimum=0, maximum=100)
    team_limit = visual_int_setting("VISUAL_TEAM_CONCURRENCY_LIMIT", 3, minimum=0, maximum=500)
    return {
        "counts": counts,
        "activeCount": active_count,
        "teamActiveCount": team_active_count,
        "userConcurrencyLimit": user_limit,
        "teamConcurrencyLimit": team_limit,
        "team": team_scope,
    }


def ensure_visual_generation_schema(conn) -> None:
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
        """
    )


def create_visual_task(
    *,
    user_id: str,
    record: dict[str, Any] | None = None,
    link_record_id: str | None = None,
    product_id: str | None = None,
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


def delete_visual_task(*, task_id: str, user_id: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        row = conn.execute(
            "SELECT id FROM visual_generation_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        if row is None:
            raise VisualTaskError("visual task not found")
        conn.execute("DELETE FROM visual_generation_modules WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM visual_generation_tasks WHERE id = ? AND user_id = ?", (task_id, user_id))

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
) -> bytes:
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
    update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
    try:
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
            record_visual_api_usage(
                analysis_settings,
                user_id=user_id,
                stage="visual_analysis",
                api_type="chat",
                model=text_model,
                status="success",
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
                )
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
                )
            record_visual_api_usage(
                prompt_settings,
                user_id=user_id,
                stage="visual_prompt",
                api_type="chat",
                model=plan_model,
                status="success",
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
            )
            raise
        mother_prompt = build_mother_prompt_from_plan(plan, task["layout"], resolved_allow_short_labels)
        persist_plan(task_id, user_id, source_ref, plan, mother_prompt)
    except Exception as exc:
        mark_task_failed(task_id, user_id, str(exc))
        raise

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
    task = get_visual_task(task_id=task_id, user_id=user_id)
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
    use_chufan_generation_mode = is_chufan_ai_image_target(settings, resolved_image_model)
    reference_paths = (
        materialize_reference_image_refs(reference_refs, task_dir)
        if resolved_use_reference_image and not use_chufan_generation_mode
        else []
    )
    reference_path = reference_paths[0] if reference_paths else None
    image_endpoint = "/images/edits" if reference_paths else "/images/generations"
    image_url = build_api_url(settings["base_url"], image_endpoint)
    compact_prompt_text = build_compact_mother_prompt_from_plan(
        task.get("analysis") if isinstance(task.get("analysis"), dict) else {},
        clean_text(task.get("layout")) or "3x3",
        visual_bool_setting("VISUAL_ALLOW_SHORT_LABELS", True),
    )
    request_image_size = "" if use_chufan_generation_mode else resolved_image_size

    update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
    try:
        assert_user_api_usage_allowed(user_id)
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
            )
            record_visual_api_usage(
                settings,
                user_id=user_id,
                stage="visual_image",
                api_type="image",
                model=resolved_image_model,
                status="success",
            )
        except Exception as exc:
            record_visual_api_usage(
                settings,
                user_id=user_id,
                stage="visual_image",
                api_type="image",
                model=resolved_image_model,
                status="failed",
                error_message=str(exc),
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
    except Exception as exc:
        mark_task_failed(task_id, user_id, str(exc))
        raise

    if resolved_split_after:
        return split_visual_task(
            task_id=task_id,
            user_id=user_id,
            mother_image_ref=str(mother_path),
            upload_to_oss=resolved_upload_to_oss,
        )
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
    task = get_visual_task(task_id=task_id, user_id=user_id)
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
    update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
    try:
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
        modules = persist_split_result(
            task_id=task_id,
            user_id=user_id,
            mother_path=mother_path,
            split_dir=split_dir,
            manifest=manifest,
            upload_to_oss=resolved_upload_to_oss,
        )
    except Exception as exc:
        mark_task_failed(task_id, user_id, str(exc))
        raise

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
) -> dict[str, Any]:
    """Run plan -> generate -> split and optionally write generated images back to the link record."""
    planned = plan_visual_task(
        task_id=task_id,
        user_id=user_id,
        source_image_ref=source_image_ref,
        reference_image_refs=reference_image_refs,
        allow_short_labels=allow_short_labels,
        analysis_model=analysis_model,
        prompt_model=prompt_model,
    )
    generated = generate_visual_task(
        task_id=task_id,
        user_id=user_id,
        split_after=split_after,
        upload_to_oss=upload_to_oss,
        image_model=image_model,
        image_size=image_size,
        use_reference_image=use_reference_image,
    )
    if apply_to_link_record:
        try:
            update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
            apply_visual_task_results_to_link_record(task_id=task_id, user_id=user_id)
            update_task_status(task_id, user_id, TASK_STATUS_COMPLETED)
        except Exception as exc:
            # The generated assets should remain usable even if link-list persistence fails.
            mark_task_failed(task_id, user_id, f"generated, but link record update failed: {exc}")
            raise
    return get_visual_task(task_id=task_id, user_id=user_id) if apply_to_link_record else generated or planned


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


def update_task_status(task_id: str, user_id: str, status: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            "UPDATE visual_generation_tasks SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (status, utc_now_text(), task_id, user_id),
        )


def mark_task_failed(task_id: str, user_id: str, error_message: str) -> None:
    with get_connection() as conn:
        ensure_visual_generation_schema(conn)
        conn.execute(
            """
            UPDATE visual_generation_tasks
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (TASK_STATUS_FAILED, error_message[:2000], utc_now_text(), task_id, user_id),
        )


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
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "linkRecordId": row["link_record_id"],
        "productId": row["product_id"],
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
    return {
        "linkRecordId": clean_text(task.get("linkRecordId")) or clean_text(record.get("id")),
        "productId": clean_text(task.get("productId")) or clean_text(record.get("productId")),
        "mode": clean_text(task.get("mode")),
        "requestedCount": task.get("requestedCount"),
        "productTitle": product_title,
        "skuNames": extract_record_sku_names(record),
        "referenceImageBindingRule": (
            "All reference images are selected SKU/product image parameters. "
            "They must be treated as binding visual references. Preserve the exact product subject appearance "
            "and do not replace selected SKU components with generic category items."
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
