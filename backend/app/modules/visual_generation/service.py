from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.core.config import STORAGE_DIR
from app.core.database import get_connection, utc_now_text
from app.modules.image_storage.aliyun_oss import ImageStorageError, read_image_ref, upload_image_bytes
from app.modules.visual_generation.clients import (
    VisualGenerationError,
    build_api_url,
    get_ai_settings,
    get_runtime_setting,
    request_generated_image,
)
from app.modules.visual_generation.planner import (
    build_mother_prompt_from_plan,
    request_product_analysis,
    request_prompt_plan,
)
from app.modules.visual_generation.splitter import GridSplitError, split_grid_file


VISUAL_STORAGE_DIR = STORAGE_DIR / "visual_generation"
TASK_STATUS_DRAFT = "draft"
TASK_STATUS_PLANNED = "planned"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_SPLIT = "split"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"

BOOL_TRUE_VALUES = {"1", "true", "yes", "on"}


class VisualTaskError(ValueError):
    pass


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
) -> dict[str, Any]:
    record = record or {}
    now = utc_now_text()
    task_id = f"visual_{uuid.uuid4().hex}"
    clean_link_record_id = clean_text(link_record_id) or clean_text(record.get("id"))
    clean_product_id = clean_text(product_id) or clean_text(record.get("productId"))
    clean_source_image_ref = clean_text(source_image_ref) or pick_record_image(record)
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


def plan_visual_task(
    *,
    task_id: str,
    user_id: str,
    source_image_ref: str | None = None,
    allow_short_labels: bool | None = None,
    analysis_model: str | None = None,
    prompt_model: str | None = None,
) -> dict[str, Any]:
    task = get_visual_task(task_id=task_id, user_id=user_id)
    source_ref = clean_text(source_image_ref) or clean_text(task.get("sourceImageRef"))
    if not source_ref:
        raise VisualTaskError("source image is required before planning")

    settings = get_ai_settings()
    base_url = settings["base_url"]
    api_key = settings["api_key"]
    text_model = analysis_model or settings["text_model"]
    plan_model = prompt_model or settings["text_model"]
    resolved_allow_short_labels = (
        visual_bool_setting("VISUAL_ALLOW_SHORT_LABELS", True) if allow_short_labels is None else allow_short_labels
    )
    analysis_url = build_api_url(base_url, "/chat/completions")
    prompt_url = build_api_url(base_url, "/chat/completions")
    task_dir = task_output_dir(user_id, task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    source_path = materialize_image_ref(source_ref, task_dir / "source_image")

    context = {
        "linkRecordId": task.get("linkRecordId"),
        "productId": task.get("productId"),
        "mode": task.get("mode"),
        "requestedCount": task.get("requestedCount"),
        "record": task.get("record") or {},
    }
    update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
    try:
        product_analysis = request_product_analysis(
            api_url=analysis_url,
            api_key=api_key,
            model=text_model,
            product_image_path=source_path,
            context=context,
        )
        plan = request_prompt_plan(
            api_url=prompt_url,
            api_key=api_key,
            model=plan_model,
            product_analysis=product_analysis,
            layout=task["layout"],
            allow_short_labels=resolved_allow_short_labels,
        )
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

    settings = get_ai_settings()
    image_url = build_api_url(settings["base_url"], "/images/generations")
    source_ref = clean_text(task.get("sourceImageRef"))
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
    reference_path = (
        materialize_image_ref(source_ref, task_dir / "source_image") if resolved_use_reference_image and source_ref else None
    )

    update_task_status(task_id, user_id, TASK_STATUS_RUNNING)
    try:
        image_bytes = request_generated_image(
            api_url=image_url,
            api_key=settings["api_key"],
            model=image_model or settings["image_model"],
            size=resolved_image_size,
            prompt=prompt_text,
            reference_image_path=reference_path,
        )
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
