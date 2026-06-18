from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR
from app.core.database import (
    assert_user_api_usage_allowed,
    record_api_usage_safe,
)
from app.modules.creative_generation.safety import sanitize_marketplace_text
from app.modules.visual_generation.clients import (
    build_api_url,
    extract_response_text,
    get_ai_stage_settings,
    parse_json_from_text,
    request_json,
    request_text_json,
)


PROMPT_PATH = BACKEND_DIR / "config" / "prompts" / "listing_optimization.md"
VARIANT_VALUE_REPLACEMENTS = {
    "默认款": "Default Option",
    "默认": "Default",
    "榛樿娆": "Default Option",
    "黑色": "Black",
    "榛戣壊": "Black",
    "白色": "White",
    "鐧借壊": "White",
    "红色": "Red",
    "绾㈣壊": "Red",
    "蓝色": "Blue",
    "钃濊壊": "Blue",
    "绿色": "Green",
    "缁胯壊": "Green",
    "黄色": "Yellow",
    "榛勮壊": "Yellow",
    "粉色": "Pink",
    "绮夎壊": "Pink",
    "紫色": "Purple",
    "绱壊": "Purple",
    "金色": "Gold",
    "閲戣壊": "Gold",
    "银色": "Silver",
    "閾惰壊": "Silver",
    "透明": "Clear",
    "閫忔槑": "Clear",
    "灰色": "Gray",
    "鐏拌壊": "Gray",
    "棕色": "Brown",
    "妫曡壊": "Brown",
    "米色": "Beige",
    "米白": "Off White",
    "单个": "Single",
    "单只": "Single",
    "套装": "Set",
    "濂楄": "Set",
    "组合": "Combo",
    "缁勫悎": "Combo",
    "立即定制": "Custom Option",
    "绔嬪嵆瀹氬埗": "Custom Option",
    "材质": "Material",
    "鏉愯川": "Material",
    "钥匙配饰分类": "Keychain Accessory Category",
    "SKU列表": "SKU List",
}
MAX_VARIANT_REFERENCE_IMAGES = 8
MAX_VARIANT_VALUE_LENGTH = 48

MOQ_MARKERS = (
    "起订",
    "起批",
    "件起",
    "个起",
    "浠惰捣",
    "璧疯",
    "璧锋壒",
    "捣璁",
    "捣批",
    "moq",
)


@dataclass
class TitleOptimizerSettings:
    api_key: str
    base_url: str
    text_model: str
    channel_id: str = ""


def optimize_listing_titles(
    record: dict[str, Any],
    *,
    fallback_title_cn: str,
    fallback_title_en: str,
    user_id: str | None = None,
    strict: bool = False,
) -> dict[str, str]:
    fallback = build_fallback_titles(fallback_title_cn, fallback_title_en)
    settings = get_title_optimizer_settings(user_id=user_id)

    if not settings.api_key:
        if strict:
            raise ValueError("Title generation is not configured")
        return fallback

    assert_user_api_usage_allowed(user_id)
    try:
        generated = generate_titles_with_ai(record, fallback, settings)
        record_title_optimizer_usage(settings, user_id=user_id, stage="title", status="success")
        result = normalize_generated_titles(generated, fallback)
    except Exception as exc:
        record_title_optimizer_usage(settings, user_id=user_id, stage="title", status="failed", error_message=str(exc))
        if strict:
            raise ValueError(f"Title generation failed: {exc}") from exc
        result = fallback

    return result


def translate_variant_values_to_english(
    values: list[str],
    *,
    user_id: str | None = None,
    strict: bool = False,
    context: dict[str, Any] | None = None,
) -> dict[str, str]:
    unique_values = []
    for value in values:
        text = clean_text(value)
        if text and text not in unique_values:
            unique_values.append(text)

    result: dict[str, str] = {}
    missing: list[str] = []
    use_context_ai = bool(context)
    for value in unique_values:
        if not use_context_ai and not contains_cjk(value):
            translated = normalize_ascii_variant_value(value)
            result[value] = translated
            continue
        missing.append(value)

    settings = get_title_optimizer_settings(user_id=user_id)
    ai_translations: dict[str, str] = {}
    if missing and not settings.api_key:
        if strict:
            raise ValueError("Variant translation API is not configured")
    elif missing and settings.api_key:
        assert_user_api_usage_allowed(user_id)
        try:
            ai_translations = generate_variant_values_with_ai(missing, settings, context=context)
            record_title_optimizer_usage(settings, user_id=user_id, stage="variant_translation", status="success")
        except Exception as exc:
            record_title_optimizer_usage(
                settings,
                user_id=user_id,
                stage="variant_translation",
                status="failed",
                error_message=str(exc),
            )
            if strict:
                raise ValueError(f"Variant translation failed: {exc}") from exc
            ai_translations = {}

    for value in missing:
        fallback = fallback_translate_variant_value(value)
        translated = normalize_variant_value_translation(ai_translations.get(value), fallback)
        if strict and value not in ai_translations:
            raise ValueError(f"Variant translation API did not return a translation for: {value}")
        result[value] = translated

    return result


def generate_variant_values_with_ai(
    values: list[str],
    settings: TitleOptimizerSettings,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, str]:
    instruction = json.dumps(
        {
            "role": (
                "You generate clean Temu SKU option values for a Dianxiaomi import template. "
                "Use the product title, SKU/source context, and reference images when provided. "
                "Return strict JSON only. Keep values concise, English-only, and faithful. "
                "Preserve real product quantities, model codes, colors, materials, and plus signs. "
                "A SKU value is a short option label, not a product title. "
                "Do not include promotions, shop metrics, ratings, sales counts, holiday/gift marketing, "
                "platform names, unsupported claims, discounts, certifications, or hype."
            ),
            "task": "Generate clean English SKU option values from the source values.",
            "requirements": [
                "Output must contain no Chinese characters.",
                "Keep each SKU value very short: usually 1-5 words and at most 48 characters.",
                "Never output full product titles, full selling points, use scenes, or sentence-like descriptions.",
                "Prefer direct labels such as Mix, 12pcs, Red, D12 Dice, Wood Dice, Pet Bowl+Feeding Mat.",
                "Translate or rewrite each source independently.",
                "Use images and titles to keep only concrete product/variant information.",
                "If the target variant field is color, output only the color/mix option, not quantity.",
                "If the target variant field is quantity, output only the quantity/pack count.",
                "If a source is a combo like A+B, preserve the plus structure using clean component product names.",
                "For combo values whose parts are only quantities, pack labels, colors, or other weak specs, use product_context.sku_items[].combo_components titles and images to rewrite each part as quantity + product noun.",
                "Never return a combo value that is only quantities or pack labels, such as 2pcs+1 Pack, when source titles or images identify different products.",
                "For dice or other geometry-sensitive products, preserve visible/product-title shape words such as Six-Sided Dice, D12 Dice, Wooden Dice, Cube Dice, or Round Dice when supported by the component title/image.",
                "Remove duplicated tokens such as Mix Quantity 12pcs+Mix when Mix already appears in the source.",
                "If unsure, use a neutral value like Custom Option or Default Option.",
            ],
            "product_context": context or {},
            "source_values": values,
            "required_json": {
                "values": [
                    {"source": "original value", "value_en": "clean English SKU value"}
                ]
            },
        },
        ensure_ascii=False,
    )
    raw = request_variant_values_json(settings, instruction, context=context)
    items = raw.get("values") or raw.get("items") or []
    translations: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        source = clean_text(item.get("source"))
        value_en = clean_text(item.get("value_en") or item.get("value"))
        if source and value_en:
            translations[source] = value_en
    return translations


def request_variant_values_json(
    settings: TitleOptimizerSettings,
    instruction: str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_url = build_api_url(settings.base_url, "/chat/completions")
    image_refs = [
        clean_text(item)
        for item in ((context or {}).get("image_urls") or [])
        if clean_text(item).lower().startswith(("http://", "https://", "data:image/"))
    ][:MAX_VARIANT_REFERENCE_IMAGES]
    if not image_refs:
        return request_text_json(
            api_url=api_url,
            api_key=settings.api_key,
            model=settings.text_model,
            instruction=instruction,
            temperature=0.05,
        )

    content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
    content.extend({"type": "image_url", "image_url": {"url": image_url}} for image_url in image_refs)
    payload = {
        "model": settings.text_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.05,
    }
    try:
        response_json = request_json(api_url, settings.api_key, payload)
        return parse_json_from_text(extract_response_text(response_json))
    except Exception:
        return request_text_json(
            api_url=api_url,
            api_key=settings.api_key,
            model=settings.text_model,
            instruction=instruction,
            temperature=0.05,
        )


def fallback_translate_variant_value(value: str) -> str:
    text = clean_text(value)
    if not text:
        return "Default Option"
    if not contains_cjk(text):
        return normalize_ascii_variant_value(text)

    if "+" in text:
        parts = [fallback_translate_variant_value(part) for part in re.split(r"\s*\+\s*", text) if clean_text(part)]
        if parts:
            return "+".join(parts)

    translated = text
    for source, target in sorted(VARIANT_VALUE_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        translated = translated.replace(source, f" {target} ")

    quantity = extract_quantity_count(text)
    has_moq = has_moq_marker(text)
    normalized = normalize_ascii_variant_value(translated, allow_empty=True)
    if quantity and has_moq:
        if "Default Option" in normalized:
            return f"Default Option ({quantity} Pcs MOQ)"
        if normalized == quantity:
            return f"{quantity} Pcs MOQ"
        if normalized:
            return f"{normalized} ({quantity} Pcs MOQ)"
    if normalized and re.search(r"[A-Za-z]", normalized):
        return normalized
    if quantity:
        return f"{quantity} Pcs"
    return "Custom Option"


def normalize_variant_value_translation(raw: Any, fallback: str) -> str:
    text = normalize_ascii_variant_value(raw, allow_empty=True)
    if not text:
        return fallback
    return text


def normalize_ascii_variant_value(value: Any, *, allow_empty: bool = False) -> str:
    text = clean_text(value)
    if not text:
        return "" if allow_empty else "Default Option"
    text = remove_cjk(text)
    text = re.sub(r"[^A-Za-z0-9+\-/().\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_/,.")
    safe_text, _ = sanitize_marketplace_text(text)
    safe_text = trim_title(remove_cjk(safe_text), MAX_VARIANT_VALUE_LENGTH)
    if safe_text:
        return safe_text
    return "" if allow_empty else "Custom Option"


def extract_quantity_count(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", value or "")
    return match.group(1) if match else ""


def has_moq_marker(value: str) -> bool:
    text = clean_text(value).lower()
    return any(marker.lower() in text for marker in MOQ_MARKERS)


def get_title_optimizer_settings(*, user_id: str | None = None) -> TitleOptimizerSettings:
    settings = get_ai_stage_settings("variant_translation", user_id=user_id)
    return TitleOptimizerSettings(
        api_key=clean_text(settings.get("api_key")),
        base_url=clean_text(settings.get("base_url")).rstrip("/"),
        text_model=clean_text(settings.get("model")) or "gpt-5.5",
        channel_id=clean_text(settings.get("channel_id")),
    )


def record_title_optimizer_usage(
    settings: TitleOptimizerSettings,
    *,
    user_id: str | None,
    stage: str,
    status: str,
    error_message: str | None = None,
) -> None:
    record_api_usage_safe(
        provider="openai-compatible",
        api_type="chat",
        stage=stage,
        model=settings.text_model,
        user_id=user_id,
        channel_id=settings.channel_id,
        status=status,
        error_message=error_message,
    )

def generate_titles_with_ai(
    record: dict[str, Any],
    fallback: dict[str, str],
    settings: TitleOptimizerSettings,
) -> dict[str, Any]:
    return request_text_json(
        api_url=build_api_url(settings.base_url, "/chat/completions"),
        api_key=settings.api_key,
        model=settings.text_model,
        instruction=json.dumps(
            {
                "role": (
                    "You are a Temu marketplace listing title optimizer. "
                    "Follow the user's listing optimization rules. Return strict JSON only. "
                    "Do not include markdown. Do not invent brands, platform names, certification claims, "
                    "medical claims, absolute guarantees, price or discount words."
                ),
                "listing_optimization_rules": load_listing_prompt(),
                "task": (
                    "Generate one optimized Chinese product title and one optimized English product title "
                    "for a Dianxiaomi TEMU semi-managed import template."
                ),
                "requirements": [
                    "title_cn must be Chinese.",
                    "title_en must be English and contain no Chinese characters.",
                    "Keep quantity or pack count when the source title clearly includes it.",
                    "Remove exact size specs when they are not core SKU identity.",
                    "Use differentiated SEO wording so repeated products do not share identical titles.",
                    "Keep the meaning faithful to the source product and SKU/bundle structure.",
                    "Avoid sensitive words, brand names, platform names, exaggerated claims, and medical claims.",
                ],
                "source": build_title_source_payload(record, fallback),
                "required_json": {
                    "title_cn": "optimized Chinese title",
                    "title_en": "optimized English title, 160-180 English characters preferred",
                },
            },
            ensure_ascii=False,
        ),
        temperature=0.1,
    )


def build_title_source_payload(record: dict[str, Any], fallback: dict[str, str]) -> dict[str, Any]:
    sku_entries = [sku for sku in record.get("skuEntries") or [] if isinstance(sku, dict)]
    source_links = [source for source in record.get("sourceLinks") or [] if isinstance(source, dict)]
    return {
        "product_id": record.get("productId") or record.get("id"),
        "current_title_cn": fallback["title_cn"],
        "current_title_en": fallback["title_en"],
        "source_product_url": record.get("productSourceUrl"),
        "source_links": [
            {
                "title": source.get("title"),
                "shop_name": source.get("shopName"),
                "product_url": source.get("productUrl"),
            }
            for source in source_links[:5]
        ],
        "sku_entries": [
            {
                "name": sku.get("name"),
                "component_skus": [
                    {
                        "spec_text": component.get("specText"),
                        "option_text": component.get("optionText"),
                        "raw_specs": component.get("rawSpecs"),
                    }
                    for component in sku.get("componentSkus") or []
                    if isinstance(component, dict)
                ][:6],
                "source_sku_links": [
                    {
                        "spec_text": source_sku.get("specText"),
                        "option_text": source_sku.get("optionText"),
                    }
                    for source_sku in sku.get("sourceSkuLinks") or []
                    if isinstance(source_sku, dict)
                ][:6],
            }
            for sku in sku_entries[:30]
        ],
    }


def build_fallback_titles(fallback_title_cn: str, fallback_title_en: str) -> dict[str, str]:
    safe_cn, _ = sanitize_marketplace_text(clean_text(fallback_title_cn) or "未命名商品")
    safe_en, _ = sanitize_marketplace_text(clean_text(fallback_title_en) or "Assorted Product")
    return {
        "title_cn": trim_title(safe_cn or "未命名商品", 180),
        "title_en": trim_title(remove_cjk(safe_en) or "Assorted Product", 200),
        "source": "fallback",
    }


def normalize_generated_titles(raw: dict[str, Any], fallback: dict[str, str]) -> dict[str, str]:
    title_cn, _ = sanitize_marketplace_text(clean_text(raw.get("title_cn")))
    title_en, _ = sanitize_marketplace_text(clean_text(raw.get("title_en")))
    title_cn = trim_title(title_cn, 180)
    title_en = trim_title(remove_cjk(title_en), 200)
    if not title_cn or not contains_cjk(title_cn):
        title_cn = fallback["title_cn"]
    if not title_en:
        title_en = fallback["title_en"]
    return {
        "title_cn": title_cn,
        "title_en": title_en,
        "source": "ai",
    }


def load_listing_prompt() -> str:
    path = Path(os.getenv("LISTING_OPTIMIZATION_PROMPT_PATH", "") or PROMPT_PATH)
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "Use the structure: quantity + core search keyword + product words + 3-5 feature keywords "
            "+ use scenario + long-tail phrase. Generate Chinese and English ecommerce listing titles."
        )


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def trim_title(value: str, max_length: int) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip(" ,，、-")


def contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def remove_cjk(value: str) -> str:
    text = re.sub(r"[\u4e00-\u9fff]+", " ", value or "")
    return re.sub(r"\s+", " ", text).strip(" ,，、-")
