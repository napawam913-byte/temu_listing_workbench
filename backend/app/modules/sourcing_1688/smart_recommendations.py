from __future__ import annotations

import json
import hashlib
import re
from typing import Any
from urllib.parse import quote

from app.core.database import get_connection
from app.modules.creative_generation.chatgpt_listing import build_openai_client, get_openai_settings
from app.modules.creative_generation.safety import sanitize_marketplace_text
from app.modules.recommendation.keyword_index import ensure_recommendation_schema
from app.modules.sourcing_1688.search_url import build_1688_search_url


DEFAULT_LIMIT = 6
IMAGE_SEARCH_1688_URL = "https://s.1688.com/youyuan/index.htm"
CACHE_SCHEMA_VERSION = "1688-smart-analysis-v2"
DOMAIN_MATCH_TERMS = [
    "钥匙扣",
    "钥匙链",
    "挂件",
    "挂饰",
    "吊坠",
    "流苏",
    "字母",
    "汽车钥匙",
    "包包",
    "收纳盒",
    "药盒",
    "药片盒",
    "分药盒",
    "包装盒",
    "礼品袋",
    "耳环",
    "项链",
    "手链",
    "发饰",
    "发圈",
    "吊牌",
]
SPECIFIC_MATCH_TERMS = [
    "情侣",
    "一对",
    "双人",
    "男女",
    "爱心",
    "心形",
    "首字母",
    "字母",
    "流苏",
    "滴胶",
    "树脂",
    "亚克力",
    "金属",
    "合金",
    "皮革",
    "硅胶",
    "陶瓷",
    "可爱",
    "卡通",
    "儿童",
    "少女",
    "男士",
    "女士",
    "钥匙包",
    "钥匙盒",
    "收纳",
    "分格",
    "圆形",
    "方形",
    "长方形",
    "透明",
    "兔",
    "猫",
    "狗",
    "车钥匙",
]
GENERIC_RECOMMENDATION_TERMS = {
    "钥匙扣",
    "钥匙链",
    "钥匙圈",
    "挂件",
    "挂饰",
    "吊坠",
    "汽车",
    "包包",
    "配饰",
    "饰品",
    "礼物",
    "批发",
    "不同款",
}
SYNONYM_TERM_GROUPS = [
    {"钥匙扣", "钥匙链", "钥匙圈", "钥匙环", "钥匙挂件"},
    {"情侣", "一对", "双人", "男女"},
    {"爱心", "心形"},
    {"字母", "首字母"},
    {"滴胶", "树脂"},
    {"汽车钥匙", "车钥匙", "汽车"},
    {"包包", "包饰", "挂包"},
    {"药盒", "药片盒", "分药盒"},
]
STOP_TERMS = {
    "1688",
    "temu",
    "商品",
    "采集",
    "采集素材",
    "素材",
    "跨境",
    "热销",
    "批发",
    "配饰",
    "饰品",
    "礼物",
}


def generate_smart_1688_keywords(product: dict[str, Any]) -> dict[str, Any]:
    analysis = analyze_product_for_1688(product)
    return {**analysis, "keywords": attach_search_urls(analysis["keywords"])}


def generate_smart_1688_recommendations(
    product: dict[str, Any],
    *,
    keywords: list[dict[str, Any] | str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    safe_limit = max(1, min(12, limit))
    selected_keywords = normalize_selected_keywords(keywords)
    if selected_keywords:
        title = clean_text(product.get("title") or product.get("titleEn"))
        analysis = {
            "summary": f"当前商品：{title or '待推荐商品'}",
            "strategy": "根据已筛选关键词，从本地商品列表中匹配可参考的相邻商品。",
            "keywords": selected_keywords,
        }
    else:
        analysis = analyze_product_for_1688(product)

    local_candidates = list_local_product_sources(product, analysis["keywords"])
    scored_candidates = score_local_candidates(local_candidates, product, analysis["keywords"])

    items: list[dict[str, Any]] = []
    for candidate in scored_candidates[:safe_limit]:
        items.append(
            {
                "id": candidate["id"],
                "type": "offer",
                "title": candidate["title"],
                "main_image_url": candidate.get("main_image_url") or product.get("mainImageUrl"),
                "product_url": candidate["product_url"],
                "image_search_url": build_1688_image_search_url(
                    candidate.get("main_image_url") or product.get("mainImageUrl")
                ),
                "keyword": candidate.get("matched_keyword") or analysis["keywords"][0]["keyword"],
                "reason": candidate.get("reason") or "本地商品列表中与当前商品用途接近，可作为差异化参考。",
                "shop_name": candidate.get("shop_name") or candidate.get("category_path"),
                "price": candidate.get("price"),
                "source": candidate["source"],
                "score": candidate["score"],
            }
        )

    return {
        "summary": analysis["summary"],
        "strategy": "已切换为本地商品列表推荐：不再打开 1688 搜索，优先回显已有商品数据供你选择。",
        "keywords": attach_search_urls(analysis["keywords"]),
        "items": items,
    }


def attach_search_urls(keywords: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            **keyword,
            "searchUrl": build_1688_search_url(keyword["keyword"]),
        }
        for keyword in keywords
    ]


def normalize_selected_keywords(keywords: list[dict[str, Any] | str] | None) -> list[dict[str, str]]:
    if not keywords:
        return []

    normalized_items: list[dict[str, str]] = []
    for item in keywords:
        if isinstance(item, str):
            keyword = clean_text(item)
            intent = "人工筛选关键词"
            reason = "由用户筛选后用于 1688 推荐。"
        elif isinstance(item, dict):
            keyword = clean_text(item.get("keyword"))
            intent = clean_text(item.get("intent")) or "人工筛选关键词"
            reason = clean_text(item.get("reason")) or "由用户筛选后用于 1688 推荐。"
        else:
            continue
        if not keyword:
            continue
        safe_keyword, _ = sanitize_marketplace_text(keyword)
        if not safe_keyword:
            continue
        normalized_items.append(
            {
                "keyword": safe_keyword[:48],
                "intent": intent[:80],
                "reason": reason[:120],
            }
        )

    return unique_keyword_items(normalized_items)[:8]


def analyze_product_for_1688(product: dict[str, Any]) -> dict[str, Any]:
    settings = get_openai_settings()
    title = clean_text(product.get("title") or product.get("titleEn"))
    category = clean_text(product.get("category") or product.get("categoryPath"))
    main_image_url = clean_text(product.get("mainImageUrl") or product.get("main_image_url"))
    cache_key = build_analysis_cache_key(product, title=title, category=category, main_image_url=main_image_url)
    title_hash = build_analysis_title_hash(title=title, category=category, main_image_url=main_image_url)

    cached_analysis = load_cached_analysis(cache_key, title_hash)
    if cached_analysis:
        return {**cached_analysis, "cache": {"hit": True, "key": cache_key}}

    if settings.api_key:
        try:
            analysis = analyze_with_chatgpt(title=title, category=category, main_image_url=main_image_url, settings=settings)
            save_cached_analysis(cache_key, title_hash, analysis, model=settings.text_model)
            return {**analysis, "cache": {"hit": False, "key": cache_key}}
        except Exception:
            pass

    analysis = build_fallback_analysis(title, category)
    save_cached_analysis(cache_key, title_hash, analysis, model="rule-fallback")
    return {**analysis, "cache": {"hit": False, "key": cache_key}}


def build_analysis_cache_key(product: dict[str, Any], *, title: str, category: str, main_image_url: str) -> str:
    source_type = clean_text(product.get("sourceType") or product.get("source_type"))
    source_product_id = clean_text(product.get("sourceProductId") or product.get("source_product_id"))
    product_id = clean_text(product.get("id"))
    if source_type and source_product_id:
        return f"{source_type}:{source_product_id}"
    if product_id:
        return product_id
    digest = hashlib.sha256(
        json.dumps([title, category, main_image_url], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"adhoc:{digest[:24]}"


def build_analysis_title_hash(*, title: str, category: str, main_image_url: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "schema": CACHE_SCHEMA_VERSION,
                "title": title,
                "category": category,
                "main_image_url": main_image_url,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def load_cached_analysis(cache_key: str, title_hash: str) -> dict[str, Any] | None:
    if not cache_key:
        return None
    with get_connection() as conn:
        ensure_recommendation_schema(conn)
        row = conn.execute(
            """
            SELECT analysis_json
            FROM product_ai_analysis_cache
            WHERE product_id = ? AND title_hash = ?
            """,
            (cache_key, title_hash),
        ).fetchone()
    if not row:
        return None
    try:
        analysis = json.loads(row["analysis_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(analysis, dict) or not isinstance(analysis.get("keywords"), list):
        return None
    return analysis


def save_cached_analysis(cache_key: str, title_hash: str, analysis: dict[str, Any], *, model: str) -> None:
    if not cache_key:
        return
    safe_analysis = {
        "summary": clean_text(analysis.get("summary")),
        "strategy": clean_text(analysis.get("strategy")),
        "keywords": analysis.get("keywords") if isinstance(analysis.get("keywords"), list) else [],
    }
    with get_connection() as conn:
        ensure_recommendation_schema(conn)
        now = conn.execute("SELECT datetime('now') AS now").fetchone()["now"]
        conn.execute(
            """
            INSERT INTO product_ai_analysis_cache (
                product_id, title_hash, analysis_json, model, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                title_hash = excluded.title_hash,
                analysis_json = excluded.analysis_json,
                model = excluded.model,
                updated_at = excluded.updated_at
            """,
            (cache_key, title_hash, json.dumps(safe_analysis, ensure_ascii=False), model, now, now),
        )


def analyze_with_chatgpt(*, title: str, category: str, main_image_url: str, settings: Any) -> dict[str, Any]:
    client = build_openai_client(settings)
    user_payload = {
        "product_title": title,
        "category": category,
        "task": (
            "Analyze the product title and image. Recommend related 1688 sourcing directions that keep the same core use "
            "but explore different shapes, materials, structures, scenes, or user groups. Do not recommend unrelated products."
        ),
        "required_json": {
            "summary": "short Chinese summary of product core use and visual traits",
            "strategy": "short Chinese strategy for adjacent 1688 sourcing",
            "keywords": [
                {
                    "keyword": "Chinese 1688 search keyword, 4-16 chars where possible",
                    "intent": "same use but different shape/material/scene",
                    "reason": "why this direction is relevant",
                }
            ],
        },
    }
    content: list[dict[str, str]] = [
        {"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}
    ]
    if main_image_url.startswith("http"):
        content.append({"type": "input_image", "image_url": main_image_url})

    response = client.responses.create(
        model=settings.text_model,
        input=[
            {
                "role": "system",
                "content": (
                    "You are a careful 1688 sourcing analyst for Temu listing operations. "
                    "Return strict JSON only. Keep recommendations practical, adjacent, and product-specific. "
                    "Avoid brand names, medical claims, certification claims, and unsafe marketplace wording."
                ),
            },
            {"role": "user", "content": content},
        ],
    )
    return normalize_analysis(json.loads(response.output_text), title, category)


def build_fallback_analysis(title: str, category: str) -> dict[str, Any]:
    base_terms = extract_terms(f"{title} {category}")
    core = " ".join(base_terms[:4]) or title[:18] or "1688 货源"
    special_keywords: list[str] = []
    if any(term in title for term in ("药盒", "药片", "药丸", "医疗", "分药")):
        special_keywords = ["便携分格药盒", "圆形药片收纳盒", "一周分药盒", "随身密封药盒"]
    elif any(term in title for term in ("盒", "收纳", "包装")):
        special_keywords = ["异形收纳盒", "分格收纳盒", "便携包装盒", "透明收纳盒"]
    elif any(term in title for term in ("钥匙扣", "挂件")):
        special_keywords = ["创意钥匙扣挂件", "汽车钥匙扣挂件", "包包装饰挂件", "字母钥匙扣"]

    keyword_values = unique_strings(
        [
            *special_keywords,
            f"{core} 不同款",
            f"{core} 批发",
            f"{core} 1688",
        ]
    )[:6]
    keywords = [
        {
            "keyword": keyword,
            "intent": "同用途差异化找货",
            "reason": "围绕当前商品的核心用途，寻找不同形状、结构或场景的 1688 货源。",
        }
        for keyword in keyword_values
    ]
    return normalize_analysis(
        {
            "summary": f"当前商品核心方向：{title or core}",
            "strategy": "优先找同用途但外观、结构或使用场景不同的 1688 货源。",
            "keywords": keywords,
        },
        title,
        category,
    )


def normalize_analysis(raw: dict[str, Any], title: str, category: str) -> dict[str, Any]:
    summary, _ = sanitize_marketplace_text(clean_text(raw.get("summary")) or f"当前商品：{title or category}")
    strategy, _ = sanitize_marketplace_text(clean_text(raw.get("strategy")) or "推荐同用途但不同形态的 1688 货源。")
    raw_keywords = raw.get("keywords") if isinstance(raw.get("keywords"), list) else []
    keywords: list[dict[str, str]] = []
    for item in raw_keywords:
        if not isinstance(item, dict):
            continue
        keyword, _ = sanitize_marketplace_text(clean_text(item.get("keyword")))
        if not keyword:
            continue
        keywords.append(
            {
                "keyword": keyword[:48],
                "intent": clean_text(item.get("intent"))[:80] or "相关货源",
                "reason": clean_text(item.get("reason"))[:120] or "与当前商品用途相关。",
            }
        )

    if not keywords:
        return build_fallback_analysis_without_recursion(title, category)

    return {
        "summary": summary,
        "strategy": strategy,
        "keywords": unique_keyword_items(keywords)[:8],
    }


def build_fallback_analysis_without_recursion(title: str, category: str) -> dict[str, Any]:
    core = " ".join(extract_terms(f"{title} {category}")[:4]) or "相关货源"
    return {
        "summary": f"当前商品核心方向：{title or core}",
        "strategy": "推荐同用途但不同形态的 1688 货源。",
        "keywords": [
            {
                "keyword": f"{core} 批发"[:48],
                "intent": "相关货源",
                "reason": "与当前商品标题和类目相关。",
            }
        ],
    }


def list_local_product_sources(product: dict[str, Any], keywords: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    excluded_ids = {
        clean_text(product.get("id")),
        clean_text(product.get("sourceProductId")),
        clean_text(product.get("source_product_id")),
    }
    query_terms = build_local_candidate_query_terms(product, keywords or [])

    items: list[dict[str, Any]] = []
    with get_connection() as conn:
        rows: list[Any] = []
        if query_terms:
            exact_terms = query_terms[:32]
            like_terms = [f"%{term}%" for term in query_terms[:24]]
            exact_clause = " OR ".join(["pk.keyword = ?" for _ in exact_terms])
            like_clause = " OR ".join(["pk.keyword LIKE ?" for _ in like_terms])
            keyword_clause = " OR ".join(clause for clause in (exact_clause, like_clause) if clause)
            rows = conn.execute(
                f"""
                SELECT
                    p.id, p.source_type, p.source_product_id, p.title, p.main_image_url, p.source_url,
                    p.category_path, p.category_level1, p.category_level2, p.price_usd,
                    p.weekly_sales, p.gmv_usd, p.review_count, p.listing_time,
                    SUM(pk.weight) AS keyword_score,
                    GROUP_CONCAT(DISTINCT pk.keyword) AS matched_keywords
                FROM product_keywords pk
                JOIN products p ON p.id = pk.product_id
                WHERE p.status != 'deleted'
                    AND ({keyword_clause})
                GROUP BY p.id
                ORDER BY
                    keyword_score DESC,
                    CASE WHEN p.source_type = '1688' THEN 0 ELSE 1 END,
                    p.weekly_sales DESC,
                    p.gmv_usd DESC,
                    datetime(p.listing_time) DESC,
                    datetime(p.updated_at) DESC
                LIMIT 600
                """,
                [*exact_terms, *like_terms],
            ).fetchall()

        if not rows:
            rows = conn.execute(
                """
                SELECT
                    id, source_type, source_product_id, title, main_image_url, source_url,
                    category_path, category_level1, category_level2, price_usd,
                    weekly_sales, gmv_usd, review_count, listing_time,
                    0 AS keyword_score,
                    '' AS matched_keywords
                FROM products
                WHERE status != 'deleted'
                ORDER BY
                    CASE WHEN source_type = '1688' THEN 0 ELSE 1 END,
                    weekly_sales DESC,
                    gmv_usd DESC,
                    datetime(listing_time) DESC,
                    datetime(updated_at) DESC
                LIMIT 800
                """
            ).fetchall()

    for row in rows:
        if row["id"] in excluded_ids or row["source_product_id"] in excluded_ids:
            continue
        source_type = clean_text(row["source_type"]) or "yunqi"
        source_product_id = clean_text(row["source_product_id"]) or row["id"]
        items.append(
            {
                "id": f"product-{row['id']}",
                "source": "product",
                "product_url": build_product_detail_url(source_type, source_product_id),
                "external_url": row["source_url"],
                "source_type": source_type,
                "source_product_id": source_product_id,
                "title": row["title"],
                "main_image_url": row["main_image_url"],
                "shop_name": row["category_path"],
                "category_path": row["category_path"],
                "category_level1": row["category_level1"],
                "category_level2": row["category_level2"],
                "price": row["price_usd"],
                "weekly_sales": row["weekly_sales"],
                "gmv_usd": row["gmv_usd"],
                "review_count": row["review_count"],
                "keyword_score": row["keyword_score"],
                "matched_keywords": row["matched_keywords"] or "",
            }
        )

    return dedupe_sources(items)


def build_product_detail_url(source_type: str, source_product_id: str) -> str:
    return f"/#/products/{quote(source_type, safe='')}/{quote(source_product_id, safe='')}"


def build_1688_image_search_url(image_url: Any) -> str:
    return f"{IMAGE_SEARCH_1688_URL}?tab=imageSearch"


def build_local_candidate_query_terms(product: dict[str, Any], keywords: list[dict[str, str]]) -> list[str]:
    product_category = clean_text(
        f"{product.get('categoryPath') or product.get('category') or ''} "
        f"{product.get('categoryLevel1') or ''} {product.get('categoryLevel2') or ''}"
    )
    product_terms = expand_match_terms(f"{product.get('title', '')} {product.get('titleEn', '')} {product_category}")
    keyword_terms = [term for keyword in keywords for term in expand_match_terms(keyword.get("keyword", ""))]
    specific_terms = build_specific_relevance_terms(product, keywords)
    return unique_strings([*specific_terms, *keyword_terms, *product_terms])[:48]


def score_local_candidates(
    candidates: list[dict[str, Any]],
    product: dict[str, Any],
    keywords: list[dict[str, str]],
) -> list[dict[str, Any]]:
    product_category = clean_text(
        f"{product.get('categoryPath') or product.get('category') or ''} "
        f"{product.get('categoryLevel1') or ''} {product.get('categoryLevel2') or ''}"
    )
    product_terms = expand_match_terms(f"{product.get('title', '')} {product.get('titleEn', '')} {product_category}")
    keyword_terms = [term for keyword in keywords for term in expand_match_terms(keyword["keyword"])]
    selected_specific_terms = build_specific_relevance_terms({}, keywords)
    product_specific_terms = build_specific_relevance_terms(product, [])
    query_terms = unique_strings([*product_terms, *keyword_terms])
    required_terms = unique_strings([*selected_specific_terms, *product_specific_terms])

    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        title = clean_text(candidate.get("title"))
        if not title:
            continue
        category_text = clean_text(candidate.get("category_path"))
        searchable_text = clean_text(f"{title} {category_text}")
        title_terms = expand_match_terms(searchable_text)
        score = float(candidate.get("keyword_score") or 0)
        matched_keyword = ""
        matched_selected_terms: list[str] = []
        matched_specific_terms: list[str] = []
        matched_keywords = [
            clean_text(keyword)
            for keyword in str(candidate.get("matched_keywords") or "").split(",")
            if clean_text(keyword)
        ]
        if matched_keywords:
            matched_keyword = matched_keywords[0]
        for term in selected_specific_terms:
            if term_matches_text(term, searchable_text, title_terms):
                matched_selected_terms.append(term)
                score += 12
                if not matched_keyword:
                    matched_keyword = term

        for term in required_terms:
            if term_matches_text(term, searchable_text, title_terms):
                matched_specific_terms.append(term)
                score += 5
                if not matched_keyword:
                    matched_keyword = term

        for term in keyword_terms:
            if term and term_matches_text(term, searchable_text, title_terms):
                score += 2 if is_generic_recommendation_term(term) else 4
                if not matched_keyword:
                    matched_keyword = term

        for term in product_terms:
            if term and term_matches_text(term, searchable_text, title_terms):
                score += 0.5 if is_generic_recommendation_term(term) else 1
                if not matched_keyword:
                    matched_keyword = term
        if product_category and category_text and (product_category in category_text or category_text in product_category):
            score += 3
            if not matched_keyword:
                matched_keyword = keywords[0]["keyword"] if "采集素材" in category_text else category_text

        if selected_specific_terms and not matched_selected_terms:
            continue
        if required_terms and not matched_specific_terms:
            continue

        min_score = 10 if selected_specific_terms else 6
        if score < min_score:
            continue

        match_label = matched_keyword or next(iter(matched_selected_terms + matched_specific_terms), "相关关键词")
        scored.append(
            {
                **candidate,
                "score": score,
                "matched_keyword": match_label,
                "reason": f"本地商品列表命中“{match_label}”，与当前商品方向更接近。",
            }
        )

    return sorted(
        scored,
        key=lambda item: (
            item["score"],
            bool(item.get("main_image_url")),
            item.get("weekly_sales") or 0,
            item.get("gmv_usd") or 0,
        ),
        reverse=True,
    )


def build_specific_relevance_terms(product: dict[str, Any], keywords: list[dict[str, str]]) -> list[str]:
    product_text = clean_text(
        f"{product.get('title', '')} {product.get('titleEn', '')} "
        f"{product.get('categoryPath') or product.get('category') or ''} "
        f"{product.get('categoryLevel1') or ''} {product.get('categoryLevel2') or ''}"
    )
    keyword_text = clean_text(" ".join(keyword.get("keyword", "") for keyword in keywords))
    raw_terms = [
        *find_known_relevance_terms(product_text),
        *find_known_relevance_terms(keyword_text),
        *extract_terms(keyword_text),
    ]
    return unique_strings([term for term in raw_terms if is_specific_relevance_term(term)])[:18]


def find_known_relevance_terms(text: str) -> list[str]:
    clean = clean_text(text).lower()
    known_terms = unique_strings([*SPECIFIC_MATCH_TERMS, *DOMAIN_MATCH_TERMS])
    return [term for term in known_terms if term.lower() in clean]


def is_specific_relevance_term(term: str) -> bool:
    value = clean_text(term).lower()
    if not value or value in STOP_TERMS or is_generic_recommendation_term(value):
        return False
    if any(stop_term in value for stop_term in STOP_TERMS if len(stop_term) >= 2):
        return False
    return 2 <= len(value) <= 12


def is_generic_recommendation_term(term: str) -> bool:
    value = clean_text(term).lower()
    return value in {item.lower() for item in GENERIC_RECOMMENDATION_TERMS}


def term_matches_text(term: str, text: str, expanded_terms: list[str]) -> bool:
    value = clean_text(term).lower()
    target_text = clean_text(text).lower()
    if not value:
        return False
    if value in target_text or any(value in expanded_term for expanded_term in expanded_terms):
        return True
    aliases = get_term_aliases(value)
    return any(alias in target_text for alias in aliases)


def get_term_aliases(term: str) -> set[str]:
    value = clean_text(term).lower()
    aliases = {value}
    for group in SYNONYM_TERM_GROUPS:
        normalized_group = {item.lower() for item in group}
        if value in normalized_group:
            aliases.update(normalized_group)
    return aliases


def dedupe_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = clean_text(item.get("product_url")) or clean_text(item.get("id"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def extract_terms(value: str) -> list[str]:
    text = clean_text(value)
    raw_terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)
    terms: list[str] = []
    for term in raw_terms:
        normalized = term.lower().strip()
        if len(normalized) > 14 and re.fullmatch(r"[\u4e00-\u9fff]+", normalized):
            terms.extend([normalized[index : index + 4] for index in range(0, len(normalized), 4)])
        else:
            terms.append(normalized)
    return unique_strings([term for term in terms if len(term) >= 2 and term not in STOP_TERMS])[:20]


def expand_match_terms(value: str) -> list[str]:
    text = clean_text(value).lower()
    terms = list(extract_terms(text))

    for term in DOMAIN_MATCH_TERMS:
        if term in text:
            terms.append(term)

    for chunk in re.findall(r"[\u4e00-\u9fff]{3,}", text):
        max_size = min(5, len(chunk))
        for size in range(max_size, 1, -1):
            for index in range(0, len(chunk) - size + 1):
                term = chunk[index : index + size]
                if term in STOP_TERMS:
                    continue
                if any(stop_term in term for stop_term in STOP_TERMS if len(stop_term) >= 2):
                    continue
                terms.append(term)

    return unique_strings([term for term in terms if len(term) >= 2])[:60]


def unique_keyword_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique_items: list[dict[str, str]] = []
    for item in items:
        keyword = item["keyword"]
        if keyword in seen:
            continue
        seen.add(keyword)
        unique_items.append(item)
    return unique_items


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = clean_text(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
