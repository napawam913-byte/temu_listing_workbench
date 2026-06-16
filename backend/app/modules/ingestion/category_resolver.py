from __future__ import annotations

import json
import uuid
from typing import Any

from app.core.database import (
    CANONICAL_CATEGORY_PROVIDER,
    build_product_category_match,
    category_path_parts_from_text,
    clean_text,
    ensure_category_mapping_schema,
    ensure_ingest_schema,
    get_connection,
    load_matchable_canonical_categories,
    normalize_category_path_text,
    parse_json_text,
    utc_now_text,
)
from app.modules.ingestion.schemas import CategoryResolution


SOURCE_CATEGORY_KEYS = (
    "source_category_path",
    "category_path",
    "category",
    "categoryName",
    "category_name",
    "front_category",
    "frontCategory",
)


def resolve_ingest_category(
    *,
    source: str,
    entity_type: str,
    raw_record: dict[str, Any],
    normalized_record: dict[str, Any],
    context: dict[str, Any] | None = None,
    source_entity_id: str = "",
) -> CategoryResolution:
    context = context or {}
    source_category_raw = first_text(
        normalized_record.get("source_category_path"),
        normalized_record.get("category_path"),
        *(raw_record.get(key) for key in SOURCE_CATEGORY_KEYS),
    )
    source_category_path = normalize_source_category_path(source_category_raw)
    if source_category_path and source_category_path != "未分类":
        return resolve_source_category_mapping(
            source=source,
            entity_type=entity_type,
            source_category_raw=source_category_raw,
            source_category_path=source_category_path,
            title=first_text(
                normalized_record.get("title"),
                normalized_record.get("title_cn"),
                normalized_record.get("title_en"),
                raw_record.get("title"),
            ),
            source_entity_id=source_entity_id,
        )

    inherited = resolve_inherited_category(context)
    if inherited:
        return inherited

    return CategoryResolution(status="missing", method="missing")


def resolve_source_category_mapping(
    *,
    source: str,
    entity_type: str,
    source_category_raw: str,
    source_category_path: str,
    title: str,
    source_entity_id: str,
) -> CategoryResolution:
    normalized_source_category = normalize_category_path_text(source_category_path)
    now = utc_now_text()
    with get_connection() as conn:
        ensure_category_mapping_schema(conn)
        ensure_ingest_schema(conn)
        existing = conn.execute(
            """
            SELECT *
            FROM source_category_mappings
            WHERE source = ? AND entity_type = ? AND normalized_source_category = ?
            """,
            (source, entity_type, normalized_source_category),
        ).fetchone()
        if existing and existing["status"] in {"auto_matched", "manual_matched"}:
            return mapping_row_to_resolution(existing, source_category_raw)

        categories = load_matchable_canonical_categories(conn)
        if not categories:
            upsert_source_category_mapping(
                conn,
                source=source,
                entity_type=entity_type,
                source_category_path=source_category_path,
                normalized_source_category=normalized_source_category,
                status="provided",
                now=now,
            )
            return build_source_resolution(
                source_category_raw=source_category_raw,
                source_category_path=source_category_path,
                status="provided",
                method="source_category",
            )

        virtual_product = {
            "id": f"ingest:{source}:{entity_type}:{source_entity_id or uuid.uuid4().hex}",
            "source_type": source,
            "category_path": source_category_path,
            "title": title,
        }
        match = build_product_category_match(virtual_product, categories, now=now)
        status = match_status_to_ingest_status(match["status"])
        candidates = parse_json_text(match.get("candidates_json"), [])
        upsert_source_category_mapping(
            conn,
            source=source,
            entity_type=entity_type,
            source_category_path=source_category_path,
            normalized_source_category=normalized_source_category,
            canonical_category_id=match.get("canonical_category_id"),
            canonical_category_path=match.get("canonical_category_path"),
            match_score=float(match.get("match_score") or 0),
            match_method=clean_text(match.get("match_method")),
            status=status,
            candidates=candidates if isinstance(candidates, list) else [],
            now=now,
        )

    return build_source_resolution(
        source_category_raw=source_category_raw,
        source_category_path=source_category_path,
        canonical_category_id=match.get("canonical_category_id"),
        canonical_category_path=clean_text(match.get("canonical_category_path")),
        status=status,
        score=float(match.get("match_score") or 0),
        method=clean_text(match.get("match_method")),
        candidates=candidates if isinstance(candidates, list) else [],
    )


def resolve_inherited_category(context: dict[str, Any]) -> CategoryResolution | None:
    product_id = first_text(
        context.get("related_product_id"),
        context.get("temu_product_id"),
        context.get("product_id"),
    )
    source_product_id = first_text(context.get("related_source_product_id"), context.get("source_product_id"))
    source_type = first_text(context.get("related_source_type"), context.get("source_type")) or "yunqi"
    if not product_id and not source_product_id:
        return None

    with get_connection() as conn:
        params: list[Any] = []
        where = ""
        if product_id:
            where = "products.id = ?"
            params.append(product_id)
        else:
            where = "products.source_type = ? AND products.source_product_id = ?"
            params.extend([source_type, source_product_id])
        row = conn.execute(
            f"""
            SELECT
                products.category_path,
                products.category_level1,
                products.category_level2,
                pcm.canonical_category_id,
                pcm.canonical_category_path,
                pcm.match_score,
                pcm.match_method,
                pcm.status,
                pcm.candidates_json
            FROM products
            LEFT JOIN product_category_matches pcm ON pcm.product_id = products.id
            WHERE {where}
            ORDER BY datetime(products.updated_at) DESC
            LIMIT 1
            """,
            params,
        ).fetchone()

    if not row:
        return None

    candidates = parse_json_text(row["candidates_json"], [])
    return CategoryResolution(
        source_category_raw=clean_text(row["category_path"]),
        source_category_path=clean_text(row["category_path"]),
        source_category_level1=clean_text(row["category_level1"]),
        source_category_level2=clean_text(row["category_level2"]),
        canonical_category_id=row["canonical_category_id"],
        canonical_category_path=clean_text(row["canonical_category_path"]),
        status="inherited",
        score=float(row["match_score"] or 0),
        method=clean_text(row["match_method"]) or "related_product",
        candidates=candidates if isinstance(candidates, list) else [],
    )


def upsert_source_category_mapping(
    conn: Any,
    *,
    source: str,
    entity_type: str,
    source_category_path: str,
    normalized_source_category: str,
    canonical_category_id: str | None = None,
    canonical_category_path: str = "",
    match_score: float = 0.0,
    match_method: str = "",
    status: str = "pending",
    candidates: list[dict[str, Any]] | None = None,
    now: str,
) -> None:
    mapping_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"source-category-mapping:{source}:{entity_type}:{normalized_source_category}",
    ).hex
    conn.execute(
        """
        INSERT INTO source_category_mappings (
            id, source, entity_type, source_category_key, source_category_path,
            normalized_source_category, canonical_provider, canonical_category_id,
            canonical_category_path, match_score, match_method, status, sample_count,
            last_seen_at, candidates_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        ON CONFLICT(source, entity_type, normalized_source_category) DO UPDATE SET
            source_category_path = excluded.source_category_path,
            canonical_category_id = COALESCE(excluded.canonical_category_id, source_category_mappings.canonical_category_id),
            canonical_category_path = COALESCE(NULLIF(excluded.canonical_category_path, ''), source_category_mappings.canonical_category_path),
            match_score = excluded.match_score,
            match_method = excluded.match_method,
            status = excluded.status,
            sample_count = source_category_mappings.sample_count + 1,
            last_seen_at = excluded.last_seen_at,
            candidates_json = excluded.candidates_json,
            updated_at = excluded.updated_at
        """,
        (
            mapping_id,
            source,
            entity_type,
            normalized_source_category,
            source_category_path,
            normalized_source_category,
            CANONICAL_CATEGORY_PROVIDER,
            canonical_category_id,
            canonical_category_path,
            match_score,
            match_method,
            status,
            now,
            json.dumps(candidates or [], ensure_ascii=False),
            now,
            now,
        ),
    )


def mapping_row_to_resolution(row: Any, source_category_raw: str) -> CategoryResolution:
    candidates = parse_json_text(row["candidates_json"], [])
    return build_source_resolution(
        source_category_raw=source_category_raw,
        source_category_path=row["source_category_path"],
        canonical_category_id=row["canonical_category_id"],
        canonical_category_path=row["canonical_category_path"],
        status=row["status"],
        score=float(row["match_score"] or 0),
        method=row["match_method"],
        candidates=candidates if isinstance(candidates, list) else [],
    )


def build_source_resolution(
    *,
    source_category_raw: str,
    source_category_path: str,
    canonical_category_id: str | None = None,
    canonical_category_path: str = "",
    status: str,
    score: float = 0.0,
    method: str = "",
    candidates: list[dict[str, Any]] | None = None,
) -> CategoryResolution:
    parts = category_path_parts_from_text(source_category_path)
    return CategoryResolution(
        source_category_raw=source_category_raw,
        source_category_path=source_category_path,
        source_category_level1=parts[0] if parts else "",
        source_category_level2=parts[1] if len(parts) > 1 else "",
        canonical_category_id=canonical_category_id,
        canonical_category_path=canonical_category_path,
        status=status,
        score=score,
        method=method,
        candidates=candidates or [],
    )


def match_status_to_ingest_status(status: str) -> str:
    if status == "auto":
        return "auto_matched"
    if status == "review":
        return "review_required"
    return "unmatched"


def normalize_source_category_path(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "/".join(clean_text(item) for item in value if clean_text(item))
    return normalize_category_path_text(value)


def first_text(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""

