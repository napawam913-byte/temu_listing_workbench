from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from app.core.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_IMAGE_MODEL, OPENAI_IMAGE_QUALITY, OPENAI_TEXT_MODEL
from app.modules.creative_generation.safety import find_sensitive_terms, sanitize_marketplace_text
from app.modules.exports.dianxiaomi_temu import normalize_english_title
from app.modules.image_storage.aliyun_oss import ImageStorageError, upload_image_bytes

IMAGE_COUNT = 8
IMAGE_SIZE = "1024x1024"

IMAGE_ROLES = [
    ("01-hero-main", "主图", "clean hero product image, one clear product focus, bright marketplace style"),
    ("02-effect", "效果图", "benefit/effect visual, show practical use result without exaggerated claims"),
    ("03-person-use", "人物场景使用图", "generic adult lifestyle usage scene, natural hands or torso only, no celebrity, no minors"),
    ("04-room-scene", "场景使用图", "realistic home or everyday usage scene matching the product category"),
    ("05-detail-material", "细节图", "macro detail image showing material, texture, finish, edges and craftsmanship"),
    ("06-detail-size", "尺寸/结构图", "clean detail layout showing components and scale with minimal neutral graphic cues"),
    ("07-comparison", "对比图", "neutral comparison layout showing feature contrast without superiority or medical claims"),
    ("08-package-lineup", "套装/变体图", "complete package or variant lineup image, organized and easy to understand"),
]

TEMU_STYLE_PROMPT = (
    "Temu marketplace compatible ecommerce image style: bright clean lighting, high clarity, simple commercial composition, "
    "soft neutral background, realistic product texture, no watermark, no platform logo, no brand logo, no celebrity, "
    "no copyrighted character, no medical claim, no exaggerated before-after result, no misleading certification badge. "
    "Keep the product recognizable and faithful to source SKU details."
)


class CreativeGenerationError(Exception):
    pass


@dataclass
class OpenAISettings:
    api_key: str
    base_url: str
    text_model: str
    image_model: str
    image_quality: str


def generate_listing_package(record: dict[str, Any], *, generate_images: bool = True) -> dict[str, Any]:
    settings = get_openai_settings()
    safe_title_cn, blocked_terms = sanitize_marketplace_text(record.get("productTitle"))
    safe_title_en = generate_safe_english_title(record, safe_title_cn, settings if settings.api_key else None)
    title_terms = find_sensitive_terms(safe_title_en)
    if title_terms:
        safe_title_en, _ = sanitize_marketplace_text(safe_title_en)
        blocked_terms = [*blocked_terms, *[term for term in title_terms if term not in blocked_terms]]

    image_plan = build_image_plan(record, safe_title_en)
    updated_record = clone_json(record)
    updated_record["productTitle"] = safe_title_cn or record.get("productTitle") or "Untitled Product"
    updated_record["productTitleEn"] = safe_title_en
    updated_record.setdefault("styleProfile", build_style_profile(record))

    if not generate_images:
        return {
            "status": "planned",
            "safeTitleCn": updated_record["productTitle"],
            "safeTitleEn": safe_title_en,
            "blockedTerms": sorted(set(blocked_terms)),
            "imagePlan": image_plan,
            "generatedImages": [],
            "record": updated_record,
        }

    if not settings.api_key:
        raise CreativeGenerationError("缺少 OPENAI_API_KEY，无法调用 ChatGPT 生图。已支持生成规划，请先配置 OpenAI API Key。")

    generated_images = []
    product_id = clean_key_part(record.get("productId") or record.get("id") or "product")
    for index, plan in enumerate(image_plan, start=1):
        prompt = build_image_prompt(record, safe_title_en, plan)
        image_bytes = generate_image_bytes(prompt, settings)
        upload = upload_generated_image(image_bytes, product_id, plan["key"])
        generated_images.append(
            {
                "id": f"{record.get('id', product_id)}-generated-main-{index}",
                "role": "product-main" if index == 1 else "product-material",
                "kind": plan["kind"],
                "label": plan["label"],
                "prompt": prompt,
                "editedCloudUrl": upload["url"],
                "displayCloudUrl": upload["url"],
                "storageKey": upload["storageKey"],
            }
        )

    if generated_images:
        first_image = generated_images[0]
        main_image = updated_record.get("mainImage") or {}
        updated_record["mainImage"] = {
            **main_image,
            "id": main_image.get("id") or f"{record.get('id', product_id)}-main-image",
            "role": "product-main",
            "editedCloudUrl": first_image["editedCloudUrl"],
            "displayCloudUrl": first_image["displayCloudUrl"],
            "storageKey": first_image["storageKey"],
            "alt": safe_title_en,
        }
        updated_record["productMaterialImages"] = [
            {
                "id": image["id"],
                "role": image["role"],
                "editedCloudUrl": image["editedCloudUrl"],
                "displayCloudUrl": image["displayCloudUrl"],
                "storageKey": image["storageKey"],
                "alt": f"{safe_title_en} {image['label']}",
            }
            for image in generated_images
        ]

    return {
        "status": "generated",
        "safeTitleCn": updated_record["productTitle"],
        "safeTitleEn": safe_title_en,
        "blockedTerms": sorted(set(blocked_terms)),
        "imagePlan": image_plan,
        "generatedImages": generated_images,
        "record": updated_record,
    }


def get_openai_settings() -> OpenAISettings:
    return OpenAISettings(
        api_key=os.getenv("OPENAI_API_KEY", OPENAI_API_KEY).strip(),
        base_url=os.getenv("OPENAI_BASE_URL", OPENAI_BASE_URL).strip().rstrip("/"),
        text_model=os.getenv("OPENAI_TEXT_MODEL", OPENAI_TEXT_MODEL).strip() or "gpt-4.1-mini",
        image_model=os.getenv("OPENAI_IMAGE_MODEL", OPENAI_IMAGE_MODEL).strip() or "gpt-image-1",
        image_quality=os.getenv("OPENAI_IMAGE_QUALITY", OPENAI_IMAGE_QUALITY).strip() or "medium",
    )


def generate_safe_english_title(record: dict[str, Any], safe_title_cn: str, settings: OpenAISettings | None) -> str:
    fallback = normalize_english_title(record.get("productTitleEn"), safe_title_cn or record.get("productTitle", ""))
    fallback, _ = sanitize_marketplace_text(fallback)
    if settings is None:
        return trim_title(fallback)

    try:
        from openai import OpenAI

        client = build_openai_client(settings)
        response = client.responses.create(
            model=settings.text_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You write safe marketplace listing titles. Return strict JSON only. "
                        "No brand names, no platform names, no medical/health claims, no superlatives, no certifications."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source_title_cn": safe_title_cn,
                            "fallback_title_en": fallback,
                            "sku_names": [sku.get("name") for sku in record.get("skuEntries") or []],
                            "required_json": {"title_en": "80-140 char safe English product title"},
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        text = response.output_text
        parsed = json.loads(text)
        title = parsed.get("title_en") or fallback
    except Exception:
        title = fallback

    safe_title, _ = sanitize_marketplace_text(title)
    return trim_title(safe_title or fallback)


def build_style_profile(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"{record.get('id', record.get('productId', 'record'))}-temu-style-profile",
        "name": "Temu bright marketplace style",
        "provider": "chatgpt",
        "prompt": TEMU_STYLE_PROMPT,
        "negativePrompt": "logos, watermark, celebrity, copyrighted character, medical claim, exaggerated result, messy background",
        "referenceImageAssetId": (record.get("mainImage") or {}).get("id"),
    }


def build_image_plan(record: dict[str, Any], safe_title_en: str) -> list[dict[str, str]]:
    product_id = clean_key_part(record.get("productId") or record.get("id") or "product")
    return [
        {
            "index": str(index),
            "key": f"products/{product_id}/main/{kind}",
            "kind": kind,
            "label": label,
            "promptFocus": focus,
            "title": safe_title_en,
        }
        for index, (kind, label, focus) in enumerate(IMAGE_ROLES, start=1)
    ]


def build_image_prompt(record: dict[str, Any], safe_title_en: str, plan: dict[str, str]) -> str:
    sku_names = ", ".join(
        clean_text(sku.get("name")) for sku in (record.get("skuEntries") or [])[:8] if clean_text(sku.get("name"))
    )
    source_titles = ", ".join(
        clean_text(source.get("title")) for source in (record.get("sourceLinks") or [])[:3] if clean_text(source.get("title"))
    )
    prompt = (
        f"Create a square ecommerce listing image for: {safe_title_en}. "
        f"Image role: {plan['label']} ({plan['promptFocus']}). "
        f"Relevant SKU/options: {sku_names or 'assorted product options'}. "
        f"Source product context: {source_titles or safe_title_en}. "
        f"{TEMU_STYLE_PROMPT} "
        "Use realistic product photography style. Avoid readable brand text. If text is necessary, use simple neutral short labels only."
    )
    sanitized_prompt, _ = sanitize_marketplace_text(prompt)
    return sanitized_prompt


def generate_image_bytes(prompt: str, settings: OpenAISettings) -> bytes:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise CreativeGenerationError("缺少 Python 依赖 openai；请先执行 pip install -r backend/requirements.txt") from exc

    client = build_openai_client(settings)
    response = client.images.generate(
        model=settings.image_model,
        prompt=prompt,
        size=IMAGE_SIZE,
        quality=settings.image_quality,
        n=1,
    )
    b64_json = response.data[0].b64_json
    if not b64_json:
        raise CreativeGenerationError("OpenAI 图片接口没有返回图片数据")
    return base64.b64decode(b64_json)


def build_openai_client(settings: OpenAISettings):
    from openai import OpenAI

    kwargs: dict[str, str] = {"api_key": settings.api_key}
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    return OpenAI(**kwargs)


def upload_generated_image(image_bytes: bytes, product_id: str, key_hint: str) -> dict[str, str]:
    try:
        return upload_image_bytes(image_bytes, "image/png", key_hint)
    except ImageStorageError as exc:
        raise CreativeGenerationError(str(exc)) from exc


def clone_json(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def trim_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value[:140].strip(" -_/|,.;:")


def clean_key_part(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", clean_text(value)).strip("-")
    return text[:80] or "product"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
