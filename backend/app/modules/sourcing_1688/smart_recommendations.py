from __future__ import annotations

import json
import hashlib
import re
from typing import Any
from urllib.parse import quote

from app.core.database import utc_now_text
from app.modules.admin_config.postgres_store import assert_user_api_usage_allowed, record_api_usage_safe
from app.modules.exports.postgres_store import get_export_connection as get_connection
from app.modules.ai_gateway import scheduler as ai_gateway_scheduler
from app.modules.creative_generation.chatgpt_listing import build_openai_client, get_openai_settings
from app.modules.creative_generation.safety import sanitize_marketplace_text
from app.modules.prompt_templates import render_prompt_template
from app.modules.recommendation.keyword_index import ensure_recommendation_schema
from app.modules.sourcing_1688.ai_response import contains_cjk, parse_ai_response_json
from app.modules.sourcing_1688.search_url import build_1688_search_url


DEFAULT_LIMIT = 6
IMAGE_SEARCH_1688_URL = "https://s.1688.com/youyuan/index.htm"
CACHE_SCHEMA_VERSION = "1688-smart-analysis-v6-adjacent-categories"
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


def generate_smart_1688_keywords(product: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
    analysis = analyze_product_for_1688(product, user_id=user_id)
    return {**analysis, "keywords": attach_search_urls(analysis["keywords"])}


def generate_smart_1688_recommendations(
    product: dict[str, Any],
    *,
    keywords: list[dict[str, Any] | str] | None = None,
    limit: int = DEFAULT_LIMIT,
    user_id: str | None = None,
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
        analysis = analyze_product_for_1688(product, user_id=user_id)

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


def analyze_product_for_1688(product: dict[str, Any], *, user_id: str | None = None) -> dict[str, Any]:
    settings = get_openai_settings("recommendation", user_id=user_id)
    title = clean_text(product.get("title") or product.get("titleEn"))
    category = clean_text(product.get("category") or product.get("categoryPath"))
    main_image_url = clean_text(product.get("mainImageUrl") or product.get("main_image_url"))
    cache_key = build_analysis_cache_key(product, title=title, category=category, main_image_url=main_image_url)
    title_hash = build_analysis_title_hash(title=title, category=category, main_image_url=main_image_url)

    cached_analysis = load_cached_analysis(cache_key, title_hash)
    if cached_analysis:
        return {**cached_analysis, "cache": {"hit": True, "key": cache_key}}

    if settings.api_key:
        assert_user_api_usage_allowed(user_id)
        try:
            analysis, usage_settings = analyze_with_gateway_fallback(
                title=title,
                category=category,
                main_image_url=main_image_url,
                settings=settings,
            )
            record_api_usage_safe(
                provider="openai-compatible",
                api_type="chat",
                stage="recommendation",
                model=usage_settings.text_model,
                user_id=user_id,
                channel_id=usage_settings.channel_id,
                credential_id=getattr(usage_settings, "credential_id", ""),
                credential_name=getattr(usage_settings, "credential_name", ""),
                status="success",
            )
            save_cached_analysis(cache_key, title_hash, analysis, model=usage_settings.text_model)
            return {**analysis, "cache": {"hit": False, "key": cache_key}}
        except Exception as exc:
            record_api_usage_safe(
                provider="openai-compatible",
                api_type="chat",
                stage="recommendation",
                model=settings.text_model,
                user_id=user_id,
                channel_id=settings.channel_id,
                credential_id=getattr(settings, "credential_id", ""),
                credential_name=getattr(settings, "credential_name", ""),
                status="failed",
                error_message=str(exc),
            )
            analysis = build_fallback_analysis(title, category)
            return {
                **analysis,
                "source": "rule-fallback",
                "warning": f"AI 推荐关键词生成失败，已使用本地规则推荐：{exc}",
                "cache": {"hit": False, "key": cache_key},
            }

    analysis = build_fallback_analysis(title, category)
    save_cached_analysis(cache_key, title_hash, analysis, model="rule-fallback")
    return {**analysis, "source": "rule-fallback", "cache": {"hit": False, "key": cache_key}}


def analyze_with_gateway_fallback(
    *,
    title: str,
    category: str,
    main_image_url: str,
    settings: Any,
) -> tuple[dict[str, Any], Any]:
    attempt_limit = ai_gateway_scheduler.resolve_attempt_limit("recommendation")
    excluded_credential_ids: set[str] = set()
    candidate = ai_gateway_scheduler.acquire_candidate(
        "recommendation",
        task_type="api",
        excluded_credential_ids=excluded_credential_ids,
    )
    if not candidate:
        return analyze_with_chatgpt(title=title, category=category, main_image_url=main_image_url, settings=settings), settings
    last_error: BaseException | None = None
    for attempt_index in range(attempt_limit):
        if not candidate:
            break
        excluded_credential_ids.add(str(candidate.get("credentialId") or ""))
        trial_settings = replace_settings_from_gateway_candidate(settings, candidate)
        try:
            result = analyze_with_chatgpt(
                title=title,
                category=category,
                main_image_url=main_image_url,
                settings=trial_settings,
            )
            ai_gateway_scheduler.finish_attempt(candidate, success=True)
            return result, trial_settings
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            ai_gateway_scheduler.finish_attempt(candidate, success=False, error_message=str(exc))
            if attempt_index < attempt_limit - 1:
                candidate = ai_gateway_scheduler.acquire_candidate(
                    "recommendation",
                    task_type="api",
                    excluded_credential_ids=excluded_credential_ids,
                )
    raise last_error or ValueError("API 中枢没有可用推荐渠道")


def replace_settings_from_gateway_candidate(settings: Any, candidate: dict[str, Any]) -> Any:
    return type(settings)(
        api_key=str(candidate.get("apiKey") or ""),
        base_url=str(candidate.get("baseUrl") or ""),
        text_model=str(candidate.get("model") or getattr(settings, "text_model", "")),
        image_model=getattr(settings, "image_model", ""),
        image_quality=getattr(settings, "image_quality", "medium"),
        channel_id=str(candidate.get("channelId") or ""),
        credential_id=str(candidate.get("credentialId") or ""),
        credential_name=str(candidate.get("credentialName") or candidate.get("credentialId") or ""),
    )


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
        "core_product_name": clean_text(analysis.get("core_product_name")),
        "removed_noise_terms": analysis.get("removed_noise_terms") if isinstance(analysis.get("removed_noise_terms"), list) else [],
        "summary": clean_text(analysis.get("summary")),
        "strategy": clean_text(analysis.get("strategy")),
        "keywords": analysis.get("keywords") if isinstance(analysis.get("keywords"), list) else [],
    }
    with get_connection() as conn:
        ensure_recommendation_schema(conn)
        now = utc_now_text()
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
        "reference_image_url": main_image_url,
        "task": (
            "Complete the whole workflow in this single API call. Step 1: analyze the title and optional image to identify the "
            "real product. Remove irrelevant adjectives, long marketing copy, audience/occasion filler, logistics words, promo text, "
            "ratings, sold counts, pack counts, model noise, and raw English fragments. Translate the concrete product name into "
            "Simplified Chinese. Step 2: based on that concrete product name, expand into useful 1688 Chinese search keywords: "
            "similar product names, same-category variants with specific attributes, adjacent categories, complementary products, "
            "same-scene products, and bundle add-ons. For example: if the product is a bowl, recommend spoon, plate, placemat, "
            "round bowl, printed bowl, or different pattern bowl. If it is a square bowl, recommend round bowl or specific pattern/style bowls. "
            "Return Chinese search keywords only."
        ),
        "translation_requirement": (
            "所有 keyword 必须是简体中文 1688 采购搜索词。英文/中英混合标题必须先提炼并转成中文商品名，不能原样输出英文连写词、型号词、物流词、促销词、评分销量词或数量词。"
        ),
        "divergent_recommendation_requirement": (
            "关键词应该围绕提炼后的具体商品名，扩散到相似商品名、明确属性变体、相邻类目、搭配类目、同使用场景或可组成套装的周边商品。"
            "允许同类目变体，但必须是可搜索的具体方向，例如圆形碗、印花碗、卡通碗、陶瓷碗；不要使用不同款、批发、1688、热销、爆款这类空泛后缀。"
        ),
        "good_examples": {
            "勺子": ["陶瓷碗", "餐盘", "餐垫", "筷子筒", "餐具收纳盒"],
            "正方形陶瓷碗": ["圆形陶瓷碗", "印花陶瓷碗", "卡通陶瓷碗", "勺子", "餐盘", "餐垫"],
            "宠物碗": ["宠物餐垫", "宠物喂食勺", "宠物储粮桶", "宠物饮水器"],
            "纸飞机玩具": ["折纸材料包", "儿童手工材料", "飞机模型玩具", "派对游戏道具"],
        },
        "bad_examples": ["勺子不同款", "勺子批发", "勺子1688", "36pcs 3d paper airplane 不同款", "square bowl", "best seller"],
        "must_translate_examples": {
            "3DPaperAirplaneF": "纸飞机玩具",
            "Pale Mini Tote Bags": "迷你托特包",
            "Wood D12 Dice": "木质十二面骰子",
        },
        "required_json": {
            "core_product_name": "提炼后的简体中文具体商品名，不要形容词杂质、数量词、促销词或英文碎片",
            "removed_noise_terms": ["被去除的英文碎片、促销词、数量词、场景填充词等"],
            "summary": "short Chinese summary of the cleaned product identity",
            "strategy": "short Chinese strategy explaining similar-name variants, adjacent category expansion, complementary bundles, or same-scene sourcing",
            "keywords": [
                {
                    "keyword": "简体中文 1688 搜索词，2-16 个中文字符为主，不要英文原词",
                    "intent": "same-product-variant/adjacent-category/complementary-bundle/same-scene/same-buyer-intent",
                    "reason": "why this adjacent product direction is commercially relevant",
                }
            ],
        },
    }
    response = client.chat.completions.create(
        model=settings.text_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful 1688 sourcing analyst for Temu listing operations. "
                    "Return strict JSON only. First clean the title into one concrete Simplified Chinese product name, then expand search keywords from that product identity. "
                    "Think like a 1688 buyer who needs similar product names, specific same-category variants, adjacent categories, complementary items, bundle add-ons, same-scene products, or same-buyer-intent products. "
                    "Same-category variants are allowed when they are specific searchable product names, such as round bowl, printed bowl, cartoon bowl, ceramic bowl, or different pattern bowl translated into Chinese. "
                    "Reject vague suffixes such as 不同款, 批发, 1688, 热销, 爆款, best seller, free shipping, sold count, rating, or pack-count-only keywords. "
                    "Every keyword must be a Simplified Chinese supplier/search phrase for 1688. "
                    "Do not output raw English title fragments, SKU/model codes, logistics text, promo text, pack counts, "
                    "brand names, medical claims, certification claims, or unsafe marketplace wording. "
                    "Only keep universal English abbreviations when paired with a Chinese product noun, such as '3D纸飞机模型', "
                    "'LED灯', or 'USB充电线'."
                ),
            },
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
    )
    return normalize_analysis(parse_ai_response_json(response), title, category)


def build_fallback_analysis(title: str, category: str) -> dict[str, Any]:
    base_terms = extract_terms(f"{title} {category}")
    core = " ".join(base_terms[:4]) or title[:18] or "1688 货源"
    special_keywords = adjacent_fallback_keywords(title, category)
    if any(term in title for term in ("药盒", "药片", "药丸", "医疗", "分药")):
        special_keywords = ["药片切割器", "药瓶收纳袋", "便携收纳包", "标签贴纸", *special_keywords]
    elif any(term in title for term in ("盒", "收纳", "包装")):
        special_keywords = ["标签贴纸", "收纳分隔板", "包装贴纸", "礼品袋", *special_keywords]
    elif any(term in title for term in ("钥匙扣", "挂件")):
        special_keywords = ["首饰收纳盒", "礼品包装盒", "手机挂绳", "包包装饰链", *special_keywords]

    keyword_values = unique_strings([*special_keywords])[:6]
    if not keyword_values:
        keyword_values = unique_strings(
            [
                "同场景搭配品",
                "礼品包装盒",
                "收纳展示架",
                "配套小工具",
            ]
        )[:6]
    keywords = [
        {
            "keyword": keyword,
            "intent": "相邻类目发散找货",
            "reason": "围绕当前商品的使用场景、买家需求或套装搭配，寻找相邻类目 1688 货源。",
        }
        for keyword in keyword_values
    ]
    return normalize_analysis(
        {
            "summary": f"当前商品核心方向：{title or core}",
            "strategy": "优先找相邻类目、搭配品、同场景商品或可组成套装的周边货源。",
            "keywords": keywords,
        },
        title,
        category,
    )


def analyze_with_chatgpt(*, title: str, category: str, main_image_url: str, settings: Any) -> dict[str, Any]:
    client = build_openai_client(settings)
    instruction = render_prompt_template(
        "recommendation",
        {
            "title": title,
            "category": category,
            "mainImageUrl": main_image_url,
        },
    )
    response = client.chat.completions.create(
        model=settings.text_model,
        messages=[{"role": "system", "content": instruction}],
    )
    return normalize_analysis(parse_ai_response_json(response), title, category)


def normalize_analysis(raw: dict[str, Any], title: str, category: str) -> dict[str, Any]:
    core_product_name, _ = sanitize_marketplace_text(clean_text(raw.get("core_product_name")))
    removed_noise_terms = [
        clean_text(item)[:40]
        for item in raw.get("removed_noise_terms", [])
        if clean_text(item)
    ][:12] if isinstance(raw.get("removed_noise_terms"), list) else []
    summary, _ = sanitize_marketplace_text(clean_text(raw.get("summary")) or f"当前商品：{title or category}")
    strategy, _ = sanitize_marketplace_text(
        clean_text(raw.get("strategy")) or "推荐相邻类目、搭配品、同场景商品或可组成套装的周边货源。"
    )
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

    if not any(contains_cjk(item.get("keyword")) for item in keywords):
        raise ValueError("模型没有返回中文 1688 推荐关键词")

    return {
        "core_product_name": core_product_name or extract_core_product_name_hint(title, category),
        "removed_noise_terms": removed_noise_terms,
        "summary": summary,
        "strategy": strategy,
        "keywords": unique_keyword_items(keywords)[:8],
    }


def build_fallback_analysis_without_recursion(title: str, category: str) -> dict[str, Any]:
    keywords = adjacent_fallback_keywords(title, category) or ["同场景搭配品", "礼品包装盒", "收纳展示架"]
    return {
        "core_product_name": extract_core_product_name_hint(title, category),
        "removed_noise_terms": [],
        "summary": f"当前商品核心方向：{title or keywords[0]}",
        "strategy": "推荐相邻类目、搭配品、同场景商品或可组成套装的周边货源。",
        "keywords": [
            {
                "keyword": keyword[:48],
                "intent": "相邻类目发散找货",
                "reason": "与当前商品的使用场景、买家需求或套装搭配相关。",
            }
            for keyword in keywords[:6]
        ],
    }


def extract_core_product_name_hint(title: str, category: str) -> str:
    terms = extract_terms(f"{title} {category}")
    return " ".join(terms[:3])[:48] or clean_text(title)[:48] or clean_text(category)[:48]


def adjacent_fallback_keywords(title: str, category: str) -> list[str]:
    text = clean_text(f"{title} {category}").lower()
    groups: list[tuple[tuple[str, ...], list[str]]] = [
        (("勺", "spoon"), ["陶瓷碗", "餐盘", "餐垫", "筷子筒", "餐具收纳盒", "儿童餐具套装"]),
        (("方形碗", "正方形碗", "square bowl"), ["圆形碗", "印花碗", "卡通碗", "勺子", "餐盘", "餐垫"]),
        (("碗", "bowl"), ["圆形碗", "印花碗", "勺子", "餐盘", "餐垫", "餐具收纳盒"]),
        (("盘", "plate"), ["勺子", "餐垫", "餐具套装", "杯垫", "桌面收纳盘"]),
        (("宠物碗", "pet bowl"), ["宠物餐垫", "宠物饮水器", "宠物储粮桶", "宠物喂食勺", "宠物零食罐"]),
        (("纸飞机", "paper airplane", "airplane"), ["折纸材料包", "儿童手工材料", "飞机模型玩具", "派对游戏道具", "手工收纳盒"]),
        (("骰子", "dice"), ["桌游配件", "骰子收纳袋", "游戏卡牌", "礼品包装盒", "派对游戏道具"]),
        (("包", "袋", "bag"), ["包包挂件", "收纳小包", "钥匙扣挂件", "礼品包装袋", "丝巾配饰"]),
        (("钥匙扣", "挂件", "keychain"), ["礼品包装盒", "手机挂绳", "包包装饰链", "首饰收纳盒", "展示卡纸"]),
        (("种子", "盆栽", "花盆"), ["园艺工具套装", "种子收纳盒", "育苗盆", "植物标签牌", "迷你喷壶"]),
    ]
    for needles, keywords in groups:
        if any(needle in text for needle in needles):
            return keywords
    return []


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
                    STRING_AGG(DISTINCT pk.keyword, ',') AS matched_keywords
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
                    NULLIF(p.listing_time, '') DESC,
                    NULLIF(p.updated_at, '') DESC
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
                    NULLIF(listing_time, '') DESC,
                    NULLIF(updated_at, '') DESC
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
