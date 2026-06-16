from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from app.core.database import (
    assert_user_api_usage_allowed,
    build_text_vector,
    cosine_similarity,
    ensure_export_product_attribute_schema,
    get_connection,
    record_api_usage_safe,
    sync_canonical_categories_from_dxm,
    utc_now_text,
)
from app.modules.visual_generation.clients import (
    build_api_url,
    get_ai_stage_settings,
    request_text_json,
)

QUEUE_STATUSES = ("queued", "running", "done", "failed")
REUSABLE_JOB_STATUSES = ("queued", "running", "done")
CHOICE_COMPONENTS = {"ant-select", "checkbox-group", "select-percent"}
NUMBER_INPUT_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
OTHER_FIBER_PERCENT_LIMIT = 5.0
CATEGORY_LEAF_POOL_LIMIT = 120
CATEGORY_BRANCH_CANDIDATE_LIMIT = 10
CATEGORY_AI_CONFIDENCE_FLOOR = 0.25
CATEGORY_VECTOR_CONFIDENT_SCORE = 0.55
ATTRIBUTE_GENERATION_VERSION = "complete-visible-fields-v2"
_CATEGORY_VECTOR_CACHE: dict[str, list[dict[str, Any]]] = {}


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
            delete_failed_product_attribute_jobs(conn, user_id=user_id, link_record_id=link_record_id)
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
            now = utc_now_text()
            if existing and existing["status"] in REUSABLE_JOB_STATUSES:
                reused += 1
                continue
            if existing:
                conn.execute(
                    """
                    UPDATE export_product_attribute_jobs
                    SET status = 'queued',
                        category_id = NULL,
                        category_path = NULL,
                        product_attribute_text = '',
                        product_attributes_json = '{}',
                        error_message = NULL,
                        record_json = ?,
                        updated_at = ?,
                        completed_at = NULL
                    WHERE id = ? AND user_id = ?
                    """,
                    (json.dumps(record, ensure_ascii=False), now, existing["id"], user_id),
                )
                inserted += 1
                continue
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
    summary = get_product_attribute_queue_summary(user_id=user_id, records=records)
    summary.update({"queuedNow": inserted, "reused": reused})
    return summary


def get_product_attribute_queue_summary(*, user_id: str, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        if records is not None:
            return get_product_attribute_queue_summary_for_records(conn, user_id=user_id, records=records)
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


def get_product_attribute_queue_summary_for_records(
    conn: Any,
    *,
    user_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    counts = {status: 0 for status in QUEUE_STATUSES}
    seen_keys: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, dict) or not record.get("skuEntries"):
            continue
        key = (record_identity(record), hash_attribute_input(record))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        row = conn.execute(
            """
            SELECT status
            FROM export_product_attribute_jobs
            WHERE user_id = ? AND link_record_id = ? AND record_hash = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id, key[0], key[1]),
        ).fetchone()
        if row and str(row["status"]) in counts:
            counts[str(row["status"])] += 1
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
            result = generate_product_attribute_for_record(record, user_id=user_id)
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


def clear_failed_product_attribute_cache_for_record(record: dict[str, Any], *, user_id: str) -> None:
    if not isinstance(record, dict):
        return
    link_record_id = record_identity(record)
    try:
        with get_connection() as conn:
            ensure_export_product_attribute_schema(conn)
            delete_failed_product_attribute_jobs(conn, user_id=user_id, link_record_id=link_record_id)
    except Exception:
        return


def delete_failed_product_attribute_jobs(
    conn: Any,
    *,
    user_id: str | None = None,
    link_record_id: str | None = None,
) -> int:
    where = ["status = 'failed'"]
    params: list[Any] = []
    if user_id is not None:
        where.append("user_id = ?")
        params.append(user_id)
    if link_record_id is not None:
        where.append("link_record_id = ?")
        params.append(link_record_id)
    cursor = conn.execute(
        f"DELETE FROM export_product_attribute_jobs WHERE {' AND '.join(where)}",
        tuple(params),
    )
    return int(cursor.rowcount or 0)


def get_product_attribute_for_export_record(record: dict[str, Any], *, user_id: str | None = None) -> dict[str, str]:
    uid = user_id or "default-user"
    clear_failed_product_attribute_cache_for_record(record, user_id=uid)
    cached = get_cached_product_attribute_for_record(record, user_id=uid)
    if cached:
        return cached

    try:
        result = generate_product_attribute_for_record(record, user_id=uid)
    except Exception as exc:
        clear_failed_product_attribute_cache_for_record(record, user_id=uid)
        return {}

    try:
        save_product_attribute_result_for_record(record, user_id=uid, result=result)
    except Exception:
        pass
    return product_attribute_result_to_cache(result)


def product_attribute_result_to_cache(result: dict[str, Any]) -> dict[str, str]:
    product_attributes = result.get("product_attributes") or []
    product_attribute_text = clean_text(result.get("product_attribute_text"))
    if not product_attribute_text:
        product_attribute_text = dump_product_attributes(product_attributes)
    return {
        "category_id": clean_text(result.get("category_id")),
        "category_path": clean_text(result.get("category_path")),
        "product_attribute_text": product_attribute_text,
        "product_attributes_json": dump_product_attributes(product_attributes),
    }


def save_product_attribute_result_for_record(record: dict[str, Any], *, user_id: str, result: dict[str, Any]) -> None:
    now = utc_now_text()
    link_record_id = record_identity(record)
    record_hash = hash_attribute_input(record)
    product_attributes = result.get("product_attributes") or []
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        row = conn.execute(
            """
            SELECT id
            FROM export_product_attribute_jobs
            WHERE user_id = ? AND link_record_id = ? AND record_hash = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id, link_record_id, record_hash),
        ).fetchone()
        payload = (
            clean_text(result.get("category_id")),
            clean_text(result.get("category_path")),
            clean_text(result.get("product_attribute_text")) or dump_product_attributes(product_attributes),
            dump_product_attributes(product_attributes),
            json.dumps(record, ensure_ascii=False),
            now,
            now,
        )
        if row:
            conn.execute(
                """
                UPDATE export_product_attribute_jobs
                SET status = 'done', category_id = ?, category_path = ?, product_attribute_text = ?,
                    product_attributes_json = ?, record_json = ?, error_message = NULL, updated_at = ?, completed_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (*payload, row["id"], user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO export_product_attribute_jobs (
                    id, user_id, link_record_id, product_id, product_title, category_id, category_path,
                    product_attribute_text, product_attributes_json, record_hash, record_json,
                    status, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'done', ?, ?, ?)
                """,
                (
                    f"attr-{uuid.uuid4().hex}",
                    user_id,
                    link_record_id,
                    clean_text(record.get("productId")),
                    clean_text(record.get("productTitle")),
                    clean_text(result.get("category_id")),
                    clean_text(result.get("category_path")),
                    clean_text(result.get("product_attribute_text")) or dump_product_attributes(product_attributes),
                    dump_product_attributes(product_attributes),
                    record_hash,
                    json.dumps(record, ensure_ascii=False),
                    now,
                    now,
                    now,
                ),
            )


def save_product_attribute_failure_for_record(record: dict[str, Any], *, user_id: str, error: str) -> None:
    now = utc_now_text()
    link_record_id = record_identity(record)
    record_hash = hash_attribute_input(record)
    with get_connection() as conn:
        ensure_export_product_attribute_schema(conn)
        row = conn.execute(
            """
            SELECT id
            FROM export_product_attribute_jobs
            WHERE user_id = ? AND link_record_id = ? AND record_hash = ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id, link_record_id, record_hash),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE export_product_attribute_jobs
                SET status = 'failed', error_message = ?, record_json = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (clean_text(error)[:1000], json.dumps(record, ensure_ascii=False), now, row["id"], user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO export_product_attribute_jobs (
                    id, user_id, link_record_id, product_id, product_title, record_hash,
                    record_json, status, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'failed', ?, ?, ?)
                """,
                (
                    f"attr-{uuid.uuid4().hex}",
                    user_id,
                    link_record_id,
                    clean_text(record.get("productId")),
                    clean_text(record.get("productTitle")),
                    record_hash,
                    json.dumps(record, ensure_ascii=False),
                    clean_text(error)[:1000],
                    now,
                    now,
                ),
            )


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
                dump_product_attributes(result.get("product_attributes") or []),
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
            DELETE FROM export_product_attribute_jobs
            WHERE id = ? AND user_id = ?
            """,
            (job_id, user_id),
        )


def generate_product_attribute_for_record(record: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
    with get_connection() as conn:
        category = resolve_category_for_record(conn, record, user_id=user_id)
        if not category:
            raise ValueError("No matching category attribute definition was found for this product")
        fields = load_category_fields(conn, str(category["category_id"]))

    if not fields:
        raise ValueError("The matched category has no available product attribute fields")

    ai_result: dict[str, Any] = {}
    ai_error = ""
    if is_product_attribute_ai_configured(user_id=user_id):
        try:
            ai_result = request_product_attribute_ai(record, category, fields, user_id=user_id)
        except Exception as exc:
            ai_error = str(exc)

    product_attributes = generate_complete_product_attributes(record, fields, ai_result)
    if not product_attributes and ai_error:
        raise ValueError(f"Product attribute AI generation failed: {ai_error}")
    return {
        "category_id": str(category["category_id"] or ""),
        "category_path": str(category["category_path_text"] or ""),
        "product_attributes": product_attributes,
        "product_attribute_text": dump_product_attributes(product_attributes),
    }


def resolve_category_for_record(conn: Any, record: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any] | None:
    product_context = load_product_context(conn, record)
    explicit_category_id = first_non_empty(
        record.get("categoryId"),
        record.get("category_id"),
        record.get("temuCategoryId"),
        record.get("dxmCategoryId"),
    )
    if explicit_category_id:
        row = conn.execute(
            """
            SELECT *
            FROM dxm_temu_category_attr_snapshots
            WHERE category_id = ?
            ORDER BY required_count DESC, attr_count DESC
            LIMIT 1
            """,
            (explicit_category_id,),
        ).fetchone()
        if row:
            return dict(row)

    context_category = resolve_category_by_known_path(conn, record, product_context)
    if context_category:
        return context_category

    semantic_category = resolve_category_by_ai_vector(conn, record, product_context, user_id=user_id)
    if semantic_category:
        return semantic_category

    product_id = clean_text(record.get("productId"))
    if product_id:
        row = conn.execute(
            """
            SELECT snapshot.*
            FROM product_category_matches match
            JOIN canonical_categories category
                ON category.id = match.canonical_category_id
            JOIN dxm_temu_category_attr_snapshots snapshot
                ON snapshot.category_id = category.external_category_id
            WHERE match.product_id = ?
                AND match.status IN ('auto', 'review')
                AND category.external_category_id != ''
            ORDER BY match.match_score DESC, snapshot.required_count DESC, snapshot.attr_count DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchone()
        if row:
            return dict(row)

    category_path = clean_text(product_context.get("category_path")) or record_category_path(record)
    title = clean_text(record.get("productTitle"))

    candidate_paths = [category_path]
    if category_path:
        candidate_paths.extend(split_search_terms(category_path))
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

    title_terms = [term for term in split_search_terms(title) if len(term) >= 2][:8]
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


def resolve_category_by_known_path(conn: Any, record: dict[str, Any], product_context: dict[str, Any]) -> dict[str, Any] | None:
    category_path = record_category_path(record) or clean_text(product_context.get("category_path"))
    candidate_paths = [category_path]
    if category_path:
        candidate_paths.extend(split_search_terms(category_path))
    candidate_paths.extend([clean_text(product_context.get("category_level2")), clean_text(product_context.get("category_level1"))])

    for value in unique_strings(candidate_paths):
        row = conn.execute(
            """
            SELECT *
            FROM dxm_temu_category_attr_snapshots
            WHERE category_path_text = ? OR leaf_name = ? OR category_path_text LIKE ?
            ORDER BY
                CASE
                    WHEN category_path_text = ? THEN 0
                    WHEN leaf_name = ? THEN 1
                    ELSE 2
                END,
                required_count DESC,
                attr_count DESC
            LIMIT 1
            """,
            (value, value, f"%{value}%", value, value),
        ).fetchone()
        if row:
            return dict(row)
    return None


def resolve_category_by_ai_vector(
    conn: Any,
    record: dict[str, Any],
    product_context: dict[str, Any],
    *,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    categories = load_canonical_categories_for_attribute_match(conn)
    leaves = [category for category in categories if clean_text(category.get("external_category_id")) and int(category.get("attr_count") or 0) > 0]
    if not leaves:
        return None

    intent = build_category_intent(record, product_context, use_ai=False, user_id=user_id)
    leaf = resolve_category_leaf_by_vector(record, product_context, leaves, intent, allow_ai_final=False, user_id=user_id)
    if leaf and float(leaf.get("score") or 0) >= CATEGORY_VECTOR_CONFIDENT_SCORE:
        return load_snapshot_for_category_leaf(conn, leaf)

    if is_product_attribute_ai_configured(user_id=user_id):
        ai_intent = build_category_intent(record, product_context, use_ai=True, user_id=user_id)
        ai_leaf = resolve_category_leaf_by_vector(record, product_context, leaves, ai_intent, allow_ai_final=False, user_id=user_id)
        if ai_leaf:
            return load_snapshot_for_category_leaf(conn, ai_leaf)

    if leaf:
        return load_snapshot_for_category_leaf(conn, leaf)
    return None


def resolve_category_leaf_by_vector(
    record: dict[str, Any],
    product_context: dict[str, Any],
    leaves: list[dict[str, Any]],
    intent: dict[str, Any],
    *,
    allow_ai_final: bool,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    query_text = category_query_text(record, product_context, intent)
    query_vector = build_text_vector(query_text)
    scored_leaves = score_category_leaves(leaves, query_vector, query_text)
    if not scored_leaves:
        return None

    selected_parts: list[str] = []
    current_leaves = scored_leaves[:CATEGORY_LEAF_POOL_LIMIT]
    for _depth in range(8):
        branches = next_category_branches(current_leaves, selected_parts)
        if not branches:
            break
        selected_branch = branches[0]
        selected_parts = selected_branch["path_parts"]
        current_leaves = [
            leaf for leaf in current_leaves
            if category_path_startswith(leaf.get("path_parts") or [], selected_parts)
        ]
        if len(current_leaves) == 1 and len(current_leaves[0].get("path_parts") or []) == len(selected_parts):
            break

    if allow_ai_final:
        return choose_final_leaf_with_ai(
            record=record,
            intent=intent,
            leaves=current_leaves[:CATEGORY_BRANCH_CANDIDATE_LIMIT],
            user_id=user_id,
        ) or (current_leaves[0] if current_leaves else None)
    return current_leaves[0] if current_leaves else None


def load_canonical_categories_for_attribute_match(conn: Any) -> list[dict[str, Any]]:
    cache_key = category_vector_cache_key(conn)
    if cache_key in _CATEGORY_VECTOR_CACHE:
        return _CATEGORY_VECTOR_CACHE[cache_key]
    try:
        sync_canonical_categories_from_dxm(conn)
        rows = conn.execute(
            """
            SELECT id, external_category_id, parent_id, level, name, path_text, path_parts_json,
                   embedding_text, embedding_json, attr_count, required_count
            FROM canonical_categories
            WHERE provider = 'dxm_temu' AND status = 'active'
            ORDER BY level ASC, path_text ASC
            """
        ).fetchall()
    except Exception:
        return []

    categories: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        parts = parse_jsonish(item.get("path_parts_json"), [])
        if not isinstance(parts, list):
            parts = category_path_parts(item.get("path_text"))
        parts = [clean_text(part) for part in parts if clean_text(part)]
        vector = parse_jsonish(item.get("embedding_json"), {})
        if not isinstance(vector, dict) or not vector:
            vector = build_text_vector(item.get("embedding_text") or item.get("path_text"))
        categories.append(
            {
                "id": clean_text(item.get("id")),
                "external_category_id": clean_text(item.get("external_category_id")),
                "parent_id": clean_text(item.get("parent_id")),
                "level": int_or_zero(item.get("level")) or len(parts),
                "name": clean_text(item.get("name")) or (parts[-1] if parts else ""),
                "path_text": normalize_category_path_for_match(item.get("path_text")),
                "path_parts": parts,
                "vector": {str(key): float(value) for key, value in vector.items() if str(key)},
                "path_terms": set(build_text_vector(item.get("path_text")).keys()),
                "path_key": normalize_choice_text(item.get("path_text")),
                "attr_count": int_or_zero(item.get("attr_count")),
                "required_count": int_or_zero(item.get("required_count")),
            }
        )
    _CATEGORY_VECTOR_CACHE[cache_key] = categories
    return categories


def category_vector_cache_key(conn: Any) -> str:
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
        for row in rows:
            values = tuple(row)
            if len(values) >= 3 and clean_text(values[1]) == "main" and clean_text(values[2]):
                return clean_text(values[2])
    except Exception:
        pass
    return f"connection:{id(conn)}"


def build_category_intent(
    record: dict[str, Any],
    product_context: dict[str, Any],
    *,
    use_ai: bool,
    user_id: str | None = None,
) -> dict[str, Any]:
    fallback = {
        "product_type": clean_text(record.get("productTitle")),
        "core_keywords": split_search_terms(category_query_text(record, product_context, {}))[:12],
        "category_hints": unique_strings([
            record_category_path(record),
            clean_text(product_context.get("category_path")),
            clean_text(product_context.get("category_level1")),
            clean_text(product_context.get("category_level2")),
        ]),
    }
    if not use_ai or not is_product_attribute_ai_configured(user_id=user_id):
        return fallback
    try:
        ai_result = request_category_intent_ai(record, product_context, user_id=user_id)
    except Exception:
        return fallback
    if not isinstance(ai_result, dict):
        return fallback
    merged = {**fallback, **{key: value for key, value in ai_result.items() if value not in (None, "", [])}}
    return merged


def request_category_intent_ai(
    record: dict[str, Any],
    product_context: dict[str, Any],
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    settings = get_ai_stage_settings("product_attribute", user_id=user_id)
    instruction = {
        "task": "Parse the product title into category matching signals for a Temu/Dianxiaomi category tree. Return concise category terms only, not marketing copy.",
        "output_schema": {
            "product_type": "short noun phrase",
            "core_keywords": ["category keyword"],
            "materials": ["material if useful"],
            "use_scenes": ["use scene"],
            "audience": ["target user or pet type"],
            "category_hints": ["likely category path words"],
            "exclude_keywords": ["words that should not drive category selection"],
        },
        "product": {
            "title_cn": clean_text(record.get("productTitle")),
            "title_en": clean_text(record.get("productTitleEn")),
            "sku_names": sku_names_for_prompt(record)[:20],
            "source_titles": [clean_text(source.get("title")) for source in record.get("sourceLinks") or [] if isinstance(source, dict)],
            "known_category_path": first_non_empty(record_category_path(record), product_context.get("category_path")),
        },
    }
    assert_user_api_usage_allowed(user_id)
    try:
        result = request_text_json(
            api_url=build_api_url(settings["base_url"]),
            api_key=settings["api_key"],
            model=settings["model"],
            instruction=json.dumps(instruction, ensure_ascii=False),
            temperature=0.05,
        )
        record_product_attribute_usage(settings, user_id=user_id, status="success")
        return result
    except Exception as exc:
        record_product_attribute_usage(settings, user_id=user_id, status="failed", error_message=str(exc))
        raise


def category_query_text(record: dict[str, Any], product_context: dict[str, Any], intent: dict[str, Any]) -> str:
    parts = [
        clean_text(record.get("productTitle")),
        clean_text(record.get("productTitleEn")),
        record_category_path(record),
        clean_text(product_context.get("category_path")),
        clean_text(product_context.get("category_level1")),
        clean_text(product_context.get("category_level2")),
        clean_text(intent.get("product_type")),
    ]
    for key in ("core_keywords", "materials", "use_scenes", "audience", "category_hints"):
        value = intent.get(key)
        if isinstance(value, list):
            parts.extend(clean_text(item) for item in value)
        else:
            parts.append(clean_text(value))
    parts.extend(sku_names_for_prompt(record)[:20])
    for source in record.get("sourceLinks") or []:
        if isinstance(source, dict):
            parts.append(clean_text(source.get("title")))
    return " ".join(part for part in parts if part)


def score_category_leaves(leaves: list[dict[str, Any]], query_vector: dict[str, float], query_text: str) -> list[dict[str, Any]]:
    query_terms = set(query_vector.keys())
    query_key = normalize_choice_text(query_text)
    scored: list[dict[str, Any]] = []
    for leaf in leaves:
        path_text = clean_text(leaf.get("path_text"))
        path_terms = leaf.get("path_terms") if isinstance(leaf.get("path_terms"), set) else set(build_text_vector(path_text).keys())
        matched_terms = query_terms & path_terms
        adjustment = category_specific_score_adjustment(query_key, leaf.get("path_key") or normalize_choice_text(path_text))
        if not matched_terms and adjustment <= 0:
            continue
        vector_score = cosine_similarity(query_vector, leaf.get("vector") or {})
        term_score = min(0.45, 0.08 * len(matched_terms))
        leaf_name = clean_text(leaf.get("name"))
        name_bonus = 0.15 if leaf_name and normalize_choice_text(leaf_name) in query_key else 0.0
        relevance_score = (
            vector_score
            + term_score
            + name_bonus
            + adjustment
        )
        if relevance_score <= 0:
            continue
        score = relevance_score + min(0.03, int(leaf.get("required_count") or 0) * 0.003)
        if score <= 0:
            continue
        scored.append({**leaf, "score": round(score, 6), "matched_terms": sorted(matched_terms)[:10]})
    scored.sort(key=lambda item: (float(item.get("score") or 0), int(item.get("required_count") or 0), int(item.get("attr_count") or 0)), reverse=True)
    return scored


def category_specific_score_adjustment(query_key: str, path_key: str) -> float:
    score = 0.0
    pet_bowl_terms = ("宠物碗", "猫碗", "狗碗", "食盆", "碗碟", "餐垫", "飞碟碗")
    if "宠物" in query_key and any(term in query_key for term in pet_bowl_terms):
        if "宠物" in path_key and any(term in path_key for term in ("碗", "碗碟", "食盆", "喂食喂水", "饮水用具")):
            score += 0.65
        if any(term in path_key for term in ("智能", "自动", "喂食机", "电子")) and not any(term in query_key for term in ("智能", "自动", "电动", "定时")):
            score -= 0.75
        if "运动风" in path_key and "运动" not in query_key:
            score -= 0.25
    if "多肉" in query_key and any(term in path_key for term in ("多肉", "盆栽", "鲜花绿植")):
        score += 0.35
    return score


def next_category_branches(scored_leaves: list[dict[str, Any]], selected_parts: list[str]) -> list[dict[str, Any]]:
    next_level = len(selected_parts) + 1
    groups: dict[str, dict[str, Any]] = {}
    for leaf in scored_leaves:
        parts = leaf.get("path_parts") or []
        if len(parts) < next_level or not category_path_startswith(parts, selected_parts):
            continue
        branch_parts = parts[:next_level]
        key = normalize_category_path_for_match("/".join(branch_parts))
        group = groups.setdefault(
            key,
            {
                "name": clean_text(branch_parts[-1]),
                "path_parts": branch_parts,
                "path_text": key,
                "score": 0.0,
                "leaf_count": 0,
                "examples": [],
            },
        )
        group["leaf_count"] += 1
        group["score"] = max(float(group["score"]), float(leaf.get("score") or 0))
        if len(group["examples"]) < 3:
            group["examples"].append(clean_text(leaf.get("path_text")))
    branches = list(groups.values())
    branches.sort(key=lambda item: (float(item["score"]), int(item["leaf_count"])), reverse=True)
    return branches[:CATEGORY_BRANCH_CANDIDATE_LIMIT]


def choose_category_branch_with_ai(
    *,
    record: dict[str, Any],
    intent: dict[str, Any],
    current_path: list[str],
    branches: list[dict[str, Any]],
    user_id: str | None = None,
) -> dict[str, Any] | None:
    if not branches or not is_product_attribute_ai_configured(user_id=user_id):
        return None
    result = request_category_branch_ai(
        record=record,
        intent=intent,
        current_path=current_path,
        candidates=branches,
        task="Choose the next category branch that best fits the product.",
        user_id=user_id,
    )
    return candidate_from_ai_choice(result, branches)


def choose_final_leaf_with_ai(
    *,
    record: dict[str, Any],
    intent: dict[str, Any],
    leaves: list[dict[str, Any]],
    user_id: str | None = None,
) -> dict[str, Any] | None:
    if not leaves:
        return None
    if len(leaves) == 1 or not is_product_attribute_ai_configured(user_id=user_id):
        return leaves[0]
    result = request_category_branch_ai(
        record=record,
        intent=intent,
        current_path=[],
        candidates=[
            {
                "name": clean_text(leaf.get("name")),
                "path_parts": leaf.get("path_parts") or [],
                "path_text": clean_text(leaf.get("path_text")),
                "score": float(leaf.get("score") or 0),
                "leaf_count": 1,
                "examples": [],
            }
            for leaf in leaves
        ],
        task="Choose the final leaf category that best fits the product.",
        user_id=user_id,
    )
    return candidate_from_ai_choice(result, leaves) or leaves[0]


def request_category_branch_ai(
    *,
    record: dict[str, Any],
    intent: dict[str, Any],
    current_path: list[str],
    candidates: list[dict[str, Any]],
    task: str,
    user_id: str | None = None,
) -> dict[str, Any]:
    settings = get_ai_stage_settings("product_attribute", user_id=user_id)
    payload_candidates = [
        {
            "index": index,
            "name": candidate.get("name"),
            "path": candidate.get("path_text"),
            "vector_score": candidate.get("score"),
            "leaf_count": candidate.get("leaf_count", 1),
            "examples": candidate.get("examples", []),
        }
        for index, candidate in enumerate(candidates, start=1)
    ]
    instruction = {
        "task": task,
        "rules": [
            "Select exactly one candidate index from the provided list.",
            "Prefer the real product type over use scenario or decorative words.",
            "Do not invent categories outside the candidate list.",
        ],
        "output_schema": {"selected_index": 1, "confidence": 0.0, "reason": "short reason"},
        "product": {
            "title_cn": clean_text(record.get("productTitle")),
            "title_en": clean_text(record.get("productTitleEn")),
            "sku_names": sku_names_for_prompt(record)[:20],
            "intent": intent,
        },
        "current_category_path": current_path,
        "candidates": payload_candidates,
    }
    assert_user_api_usage_allowed(user_id)
    try:
        result = request_text_json(
            api_url=build_api_url(settings["base_url"]),
            api_key=settings["api_key"],
            model=settings["model"],
            instruction=json.dumps(instruction, ensure_ascii=False),
            temperature=0.05,
        )
        record_product_attribute_usage(settings, user_id=user_id, status="success")
        return result
    except Exception as exc:
        record_product_attribute_usage(settings, user_id=user_id, status="failed", error_message=str(exc))
        return {}


def candidate_from_ai_choice(ai_result: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected_index = positive_int(ai_result.get("selected_index") or ai_result.get("index"))
    try:
        confidence = float(ai_result.get("confidence", 0))
    except Exception:
        confidence = 0.0
    if selected_index < 1 or selected_index > len(candidates) or confidence < CATEGORY_AI_CONFIDENCE_FLOOR:
        return None
    return candidates[selected_index - 1]


def load_snapshot_for_category_leaf(conn: Any, leaf: dict[str, Any]) -> dict[str, Any] | None:
    category_id = clean_text(leaf.get("external_category_id"))
    if category_id:
        row = conn.execute(
            """
            SELECT *
            FROM dxm_temu_category_attr_snapshots
            WHERE category_id = ?
            ORDER BY required_count DESC, attr_count DESC
            LIMIT 1
            """,
            (category_id,),
        ).fetchone()
        if row:
            return dict(row)
    path_text = clean_text(leaf.get("path_text"))
    if path_text:
        row = conn.execute(
            """
            SELECT *
            FROM dxm_temu_category_attr_snapshots
            WHERE category_path_text = ? OR category_path_text LIKE ?
            ORDER BY required_count DESC, attr_count DESC
            LIMIT 1
            """,
            (path_text, f"%{path_text.replace('/', '%')}%"),
        ).fetchone()
        if row:
            return dict(row)
    return None


def category_path_startswith(parts: list[str], prefix: list[str]) -> bool:
    return len(parts) >= len(prefix) and parts[: len(prefix)] == prefix


def category_path_parts(value: Any) -> list[str]:
    return [clean_text(part) for part in re.split(r"[/>\u203a\u300b]+", clean_text(value)) if clean_text(part)]


def normalize_category_path_for_match(value: Any) -> str:
    return "/".join(category_path_parts(value))


def load_product_context(conn: Any, record: dict[str, Any]) -> dict[str, Any]:
    product_id = clean_text(record.get("productId"))
    product_title = clean_text(record.get("productTitle"))
    source_urls = record_source_urls(record)
    for table in ("products", "product_pool_products"):
        try:
            if product_id:
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
            if source_urls:
                placeholders = ",".join("?" for _ in source_urls)
                row = conn.execute(
                    f"""
                    SELECT id, source_product_id, category_path, category_level1, category_level2, raw_data_json
                    FROM {table}
                    WHERE source_url IN ({placeholders})
                    LIMIT 1
                    """,
                    source_urls,
                ).fetchone()
                if row:
                    return dict(row)
            if product_title:
                row = conn.execute(
                    f"""
                    SELECT id, source_product_id, category_path, category_level1, category_level2, raw_data_json
                    FROM {table}
                    WHERE title = ? OR title_cn = ? OR title LIKE ? OR title_cn LIKE ?
                    LIMIT 1
                    """,
                    (product_title, product_title, f"%{product_title[:32]}%", f"%{product_title[:32]}%"),
                ).fetchone()
                if row:
                    return dict(row)
        except Exception:
            continue
    return record_category_context(record)


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


def request_product_attribute_ai(
    record: dict[str, Any],
    category: dict[str, Any],
    fields: list[dict[str, Any]],
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    settings = get_ai_stage_settings("product_attribute", user_id=user_id)
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
        source_raw = raw.get("raw") if isinstance(raw.get("raw"), dict) else raw
        compact_fields.append(
            {
                "field_key": field.get("field_key"),
                "field_label": field.get("field_label"),
                "required": bool(field.get("required")),
                "component": field.get("component"),
                "pid": raw.get("pid") or source_raw.get("pid") or raw.get("attributeId") or raw.get("id"),
                "templatePid": raw.get("templatePid") or source_raw.get("templatePid"),
                "refPid": raw.get("refPid") or raw.get("refPID") or source_raw.get("refPid") or source_raw.get("refPID"),
                "choose_max_num": positive_int(source_raw.get("chooseMaxNum") or raw.get("chooseMaxNum")),
                "value_units": value_units_for_field(field),
                "options": options,
            }
        )

    instruction = {
        "role": "You are a Dianxiaomi TEMU semi-managed product attribute assistant. Return JSON only, no explanations.",
        "task": "Use the product title, SKU names, category path, and candidate attribute fields to fill every visible product attribute field. For select fields, use exactly one provided option label and return its vid. For checkbox-group fields, choose at least one provided option. If the exact value cannot be confidently inferred, choose the safest generic/neutral option from the provided options, such as no/none/not applicable/generic/other. Do not leave fields blank. Do not invent certifications, brands, medical claims, safety claims, waterproof claims, or unverifiable sensitive attributes.",
        "output_schema": {
            "attributes": [
                {
                    "field_label": "field label",
                    "prop_value": "single selected value for select/input",
                    "prop_values": ["selected values for checkbox-group"],
                    "number_input_value": "numeric input value when needed",
                    "value_unit": "",
                    "vid": "option vid if available"
                }
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
    assert_user_api_usage_allowed(user_id)
    try:
        result = request_text_json(
            api_url=api_url,
            api_key=settings["api_key"],
            model=settings["model"],
            instruction=json.dumps(instruction, ensure_ascii=False),
            temperature=0.15,
        )
        record_product_attribute_usage(settings, user_id=user_id, status="success")
        return result
    except Exception as exc:
        record_product_attribute_usage(settings, user_id=user_id, status="failed", error_message=str(exc))
        raise


def record_product_attribute_usage(
    settings: dict[str, str],
    *,
    user_id: str | None,
    status: str,
    error_message: str | None = None,
) -> None:
    record_api_usage_safe(
        provider="openai-compatible",
        api_type="chat",
        stage="product_attribute",
        model=settings.get("model") or "unknown",
        user_id=user_id,
        channel_id=settings.get("channel_id"),
        status=status,
        error_message=error_message,
    )


def normalize_product_attributes(ai_result: dict[str, Any], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_items = ai_result.get("attributes") or ai_result.get("product_attributes") or []
    if not isinstance(raw_items, list):
        raw_items = []
    decisions = index_attribute_decisions(raw_items)
    normalized: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for field in fields:
        label = clean_text(field.get("field_label"))
        item = decisions.get(label) or decisions.get(clean_text(field.get("field_key")))
        if not item:
            continue
        if not field_conditions_match(field, selected):
            continue
        normalized.extend(normalize_decision_for_field(item, field, selected))
        selected = normalized[:]
    return normalized


def generate_complete_product_attributes(
    record: dict[str, Any],
    fields: list[dict[str, Any]],
    ai_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_items = (ai_result or {}).get("attributes") or (ai_result or {}).get("product_attributes") or []
    if not isinstance(raw_items, list):
        raw_items = []
    decisions = index_attribute_decisions(raw_items)
    normalized: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    product_text = f"{product_context_text(record)} {clean_text((fields[0] if fields else {}).get('category_path_text'))}"

    for field in fields:
        if not field_conditions_match(field, selected):
            continue
        label = clean_text(field.get("field_label"))
        item = decisions.get(label) or decisions.get(clean_text(field.get("field_key")))
        field_items: list[dict[str, Any]] = []
        if item:
            field_items = normalize_decision_for_field(item, field, selected)
        if not field_items:
            field_items = generate_default_attribute_for_field(field, selected, product_text)
        if not field_items:
            continue
        normalized.extend(field_items)
        selected = normalized[:]
    return normalized


def generate_rule_based_product_attributes(record: dict[str, Any], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    product_text = f"{product_context_text(record)} {clean_text((fields[0] if fields else {}).get('category_path_text'))}"
    for field in fields:
        if not bool(field.get("required")):
            continue
        if not field_conditions_match(field, selected):
            continue
        component = clean_text(field.get("component"))
        if component not in CHOICE_COMPONENTS:
            continue
        option = pick_rule_based_option(field, product_text)
        if not option:
            continue
        item = {"field_label": clean_text(field.get("field_label")), "prop_value": option_label(option), "vid": clean_text(option.get("vid"))}
        normalized.extend(normalize_decision_for_field(item, field, selected))
        selected = normalized[:]
    return normalized


def generate_default_attribute_for_field(
    field: dict[str, Any],
    selected: list[dict[str, Any]],
    product_text: str,
) -> list[dict[str, Any]]:
    component = clean_text(field.get("component"))
    if component in CHOICE_COMPONENTS or field.get("options"):
        allowed_vids = allowed_option_vids_for_field(field, selected)
        number_input_value, value_unit = choice_number_input_for_item({}, field)
        option = pick_rule_based_option(field, product_text, allowed_vids=allowed_vids)
        if not option:
            option = default_choice_option(field, allowed_vids=allowed_vids, number_input_value=number_input_value)
        if not option:
            return []
        item = {
            "field_label": clean_text(field.get("field_label")),
            "prop_value": option_label(option),
            "vid": clean_text(option.get("vid")),
            "number_input_value": number_input_value,
            "value_unit": value_unit,
        }
        return normalize_decision_for_field(item, field, selected)

    if is_numeric_input_field(field):
        number_input_value, value_unit = default_numeric_input_for_field(field, product_text)
        if not number_input_value:
            return []
        return [make_product_attribute_item(field, number_input_value=number_input_value, value_unit=value_unit)]

    value = default_text_input_for_field(field)
    if not value:
        return []
    return [make_product_attribute_item(field, prop_value=value, value_unit=default_value_unit_for_field(field))]


def normalize_decision_for_field(item: dict[str, Any], field: dict[str, Any], selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    component = clean_text(field.get("component"))
    if component in CHOICE_COMPONENTS or field.get("options"):
        values = decision_values(item)
        if not values and clean_text(item.get("vid")):
            values = [clean_text(item.get("vid"))]
        max_values = choose_max_for_field(field)
        if component != "checkbox-group" and max_values <= 1:
            values = values[:1]
        elif max_values > 0:
            values = values[:max_values]

        allowed_vids = allowed_option_vids_for_field(field, selected)
        number_input_value, value_unit = choice_number_input_for_item(item, field)
        result: list[dict[str, Any]] = []
        seen_vids: set[str] = set()
        for value in values:
            option = find_option(value, field.get("options") or [], allowed_vids=allowed_vids)
            if not option:
                continue
            option = safe_choice_option(field, option, number_input_value, allowed_vids=allowed_vids)
            if not option:
                continue
            vid = clean_text(option.get("vid"))
            if vid and vid in seen_vids:
                continue
            seen_vids.add(vid)
            result.append(
                make_product_attribute_item(
                    field,
                    prop_value=option_label(option),
                    vid=vid,
                    number_input_value=number_input_value,
                    value_unit=value_unit,
                )
            )
        if result:
            return result
        if allowed_vids:
            fallback = first_allowed_option(field.get("options") or [], allowed_vids)
            if fallback:
                fallback = safe_choice_option(field, fallback, number_input_value, allowed_vids=allowed_vids)
            if fallback:
                return [
                    make_product_attribute_item(
                        field,
                        prop_value=option_label(fallback),
                        vid=clean_text(fallback.get("vid")),
                        number_input_value=number_input_value,
                        value_unit=value_unit,
                    )
                ]
        return []

    value = clean_text(
        item.get("number_input_value")
        or item.get("numberInputValue")
        or item.get("prop_value")
        or item.get("propValue")
        or item.get("value")
    )
    if not value:
        return []
    value_unit = clean_text(item.get("value_unit") or item.get("valueUnit"))
    if is_numeric_input_field(field):
        number_input_value, value_unit = normalize_number_input(value, field, value_unit)
        return [make_product_attribute_item(field, number_input_value=number_input_value, value_unit=value_unit)]
    value_unit = value_unit or default_value_unit_for_field(field)
    return [make_product_attribute_item(field, prop_value=value, value_unit=value_unit)]


def index_attribute_decisions(raw_items: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        keys = [
            clean_text(item.get("field_label") or item.get("propName") or item.get("name")),
            clean_text(item.get("field_key")),
        ]
        for key in keys:
            if key and key not in result:
                result[key] = item
    return result


def decision_values(item: dict[str, Any]) -> list[str]:
    for key in ("prop_values", "propValues", "values", "selected_values", "selectedValues"):
        value = item.get(key)
        if isinstance(value, list):
            return unique_strings([clean_text(part) for part in value])
    value = clean_text(item.get("prop_value") or item.get("propValue") or item.get("value"))
    if not value:
        return []
    if "|" in value:
        return unique_strings(value.split("|"))
    return [value]


def choice_number_input_for_item(item: dict[str, Any], field: dict[str, Any]) -> tuple[str, str]:
    number_input_value = clean_text(item.get("number_input_value") or item.get("numberInputValue"))
    value_unit = clean_text(item.get("value_unit") or item.get("valueUnit"))
    if number_input_value or is_numeric_input_field(field):
        number_input_value, value_unit = normalize_number_input(number_input_value, field, value_unit)
    if clean_text(field.get("component")) == "select-percent":
        number_input_value = number_input_value or "100"
        value_unit = value_unit or default_value_unit_for_field(field)
    return number_input_value, value_unit


def normalize_number_input(value: Any, field: dict[str, Any], value_unit: Any = "") -> tuple[str, str]:
    text = clean_text(value).replace(",", "")
    unit = clean_text(value_unit)
    if not text:
        return "", unit or default_value_unit_for_field(field)
    match = NUMBER_INPUT_PATTERN.search(text)
    if not match:
        return text, unit or default_value_unit_for_field(field)
    number = match.group(0)
    detected_unit = clean_text(text[match.end():])
    unit = unit or match_value_unit_for_field(field, detected_unit) or default_value_unit_for_field(field)
    return number, unit


def match_value_unit_for_field(field: dict[str, Any], unit: Any) -> str:
    unit_text = clean_text(unit)
    if not unit_text:
        return ""
    unit_key = normalize_unit_text(unit_text)
    for candidate in value_units_for_field(field):
        candidate_key = normalize_unit_text(candidate)
        if candidate_key and (candidate_key == unit_key or candidate_key in unit_key or unit_key in candidate_key):
            return candidate
    return unit_text


def normalize_unit_text(value: Any) -> str:
    return re.sub(r"\s+", "", clean_text(value).lower())


def safe_choice_option(
    field: dict[str, Any],
    option: dict[str, Any],
    number_input_value: str,
    *,
    allowed_vids: set[str] | None,
) -> dict[str, Any] | None:
    if not should_replace_other_fiber_option(field, option, number_input_value):
        return option
    return concrete_fiber_fallback_option(field, allowed_vids=allowed_vids)


def should_replace_other_fiber_option(field: dict[str, Any], option: dict[str, Any], number_input_value: str) -> bool:
    if clean_text(field.get("component")) != "select-percent":
        return False
    if not is_other_fiber_option(option):
        return False
    percent = parse_number_value(number_input_value)
    return percent is None or percent >= OTHER_FIBER_PERCENT_LIMIT


def is_other_fiber_option(option: dict[str, Any]) -> bool:
    other_fiber = normalize_choice_text("\u5176\u4ed6\u7ea4\u7ef4")
    other_fibers = normalize_choice_text("Other Fibers")
    for label in (option.get("label"), option.get("value"), option.get("en")):
        key = normalize_choice_text(label)
        if not key:
            continue
        if other_fiber in key or other_fibers in key:
            return True
    return False


def concrete_fiber_fallback_option(field: dict[str, Any], *, allowed_vids: set[str] | None) -> dict[str, Any] | None:
    options = [option for option in field.get("options") or [] if isinstance(option, dict)]
    candidate_groups = [
        ["\u805a\u916f\u7ea4\u7ef4(\u6da4\u7eb6)", "\u805a\u916f\u7ea4\u7ef4\uff08\u6da4\u7eb6\uff09", "\u805a\u916f\u7ea4\u7ef4", "\u6da4\u7eb6", "Polyester"],
        ["\u68c9", "Cotton"],
        ["\u5c3c\u9f99", "Nylon"],
        ["\u7af9\u7ea4\u7ef4", "Bamboo"],
    ]
    for candidates in candidate_groups:
        option = find_first_option_by_candidates(options, candidates, allowed_vids=allowed_vids)
        if option:
            return option
    return None


def parse_number_value(value: Any) -> float | None:
    match = NUMBER_INPUT_PATTERN.search(clean_text(value).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def make_product_attribute_item(
    field: dict[str, Any],
    *,
    prop_value: str = "",
    vid: str = "",
    number_input_value: str = "",
    value_unit: str = "",
) -> dict[str, Any]:
    raw = field_raw(field)
    return {
        "propName": clean_text(field.get("field_label")),
        "refPid": int_or_zero(raw.get("refPid") or raw.get("refPID")),
        "pid": int_or_zero(raw.get("pid") or raw.get("attributeId") or raw.get("id")),
        "templatePid": int_or_zero(raw.get("templatePid")),
        "numberInputValue": clean_text(number_input_value),
        "valueUnit": clean_text(value_unit),
        "vid": clean_text(vid),
        "propValue": clean_text(prop_value),
    }


def field_raw(field: dict[str, Any]) -> dict[str, Any]:
    raw = field.get("raw") if isinstance(field.get("raw"), dict) else {}
    nested = raw.get("raw")
    if isinstance(nested, dict):
        return {**nested, **raw}
    return raw


def find_option_vid(prop_value: str, options: list[Any]) -> str:
    option = find_option(prop_value, options)
    return clean_text(option.get("vid")) if option else ""


def find_option(value: str, options: list[Any], *, allowed_vids: set[str] | None = None) -> dict[str, Any] | None:
    value = clean_text(value)
    if not value:
        return None
    for option in options:
        if not isinstance(option, dict):
            continue
        vid = clean_text(option.get("vid"))
        if allowed_vids is not None and vid not in allowed_vids:
            continue
        labels = [option.get("label"), option.get("value"), option.get("en"), vid]
        if any(normalize_choice_text(label) == normalize_choice_text(value) for label in labels):
            return option
    for option in options:
        if not isinstance(option, dict):
            continue
        vid = clean_text(option.get("vid"))
        if allowed_vids is not None and vid not in allowed_vids:
            continue
        labels = [option.get("label"), option.get("value"), option.get("en")]
        if any(
            normalize_choice_text(label)
            and (
                normalize_choice_text(label) in normalize_choice_text(value)
                or normalize_choice_text(value) in normalize_choice_text(label)
            )
            for label in labels
        ):
            return option
    return None


def option_label(option: dict[str, Any]) -> str:
    return clean_text(option.get("label") or option.get("value") or option.get("en"))


def first_allowed_option(options: list[Any], allowed_vids: set[str]) -> dict[str, Any] | None:
    for option in options:
        if isinstance(option, dict) and clean_text(option.get("vid")) in allowed_vids:
            return option
    return None


def allowed_option_vids_for_field(field: dict[str, Any], selected: list[dict[str, Any]]) -> set[str] | None:
    raw = field_raw(field)
    rules = parse_jsonish(raw.get("templatePropertyValueParent"), [])
    if not isinstance(rules, list) or not rules:
        return None

    parent_template_pid = int_or_zero(raw.get("parentTemplatePid"))
    parent_selected = [
        item for item in selected
        if not parent_template_pid or int_or_zero(item.get("templatePid")) == parent_template_pid
    ]
    if not parent_selected:
        return None

    allowed: set[str] = set()
    selected_vids = {clean_text(item.get("vid")) for item in parent_selected}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        parent_vids = {clean_text(value) for value in rule.get("parentVidList") or []}
        if parent_vids and selected_vids.isdisjoint(parent_vids):
            continue
        allowed.update(clean_text(value) for value in rule.get("vidList") or [] if clean_text(value))
    return allowed or set()


def field_conditions_match(field: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    raw = field_raw(field)
    conditions = parse_jsonish(raw.get("showCondition"), [])
    if not isinstance(conditions, list) or not conditions:
        return True
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        parent_ref_pid = int_or_zero(condition.get("parentRefPid"))
        parent_vids = {clean_text(value) for value in condition.get("parentVids") or []}
        for item in selected:
            if parent_ref_pid and int_or_zero(item.get("refPid")) != parent_ref_pid:
                continue
            if not parent_vids or clean_text(item.get("vid")) in parent_vids:
                return True
    return False


def pick_rule_based_option(
    field: dict[str, Any],
    product_text: str,
    *,
    allowed_vids: set[str] | None = None,
) -> dict[str, Any] | None:
    options = [option for option in field.get("options") or [] if isinstance(option, dict)]
    if not options:
        return None
    label = clean_text(field.get("field_label"))
    label_key = normalize_choice_text(label)
    text_key = normalize_choice_text(product_text)

    color_terms = [
        ("黑", ["黑色", "Black"]),
        ("白", ["白色", "White"]),
        ("红", ["红色", "Red"]),
        ("粉", ["粉色", "Pink"]),
        ("蓝", ["蓝色", "Blue"]),
        ("绿", ["绿色", "Green"]),
        ("灰", ["灰色", "Grey", "Gray"]),
        ("黄", ["黄色", "Yellow"]),
        ("紫", ["紫色", "Purple"]),
        ("咖", ["咖啡色", "Coffee", "Brown"]),
    ]
    if "颜色" in label_key:
        for token, candidates in color_terms:
            if token in text_key:
                option = find_first_option_by_candidates(options, candidates, allowed_vids=allowed_vids)
                if option:
                    return option

    candidate_groups: list[list[str]] = []
    if any(token in label_key for token in ("品牌", "brand")):
        candidate_groups.append(["无品牌", "没有品牌", "No Brand", "Unbranded", "Generic", "通用", "其他", "其它"])
    if "类型" in label_key:
        candidate_groups.append(["详见商品详情", "其他"])
    if "是否" in label_key:
        if "成人" in label_key and any(token in text_key for token in ("成人", "男士", "女士", "adult", "men", "women")):
            candidate_groups.append(["是", "Yes"])
        candidate_groups.append(["否", "No"])
    if "适用人种" in label_key:
        candidate_groups.append(["适用各种人种", "Suitable For All People", "各种", "All"])
    if "适用年龄" in label_key:
        if any(token in text_key for token in ("成人", "男士", "女士", "adult", "men", "women")):
            candidate_groups.append(["18+", "18 Years+"])
        candidate_groups.append(["3+", "0+"])
    if any(token in label_key for token in ("材质", "材料", "成分", "纤维")):
        for token, candidates in [
            ("硅胶", ["硅胶", "Silicone"]),
            ("塑料", ["塑料", "Plastic"]),
            ("聚酯", ["聚酯纤维", "涤纶", "Polyester"]),
            ("微纤维", ["超细纤维", "Microfiber"]),
            ("超细", ["超细纤维", "Microfiber"]),
            ("木", ["木", "Wood"]),
            ("金属", ["金属", "Metal"]),
            ("高温丝", ["高温丝", "High temperature fiber"]),
        ]:
            if token in text_key:
                candidate_groups.append(candidates)
        if is_fiber_composition_field(field):
            candidate_groups.append(["聚酯纤维(涤纶)", "聚酯纤维（涤纶）", "聚酯纤维", "涤纶", "Polyester"])
        else:
            candidate_groups.append(["其他", "Else", "Other"])
    if "风格" in label_key:
        candidate_groups.append(["Fashionable时尚", "时尚", "Fashionable", "简约", "休闲", "其他"])
    if "主题" in label_key:
        candidate_groups.append(["时髦", "Sassy", "动物", "其他"])
    candidate_groups.append(["通用", "不限", "不适用", "其他", "其它"])

    for candidates in candidate_groups:
        option = find_first_option_by_candidates(options, candidates, allowed_vids=allowed_vids)
        if option:
            return option
    if len(options) == 1 and (allowed_vids is None or clean_text(options[0].get("vid")) in allowed_vids):
        return options[0]
    return None


def default_choice_option(
    field: dict[str, Any],
    *,
    allowed_vids: set[str] | None,
    number_input_value: str = "",
) -> dict[str, Any] | None:
    options = [option for option in field.get("options") or [] if isinstance(option, dict)]
    if allowed_vids is not None:
        options = [option for option in options if clean_text(option.get("vid")) in allowed_vids]
    if not options:
        return None

    label_key = normalize_choice_text(field.get("field_label"))
    candidate_groups: list[list[str]] = []
    if any(token in label_key for token in ("品牌", "brand")):
        candidate_groups.append(["无品牌", "没有品牌", "No Brand", "Unbranded", "Generic", "通用", "其他", "其它"])
    if any(token in label_key for token in ("是否", "有无", "is", "has", "with")):
        candidate_groups.append(["否", "无", "没有", "不含", "No", "None", "Without"])
    if any(token in label_key for token in ("材料特征", "材质特征", "materialfeature")):
        candidate_groups.append(["无", "无特殊", "无特殊材料", "不适用", "普通", "常规", "其他", "其它", "None", "Not Applicable", "Other"])
    if "颜色" in label_key or "color" in label_key:
        candidate_groups.append(["混合色", "多色", "白色", "黑色", "粉红色", "红色", "Mixed Color", "Multicolor", "White", "Black", "Pink", "Red"])
    if clean_text(field.get("component")) == "select-percent":
        candidate_groups.append(["聚酯纤维(涤纶)", "聚酯纤维（涤纶）", "聚酯纤维", "涤纶", "Polyester", "棉", "Cotton"])
    candidate_groups.append(["无", "否", "不适用", "不限", "通用", "普通", "常规", "其他", "其它", "None", "No", "N/A", "Not Applicable", "Generic", "Other"])

    for candidates in candidate_groups:
        option = find_first_option_by_candidates(options, candidates)
        if not option:
            continue
        option = safe_choice_option(field, option, number_input_value, allowed_vids=allowed_vids)
        if option:
            return option

    for option in options:
        option = safe_choice_option(field, option, number_input_value, allowed_vids=allowed_vids)
        if option:
            return option
    return None


def default_numeric_input_for_field(field: dict[str, Any], product_text: str) -> tuple[str, str]:
    value_unit = default_value_unit_for_field(field)
    label_key = normalize_choice_text(field.get("field_label"))
    text = clean_text(product_text)
    if value_unit:
        match = re.search(rf"([-+]?\d+(?:\.\d+)?)\s*{re.escape(value_unit)}", text, flags=re.IGNORECASE)
        if match:
            return normalize_number_input(match.group(1), field, value_unit)
    if any(token in label_key for token in ("克重", "gsm", "g/㎡", "g/m2")):
        match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(?:g/㎡|g/m2|gsm|克)", text, flags=re.IGNORECASE)
        if match:
            return normalize_number_input(match.group(1), field, value_unit)
        return normalize_number_input("250", field, value_unit)
    if any(token in label_key for token in ("百分比", "比例", "含量", "percent", "percentage")):
        return normalize_number_input("100", field, value_unit or "%")
    return normalize_number_input("1", field, value_unit)


def default_text_input_for_field(field: dict[str, Any]) -> str:
    label_key = normalize_choice_text(field.get("field_label"))
    if any(token in label_key for token in ("品牌", "brand")):
        return "无品牌"
    if any(token in label_key for token in ("型号", "model")):
        return "通用"
    return "详见商品详情"


def find_first_option_by_candidates(
    options: list[dict[str, Any]],
    candidates: list[str],
    *,
    allowed_vids: set[str] | None = None,
) -> dict[str, Any] | None:
    for candidate in candidates:
        option = find_option(candidate, options, allowed_vids=allowed_vids)
        if option:
            return option
    return None


def product_context_text(record: dict[str, Any]) -> str:
    parts = [
        clean_text(record.get("productTitle")),
        clean_text(record.get("productTitleEn")),
        record_category_path(record),
    ]
    parts.extend(sku_names_for_prompt(record))
    for source in record.get("sourceLinks") or []:
        if isinstance(source, dict):
            parts.append(clean_text(source.get("title")))
    return " ".join(part for part in parts if part)


def record_category_context(record: dict[str, Any]) -> dict[str, Any]:
    category_path = record_category_path(record)
    category_level1 = first_non_empty(record.get("categoryLevel1"), record.get("category_level1"))
    category_level2 = first_non_empty(record.get("categoryLevel2"), record.get("category_level2"))
    if not any((category_path, category_level1, category_level2)):
        return {}
    return {
        "id": clean_text(record.get("productId")),
        "source_product_id": clean_text(record.get("sourceProductId") or record.get("source_product_id")),
        "category_path": category_path,
        "category_level1": category_level1,
        "category_level2": category_level2,
        "raw_data_json": "{}",
    }


def record_category_path(record: dict[str, Any]) -> str:
    return first_non_empty(record.get("categoryPath"), record.get("category_path"), record.get("category"))


def record_source_urls(record: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("productSourceUrl", "product_source_url", "sourceUrl", "source_url"):
        value = clean_text(record.get(key))
        if value:
            urls.append(value)
    for source in record.get("sourceLinks") or []:
        if not isinstance(source, dict):
            continue
        for key in ("productUrl", "product_url", "sourceUrl", "source_url", "url"):
            value = clean_text(source.get(key))
            if value:
                urls.append(value)
    return unique_strings(urls)[:10]


def record_identity(record: dict[str, Any]) -> str:
    return clean_text(record.get("id")) or clean_text(record.get("productId")) or f"record-{uuid.uuid4().hex}"


def hash_attribute_input(record: dict[str, Any]) -> str:
    payload = {
        "attributeGenerationVersion": ATTRIBUTE_GENERATION_VERSION,
        "productId": clean_text(record.get("productId")),
        "productTitle": clean_text(record.get("productTitle")),
        "productTitleEn": clean_text(record.get("productTitleEn")),
        "categoryId": first_non_empty(record.get("categoryId"), record.get("category_id"), record.get("temuCategoryId"), record.get("dxmCategoryId")),
        "categoryPath": record_category_path(record),
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


def is_product_attribute_ai_configured(*, user_id: str | None = None) -> bool:
    settings = get_ai_stage_settings("product_attribute", user_id=user_id)
    return bool(clean_text(settings.get("api_key")))


def split_search_terms(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"\s+|>|/|\\|\||,|，|、|-", text) if part.strip()]


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def parse_jsonish(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def normalize_choice_text(value: Any) -> str:
    return re.sub(r"[\s\-_()/（）]+", "", clean_text(value).lower())


def is_fiber_composition_field(field: dict[str, Any]) -> bool:
    label_key = normalize_choice_text(field.get("field_label"))
    return clean_text(field.get("component")) == "select-percent" or any(token in label_key for token in ("成分", "纤维"))


def value_units_for_field(field: dict[str, Any]) -> list[str]:
    raw = field_raw(field)
    units = raw.get("valueUnits") or raw.get("valueUnit") or []
    if isinstance(units, str):
        units = parse_jsonish(units, [units])
    if not isinstance(units, list):
        return []
    return [clean_text(unit) for unit in units if clean_text(unit)]


def default_value_unit_for_field(field: dict[str, Any]) -> str:
    units = value_units_for_field(field)
    return units[0] if units else ""


def is_numeric_input_field(field: dict[str, Any]) -> bool:
    raw = field_raw(field)
    if clean_text(field.get("component")) == "select-percent":
        return True
    return positive_int(raw.get("valueRule")) == 2 or positive_int(raw.get("propertyValueType")) == 1


def choose_max_for_field(field: dict[str, Any]) -> int:
    raw = field_raw(field)
    return positive_int(raw.get("chooseMaxNum")) or (8 if clean_text(field.get("component")) == "checkbox-group" else 1)


def positive_int(value: Any) -> int:
    try:
        number = int(float(str(value).strip()))
    except Exception:
        return 0
    return number if number > 0 else 0


def dump_product_attributes(product_attributes: list[Any]) -> str:
    return json.dumps(product_attributes or [], ensure_ascii=False, separators=(",", ":"))


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
