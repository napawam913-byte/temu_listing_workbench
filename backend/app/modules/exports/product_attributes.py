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
    record_api_usage_safe,
)
from app.modules.exports.postgres_store import get_export_connection as get_connection
from app.modules.visual_generation.clients import (
    build_api_url,
    extract_response_text,
    get_ai_stage_settings,
    parse_json_from_text,
    request_json,
    request_text_json,
)

QUEUE_STATUSES = ("queued", "running", "done", "failed")
CHOICE_COMPONENTS = {"ant-select", "checkbox-group", "select-percent"}
NUMBER_INPUT_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?")
OTHER_FIBER_PERCENT_LIMIT = 5.0
CATEGORY_LEAF_POOL_LIMIT = 120
CATEGORY_BRANCH_CANDIDATE_LIMIT = 10
CATEGORY_FINAL_CANDIDATE_LIMIT = 20
CATEGORY_TREE_BRANCH_CANDIDATE_LIMIT = 30
CATEGORY_AI_CONFIDENCE_FLOOR = 0.25
CATEGORY_VECTOR_CONFIDENT_SCORE = 0.55
MAX_CATEGORY_REFERENCE_IMAGES = 6
ATTRIBUTE_GENERATION_VERSION = "complete-visible-fields-v7-red-line-guards"
NOISY_CATEGORY_PATH_SEGMENTS = {"companyinfo", "categories"}

RED_LINE_CHILD_FIELD_TOKENS = (
    "\u5de5\u4f5c\u7535\u538b",
    "\u7535\u538b",
    "\u63d2\u5934\u89c4\u683c",
    "\u63d2\u5934",
    "\u53ef\u5145\u7535\u7535\u6c60",
    "\u592a\u9633\u80fd\u7535\u6c60",
    "\u7535\u6c60\u7c7b\u578b",
    "\u6253\u706b\u673a\u7c7b\u578b",
    "\u71c3\u6599\u7c7b\u578b",
    "\u6db2\u4f53\u5bb9\u91cf",
    "\u6db2\u4f53\u7c7b\u578b",
    "\u6db2\u4f53\u5f62\u5f0f",
)

RED_LINE_PARENT_FIELD_TOKENS = (
    "\u662f\u5426\u5e26\u7535\u6c60",
    "\u5305\u542b\u7535\u6c60",
    "\u662f\u5426\u542b\u7535\u6c60",
    "\u7535\u6e90\u65b9\u5f0f",
    "\u4f9b\u7535\u65b9\u5f0f",
    "\u662f\u5426\u5e26\u7535",
    "\u662f\u5426\u542b\u71c3\u6599",
    "\u662f\u5426\u542b\u6db2\u4f53",
)

RED_LINE_NEGATIVE_VALUE_TOKENS = (
    "\u5426",
    "\u65e0",
    "\u6ca1\u6709",
    "\u4e0d\u5e26",
    "\u4e0d\u542b",
    "\u65e0\u9700",
    "\u4e0d\u9700",
    "\u4e0d\u9002\u7528",
    "no",
    "none",
    "without",
    "notapplicable",
    "batteryfree",
)


def prepare_product_attribute_jobs(records: list[dict[str, Any]], *, user_id: str, process_now: bool = False) -> dict[str, Any]:
    summary = empty_product_attribute_queue_summary()
    summary.update({"queuedNow": 0, "reused": 0})
    return summary


def get_product_attribute_queue_summary(*, user_id: str, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return empty_product_attribute_queue_summary()


def get_product_attribute_queue_summary_for_records(
    conn: Any,
    *,
    user_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return empty_product_attribute_queue_summary()


def empty_product_attribute_queue_summary(**extra: Any) -> dict[str, Any]:
    counts = {status: 0 for status in QUEUE_STATUSES}
    counts["pending"] = 0
    counts["total"] = 0
    counts.update(extra)
    return counts


def get_product_attribute_for_export_record(
    record: dict[str, Any],
    *,
    user_id: str | None = None,
    strict: bool = False,
    title_context: dict[str, Any] | None = None,
) -> dict[str, str]:
    uid = user_id or "default-user"
    attribute_record = apply_product_attribute_title_context(record, title_context)

    try:
        result = generate_product_attribute_for_record(attribute_record, user_id=uid, require_api=strict)
    except Exception as exc:
        if strict:
            title = clean_text(attribute_record.get("productTitle")) or record_identity(attribute_record)
            raise ValueError(f"Product category/attributes unavailable for export: {title}: {exc}") from exc
        return {}

    export_payload = product_attribute_result_to_export_payload(result)
    if strict and not is_export_attribute_payload_complete(export_payload):
        title = clean_text(attribute_record.get("productTitle")) or record_identity(attribute_record)
        raise ValueError(f"Product category/attributes unavailable for export: {title}")
    return export_payload


def apply_product_attribute_title_context(
    record: dict[str, Any],
    title_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not title_context:
        return record
    title_cn = first_non_empty(
        title_context.get("title_cn"),
        title_context.get("productTitle"),
        title_context.get("title"),
    )
    title_en = first_non_empty(
        title_context.get("title_en"),
        title_context.get("productTitleEn"),
        title_context.get("titleEn"),
    )
    if not title_cn and not title_en:
        return record

    next_record = dict(record)
    original_title_cn = clean_text(record.get("productTitle"))
    original_title_en = clean_text(record.get("productTitleEn"))
    if title_cn:
        if original_title_cn and original_title_cn != title_cn:
            next_record["originalProductTitle"] = original_title_cn
        next_record["productTitle"] = title_cn
        next_record["attributeTitle"] = title_cn
    if title_en:
        if original_title_en and original_title_en != title_en:
            next_record["originalProductTitleEn"] = original_title_en
        next_record["productTitleEn"] = title_en
        next_record["attributeTitleEn"] = title_en
    return next_record


def is_export_attribute_payload_complete(payload: dict[str, Any]) -> bool:
    category_id = clean_text(payload.get("category_id"))
    attribute_text = clean_text(payload.get("product_attribute_text"))
    attribute_json = clean_text(payload.get("product_attributes_json"))
    has_attributes = attribute_text not in ("", "[]", "{}") or attribute_json not in ("", "[]", "{}")
    return bool(category_id and has_attributes)


def product_attribute_result_to_export_payload(result: dict[str, Any]) -> dict[str, str]:
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


def ai_result_has_attributes(ai_result: dict[str, Any]) -> bool:
    raw_items = ai_result.get("attributes") or ai_result.get("product_attributes") or []
    return isinstance(raw_items, list) and bool(raw_items)


def generate_product_attribute_for_record(
    record: dict[str, Any],
    *,
    user_id: str | None = None,
    require_api: bool = False,
) -> dict[str, Any]:
    if require_api and not is_product_attribute_ai_configured(user_id=user_id):
        raise ValueError("Product attribute API is not configured")

    with get_connection() as conn:
        category = resolve_category_for_record(conn, record, user_id=user_id, require_api=require_api)
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
            if require_api:
                raise ValueError(f"Product attribute API generation failed: {ai_error}") from exc

    if require_api and not ai_result_has_attributes(ai_result):
        raise ValueError("Product attribute API did not return product attributes")

    product_attributes = generate_complete_product_attributes(record, fields, ai_result)
    if not product_attributes and ai_error:
        raise ValueError(f"Product attribute AI generation failed: {ai_error}")
    return {
        "category_id": str(category["category_id"] or ""),
        "category_path": str(category["category_path_text"] or ""),
        "product_attributes": product_attributes,
        "product_attribute_text": dump_product_attributes(product_attributes),
    }


def resolve_category_for_record(
    conn: Any,
    record: dict[str, Any],
    *,
    user_id: str | None = None,
    require_api: bool = False,
) -> dict[str, Any] | None:
    product_context = load_product_context(conn, record)

    semantic_category = resolve_category_by_ai_vector(
        conn,
        record,
        product_context,
        user_id=user_id,
        require_api=require_api,
    )
    if semantic_category:
        return semantic_category
    return None


def resolve_category_by_known_path(conn: Any, record: dict[str, Any], product_context: dict[str, Any]) -> dict[str, Any] | None:
    category_path = record_category_path(record) or trusted_category_hint(product_context.get("category_path"))
    candidate_paths = [category_path]
    if category_path:
        candidate_paths.extend(split_search_terms(category_path))
    candidate_paths.extend([
        trusted_category_hint(product_context.get("category_level2")),
        trusted_category_hint(product_context.get("category_level1")),
    ])

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
    require_api: bool = False,
) -> dict[str, Any] | None:
    categories = load_category_snapshots_for_attribute_match(conn)
    leaves = [category for category in categories if clean_text(category.get("external_category_id")) and int(category.get("attr_count") or 0) > 0]
    if not leaves:
        return None

    if require_api:
        if not is_product_attribute_ai_configured(user_id=user_id):
            raise ValueError("Product attribute API is not configured")
        fallback_intent = build_category_intent(record, product_context, use_ai=False, user_id=user_id)
        ai_result = request_category_intent_ai(record, product_context, user_id=user_id)
        if not isinstance(ai_result, dict) or not ai_result:
            raise ValueError("Category intent API did not return usable category signals")
        intent = merge_category_intent(fallback_intent, ai_result)
        leaf = resolve_category_leaf_by_ai_tree(record, product_context, leaves, intent, user_id=user_id)
        if leaf:
            return load_snapshot_for_category_leaf(conn, leaf)
        raise ValueError("Category intent API did not match a category")

    if is_product_attribute_ai_configured(user_id=user_id):
        try:
            ai_intent = build_category_intent(record, product_context, use_ai=True, user_id=user_id)
            ai_leaf = resolve_category_leaf_by_ai_tree(record, product_context, leaves, ai_intent, user_id=user_id)
            if ai_leaf:
                return load_snapshot_for_category_leaf(conn, ai_leaf)
        except Exception:
            pass

    intent = build_category_intent(record, product_context, use_ai=False, user_id=user_id)
    leaf = resolve_category_leaf_by_vector(record, product_context, leaves, intent, allow_ai_final=False, user_id=user_id)
    if leaf:
        return load_snapshot_for_category_leaf(conn, leaf)
    return None


def merge_category_intent(fallback: dict[str, Any], ai_result: dict[str, Any]) -> dict[str, Any]:
    return {**fallback, **{key: value for key, value in ai_result.items() if value not in (None, "", [])}}


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

    if allow_ai_final:
        top_leaves = scored_leaves[:CATEGORY_FINAL_CANDIDATE_LIMIT]
        return choose_final_leaf_with_ai(
            record=record,
            intent=intent,
            leaves=top_leaves,
            user_id=user_id,
        ) or top_leaves[0]

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

    return current_leaves[0] if current_leaves else None


def resolve_category_leaf_by_ai_tree(
    record: dict[str, Any],
    product_context: dict[str, Any],
    leaves: list[dict[str, Any]],
    intent: dict[str, Any],
    *,
    user_id: str | None = None,
) -> dict[str, Any] | None:
    query_text = category_query_text(record, product_context, intent)
    query_vector = build_text_vector(query_text)
    scored_leaves = score_category_leaves(leaves, query_vector, query_text)
    scored_by_path = {
        clean_text(leaf.get("path_text")): leaf
        for leaf in scored_leaves
        if clean_text(leaf.get("path_text"))
    }

    selected_parts: list[str] = []
    current_leaves = leaves[:]
    for _depth in range(8):
        current_leaves = [
            leaf for leaf in leaves
            if category_path_startswith(leaf.get("path_parts") or [], selected_parts)
        ]
        if not current_leaves:
            return top_scored_leaf(scored_leaves)

        final_candidates = rank_leaves_for_ai(current_leaves, scored_by_path)[:CATEGORY_FINAL_CANDIDATE_LIMIT]
        if len(final_candidates) == 1:
            return final_candidates[0]
        if should_choose_final_leaf(selected_parts, final_candidates):
            chosen_leaf = choose_final_leaf_with_ai(
                record=record,
                intent=intent,
                leaves=final_candidates,
                user_id=user_id,
            )
            return chosen_leaf or final_candidates[0]

        branches = next_category_tree_branches(
            leaves=current_leaves,
            selected_parts=selected_parts,
            scored_by_path=scored_by_path,
            limit=CATEGORY_TREE_BRANCH_CANDIDATE_LIMIT,
        )
        if not branches:
            chosen_leaf = choose_final_leaf_with_ai(
                record=record,
                intent=intent,
                leaves=final_candidates,
                user_id=user_id,
            )
            return chosen_leaf or final_candidates[0]

        selected_branch = choose_category_branch_with_ai(
            record=record,
            intent=intent,
            current_path=selected_parts,
            branches=branches,
            user_id=user_id,
        )
        if not selected_branch:
            selected_branch = branches[0]
        next_parts = selected_branch.get("path_parts") or []
        if next_parts == selected_parts:
            return final_candidates[0]
        selected_parts = [clean_text(part) for part in next_parts if clean_text(part)]

    current_leaves = [
        leaf for leaf in leaves
        if category_path_startswith(leaf.get("path_parts") or [], selected_parts)
    ]
    ranked = rank_leaves_for_ai(current_leaves or leaves, scored_by_path)
    return ranked[0] if ranked else None


def should_choose_final_leaf(selected_parts: list[str], leaves: list[dict[str, Any]]) -> bool:
    if len(leaves) <= 1:
        return True
    if len(leaves) > CATEGORY_FINAL_CANDIDATE_LIMIT:
        return False
    next_level = len(selected_parts) + 1
    branch_keys = {
        normalize_category_path_for_match("/".join((leaf.get("path_parts") or [])[:next_level]))
        for leaf in leaves
        if len(leaf.get("path_parts") or []) >= next_level
    }
    return len(branch_keys) <= 1


def rank_leaves_for_ai(leaves: list[dict[str, Any]], scored_by_path: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for leaf in leaves:
        path = clean_text(leaf.get("path_text"))
        scored = scored_by_path.get(path)
        ranked.append(
            {
                **leaf,
                "score": float((scored or {}).get("score") or leaf.get("score") or 0),
                "matched_terms": (scored or {}).get("matched_terms", leaf.get("matched_terms", [])),
            }
        )
    ranked.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            int(item.get("required_count") or 0),
            int(item.get("attr_count") or 0),
            clean_text(item.get("path_text")),
        ),
        reverse=True,
    )
    return ranked


def top_scored_leaf(scored_leaves: list[dict[str, Any]]) -> dict[str, Any] | None:
    return scored_leaves[0] if scored_leaves else None


def load_category_snapshots_for_attribute_match(conn: Any) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """
            SELECT category_id, category_path_text, category_path_json, leaf_name,
                   category_depth, attr_count, required_count
            FROM dxm_temu_category_attr_snapshots
            WHERE category_id != '' AND attr_count > 0
            ORDER BY category_depth ASC, category_path_text ASC
            """
        ).fetchall()
    except Exception:
        return []

    categories: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        parts = parse_jsonish(item.get("category_path_json"), [])
        if not isinstance(parts, list):
            parts = category_path_parts(item.get("category_path_text"))
        parts = [clean_text(part) for part in parts if clean_text(part)]
        path_text = normalize_category_path_for_match(item.get("category_path_text"))
        vector = build_text_vector(path_text)
        categories.append(
            {
                "id": clean_text(item.get("category_id")),
                "external_category_id": clean_text(item.get("category_id")),
                "parent_id": "",
                "level": int_or_zero(item.get("category_depth")) or len(parts),
                "name": clean_text(item.get("leaf_name")) or (parts[-1] if parts else ""),
                "path_text": path_text,
                "path_parts": parts,
                "vector": {str(key): float(value) for key, value in vector.items() if str(key)},
                "path_terms": set(vector.keys()),
                "path_key": normalize_choice_text(path_text),
                "attr_count": int_or_zero(item.get("attr_count")),
                "required_count": int_or_zero(item.get("required_count")),
            }
        )
    return categories


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
        "category_hints": [],
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
        "task": (
            "First identify the real product from the final export title and reference images, then convert that identity "
            "into category matching signals for a Temu/Dianxiaomi category tree. Return concise category terms only, not marketing copy."
        ),
        "rules": [
            "Use the attached product images and final export title as primary evidence; source titles and SKU names are secondary hints.",
            "Decide what the physical product actually is before matching any category.",
            "Return concrete product nouns and category words, not quantities, marketing adjectives, shipping text, promotion text, or generic words.",
            "Treat source titles as unreliable when they conflict with the final export title or product images.",
            "Do not classify by container/storage/organizer words unless the image and title show the product is actually a storage container.",
            "Ignore logistics text, promotions, use-scene marketing, gift occasion words, shop metrics, ratings, and generic package words.",
            "If the product is a party favor bag, party gift bag, favor box, pinata, confetti popper, balloon, garland, or other party supply, keep party-supply category terms explicit.",
            "If title text conflicts with the image, trust the image for product identity and material/shape.",
        ],
        "output_schema": {
            "product_identity": "short concrete identity from title and image, e.g. kids party favor gift bag",
            "product_type": "short noun phrase",
            "visual_subject": "what the reference image actually shows",
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
            "reference_images": category_reference_images_for_prompt(record),
        },
    }
    assert_user_api_usage_allowed(user_id)
    try:
        result = request_category_json(
            api_url=build_api_url(settings["base_url"], "/chat/completions"),
            api_key=settings["api_key"],
            model=settings["model"],
            instruction=json.dumps(instruction, ensure_ascii=False),
            image_refs=category_reference_image_urls(record),
            temperature=0.05,
        )
        record_product_attribute_usage(settings, user_id=user_id, status="success")
        return result
    except Exception as exc:
        record_product_attribute_usage(settings, user_id=user_id, status="failed", error_message=str(exc))
        raise


def request_category_json(
    *,
    api_url: str,
    api_key: str,
    model: str,
    instruction: str,
    image_refs: list[str],
    temperature: float,
) -> dict[str, Any]:
    clean_images = unique_strings([url for url in image_refs if is_image_reference_url(url)])[:MAX_CATEGORY_REFERENCE_IMAGES]
    if not clean_images:
        return request_text_json(
            api_url=api_url,
            api_key=api_key,
            model=model,
            instruction=instruction,
            temperature=temperature,
        )

    payload = build_category_multimodal_payload(
        api_url=api_url,
        model=model,
        instruction=instruction,
        image_refs=clean_images,
        temperature=temperature,
    )
    try:
        response_json = request_json(api_url, api_key, payload)
        return parse_json_from_text(extract_response_text(response_json))
    except Exception:
        return request_text_json(
            api_url=api_url,
            api_key=api_key,
            model=model,
            instruction=instruction,
            temperature=temperature,
        )


def build_category_multimodal_payload(
    *,
    api_url: str,
    model: str,
    instruction: str,
    image_refs: list[str],
    temperature: float,
) -> dict[str, Any]:
    if api_url.rstrip("/").endswith("/chat/completions"):
        content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
        content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_refs)
        return {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": temperature,
        }

    content = [{"type": "input_text", "text": instruction}]
    content.extend({"type": "input_image", "image_url": url} for url in image_refs)
    return {
        "model": model,
        "input": [{"role": "user", "content": content}],
        "temperature": temperature,
    }


def category_reference_images_for_prompt(record: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"role": role, "url": url}
        for role, url in iter_category_reference_images(record)
    ][:MAX_CATEGORY_REFERENCE_IMAGES]


def category_reference_image_urls(record: dict[str, Any]) -> list[str]:
    return [url for _role, url in iter_category_reference_images(record)][:MAX_CATEGORY_REFERENCE_IMAGES]


def iter_category_reference_images(record: dict[str, Any]) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(role: str, value: Any) -> None:
        url = clean_text(value)
        if not is_image_reference_url(url) or url in seen:
            return
        references.append((role, url))
        seen.add(url)

    add("main_image", pick_image_asset_url(record.get("mainImage")))
    for key in ("productImageUrl", "mainImageUrl", "main_image_url", "imageUrl", "image_url", "thumbnailUrl"):
        add("main_image", record.get(key))

    for url in parse_image_url_list(record.get("galleryImageUrls") or record.get("gallery_image_urls")):
        add("gallery_image", url)

    for asset in record.get("productMaterialImages") or []:
        if isinstance(asset, dict):
            add("material_image", pick_image_asset_url(asset))
        else:
            add("material_image", asset)

    for source in record.get("sourceLinks") or []:
        if not isinstance(source, dict):
            continue
        for key in ("imageUrl", "image_url", "mainImageUrl", "main_image_url", "sourceImageUrl", "source_image_url"):
            add("source_image", source.get(key))

    for sku_entry in record.get("skuEntries") or []:
        if not isinstance(sku_entry, dict):
            continue
        add("sku_image", pick_image_asset_url(sku_entry.get("imageAsset")))
        for key in ("imageUrl", "image_url", "sourceImageUrl", "source_image_url"):
            add("sku_image", sku_entry.get(key))
        for source_sku in sku_entry.get("sourceSkuLinks") or []:
            if isinstance(source_sku, dict):
                add("sku_source_image", source_sku.get("imageUrl") or source_sku.get("sourceImageUrl"))
        for component in sku_entry.get("componentSkus") or []:
            if isinstance(component, dict):
                add("combo_component_image", component.get("imageUrl") or component.get("sourceImageUrl"))

    return references[:MAX_CATEGORY_REFERENCE_IMAGES]


def pick_image_asset_url(asset: Any) -> str:
    if isinstance(asset, str):
        return asset
    if not isinstance(asset, dict):
        return ""
    return first_non_empty(
        asset.get("editedCloudUrl"),
        asset.get("editedUrl"),
        asset.get("displayCloudUrl"),
        asset.get("displayUrl"),
        asset.get("sourceCloudUrl"),
        asset.get("sourceUrl"),
        asset.get("url"),
        asset.get("imageUrl"),
    )


def parse_image_url_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item.get("url") if isinstance(item, dict) else item) for item in value]
    parsed = parse_jsonish(value, None)
    if isinstance(parsed, list):
        return [clean_text(item.get("url") if isinstance(item, dict) else item) for item in parsed]
    text = clean_text(value)
    if not text:
        return []
    return [part for part in re.split(r"[\n,;\s]+", text) if clean_text(part)]


def is_image_reference_url(value: Any) -> bool:
    text = clean_text(value).lower()
    return text.startswith(("http://", "https://", "data:image/"))


def category_query_text(record: dict[str, Any], product_context: dict[str, Any], intent: dict[str, Any]) -> str:
    parts = [
        clean_text(record.get("productTitle")),
        clean_text(record.get("productTitleEn")),
        clean_text(intent.get("product_identity")),
        clean_text(intent.get("product_type")),
        clean_text(intent.get("visual_subject")),
        clean_text(intent.get("product_function")),
    ]
    for key in ("core_keywords", "materials", "use_scenes", "audience", "category_hints"):
        value = intent.get(key)
        if isinstance(value, list):
            parts.extend(clean_text(item) for item in value)
        else:
            parts.append(clean_text(value))
    parts.extend(sku_names_for_prompt(record)[:20])
    has_identity = any(
        clean_text(intent.get(key))
        for key in ("product_identity", "product_type", "visual_subject")
    ) or bool(intent.get("core_keywords"))
    if not has_identity:
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


def next_category_tree_branches(
    *,
    leaves: list[dict[str, Any]],
    selected_parts: list[str],
    scored_by_path: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    next_level = len(selected_parts) + 1
    groups: dict[str, dict[str, Any]] = {}
    for leaf in leaves:
        parts = leaf.get("path_parts") or []
        if len(parts) < next_level or not category_path_startswith(parts, selected_parts):
            continue
        branch_parts = [clean_text(part) for part in parts[:next_level] if clean_text(part)]
        if not branch_parts:
            continue
        key = normalize_category_path_for_match("/".join(branch_parts))
        scored_leaf = scored_by_path.get(clean_text(leaf.get("path_text"))) or {}
        leaf_score = float(scored_leaf.get("score") or 0)
        group = groups.setdefault(
            key,
            {
                "name": branch_parts[-1],
                "path_parts": branch_parts,
                "path_text": key,
                "score": 0.0,
                "leaf_count": 0,
                "examples": [],
                "matched_terms": set(),
            },
        )
        group["leaf_count"] += 1
        group["score"] = max(float(group["score"]), leaf_score)
        if len(group["examples"]) < 3:
            group["examples"].append(clean_text(leaf.get("path_text")))
        for term in scored_leaf.get("matched_terms") or []:
            group["matched_terms"].add(clean_text(term))

    branches = list(groups.values())
    for branch in branches:
        branch["matched_terms"] = sorted(term for term in branch["matched_terms"] if term)[:10]
    branches.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            int(item.get("leaf_count") or 0),
            clean_text(item.get("path_text")),
        ),
        reverse=True,
    )
    if len(branches) <= limit:
        return branches
    positive = [branch for branch in branches if float(branch.get("score") or 0) > 0]
    zero = [branch for branch in branches if float(branch.get("score") or 0) <= 0]
    return [*positive[:limit], *zero[: max(0, limit - len(positive[:limit]))]][:limit]


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
        task="Choose the final leaf category that best fits the product from the local vector Top 20 candidates.",
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
            "local_vector_score": candidate.get("score"),
            "local_matched_terms": candidate.get("matched_terms", []),
            "leaf_count": candidate.get("leaf_count", 1),
            "examples": candidate.get("examples", []),
        }
        for index, candidate in enumerate(candidates, start=1)
    ]
    instruction = {
        "task": task,
        "rules": [
            "Select exactly one candidate index from the provided list.",
            "First identify the real product from final title and reference images, then choose the closest category path.",
            "Treat local_vector_score as a recall hint only. Do not select a category solely because it has the highest local score.",
            "Prefer the real product type over use scenario, decorative words, packaging words, or generic container/storage words.",
            "Do not choose storage/organizer/container categories unless the image and title show the product is actually a storage container.",
            "If the product identity is party favor bag, party gift bag, favor box, pinata, confetti popper, balloon, garland, or party supply, prefer party-supply branches over home storage branches.",
            "If source titles conflict with the final product title or images, ignore the conflicting source titles for category selection.",
            "Do not invent categories outside the candidate list.",
            "When the best local_vector_score conflicts with the real product identity, choose the candidate that matches the real product identity and explain briefly.",
        ],
        "output_schema": {"selected_index": 1, "confidence": 0.0, "reason": "short reason"},
        "product": {
            "title_cn": clean_text(record.get("productTitle")),
            "title_en": clean_text(record.get("productTitleEn")),
            "sku_names": sku_names_for_prompt(record)[:20],
            "intent": intent,
            "reference_images": category_reference_images_for_prompt(record),
        },
        "current_category_path": current_path,
        "candidates": payload_candidates,
    }
    assert_user_api_usage_allowed(user_id)
    try:
        result = request_category_json(
            api_url=build_api_url(settings["base_url"], "/chat/completions"),
            api_key=settings["api_key"],
            model=settings["model"],
            instruction=json.dumps(instruction, ensure_ascii=False),
            image_refs=category_reference_image_urls(record),
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


def trusted_category_hint(value: Any) -> str:
    text = clean_text(value)
    if not text or is_noisy_source_category_path(text):
        return ""
    return text


def is_noisy_source_category_path(value: Any) -> bool:
    text = clean_text(value)
    if not text:
        return False
    lowered = text.lower().replace("\\", "/")
    if "company_info" in lowered or lowered.endswith("/categories") or "/categories/" in lowered:
        return True
    parts = category_path_parts(text)
    if any("..." in part for part in parts):
        return True
    normalized_parts = {normalize_choice_text(part) for part in parts}
    return bool(normalized_parts & NOISY_CATEGORY_PATH_SEGMENTS)


def sanitize_product_context_category_hints(context: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(context)
    for key in ("category_path", "category_level1", "category_level2"):
        sanitized[key] = trusted_category_hint(sanitized.get(key))
    return sanitized


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
                    return sanitize_product_context_category_hints(dict(row))
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
                    return sanitize_product_context_category_hints(dict(row))
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
                    return sanitize_product_context_category_hints(dict(row))
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
        "task": "Use the product title, SKU names, category path, and candidate attribute fields to fill visible product attribute fields. For select fields, use exactly one provided option label and return its vid. For checkbox-group fields, choose provided options only when clearly applicable. If a safe parent yes/no field is present for batteries, electricity, fuel, or liquid, prefer no/none/not applicable unless the product is explicitly such an item. Do not invent certifications, brands, medical claims, safety claims, waterproof claims, or unverifiable sensitive attributes.",
        "red_line_rules": [
            "Do not output child attributes for electricity or plug products unless the product is explicitly electric: working voltage, plug specification, plug type, power voltage.",
            "Do not output child attributes for batteries unless the product explicitly includes a battery: rechargeable battery, solar battery, battery type, lithium battery.",
            "Do not output child attributes for fuel, lighter, or liquid unless the product itself is explicitly fuel/liquid. If the product merely says liquid food, wet food, or liquid feeding bowl, it is not a liquid product.",
            "When a parent field says no battery, no power, no fuel, no liquid, not applicable, or without, do not output the related child fields.",
            "For red-line parent fields, use objective negative options such as no, none, without, not applicable when the title/SKU/images do not prove the red-line property.",
        ],
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
            "final_export_title_cn": clean_text(record.get("attributeTitle") or record.get("productTitle")),
            "final_export_title_en": clean_text(record.get("attributeTitleEn") or record.get("productTitleEn")),
            "source_original_title_cn": clean_text(record.get("originalProductTitle")),
            "source_original_title_en": clean_text(record.get("originalProductTitleEn")),
            "sku_names": sku_names_for_prompt(record),
            "source_titles": [clean_text(source.get("title")) for source in record.get("sourceLinks") or [] if isinstance(source, dict)],
            "reference_images": category_reference_images_for_prompt(record),
        },
        "category": {
            "category_id": category.get("category_id"),
            "category_path": category.get("category_path_text"),
        },
        "fields": compact_fields,
    }
    assert_user_api_usage_allowed(user_id)
    try:
        result = request_category_json(
            api_url=api_url,
            api_key=settings["api_key"],
            model=settings["model"],
            instruction=json.dumps(instruction, ensure_ascii=False),
            image_refs=category_reference_image_urls(record),
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
        if should_skip_red_line_field(field, selected):
            continue
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
        if should_skip_red_line_field(field, selected):
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
        if should_skip_red_line_field(field, selected):
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


def should_skip_red_line_field(field: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    if not is_red_line_child_field(field):
        return False
    if selected_has_negative_red_line_parent(selected):
        return True
    return True


def is_red_line_child_field(field: dict[str, Any]) -> bool:
    label_key = normalize_choice_text(field.get("field_label"))
    if not label_key:
        return False
    if any(normalize_choice_text(token) in label_key for token in RED_LINE_CHILD_FIELD_TOKENS):
        return True
    if "\u7535\u6c60" in label_key and not is_red_line_parent_field(field):
        return True
    if "\u71c3\u6599" in label_key and not is_red_line_parent_field(field):
        return True
    if "\u6db2\u4f53" in label_key and not is_red_line_parent_field(field):
        return True
    return False


def is_red_line_parent_field(field_or_item: dict[str, Any]) -> bool:
    label = field_or_item.get("field_label") or field_or_item.get("propName") or field_or_item.get("name")
    label_key = normalize_choice_text(label)
    return any(normalize_choice_text(token) in label_key for token in RED_LINE_PARENT_FIELD_TOKENS)


def selected_has_negative_red_line_parent(selected: list[dict[str, Any]]) -> bool:
    for item in selected:
        if not is_red_line_parent_field(item):
            continue
        value_key = normalize_choice_text(item.get("propValue") or item.get("prop_value") or item.get("value"))
        if any(normalize_choice_text(token) in value_key for token in RED_LINE_NEGATIVE_VALUE_TOKENS):
            return True
    return False


def red_line_negative_option_candidates() -> list[str]:
    return [
        "\u5426",
        "\u65e0",
        "\u65e0\u7535\u6c60",
        "\u4e0d\u5e26\u7535",
        "\u4e0d\u542b",
        "\u65e0\u9700\u63a5\u7535\u4f7f\u7528",
        "\u4e0d\u9002\u7528",
        "No",
        "None",
        "Without",
        "Not Applicable",
    ]


def generate_default_attribute_for_field(
    field: dict[str, Any],
    selected: list[dict[str, Any]],
    product_text: str,
) -> list[dict[str, Any]]:
    if should_skip_red_line_field(field, selected):
        return []
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
    if is_red_line_parent_field(field):
        candidate_groups.append(red_line_negative_option_candidates())
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
    if is_red_line_parent_field(field):
        candidate_groups.append(red_line_negative_option_candidates())
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
    category_level1 = first_non_empty(
        trusted_category_hint(record.get("categoryLevel1")),
        trusted_category_hint(record.get("category_level1")),
    )
    category_level2 = first_non_empty(
        trusted_category_hint(record.get("categoryLevel2")),
        trusted_category_hint(record.get("category_level2")),
    )
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
    return first_non_empty(
        trusted_category_hint(record.get("dxmCategoryPath")),
        trusted_category_hint(record.get("dianxiaomiCategoryPath")),
        trusted_category_hint(record.get("categoryPath")),
        trusted_category_hint(record.get("category_path")),
        trusted_category_hint(record.get("category")),
    )


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
