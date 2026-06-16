from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from app.core.config import UPLOADS_DIR, ensure_runtime_dirs
from app.core.database import ensure_ingest_schema, get_connection, normalize_product_catalog_scope, parse_json_text, utc_now_text
from app.modules.ingestion.adapters import generic_product, yunqi_product
from app.modules.ingestion.category_resolver import resolve_ingest_category
from app.modules.ingestion.schemas import CategoryResolution, IngestRequest, NormalizedIngestItem


SUPPORTED_ADAPTERS = {
    ("yunqi", "product"),
    ("1688", "product"),
}


class IngestError(ValueError):
    pass


def ingest_records(payload: IngestRequest, *, user_id: str | None = None) -> dict[str, Any]:
    source = normalize_identifier(payload.source)
    entity_type = normalize_entity_type(payload.entity_type)
    mode = normalize_mode(payload.mode)
    if (source, entity_type) not in SUPPORTED_ADAPTERS:
        raise IngestError(f"暂不支持的数据入口：source={source}, entity_type={entity_type}")

    ensure_runtime_dirs()
    with get_connection() as conn:
        ensure_ingest_schema(conn)
        existing = find_idempotent_batch(conn, source, entity_type, payload.idempotency_key)
        if existing:
            return build_batch_response(conn, existing["id"], idempotent_replay=True)

    batch_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    now = utc_now_text()
    metadata = {
        **payload.metadata,
        "context": payload.context,
    }
    raw_file_path = save_ingest_snapshot(batch_id, payload)

    with get_connection() as conn:
        ensure_ingest_schema(conn)
        conn.execute(
            """
            INSERT INTO ingest_batches (
                id, source, entity_type, mode, idempotency_key, request_id, user_id,
                status, raw_file_path, file_type, total_count, metadata_json,
                created_at, updated_at, started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'processing', ?, 'json', ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                source,
                entity_type,
                mode,
                clean_optional(payload.idempotency_key),
                request_id,
                user_id,
                str(raw_file_path),
                len(payload.records),
                stable_json(metadata),
                now,
                now,
                now,
            ),
        )
        for index, record in enumerate(payload.records, start=1):
            item_id = uuid.uuid4().hex
            source_entity_id = guess_source_entity_id(source, entity_type, record)
            content_hash = stable_hash(record)
            conn.execute(
                """
                INSERT INTO ingest_items (
                    id, batch_id, source, entity_type, source_entity_id, dedupe_key,
                    content_hash, source_row_index, status, raw_data_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    item_id,
                    batch_id,
                    source,
                    entity_type,
                    source_entity_id,
                    build_dedupe_key(source, entity_type, source_entity_id or content_hash),
                    content_hash,
                    to_int(record.get("source_row_index")) or index,
                    stable_json(record),
                    now,
                    now,
                ),
            )

    try:
        if source == "yunqi" and entity_type == "product":
            process_yunqi_products(batch_id, payload)
            target_table = "products"
            target_batch_id = batch_id
        elif source == "1688" and entity_type == "product":
            process_1688_products(batch_id, payload)
            target_table = "products"
            target_batch_id = batch_id
        else:
            raise IngestError(f"暂不支持的数据入口：source={source}, entity_type={entity_type}")
    except Exception as exc:  # noqa: BLE001
        mark_batch_failed(batch_id, str(exc))
        raise

    finalize_batch(batch_id, target_table=target_table, target_batch_id=target_batch_id)
    with get_connection() as conn:
        return build_batch_response(conn, batch_id)


def process_yunqi_products(batch_id: str, payload: IngestRequest) -> None:
    source = normalize_identifier(payload.source)
    entity_type = normalize_entity_type(payload.entity_type)
    valid_items: list[NormalizedIngestItem] = []
    errors: list[str] = []

    rows = load_pending_items(batch_id)
    for row in rows:
        raw_record = parse_json_text(row["raw_data_json"], {})
        if not isinstance(raw_record, dict):
            mark_item_failed(row["id"], "raw_data_json is not an object")
            continue
        try:
            normalized = yunqi_product.normalize_record(raw_record, source_row_index=int(row["source_row_index"] or 1))
            normalized["catalog_scope"] = normalize_product_catalog_scope(payload.context.get("catalog_scope"))
            category = resolve_ingest_category(
                source=source,
                entity_type=entity_type,
                raw_record=raw_record,
                normalized_record=normalized,
                context=payload.context,
                source_entity_id=str(normalized.get("source_product_id") or ""),
            )
            valid_items.append(
                NormalizedIngestItem(
                    item_id=row["id"],
                    source_row_index=int(row["source_row_index"] or 1),
                    raw_record=raw_record,
                    normalized_record=normalized,
                    source_entity_id=str(normalized.get("source_product_id") or ""),
                    category=category,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"row {row['source_row_index']}: {exc}")
            mark_item_failed(row["id"], str(exc))

    if not valid_items:
        raise IngestError("没有可导入的云启商品记录")

    persist_result = yunqi_product.persist_records(
        [item.normalized_record for item in valid_items],
        batch_id=batch_id,
        source_filename=str(payload.metadata.get("original_filename") or "ingest-yunqi-product.json"),
        saved_path=UPLOADS_DIR / f"{batch_id}_ingest_yunqi_product.json",
        total_rows=len(payload.records),
        failed_count=len(errors),
        error_message="\n".join(errors[:20]) if errors else None,
        rebuild_keywords=True,
    )
    targets_by_source_id = {
        str(target.get("source_product_id") or ""): str(target.get("id") or "")
        for target in persist_result.get("targets", [])
    }
    for item in valid_items:
        target_id = targets_by_source_id.get(item.source_entity_id) or item.normalized_record.get("id") or ""
        mark_item_processed(
            item.item_id,
            normalized_record=item.normalized_record,
            source_entity_id=item.source_entity_id,
            target_table="products",
            target_id=target_id,
            category=item.category,
        )


def process_1688_products(batch_id: str, payload: IngestRequest) -> None:
    source = normalize_identifier(payload.source)
    entity_type = normalize_entity_type(payload.entity_type)
    valid_items: list[NormalizedIngestItem] = []
    errors: list[str] = []

    rows = load_pending_items(batch_id)
    for row in rows:
        raw_record = parse_json_text(row["raw_data_json"], {})
        if not isinstance(raw_record, dict):
            mark_item_failed(row["id"], "raw_data_json is not an object")
            continue
        try:
            normalized = generic_product.normalize_record(
                raw_record,
                source=source,
                source_row_index=int(row["source_row_index"] or 1),
                context=payload.context,
            )
            source_entity_id = str(normalized.get("source_product_id") or "")
            category = resolve_ingest_category(
                source=source,
                entity_type=entity_type,
                raw_record=raw_record,
                normalized_record=normalized,
                context=payload.context,
                source_entity_id=source_entity_id,
            )
            valid_items.append(
                NormalizedIngestItem(
                    item_id=row["id"],
                    source_row_index=int(row["source_row_index"] or 1),
                    raw_record=raw_record,
                    normalized_record=normalized,
                    source_entity_id=source_entity_id,
                    category=category,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"row {row['source_row_index']}: {exc}")
            mark_item_failed(row["id"], str(exc))

    if not valid_items:
        raise IngestError("No valid 1688 product records were found.")

    persist_result = generic_product.upsert_products(
        [item.normalized_record for item in valid_items],
        batch_id=batch_id,
        source_filename=str(payload.metadata.get("original_filename") or "ingest-1688-product.json"),
        saved_path=UPLOADS_DIR / f"{batch_id}_ingest_1688_product.json",
        total_rows=len(payload.records),
        failed_count=len(errors),
        error_message="\n".join(errors[:20]) if errors else None,
        rebuild_keywords=True,
    )
    targets_by_source_id = {
        str(target.get("source_product_id") or ""): str(target.get("id") or "")
        for target in persist_result.get("targets", [])
    }
    for item in valid_items:
        mark_item_processed(
            item.item_id,
            normalized_record=item.normalized_record,
            source_entity_id=item.source_entity_id,
            target_table="products",
            target_id=targets_by_source_id.get(item.source_entity_id) or item.normalized_record.get("id") or "",
            category=item.category,
        )


def process_1688_materials(batch_id: str, payload: IngestRequest) -> None:
    return process_1688_products(batch_id, payload)

    source = normalize_identifier(payload.source)
    entity_type = normalize_identifier(payload.entity_type)
    rows = load_pending_items(batch_id)
    processed = 0
    for row in rows:
        raw_record = parse_json_text(row["raw_data_json"], {})
        if not isinstance(raw_record, dict):
            mark_item_failed(row["id"], "raw_data_json is not an object")
            continue
        try:
            normalized = source_1688_material.normalize_record(raw_record, context=payload.context)
            source_entity_id = source_1688_material.source_entity_id(normalized)
            category = resolve_ingest_category(
                source=source,
                entity_type=entity_type,
                raw_record=raw_record,
                normalized_record=normalized,
                context=payload.context,
                source_entity_id=source_entity_id,
            )
            material = source_1688_material.persist_record(normalized)
            mark_item_processed(
                row["id"],
                normalized_record=normalized,
                source_entity_id=source_entity_id,
                target_table="sourcing_materials_1688",
                target_id=str(material.get("id") or ""),
                category=category,
            )
            processed += 1
        except Exception as exc:  # noqa: BLE001
            mark_item_failed(row["id"], str(exc))
    if processed == 0:
        raise IngestError("没有可导入的 1688 采集素材记录")


def load_pending_items(batch_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM ingest_items
            WHERE batch_id = ?
            ORDER BY source_row_index ASC, created_at ASC
            """,
            (batch_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_item_processed(
    item_id: str,
    *,
    normalized_record: dict[str, Any],
    source_entity_id: str,
    target_table: str,
    target_id: str,
    category: CategoryResolution,
) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE ingest_items
            SET
                source_entity_id = ?,
                dedupe_key = ?,
                status = 'processed',
                normalized_data_json = ?,
                source_category_raw = ?,
                source_category_path = ?,
                source_category_level1 = ?,
                source_category_level2 = ?,
                canonical_category_id = ?,
                canonical_category_path = ?,
                category_match_status = ?,
                category_match_score = ?,
                category_match_method = ?,
                category_candidates_json = ?,
                target_table = ?,
                target_id = ?,
                updated_at = ?,
                processed_at = ?
            WHERE id = ?
            """,
            (
                source_entity_id,
                build_dedupe_key_from_item(conn, item_id, source_entity_id),
                stable_json(normalized_record),
                category.source_category_raw,
                category.source_category_path,
                category.source_category_level1,
                category.source_category_level2,
                category.canonical_category_id,
                category.canonical_category_path,
                category.status,
                category.score,
                category.method,
                stable_json(category.candidates),
                target_table,
                target_id,
                now,
                now,
                item_id,
            ),
        )


def build_dedupe_key_from_item(conn: Any, item_id: str, source_entity_id: str) -> str:
    row = conn.execute("SELECT source, entity_type, content_hash FROM ingest_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        return source_entity_id
    return build_dedupe_key(row["source"], row["entity_type"], source_entity_id or row["content_hash"])


def mark_item_failed(item_id: str, error_message: str) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE ingest_items
            SET status = 'failed', error_message = ?, updated_at = ?, processed_at = ?
            WHERE id = ?
            """,
            (error_message[:2000], now, now, item_id),
        )


def finalize_batch(batch_id: str, *, target_table: str, target_batch_id: str | None) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        counts = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS success_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count,
                COUNT(*) AS total_count
            FROM ingest_items
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        success_count = int(counts["success_count"] or 0)
        failed_count = int(counts["failed_count"] or 0)
        skipped_count = int(counts["skipped_count"] or 0)
        total_count = int(counts["total_count"] or 0)
        if failed_count == 0 and success_count > 0:
            status = "completed"
        elif success_count > 0:
            status = "partial"
        else:
            status = "failed"
        conn.execute(
            """
            UPDATE ingest_batches
            SET
                status = ?,
                total_count = ?,
                success_count = ?,
                failed_count = ?,
                skipped_count = ?,
                target_table = ?,
                target_batch_id = ?,
                updated_at = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (
                status,
                total_count,
                success_count,
                failed_count,
                skipped_count,
                target_table,
                target_batch_id,
                now,
                now,
                batch_id,
            ),
        )


def mark_batch_failed(batch_id: str, error_message: str) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE ingest_batches
            SET status = 'failed', error_message = ?, updated_at = ?, finished_at = ?
            WHERE id = ?
            """,
            (error_message[:2000], now, now, batch_id),
        )


def build_batch_response(conn: Any, batch_id: str, *, idempotent_replay: bool = False) -> dict[str, Any]:
    batch = conn.execute("SELECT * FROM ingest_batches WHERE id = ?", (batch_id,)).fetchone()
    if not batch:
        raise IngestError(f"找不到 ingest batch: {batch_id}")
    items = conn.execute(
        """
        SELECT id, source_entity_id, status, target_table, target_id, error_message,
               category_match_status, canonical_category_path
        FROM ingest_items
        WHERE batch_id = ?
        ORDER BY source_row_index ASC, created_at ASC
        """,
        (batch_id,),
    ).fetchall()
    return {
        "ok": batch["status"] in {"completed", "partial"},
        "idempotent_replay": idempotent_replay,
        "batch": ingest_batch_row_to_api(batch),
        "items": [ingest_item_summary_to_api(row) for row in items],
    }


def ingest_batch_row_to_api(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "entityType": row["entity_type"],
        "mode": row["mode"],
        "idempotencyKey": row["idempotency_key"],
        "requestId": row["request_id"],
        "status": row["status"],
        "totalCount": int(row["total_count"] or 0),
        "successCount": int(row["success_count"] or 0),
        "failedCount": int(row["failed_count"] or 0),
        "skippedCount": int(row["skipped_count"] or 0),
        "targetTable": row["target_table"],
        "targetBatchId": row["target_batch_id"],
        "errorMessage": row["error_message"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "finishedAt": row["finished_at"],
    }


def ingest_item_summary_to_api(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "sourceEntityId": row["source_entity_id"],
        "status": row["status"],
        "targetTable": row["target_table"],
        "targetId": row["target_id"],
        "categoryMatchStatus": row["category_match_status"],
        "canonicalCategoryPath": row["canonical_category_path"],
        "errorMessage": row["error_message"],
    }


def find_idempotent_batch(conn: Any, source: str, entity_type: str, idempotency_key: str | None) -> Any | None:
    key = clean_optional(idempotency_key)
    if not key:
        return None
    return conn.execute(
        """
        SELECT *
        FROM ingest_batches
        WHERE source = ? AND entity_type = ? AND idempotency_key = ?
        ORDER BY datetime(created_at) DESC
        LIMIT 1
        """,
        (source, entity_type, key),
    ).fetchone()


def save_ingest_snapshot(batch_id: str, payload: IngestRequest) -> Path:
    path = UPLOADS_DIR / f"{batch_id}_ingest_{normalize_identifier(payload.source)}_{normalize_entity_type(payload.entity_type)}.json"
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return path


def guess_source_entity_id(source: str, entity_type: str, record: dict[str, Any]) -> str:
    if source == "yunqi" and entity_type == "product":
        for key in ("source_product_id", "product_id", "productId", "商品ID", "商品 ID", "id"):
            value = clean_optional(record.get(key))
            if value:
                return value
    if source == "1688":
        for key in ("offer_id", "offerId", "source_entity_id"):
            value = clean_optional(record.get(key))
            if value:
                return value
        for key in ("product_url", "source_url", "url", "link"):
            value = clean_optional(record.get(key))
            if value:
                return value
    return ""


def build_dedupe_key(source: str, entity_type: str, source_entity_id: str) -> str:
    return f"{source}:{entity_type}:{source_entity_id}"


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def normalize_identifier(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def normalize_entity_type(value: str | None) -> str:
    entity_type = normalize_identifier(value or "product")
    if entity_type in {"products", "sourcing_material", "sourcing_materials", "material", "materials"}:
        return "product"
    return entity_type


def normalize_mode(value: str) -> str:
    mode = normalize_identifier(value or "upsert")
    if mode not in {"append", "upsert", "replace"}:
        raise IngestError(f"不支持的导入模式：{value}")
    return mode


def clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None
