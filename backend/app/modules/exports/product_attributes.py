from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from app.core.database import get_connection, utc_now_text, ensure_export_product_attribute_schema
from app.modules.visual_generation.clients import (
    build_api_url,
    get_ai_stage_settings,
    request_text_json,
)

QUEUE_STATUSES = ("queued", "running", "done", "failed")


def prepare_product_attribute_jobs(records: list[dict[str, Any]], *, user_id: str, process_now: bool = False) -> dict[str, Any]:
    inserted = 0
    reused = 0
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        for record in records:
            if not isinstance(record, dict) or not record.get("skuEntries"):
                continue
            link_record_id = record_identity(record)
            record_hash = hash_attribute_input(record)
            existing = conn.execute(
                """
                SELECT id, status
                FROM export_product_attribute_jobs
                WHERE user_id = ? AND link_record_id = ? AND record_hash = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (user_id, link_record_id, record_hash),
            ).fetchone()
            if existing and existing["status"] in QUEUE_STATUSES:
                reused += 1
                continue
            now = utc_now_text()
            conn.execute(
                """
                INSERT INTO export_product_attribute_jobs (
                    id, user_id, link_record_id, product_id, product_title,
                    record_hash, record_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    f"attr-{uuid.uuid4().hex}",
                    user_id,
                    link_record_id,
                    clean_text(record.get("productId")),
                    clean_text(record.get("productTitle")),
                    record_hash,
                    json.dumps(record, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            inserted += 1
    if process_now:
        process_pending_product_attribute_jobs(user_id=user_id, limit=max(inserted, 1))
    summary = get_product_attribute_queue_summary(user_id=user_id)
    summary.update({"queuedNow": inserted, "reused": reused})
    return summary


def get_product_attribute_queue_summary(*, user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM export_product_attribute_jobs
            WHERE user_id = ?
            GROUP BY status
            """,
            (user_id,),
        ).fetchall()
    counts = {status: 0 for status in QUEUE_STATUSES}
    for row in rows:
        counts[str(row["status"])] = int(row["count"] or 0)
    counts["pending"] = counts["queued"] + counts["running"]
    counts["total"] = sum(counts[status] for status in QUEUE_STATUSES)
    return counts


def process_pending_product_attribute_jobs(*, user_id: str, limit: int = 20) -> dict[str, Any]:
    processed = 0
    failed = 0
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM export_product_attribute_jobs
            WHERE user_id = ? AND status = 'queued'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (user_id, max(1, limit)),
        ).fetchall()

    for row in rows:
        job_id = row["id"]
        mark_job_running(job_id, user_id=user_id)
        try:
            record = json.loads(row["record_json"] or "{}")
            result = generate_product_attribute_for_record(record)
            mark_job_done(job_id, user_id=user_id, result=result)
            processed += 1
        except Exception as exc:  # queue captures provider/category failures
            mark_job_failed(job_id, user_id=user_id, error=str(exc))
            failed += 1
    summary = get_product_attribute_queue_summary(user_id=user_id)
    summary.update({"processedNow": processed, "failedNow": failed})
    return summary


def get_cached_product_attribute_for_record(record: dict[str, Any], *, user_id: str | None = None) -> dict[str, str]:
    if not isinstance(record, dict):
        return {}
    uid = user_id or "default-user"
    link_record_id = record_identity(record)
    record_hash = hash_attribute_input(record)
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        row = conn.execute(
            """
            SELECT category_id, category_path, product_attribute_text, product_attributes_json
            FROM export_product_attribute_jobs
            WHERE user_id = ? AND link_record_id = ? AND record_hash = ? AND status = 'done'
            ORDER BY completed_at DESC, updated_at DESC
            LIMIT 1
            """,
            (uid, link_record_id, record_hash),
        ).fetchone()
    if not row:
        return {}
    return {
        "category_id": clean_text(row["category_id"]),
        "category_path": clean_text(row["category_path"]),
        "product_attribute_text": clean_text(row["product_attribute_text"]),
        "product_attributes_json": clean_text(row["product_attributes_json"]),
    }


def mark_job_running(job_id: str, *, user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE export_product_attribute_jobs SET status = 'running', updated_at = ? WHERE id = ? AND user_id = ?",
            (utc_now_text(), job_id, user_id),
        )


def mark_job_done(job_id: str, *, user_id: str, result: dict[str, Any]) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE export_product_attribute_jobs
            SET status = 'done', category_id = ?, category_path = ?, product_attribute_text = ?,
                product_attributes_json = ?, error_message = NULL, updated_at = ?, completed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                clean_text(result.get("category_id")),
                clean_text(result.get("category_path")),
                clean_text(result.get("product_attribute_text")),
                json.dumps(result.get("product_attributes") or [], ensure_ascii=False),
                now,
                now,
                job_id,
                user_id,
            ),
        )


def mark_job_failed(job_id: str, *, user_id: str, error: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE export_product_attribute_jobs
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (clean_text(error)[:1000], utc_now_text(), job_id, user_id),
        )


def generate_product_attribute_for_record(record: dict[str, Any]) -> dict[str, Any]:
    with get_connection() as conn:
        category = resolve_category_for_record(conn, record)
        if not category:
            raise ValueError("No matching category attribute definition was found for this product")
        fields = load_category_fields(conn, str(category["category_id"]))

    if not fields:
        raise ValueError("The matched category has no available product attribute fields")

    ai_result = request_product_attribute_ai(record, category, fields)
    product_attributes = normalize_product_attributes(ai_result, fields)
    return {
        "category_id": str(category["category_id"] or ""),
        "category_path": str(category["category_path_text"] or ""),
        "product_attributes": product_attributes,
        "product_attribute_text": json.dumps(product_attributes, ensure_ascii=False),
    }


def resolve_category_for_record(conn: Any, record: dict[str, Any]) -> dict[str, Any] | None:
    product_context = load_product_context(conn, record)
    category_path = clean_text(product_context.get("category_path")) or clean_text(record.get("categoryPath"))
    title = clean_text(record.get("productTitle"))

    candidate_paths = [category_path]
    if category_path:
        candidate_paths.extend([part.strip() for part in re.split(r">|/|?|,|?", category_path) if part.strip()])
    candidate_paths.extend([clean_text(product_context.get("category_level2")), clean_text(product_context.get("category_level1"))])

    for value in unique_strings(candidate_paths):
        row = conn.execute(
            """
            SELECT *
            FROM dxm_temu_category_attr_snapshots
            WHERE category_path_text = ? OR leaf_name = ? OR category_path_text LIKE ?
            ORDER BY required_count DESC, attr_count DESC
            LIMIT 1
            """,
            (value, value, f"%{value}%"),
        ).fetchone()
        if row:
            return dict(row)

    title_terms = [term for term in re.split(r"\s+|,|?|?|-", title) if len(term) >= 2][:8]
    for term in title_terms:
        row = conn.execute(
            """
            SELECT *
            FROM dxm_temu_category_attr_snapshots
            WHERE leaf_name LIKE ? OR category_path_text LIKE ?
            ORDER BY required_count DESC, attr_count DESC
            LIMIT 1
            """,
            (f"%{term}%", f"%{term}%"),
        ).fetchone()
        if row:
            return dict(row)
    return None


def load_product_context(conn: Any, record: dict[str, Any]) -> dict[str, Any]:
    product_id = clean_text(record.get("productId"))
    if not product_id:
        return {}
    for table in ("products", "product_pool_products"):
        row = conn.execute(
            f"""
            SELECT id, source_product_id, category_path, category_level1, category_level2, raw_data_json
            FROM {table}
            WHERE id = ? OR source_product_id = ?
            LIMIT 1
            """,
            (product_id, product_id),
        ).fetchone()
        if row:
            return dict(row)
    return {}


def load_category_fields(conn: Any, category_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM dxm_temu_category_attr_fields
        WHERE category_id = ?
        ORDER BY required DESC, option_count ASC, field_label ASC
        LIMIT 80
        """,
        (category_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["raw"] = json.loads(item.get("raw_json") or "{}")
        except Exception:
            item["raw"] = {}
        try:
            item["options"] = json.loads(item.get("options_json") or "[]")
        except Exception:
            item["options"] = []
        result.append(item)
    return result


def request_product_attribute_ai(record: dict[str, Any], category: dict[str, Any], fields: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_ai_stage_settings("product_attribute")
    api_url = build_api_url(settings["base_url"], "/chat/completions")
    compact_fields = []
    for field in fields[:50]:
        options = []
        for option in (field.get("options") or [])[:30]:
            if not isinstance(option, dict):
                continue
            label = clean_text(option.get("label") or option.get("value") or option.get("en"))
            vid = clean_text(option.get("vid"))
            if label:
                options.append({"label": label, "vid": vid})
        raw = field.get("raw") or {}
        compact_fields.append(
            {
                "field_key": field.get("field_key"),
                "field_label": field.get("field_label"),
                "required": bool(field.get("required")),
                "component": field.get("component"),
                "pid": raw.get("pid") or raw.get("attributeId") or raw.get("id"),
                "templatePid": raw.get("templatePid"),
                "refPid": raw.get("refPid") or raw.get("refPID"),
                "options": options,
            }
        )

    instruction = {
        "role": "You are a Dianxiaomi TEMU semi-managed product attribute assistant. Return JSON only, no explanations.",
        "task": "Use the product title, SKU names, category path, and candidate attribute fields to fill product attributes. Prioritize fields where required=true. If a value cannot be confidently inferred, leave prop_value empty. For select fields, use exactly one provided option label and return its vid. Do not invent certifications, brands, medical claims, safety claims, waterproof claims, or unverifiable sensitive attributes.",
        "output_schema": {
            "attributes": [
                {"field_label": "field label", "prop_value": "attribute value", "value_unit": "", "vid": "option vid if available"}
            ]
        },
        "product": {
            "title": clean_text(record.get("productTitle")),
            "title_en": clean_text(record.get("productTitleEn")),
            "sku_names": sku_names_for_prompt(record),
            "source_titles": [clean_text(source.get("title")) for source in record.get("sourceLinks") or [] if isinstance(source, dict)],
        },
        "category": {
            "category_id": category.get("category_id"),
            "category_path": category.get("category_path_text"),
        },
        "fields": compact_fields,
    }
    return request_text_json(
        api_url=api_url,
        api_key=settings["api_key"],
        model=settings["model"],
        instruction=json.dumps(instruction, ensure_ascii=False),
        temperature=0.15,
    )


def normalize_product_attributes(ai_result: dict[str, Any], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_items = ai_result.get("attributes") or ai_result.get("product_attributes") or []
    if not isinstance(raw_items, list):
        raw_items = []
    field_map = {clean_text(field.get("field_label")): field for field in fields}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("field_label") or item.get("propName") or item.get("name"))
        field = field_map.get(label)
        if not field or label in seen:
            continue
        seen.add(label)
        prop_value = clean_text(item.get("prop_value") or item.get("propValue") or item.get("value"))
        raw = field.get("raw") or {}
        vid = clean_text(item.get("vid")) or find_option_vid(prop_value, field.get("options") or [])
        normalized.append(
            {
                "valueUnit": clean_text(item.get("value_unit") or item.get("valueUnit")),
                "propValue": prop_value,
                "propName": clean_text(field.get("field_label")),
                "refPid": int_or_zero(raw.get("refPid") or raw.get("refPID")),
                "vid": int_or_zero(vid),
                "pid": int_or_zero(raw.get("pid") or raw.get("attributeId") or raw.get("id")),
                "templatePid": int_or_zero(raw.get("templatePid")),
            }
        )
    return normalized


def find_option_vid(prop_value: str, options: list[Any]) -> str:
    value = clean_text(prop_value)
    if not value:
        return ""
    for option in options:
        if not isinstance(option, dict):
            continue
        labels = [option.get("label"), option.get("value"), option.get("en")]
        if any(clean_text(label) == value for label in labels):
            return clean_text(option.get("vid"))
    return ""


def record_identity(record: dict[str, Any]) -> str:
    return clean_text(record.get("id")) or clean_text(record.get("productId")) or f"record-{uuid.uuid4().hex}"


def hash_attribute_input(record: dict[str, Any]) -> str:
    payload = {
        "productId": clean_text(record.get("productId")),
        "productTitle": clean_text(record.get("productTitle")),
        "productTitleEn": clean_text(record.get("productTitleEn")),
        "skuNames": sku_names_for_prompt(record),
        "sourceTitles": [clean_text(source.get("title")) for source in record.get("sourceLinks") or [] if isinstance(source, dict)],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def sku_names_for_prompt(record: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for sku in record.get("skuEntries") or []:
        if not isinstance(sku, dict):
            continue
        name = clean_text(sku.get("name"))
        if name:
            names.append(name)
    return unique_strings(names)[:80]


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def int_or_zero(value: Any) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return 0
