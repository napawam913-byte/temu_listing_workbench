from __future__ import annotations

import base64
import json
import re
import sqlite3
import uuid
from typing import Any

from app.core.database import get_connection, utc_now_text
from app.modules.creative_generation.chatgpt_listing import (
    IMAGE_COUNT,
    build_image_plan,
    build_image_prompt,
    build_sku_image_prompt,
)
from app.modules.creative_generation.safety import sanitize_marketplace_text
from app.modules.exports.dianxiaomi_temu import normalize_english_title
from app.modules.image_storage.aliyun_oss import ImageStorageError, mirror_export_image, upload_image_bytes

PLUGIN_PROVIDER = "plugin_chatgpt_web"
JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


class CreativePluginJobError(Exception):
    pass


def ensure_creative_jobs_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS creative_image_jobs (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'plugin_chatgpt_web',
            status TEXT NOT NULL DEFAULT 'queued',
            record_id TEXT NOT NULL,
            product_id TEXT,
            record_title TEXT,
            safe_title_en TEXT,
            record_json TEXT NOT NULL DEFAULT '{}',
            image_index INTEGER NOT NULL,
            image_kind TEXT NOT NULL,
            image_label TEXT NOT NULL,
            target_sku_entry_id TEXT,
            prompt TEXT NOT NULL,
            analysis_text TEXT,
            input_image_url TEXT,
            result_image_url TEXT,
            result_storage_key TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            claimed_at TEXT,
            completed_at TEXT,
            UNIQUE(provider, record_id, image_kind)
        );

        CREATE INDEX IF NOT EXISTS idx_creative_image_jobs_status
            ON creative_image_jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_creative_image_jobs_record
            ON creative_image_jobs(record_id, image_index);
        """
    )
    ensure_creative_job_column(conn, "target_sku_entry_id", "target_sku_entry_id TEXT")
    ensure_creative_job_column(conn, "analysis_text", "analysis_text TEXT")


def ensure_creative_job_column(conn: sqlite3.Connection, column_name: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(creative_image_jobs)").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE creative_image_jobs ADD COLUMN {ddl}")


def create_plugin_jobs(records: list[dict[str, Any]], provider: str = PLUGIN_PROVIDER) -> list[dict[str, Any]]:
    provider = clean_text(provider) or PLUGIN_PROVIDER
    now = utc_now_text()
    created_or_existing: list[dict[str, Any]] = []

    with get_connection() as conn:
        ensure_creative_jobs_schema(conn)
        for record in records:
            record_id = clean_text(record.get("id"))
            if not record_id:
                continue
            product_id = clean_text(record.get("productId")) or record_id
            safe_title_cn, _ = sanitize_marketplace_text(record.get("productTitle"))
            safe_title_en = normalize_english_title(record.get("productTitleEn"), safe_title_cn or record.get("productTitle", ""))
            safe_title_en, _ = sanitize_marketplace_text(safe_title_en)
            input_image_url = pick_record_input_image(record)
            plan = build_image_plan(record, safe_title_en)

            for image_index, image_plan in enumerate(plan, start=1):
                job_id = stable_job_id(provider, record_id, image_plan["kind"])
                prompt = build_image_prompt(record, safe_title_en, image_plan)
                conn.execute(
                    """
                    INSERT INTO creative_image_jobs (
                        id, provider, status, record_id, product_id, record_title, safe_title_en,
                        record_json, image_index, image_kind, image_label, target_sku_entry_id, prompt, input_image_url,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, record_id, image_kind) DO UPDATE SET
                        status = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.status
                            ELSE excluded.status
                        END,
                        product_id = excluded.product_id,
                        record_title = excluded.record_title,
                        safe_title_en = excluded.safe_title_en,
                        record_json = excluded.record_json,
                        image_index = excluded.image_index,
                        image_label = excluded.image_label,
                        target_sku_entry_id = excluded.target_sku_entry_id,
                        prompt = excluded.prompt,
                        input_image_url = excluded.input_image_url,
                        result_image_url = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.result_image_url
                            ELSE NULL
                        END,
                        result_storage_key = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.result_storage_key
                            ELSE NULL
                        END,
                        analysis_text = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.analysis_text
                            ELSE NULL
                        END,
                        error_message = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.error_message
                            ELSE NULL
                        END,
                        claimed_at = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.claimed_at
                            ELSE NULL
                        END,
                        completed_at = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.completed_at
                            ELSE NULL
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        job_id,
                        provider,
                        JOB_STATUS_QUEUED,
                        record_id,
                        product_id,
                        clean_text(record.get("productTitle")),
                        safe_title_en,
                        json.dumps(record, ensure_ascii=False),
                        image_index,
                        image_plan["kind"],
                        image_plan["label"],
                        None,
                        prompt,
                        input_image_url,
                        now,
                        now,
                    ),
                )

            for sku_index, sku_entry in enumerate(iter_sku_entries(record), start=1):
                sku_entry_id = clean_text(sku_entry.get("id")) or f"sku-{sku_index}"
                image_kind = f"sku-{sku_index:02d}-{clean_key_part(sku_entry_id)}"
                job_id = stable_job_id(provider, record_id, image_kind)
                sku_name = clean_text(sku_entry.get("name")) or f"SKU {sku_index}"
                prompt = build_sku_image_prompt(record, safe_title_en, sku_entry, sku_index)
                sku_input_image_url = pick_sku_input_image(record, sku_entry) or input_image_url
                conn.execute(
                    """
                    INSERT INTO creative_image_jobs (
                        id, provider, status, record_id, product_id, record_title, safe_title_en,
                        record_json, image_index, image_kind, image_label, target_sku_entry_id, prompt, input_image_url,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider, record_id, image_kind) DO UPDATE SET
                        status = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.status
                            ELSE excluded.status
                        END,
                        product_id = excluded.product_id,
                        record_title = excluded.record_title,
                        safe_title_en = excluded.safe_title_en,
                        record_json = excluded.record_json,
                        image_index = excluded.image_index,
                        image_label = excluded.image_label,
                        target_sku_entry_id = excluded.target_sku_entry_id,
                        prompt = excluded.prompt,
                        input_image_url = excluded.input_image_url,
                        result_image_url = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.result_image_url
                            ELSE NULL
                        END,
                        result_storage_key = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.result_storage_key
                            ELSE NULL
                        END,
                        analysis_text = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.analysis_text
                            ELSE NULL
                        END,
                        error_message = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.error_message
                            ELSE NULL
                        END,
                        claimed_at = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.claimed_at
                            ELSE NULL
                        END,
                        completed_at = CASE
                            WHEN creative_image_jobs.status = 'completed' THEN creative_image_jobs.completed_at
                            ELSE NULL
                        END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        job_id,
                        provider,
                        JOB_STATUS_QUEUED,
                        record_id,
                        product_id,
                        clean_text(record.get("productTitle")),
                        safe_title_en,
                        json.dumps(record, ensure_ascii=False),
                        IMAGE_COUNT + sku_index,
                        image_kind,
                        f"SKU {sku_index}: {sku_name}",
                        sku_entry_id,
                        prompt,
                        sku_input_image_url,
                        now,
                        now,
                    ),
                )

        record_ids = [clean_text(record.get("id")) for record in records if clean_text(record.get("id"))]
        created_or_existing = list_creative_jobs(conn, provider=provider, record_ids=record_ids)

    return created_or_existing


def claim_next_plugin_job(provider: str = PLUGIN_PROVIDER) -> dict[str, Any] | None:
    jobs = claim_next_plugin_jobs(provider=provider, limit=1)
    return jobs[0] if jobs else None


def claim_next_plugin_jobs(provider: str = PLUGIN_PROVIDER, limit: int = 20) -> list[dict[str, Any]]:
    provider = clean_text(provider) or PLUGIN_PROVIDER
    now = utc_now_text()
    safe_limit = max(1, min(int(limit or 20), 50))
    with get_connection() as conn:
        ensure_creative_jobs_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM creative_image_jobs
            WHERE provider = ? AND status = ?
            ORDER BY created_at ASC, record_id ASC, image_index ASC
            LIMIT ?
            """,
            (provider, JOB_STATUS_QUEUED, safe_limit),
        ).fetchall()
        if not rows:
            return []

        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""
            UPDATE creative_image_jobs
            SET status = ?, claimed_at = ?, updated_at = ?, error_message = NULL
            WHERE id IN ({placeholders})
            """,
            [JOB_STATUS_RUNNING, now, now, *ids],
        )
        updated_rows = conn.execute(
            f"""
            SELECT *
            FROM creative_image_jobs
            WHERE id IN ({placeholders})
            ORDER BY created_at ASC, record_id ASC, image_index ASC
            """,
            ids,
        ).fetchall()

    return [creative_job_row_to_api(row) for row in updated_rows]


def complete_plugin_job(
    job_id: str,
    *,
    image_data_url: str | None = None,
    image_url: str | None = None,
    analysis_text: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    now = utc_now_text()
    clean_analysis_text = clean_text(analysis_text) or None
    with get_connection() as conn:
        ensure_creative_jobs_schema(conn)
        row = conn.execute("SELECT * FROM creative_image_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise CreativePluginJobError("生图任务不存在")

    if clean_text(error_message):
        with get_connection() as conn:
            ensure_creative_jobs_schema(conn)
            conn.execute(
                """
                UPDATE creative_image_jobs
                SET status = ?, error_message = ?, analysis_text = COALESCE(?, analysis_text), updated_at = ?
                WHERE id = ?
                """,
                (JOB_STATUS_FAILED, clean_text(error_message), clean_analysis_text, now, job_id),
            )
            updated = conn.execute("SELECT * FROM creative_image_jobs WHERE id = ?", (job_id,)).fetchone()
        return creative_job_row_to_api(updated)

    try:
        upload = upload_generated_result(row, image_data_url=image_data_url, image_url=image_url)
    except ImageStorageError as exc:
        raise CreativePluginJobError(str(exc)) from exc

    with get_connection() as conn:
        ensure_creative_jobs_schema(conn)
        conn.execute(
            """
            UPDATE creative_image_jobs
            SET status = ?, result_image_url = ?, result_storage_key = ?, analysis_text = COALESCE(?, analysis_text), error_message = NULL,
                completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (JOB_STATUS_COMPLETED, upload["url"], upload.get("storageKey", ""), clean_analysis_text, now, now, job_id),
        )
        updated = conn.execute("SELECT * FROM creative_image_jobs WHERE id = ?", (job_id,)).fetchone()

    return creative_job_row_to_api(updated)


def sync_records_with_plugin_jobs(records: list[dict[str, Any]], provider: str = PLUGIN_PROVIDER) -> dict[str, Any]:
    provider = clean_text(provider) or PLUGIN_PROVIDER
    record_ids = [clean_text(record.get("id")) for record in records if clean_text(record.get("id"))]
    with get_connection() as conn:
        ensure_creative_jobs_schema(conn)
        jobs = list_creative_jobs(conn, provider=provider, record_ids=record_ids)

    jobs_by_record: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        jobs_by_record.setdefault(job["recordId"], []).append(job)

    completed_record_ids: list[str] = []
    updated_records: list[dict[str, Any]] = []
    for record in records:
        record_id = clean_text(record.get("id"))
        record_jobs = sorted(jobs_by_record.get(record_id, []), key=lambda item: item["imageIndex"])
        updated = json.loads(json.dumps(record, ensure_ascii=False))
        updated["creativeJobs"] = [
            {
                "id": job["id"],
                "provider": job["provider"],
                "status": job["status"],
                "imageIndex": job["imageIndex"],
                "imageKind": job["imageKind"],
                "imageLabel": job["imageLabel"],
                "targetSkuEntryId": job.get("targetSkuEntryId"),
                "resultImageUrl": job.get("resultImageUrl"),
                "analysisText": job.get("analysisText"),
                "updatedAt": job["updatedAt"],
            }
            for job in record_jobs
        ]

        completed_jobs = [job for job in record_jobs if job["status"] == JOB_STATUS_COMPLETED and job.get("resultImageUrl")]
        completed_product_jobs = [job for job in completed_jobs if not clean_text(job.get("targetSkuEntryId"))]
        completed_sku_jobs = [job for job in completed_jobs if clean_text(job.get("targetSkuEntryId"))]
        if len(completed_product_jobs) >= IMAGE_COUNT:
            updated = apply_completed_jobs_to_record(updated, completed_product_jobs[:IMAGE_COUNT])
            completed_record_ids.append(record_id)
        if completed_sku_jobs:
            updated = apply_completed_sku_jobs_to_record(updated, completed_sku_jobs)
        updated_records.append(updated)

    return {
        "records": updated_records,
        "jobs": jobs,
        "completedRecordIds": completed_record_ids,
        "pendingCount": len([job for job in jobs if job["status"] in {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}]),
        "failedCount": len([job for job in jobs if job["status"] == JOB_STATUS_FAILED]),
    }


def list_plugin_jobs(
    *,
    provider: str = PLUGIN_PROVIDER,
    record_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    provider = clean_text(provider) or PLUGIN_PROVIDER
    with get_connection() as conn:
        ensure_creative_jobs_schema(conn)
        return list_creative_jobs(
            conn,
            provider=provider,
            record_ids=[record_id] if clean_text(record_id) else None,
            status=clean_text(status) or None,
            limit=limit,
        )


def list_creative_jobs(
    conn: sqlite3.Connection,
    *,
    provider: str,
    record_ids: list[str] | None = None,
    status: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    clauses = ["provider = ?"]
    params: list[Any] = [provider]
    if record_ids:
        clean_ids = [record_id for record_id in record_ids if clean_text(record_id)]
        if clean_ids:
            placeholders = ",".join("?" for _ in clean_ids)
            clauses.append(f"record_id IN ({placeholders})")
            params.extend(clean_ids)
    if status:
        clauses.append("status = ?")
        params.append(status)

    params.append(max(1, min(limit, 1000)))
    rows = conn.execute(
        f"""
        SELECT *
        FROM creative_image_jobs
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at ASC, record_id ASC, image_index ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [creative_job_row_to_api(row) for row in rows]


def apply_completed_jobs_to_record(record: dict[str, Any], completed_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    safe_title_en = clean_text(completed_jobs[0].get("safeTitleEn")) if completed_jobs else ""
    if safe_title_en:
        record["productTitleEn"] = safe_title_en

    generated_assets = []
    for job in completed_jobs:
        image_url = job["resultImageUrl"]
        generated_assets.append(
            {
                "id": f"{record.get('id', record.get('productId', 'record'))}-plugin-{job['imageKind']}",
                "role": "product-main" if job["imageIndex"] == 1 else "product-material",
                "editedCloudUrl": image_url,
                "displayCloudUrl": image_url,
                "storageKey": job.get("resultStorageKey") or "",
                "alt": f"{record.get('productTitleEn') or record.get('productTitle') or 'Product'} {job['imageLabel']}",
            }
        )

    if generated_assets:
        current_main = record.get("mainImage") or {}
        first = generated_assets[0]
        record["mainImage"] = {
            **current_main,
            "id": current_main.get("id") or f"{record.get('id', record.get('productId', 'record'))}-main-image",
            "role": "product-main",
            "editedCloudUrl": first["editedCloudUrl"],
            "displayCloudUrl": first["displayCloudUrl"],
            "storageKey": first["storageKey"],
            "alt": first["alt"],
        }
        record["productMaterialImages"] = generated_assets

    return record


def apply_completed_sku_jobs_to_record(record: dict[str, Any], completed_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    jobs_by_sku_id = {
        clean_text(job.get("targetSkuEntryId")): job
        for job in completed_jobs
        if clean_text(job.get("targetSkuEntryId")) and clean_text(job.get("resultImageUrl"))
    }
    if not jobs_by_sku_id:
        return record

    sku_entries = record.get("skuEntries")
    if not isinstance(sku_entries, list):
        return record

    for index, sku_entry in enumerate(sku_entries, start=1):
        if not isinstance(sku_entry, dict):
            continue
        sku_id = clean_text(sku_entry.get("id")) or f"sku-{index}"
        job = jobs_by_sku_id.get(sku_id)
        if not job:
            continue

        image_url = clean_text(job.get("resultImageUrl"))
        image_asset = sku_entry.get("imageAsset") if isinstance(sku_entry.get("imageAsset"), dict) else {}
        sku_entry["imageAsset"] = {
            **image_asset,
            "id": image_asset.get("id") or f"{record.get('id', record.get('productId', 'record'))}-{sku_id}-image",
            "role": "sales-sku",
            "sourceUrl": image_asset.get("sourceUrl") or sku_entry.get("imageUrl"),
            "editedCloudUrl": image_url,
            "displayCloudUrl": image_url,
            "storageKey": job.get("resultStorageKey") or "",
            "alt": f"{record.get('productTitleEn') or record.get('productTitle') or 'Product'} {clean_text(sku_entry.get('name')) or sku_id}",
        }

    return record


def upload_generated_result(row: sqlite3.Row, *, image_data_url: str | None, image_url: str | None) -> dict[str, str]:
    key_hint = f"products/{clean_key_part(row['product_id'] or row['record_id'])}/plugin/{row['image_kind']}"
    data_url = clean_text(image_data_url)
    if data_url:
        content_type, image_bytes = parse_data_url(data_url)
        return upload_image_bytes(image_bytes, content_type, key_hint)

    source_url = clean_text(image_url)
    if source_url:
        mirrored_url = mirror_export_image(source_url, key_hint)
        return {"url": mirrored_url, "storageKey": ""}

    raise CreativePluginJobError("缺少生成图片数据")


def parse_data_url(data_url: str) -> tuple[str, bytes]:
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", data_url, flags=re.DOTALL)
    if not match:
        raise CreativePluginJobError("图片 data URL 格式不正确")
    content_type = match.group(1) or "image/png"
    is_base64 = bool(match.group(2))
    payload = match.group(3) or ""
    if not is_base64:
        raise CreativePluginJobError("图片 data URL 必须是 base64")
    return content_type, base64.b64decode(payload)


def pick_record_input_image(record: dict[str, Any]) -> str:
    main_image = record.get("mainImage") or {}
    candidates = [
        main_image.get("sourceCloudUrl"),
        main_image.get("sourceUrl"),
        main_image.get("displayCloudUrl"),
        main_image.get("displayUrl"),
        main_image.get("editedCloudUrl"),
        main_image.get("editedUrl"),
        record.get("productImageUrl"),
    ]
    candidates.extend(source.get("imageUrl") for source in record.get("sourceLinks") or [] if isinstance(source, dict))
    for sku in record.get("skuEntries") or []:
        if not isinstance(sku, dict):
            continue
        image_asset = sku.get("imageAsset") or {}
        candidates.extend(
            [
                image_asset.get("sourceUrl"),
                image_asset.get("displayUrl"),
                sku.get("imageUrl"),
            ]
        )
    return first_non_empty(*candidates)


def iter_sku_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [sku for sku in record.get("skuEntries") or [] if isinstance(sku, dict)]


def pick_sku_input_image(record: dict[str, Any], sku_entry: dict[str, Any]) -> str:
    image_asset = sku_entry.get("imageAsset") if isinstance(sku_entry.get("imageAsset"), dict) else {}
    candidates: list[Any] = [
        image_asset.get("sourceCloudUrl"),
        image_asset.get("sourceUrl"),
        image_asset.get("displayCloudUrl"),
        image_asset.get("displayUrl"),
        image_asset.get("editedCloudUrl"),
        image_asset.get("editedUrl"),
        sku_entry.get("imageUrl"),
    ]

    for component in sku_entry.get("componentSkus") or []:
        if not isinstance(component, dict):
            continue
        candidates.extend(
            [
                component.get("imageUrl"),
                component.get("sourceImageUrl"),
            ]
        )

    for source_sku in sku_entry.get("sourceSkuLinks") or []:
        if not isinstance(source_sku, dict):
            continue
        candidates.append(source_sku.get("imageUrl"))

    return first_non_empty(*candidates, pick_record_input_image(record))


def creative_job_row_to_api(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "provider": row["provider"],
        "status": row["status"],
        "recordId": row["record_id"],
        "productId": row["product_id"],
        "recordTitle": row["record_title"],
        "safeTitleEn": row["safe_title_en"],
        "imageIndex": row["image_index"],
        "imageKind": row["image_kind"],
        "imageLabel": row["image_label"],
        "targetSkuEntryId": row["target_sku_entry_id"],
        "prompt": row["prompt"],
        "analysisText": row["analysis_text"],
        "inputImageUrl": row["input_image_url"],
        "resultImageUrl": row["result_image_url"],
        "resultStorageKey": row["result_storage_key"],
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "claimedAt": row["claimed_at"],
        "completedAt": row["completed_at"],
    }


def stable_job_id(provider: str, record_id: str, image_kind: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"creative-image-job:{provider}:{record_id}:{image_kind}").hex


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def clean_key_part(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", clean_text(value)).strip("-")
    return text[:80] or "product"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
