from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import BACKEND_DIR, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_TEXT_MODEL
from app.core.database import get_app_setting_value
from app.modules.creative_generation.safety import sanitize_marketplace_text


PROMPT_PATH = BACKEND_DIR / "config" / "prompts" / "listing_optimization.md"
TITLE_CACHE_SCHEMA = "listing-title-v1"
VARIANT_VALUE_CACHE_SCHEMA = "variant-value-v1"
_TITLE_CACHE: dict[str, dict[str, str]] = {}
_VARIANT_VALUE_CACHE: dict[str, str] = {}

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


def optimize_listing_titles(
    record: dict[str, Any],
    *,
    fallback_title_cn: str,
    fallback_title_en: str,
) -> dict[str, str]:
    fallback = build_fallback_titles(fallback_title_cn, fallback_title_en)
    settings = get_title_optimizer_settings()
    cache_key = build_title_cache_key(record, fallback)
    cached = _TITLE_CACHE.get(cache_key)
    if cached:
        return cached

    if not settings.api_key:
        _TITLE_CACHE[cache_key] = fallback
        return fallback

    try:
        generated = generate_titles_with_ai(record, fallback, settings)
        result = normalize_generated_titles(generated, fallback)
    except Exception:
        result = fallback

    _TITLE_CACHE[cache_key] = result
    return result


def translate_variant_values_to_english(values: list[str]) -> dict[str, str]:
    unique_values = []
    for value in values:
        text = clean_text(value)
        if text and text not in unique_values:
            unique_values.append(text)

    result: dict[str, str] = {}
    missing: list[str] = []
    for value in unique_values:
        cached = _VARIANT_VALUE_CACHE.get(value)
        if cached:
            result[value] = cached
            continue
        if not contains_cjk(value):
            translated = normalize_ascii_variant_value(value)
            _VARIANT_VALUE_CACHE[value] = translated
            result[value] = translated
            continue
        missing.append(value)

    settings = get_title_optimizer_settings()
    ai_translations: dict[str, str] = {}
    if missing and settings.api_key:
        try:
            ai_translations = generate_variant_values_with_ai(missing, settings)
        except Exception:
            ai_translations = {}

    for value in missing:
        fallback = fallback_translate_variant_value(value)
        translated = normalize_variant_value_translation(ai_translations.get(value), fallback)
        _VARIANT_VALUE_CACHE[value] = translated
        result[value] = translated

    return result


def generate_variant_values_with_ai(values: list[str], settings: TitleOptimizerSettings) -> dict[str, str]:
    from openai import OpenAI

    kwargs: dict[str, str] = {"api_key": settings.api_key}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    client = OpenAI(**kwargs)

    response = client.responses.create(
        model=settings.text_model,
        input=[
            {
                "role": "system",
                "content": (
                    "You translate Temu SKU variant option values for a Dianxiaomi import template. "
                    "Return strict JSON only. Keep values concise, English-only, and faithful. "
                    "Preserve letters, numbers, model codes, quantities, and plus signs. "
                    "Do not invent brands, platform names, claims, discounts, certifications, or marketing hype."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Translate these SKU variant values into concise English option values.",
                        "requirements": [
                            "Output must contain no Chinese characters.",
                            "Translate each source independently.",
                            "If a source is a combo like A+B, preserve the plus structure.",
                            "If a source contains a minimum order quantity, express it as MOQ.",
                            "If unsure, use a neutral value like Custom Option or Default Option.",
                        ],
                        "source_values": values,
                        "required_json": {
                            "values": [
                                {"source": "original value", "value_en": "English variant value"}
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    raw = json.loads(response.output_text)
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
    safe_text = trim_title(remove_cjk(safe_text), 80)
    if safe_text:
        return safe_text
    return "" if allow_empty else "Custom Option"


def extract_quantity_count(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", value or "")
    return match.group(1) if match else ""


def has_moq_marker(value: str) -> bool:
    text = clean_text(value).lower()
    return any(marker.lower() in text for marker in MOQ_MARKERS)


def get_title_optimizer_settings() -> TitleOptimizerSettings:
    common_api_key = get_runtime_setting("OPENAI_API_KEY", OPENAI_API_KEY).strip()
    common_base_url = get_runtime_setting("OPENAI_BASE_URL", OPENAI_BASE_URL).strip().rstrip("/")
    common_text_model = get_runtime_setting("OPENAI_TEXT_MODEL", OPENAI_TEXT_MODEL).strip() or "gpt-5.5"
    return TitleOptimizerSettings(
        api_key=get_runtime_setting("OPENAI_TITLE_API_KEY", "").strip() or common_api_key,
        base_url=get_runtime_setting("OPENAI_TITLE_BASE_URL", "").strip().rstrip("/") or common_base_url,
        text_model=get_runtime_setting("OPENAI_TITLE_MODEL", "").strip() or common_text_model,
    )


def get_runtime_setting(key: str, default: str = "") -> str:
    saved_value = get_app_setting_value(key, "")
    if saved_value != "":
        return saved_value
    return os.getenv(key, default).strip()


def generate_titles_with_ai(
    record: dict[str, Any],
    fallback: dict[str, str],
    settings: TitleOptimizerSettings,
) -> dict[str, Any]:
    from openai import OpenAI

    kwargs: dict[str, str] = {"api_key": settings.api_key}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    client = OpenAI(**kwargs)

    response = client.responses.create(
        model=settings.text_model,
        input=[
            {
                "role": "system",
                "content": (
                    "You are a Temu marketplace listing title optimizer. "
                    "Follow the user's listing optimization rules. Return strict JSON only. "
                    "Do not include markdown. Do not invent brands, platform names, certification claims, "
                    "medical claims, absolute guarantees, price or discount words."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
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
                            "title_en": "optimized English title, 50-200 characters preferred",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    return json.loads(response.output_text)


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


def build_title_cache_key(record: dict[str, Any], fallback: dict[str, str]) -> str:
    payload = {
        "schema": TITLE_CACHE_SCHEMA,
        "product_id": record.get("productId") or record.get("id"),
        "title_cn": fallback["title_cn"],
        "title_en": fallback["title_en"],
        "sku_names": [sku.get("name") for sku in record.get("skuEntries") or [] if isinstance(sku, dict)],
        "source_titles": [
            source.get("title") for source in record.get("sourceLinks") or [] if isinstance(source, dict)
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


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
