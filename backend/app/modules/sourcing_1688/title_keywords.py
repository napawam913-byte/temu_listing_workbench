from __future__ import annotations

import json
import re
from typing import Any

from app.modules.admin_config.postgres_store import assert_user_api_usage_allowed, record_api_usage_safe
from app.modules.ai_gateway import scheduler as ai_gateway_scheduler
from app.modules.creative_generation.chatgpt_listing import build_openai_client, get_openai_settings
from app.modules.creative_generation.safety import sanitize_marketplace_text
from app.modules.prompt_templates import render_prompt_template
from app.modules.sourcing_1688.ai_response import contains_cjk, parse_ai_response_json
from app.modules.sourcing_1688.search_url import build_1688_search_url

TITLE_SPLIT_STAGE = "title_split"

NOISE_TERMS = (
    "适合",
    "用于",
    "家居装饰",
    "家居",
    "装饰",
    "礼物",
    "完美礼物",
    "园丁",
    "diy",
    "DIY",
    "新款",
    "热卖",
    "爆款",
    "跨境",
    "temu",
    "Temu",
    "amazon",
    "Amazon",
    "批发",
    "包邮",
)

PLANT_SUBJECT_TERMS = (
    "樱花",
    "玫瑰",
    "向日葵",
    "薰衣草",
    "多肉",
    "薄荷",
    "草莓",
    "番茄",
)

PRODUCT_NOUNS = (
    "种子",
    "钥匙扣",
    "挂件",
    "收纳盒",
    "药盒",
    "贴纸",
    "模具",
    "花盆",
    "盆栽",
    "玩具",
    "灯",
    "袋",
)


def split_title_for_1688_search(title: str, category: str = "", *, user_id: str | None = None) -> dict[str, Any]:
    clean_title = clean_text(title)
    clean_category = clean_text(category)
    if not clean_title:
        raise ValueError("商品标题不能为空")

    settings = get_openai_settings(TITLE_SPLIT_STAGE, user_id=user_id)
    if settings.api_key:
        assert_user_api_usage_allowed(user_id)
        try:
            result, usage_settings = split_title_with_gateway_fallback(
                title=clean_title,
                category=clean_category,
                settings=settings,
            )
            record_api_usage_safe(
                provider="openai-compatible",
                api_type="chat",
                stage=TITLE_SPLIT_STAGE,
                model=usage_settings.text_model,
                user_id=user_id,
                channel_id=usage_settings.channel_id,
                credential_id=getattr(usage_settings, "credential_id", ""),
                credential_name=getattr(usage_settings, "credential_name", ""),
                status="success",
            )
            return {**result, "source": "gpt", "model": usage_settings.text_model}
        except Exception as exc:  # noqa: BLE001
            record_api_usage_safe(
                provider="openai-compatible",
                api_type="chat",
                stage=TITLE_SPLIT_STAGE,
                model=settings.text_model,
                user_id=user_id,
                channel_id=settings.channel_id,
                credential_id=getattr(settings, "credential_id", ""),
                credential_name=getattr(settings, "credential_name", ""),
                status="failed",
                error_message=str(exc),
            )
            raise ValueError(f"1688 中文关键词转换失败：{exc}") from exc

    fallback = build_fallback_title_keywords(clean_title, clean_category)
    return {**fallback, "source": "rule-fallback", "model": "rule-fallback"}


def split_title_with_gateway_fallback(
    *,
    title: str,
    category: str,
    settings: Any,
) -> tuple[dict[str, Any], Any]:
    attempt_limit = ai_gateway_scheduler.resolve_attempt_limit(TITLE_SPLIT_STAGE)
    excluded_credential_ids: set[str] = set()
    first_candidate = ai_gateway_scheduler.acquire_candidate(
        TITLE_SPLIT_STAGE,
        task_type="api",
        excluded_credential_ids=excluded_credential_ids,
    )
    if not first_candidate:
        return split_title_with_gpt(title=title, category=category, settings=settings), settings
    last_error: BaseException | None = None
    candidate: dict[str, Any] | None = first_candidate
    for attempt_index in range(attempt_limit):
        if not candidate:
            break
        excluded_credential_ids.add(str(candidate.get("credentialId") or ""))
        trial_settings = replace_settings_from_gateway_candidate(settings, candidate)
        try:
            result = split_title_with_gpt(title=title, category=category, settings=trial_settings)
            ai_gateway_scheduler.finish_attempt(candidate, success=True)
            return result, trial_settings
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            ai_gateway_scheduler.finish_attempt(candidate, success=False, error_message=str(exc))
            if attempt_index < attempt_limit - 1:
                candidate = ai_gateway_scheduler.acquire_candidate(
                    TITLE_SPLIT_STAGE,
                    task_type="api",
                    excluded_credential_ids=excluded_credential_ids,
                )
    raise last_error or ValueError("API 中枢没有可用标题拆分渠道")


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


def split_title_with_gpt(title: str, category: str, settings: Any) -> dict[str, Any]:
    client = build_openai_client(settings)
    response = client.chat.completions.create(
        model=settings.text_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You convert noisy marketplace product titles into concise Simplified Chinese 1688 sourcing keywords. "
                    "If the title is English or mixed-language, first translate the real product subject, material, shape, "
                    "structure, and key attributes into Chinese supplier search terms. Return strict JSON only. "
                    "Every keyword must be suitable for 1688 supplier search in Simplified Chinese. "
                    "Do not output raw English title fragments, SKU/model codes, logistics text, quantity, marketing copy, "
                    "target users, scenes, gift wording, platform names, or broad usage claims. "
                    "Examples: '3DPaperAirplaneF' -> '纸飞机玩具'; 'Mini Tote Bags' -> '迷你托特包'; "
                    "'Wood D12 Dice' -> '木质十二面骰子'. "
                    "Only keep universal English abbreviations when paired with a Chinese product noun, such as '3D纸飞机模型', "
                    "'LED灯', or 'USB充电线'."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "title": title,
                        "category": category,
                        "translation_requirement": (
                            "英文或中英混合标题必须先转成简体中文 1688 采购搜索词，不能原样输出英文连写词、型号词、物流词或营销词。"
                        ),
                        "must_translate_examples": {
                            "3DPaperAirplaneF": "纸飞机玩具",
                            "Pale Mini Tote Bags": "迷你托特包",
                            "Wood D12 Dice": "木质十二面骰子",
                        },
                        "required_json": {
                            "primary_keyword": "最精准的简体中文 1688 采购搜索词，通常 4-12 个中文字符；英文标题必须翻译成中文，不要原样输出英文",
                            "keywords": [
                                {
                                    "keyword": "简体中文 1688 采购搜索词，不要英文原词",
                                    "intent": "precise/core/attribute/broaden",
                                    "reason": "short Chinese reason",
                                }
                            ],
                            "removed_terms": ["noise term removed from title"],
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    result = normalize_title_keyword_response(parse_ai_response_json(response), title, category)
    if not contains_cjk(result.get("primary_keyword")):
        raise ValueError("模型没有返回中文 1688 搜索词")
    return result


def build_fallback_title_keywords(title: str, category: str = "") -> dict[str, Any]:
    clean_title_value = strip_noise(title)
    keywords: list[dict[str, str]] = []

    if "种子" in clean_title_value:
        subject = next((term for term in PLANT_SUBJECT_TERMS if term in clean_title_value), "")
        if subject and "盆景" in clean_title_value:
            keywords.append(keyword_item(f"{subject}盆景种子", "精准采购词", "保留植物主体、盆景形态和种子品类。"))
        if subject:
            keywords.append(keyword_item(f"{subject}种子", "核心品类词", "保留植物主体和种子品类。"))
        if subject and "粉色" in clean_title_value:
            keywords.append(keyword_item(f"粉色{subject}种子", "属性品类词", "保留颜色属性和种子品类。"))
        if "盆景" in clean_title_value:
            keywords.append(keyword_item("盆景树种子", "拓展品类词", "保留盆景树种子采购方向。"))

    for noun in PRODUCT_NOUNS:
        if noun not in clean_title_value:
            continue
        compact = compact_cjk_around_noun(clean_title_value, noun)
        if compact:
            keywords.append(keyword_item(compact, "规则提炼词", "从标题中提取主体和品类词。"))

    if not keywords:
        fallback_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", clean_title_value)
        fallback_keyword = (
            "".join(fallback_terms)[:16]
            or clean_text(category)[:16]
            or title[:16]
        )
        keywords.append(keyword_item(fallback_keyword, "兜底关键词", "未配置 GPT 时使用标题主体片段。"))

    return normalize_title_keyword_response(
        {
            "primary_keyword": keywords[0]["keyword"],
            "keywords": keywords,
            "removed_terms": [term for term in NOISE_TERMS if term in title],
        },
        title,
        category,
    )


def normalize_title_keyword_response(raw: dict[str, Any], title: str, category: str = "") -> dict[str, Any]:
    raw_keywords = raw.get("keywords") if isinstance(raw.get("keywords"), list) else []
    normalized_items: list[dict[str, str]] = []

    primary_keyword = clean_keyword(raw.get("primary_keyword"))
    if primary_keyword:
        normalized_items.append(keyword_item(primary_keyword, "首选搜索词", "GPT 提炼出的最优先 1688 搜索词。"))

    for item in raw_keywords:
        if isinstance(item, str):
            keyword = clean_keyword(item)
            intent = "相关搜索词"
            reason = "标题拆分得到的 1688 搜索词。"
        elif isinstance(item, dict):
            keyword = clean_keyword(item.get("keyword"))
            intent = clean_text(item.get("intent")) or "相关搜索词"
            reason = clean_text(item.get("reason")) or "标题拆分得到的 1688 搜索词。"
        else:
            continue
        if keyword:
            normalized_items.append(keyword_item(keyword, intent[:80], reason[:120]))

    unique_items = unique_keyword_items(normalized_items)[:6]
    if not unique_items:
        return build_fallback_title_keywords(title, category)

    removed_terms = raw.get("removed_terms") if isinstance(raw.get("removed_terms"), list) else []
    return {
        "primary_keyword": unique_items[0]["keyword"],
        "keywords": [
            {
                **item,
                "searchUrl": build_1688_search_url(item["keyword"]),
            }
            for item in unique_items
        ],
        "removed_terms": [clean_text(term) for term in removed_terms if clean_text(term)][:12],
    }


def clean_keyword(value: Any) -> str:
    keyword, _ = sanitize_marketplace_text(clean_text(value))
    keyword = re.sub(r"https?://\S+", "", keyword)
    keyword = re.sub(r"\b(?:1688|temu|amazon)\b", "", keyword, flags=re.I)
    keyword = re.sub(r"[，,。.;；:：!！?？|/\\()\[\]{}【】<>《》]+", " ", keyword)
    keyword = re.sub(r"\s+", "", keyword).strip()
    if len(keyword) < 2:
        return ""
    return keyword[:24]


def strip_noise(title: str) -> str:
    text = clean_text(title)
    text = re.sub(r"\b\d+\+?\s*(?:个|件|片|只|套|组|pcs?|packs?)\b", " ", text, flags=re.I)
    text = re.sub(r"\d+\+?\s*(?:个|件|片|只|套|组)", " ", text)
    for term in NOISE_TERMS:
        text = text.replace(term, " ")
    text = re.sub(r"[，,。.;；:：!！?？|/\\()\[\]{}【】<>《》、]+", " ", text)
    return clean_text(text)


def compact_cjk_around_noun(title: str, noun: str) -> str:
    index = title.find(noun)
    if index < 0:
        return ""
    before = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", title[max(0, index - 8) : index])
    before = before[-6:]
    candidate = f"{before}{noun}" if before else noun
    return clean_keyword(candidate)


def keyword_item(keyword: str, intent: str, reason: str) -> dict[str, str]:
    return {"keyword": keyword, "intent": intent, "reason": reason}


def split_title_with_gpt(title: str, category: str, settings: Any) -> dict[str, Any]:
    client = build_openai_client(settings)
    instruction = render_prompt_template(
        "title_split",
        {
            "productTitle": title,
            "category": category,
        },
    )
    response = client.chat.completions.create(
        model=settings.text_model,
        messages=[{"role": "system", "content": instruction}],
    )
    result = normalize_title_keyword_response(parse_ai_response_json(response), title, category)
    if not contains_cjk(result.get("primary_keyword")):
        raise ValueError("模型没有返回中文 1688 搜索词")
    return result


def unique_keyword_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for item in items:
        keyword = clean_keyword(item.get("keyword"))
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        result.append({**item, "keyword": keyword})
    return result


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
