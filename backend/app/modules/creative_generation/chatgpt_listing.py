from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.admin_config.postgres_store import (
    assert_user_api_usage_allowed,
    get_app_setting_value,
    record_api_usage_safe,
)
from app.modules.ai_gateway import scheduler as ai_gateway_scheduler
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

IMAGE_TEXT_COPY_POLICY = (
    "On-image text policy: short on-image text is allowed when it helps explain function, but it must be safe and minimal. "
    "Use 0-4 small English callout labels, each 1-4 words, such as 'Easy Carry', 'Compact Size', 'Soft Touch', "
    "'Organized Storage', or 'Gift Ready'. Do not use platform names, brand names, IP names, medical/health claims, "
    "certification words, absolute marketing words, price/discount words, guarantee words, or any sensitive terms. "
    "Do not add long paragraphs, badges, fake certifications, star ratings, urgency banners, QR codes, watermarks, "
    "or UI-like sale labels. If no safe text is needed, use no on-image text."
)

ANALYZE_THEN_EXECUTE_PROMPT = (
    "Workflow is mandatory: first analyze, then execute. "
    "Analysis phase: identify the real product category, visible components, SKU/bundle contents, reusable visual style, "
    "safe short on-image text options, sensitive text risks, watermark/brand/medical claims, and which elements must stay consistent across all generated images. "
    "Execution phase: generate only the requested target image role, keeping all required components accurate and reusable "
    "with the same lighting, background, camera angle family, color temperature, and marketplace style."
)

REUSE_STRATEGY_PROMPT = (
    "Reuse strategy: treat this product image set as one reusable visual system. "
    "The 8 product images are shared listing assets, not independent redesigns. "
    "When a product can be sold with multiple other products, keep the base product appearance reusable, "
    "and only change the bundle composition needed by the target image."
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
    channel_id: str = ""
    credential_id: str = ""
    credential_name: str = ""
    gateway_stage: str = ""
    gateway_candidate: dict[str, Any] = field(default_factory=dict)


def generate_listing_package(record: dict[str, Any], *, generate_images: bool = True, user_id: str | None = None) -> dict[str, Any]:
    title_settings = get_openai_settings("title", user_id=user_id)
    image_settings = get_openai_settings("image", user_id=user_id)
    safe_title_cn, blocked_terms = sanitize_marketplace_text(record.get("productTitle"))
    safe_title_en = generate_safe_english_title(
        record,
        safe_title_cn,
        title_settings if title_settings.api_key else None,
        user_id=user_id,
    )
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

    if not image_settings.api_key:
        raise CreativeGenerationError("API 中枢没有可用生图渠道，请先在 API 中枢配置可用 Key。")

    generated_images = []
    product_id = clean_key_part(record.get("productId") or record.get("id") or "product")
    for index, plan in enumerate(image_plan, start=1):
        prompt = build_image_prompt(record, safe_title_en, plan)
        image_bytes = generate_image_bytes(prompt, image_settings, user_id=user_id)
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


def get_openai_settings(stage: str | None = None, *, user_id: str | None = None) -> OpenAISettings:
    _ = user_id
    stage_key = clean_text(stage).lower().replace("-", "_")
    gateway_candidates = ai_gateway_scheduler.resolve_candidates(stage_key)
    if not gateway_candidates:
        raise CreativeGenerationError(f"API 中枢没有可用渠道：{stage_key}")
    candidate = gateway_candidates[0]
    model = str(candidate.get("model") or "").strip()
    model_type = str(candidate.get("modelType") or "").strip()
    return OpenAISettings(
        api_key=str(candidate.get("apiKey") or "").strip(),
        base_url=str(candidate.get("baseUrl") or "").strip().rstrip("/"),
        text_model=model or "gpt-5.5",
        image_model=model if model_type == "image" else "gpt-image-2-1k",
        image_quality=get_runtime_setting("OPENAI_IMAGE_QUALITY", "medium").strip() or "medium",
        channel_id=str(candidate.get("channelId") or ""),
        credential_id=str(candidate.get("credentialId") or ""),
        credential_name=str(candidate.get("credentialName") or candidate.get("credentialId") or ""),
        gateway_stage=stage_key,
        gateway_candidate=dict(candidate),
    )


def get_runtime_setting(key: str, default: str = "") -> str:
    saved_value = get_app_setting_value(key, "")
    if saved_value != "":
        return saved_value
    return os.getenv(key, default).strip()


def generate_safe_english_title(
    record: dict[str, Any],
    safe_title_cn: str,
    settings: OpenAISettings | None,
    *,
    user_id: str | None = None,
) -> str:
    fallback = normalize_english_title(record.get("productTitleEn"), safe_title_cn or record.get("productTitle", ""))
    fallback, _ = sanitize_marketplace_text(fallback)
    if settings is None:
        return trim_title(fallback)

    assert_user_api_usage_allowed(user_id)
    candidate = settings.gateway_candidate if settings.gateway_stage and settings.credential_id else None
    started = time.monotonic()
    if candidate:
        ai_gateway_scheduler.begin_attempt(candidate)
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
        record_api_usage_safe(
            provider="openai-compatible",
            api_type="chat",
            stage="title",
            model=settings.text_model,
            user_id=user_id,
            channel_id=settings.channel_id,
            credential_id=settings.credential_id,
            credential_name=settings.credential_name,
            status="success",
        )
        if candidate:
            ai_gateway_scheduler.finish_attempt(
                candidate,
                success=True,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    except Exception as exc:
        record_api_usage_safe(
            provider="openai-compatible",
            api_type="chat",
            stage="title",
            model=settings.text_model,
            user_id=user_id,
            channel_id=settings.channel_id,
            credential_id=settings.credential_id,
            credential_name=settings.credential_name,
            status="failed",
            error_message=str(exc),
        )
        if candidate:
            ai_gateway_scheduler.finish_attempt(
                candidate,
                success=False,
                error_message=str(exc),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
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
    listing_structure = describe_listing_structure(record)
    component_summary = summarize_bundle_components(record)
    sku_summary = summarize_sku_entries(record)
    prompt = (
        f"{ANALYZE_THEN_EXECUTE_PROMPT} "
        f"{REUSE_STRATEGY_PROMPT} "
        f"Create a square ecommerce listing image for: {safe_title_en}. "
        f"This image belongs to the 8-image product set: hero main image, effect image, person usage scene, room/everyday scene, "
        f"material/detail image, size/structure image, comparison image, and package/variant lineup image. "
        f"Current target image role: {plan['label']} ({plan['promptFocus']}). "
        f"Listing structure: {listing_structure}. "
        f"Relevant SKU/options: {sku_names or 'assorted product options'}. "
        f"SKU structure: {sku_summary}. "
        f"Bundle/components that may need to appear together: {component_summary}. "
        f"Source product context: {source_titles or safe_title_en}. "
        f"{TEMU_STYLE_PROMPT} "
        f"{IMAGE_TEXT_COPY_POLICY} "
        "For bundle or combo listings, the hero/main image and combo SKU images must show all products included in the purchase "
        "in the same image, arranged clearly without merging them into one object. "
        "Use realistic product photography style. Any text placed inside the image must be neutral, factual, short, and safe."
    )
    sanitized_prompt, _ = sanitize_marketplace_text(prompt)
    return sanitized_prompt


def build_sku_image_prompt(record: dict[str, Any], safe_title_en: str, sku_entry: dict[str, Any], sku_index: int) -> str:
    sku_name = clean_text(sku_entry.get("name")) or f"SKU {sku_index}"
    sku_kind = clean_text(sku_entry.get("kind")) or "single"
    listing_structure = describe_listing_structure(record)
    all_sku_summary = summarize_sku_entries(record)
    component_summary = summarize_single_sku_components(sku_entry)
    source_summary = summarize_single_sku_sources(sku_entry)
    prompt = (
        f"{ANALYZE_THEN_EXECUTE_PROMPT} "
        f"{REUSE_STRATEGY_PROMPT} "
        f"Create one square ecommerce SKU option image for the listing: {safe_title_en}. "
        f"Target SKU #{sku_index}: {sku_name}. SKU type: {sku_kind}. "
        f"This is a SKU image, so the generated image must faithfully show only what the buyer receives for this SKU option. "
        f"If this SKU is a bundle/combo, show every included component together in the same image, clearly separated and not merged. "
        f"If this SKU is a single option, keep the option's color, style, material, size cues, and visible structure accurate. "
        f"Target SKU components: {component_summary}. "
        f"Source SKU details: {source_summary}. "
        f"Full listing structure: {listing_structure}. "
        f"All listing SKU context: {all_sku_summary}. "
        f"{TEMU_STYLE_PROMPT} "
        f"{IMAGE_TEXT_COPY_POLICY} "
        "Use the same reusable visual system as the product's main 8-image set: consistent lighting, background, camera angle family, "
        "scale, color temperature, and clean Temu marketplace style. Any SKU image text must describe only the exact SKU contents "
        "with safe, short, neutral wording."
    )
    sanitized_prompt, _ = sanitize_marketplace_text(prompt)
    return sanitized_prompt


def describe_listing_structure(record: dict[str, Any]) -> str:
    sku_entries = [sku for sku in record.get("skuEntries") or [] if isinstance(sku, dict)]
    combo_count = sum(1 for sku in sku_entries if sku.get("kind") == "combo" or len(sku.get("componentSkus") or []) > 1)
    source_count = len([source for source in record.get("sourceLinks") or [] if isinstance(source, dict)])
    if combo_count and len(sku_entries) == combo_count:
        return f"bundle listing with {combo_count} combo SKU(s) from {source_count or 'multiple'} source product(s)"
    if combo_count:
        return f"family listing with {len(sku_entries)} SKU(s), including {combo_count} bundle/combo SKU(s)"
    if len(sku_entries) > 1:
        return f"multi-SKU listing with {len(sku_entries)} single SKU option(s)"
    return "single-SKU or simple listing"


def summarize_sku_entries(record: dict[str, Any]) -> str:
    summaries: list[str] = []
    for sku in (record.get("skuEntries") or [])[:12]:
        if not isinstance(sku, dict):
            continue
        name = clean_text(sku.get("name")) or "Unnamed SKU"
        kind = clean_text(sku.get("kind")) or "single"
        component_count = len(sku.get("componentSkus") or [])
        if component_count > 1:
            summaries.append(f"{name} ({kind}, {component_count} components)")
        else:
            summaries.append(f"{name} ({kind})")
    return "; ".join(summaries) or "No explicit SKU entries"


def summarize_bundle_components(record: dict[str, Any]) -> str:
    bundle_summaries: list[str] = []
    for sku in (record.get("skuEntries") or [])[:12]:
        if not isinstance(sku, dict):
            continue
        components = [component for component in sku.get("componentSkus") or [] if isinstance(component, dict)]
        if len(components) <= 1:
            continue
        component_text = " + ".join(
            clean_text(component.get("name"))
            or clean_text(component.get("specText"))
            or clean_text(component.get("sourceTitle"))
            or "component"
            for component in components[:6]
        )
        bundle_summaries.append(f"{clean_text(sku.get('name')) or 'Combo SKU'} = {component_text}")
    return "; ".join(bundle_summaries) or "No combo components; reuse the base product style across the 8-image set"


def summarize_single_sku_components(sku_entry: dict[str, Any]) -> str:
    components = [component for component in sku_entry.get("componentSkus") or [] if isinstance(component, dict)]
    if not components:
        return clean_text(sku_entry.get("name")) or "No explicit component list; use the target SKU option itself"

    summaries: list[str] = []
    for component in components[:8]:
        name = clean_text(component.get("name")) or clean_text(component.get("specText")) or "component"
        source_title = clean_text(component.get("sourceTitle"))
        raw_specs = component.get("rawSpecs") if isinstance(component.get("rawSpecs"), dict) else {}
        spec_text = clean_text(component.get("specText"))
        option_text = clean_text(component.get("optionText"))
        spec_pairs = ", ".join(
            f"{clean_text(key)}={clean_text(value)}"
            for key, value in list(raw_specs.items())[:6]
            if clean_text(key) and clean_text(value)
        )
        detail = first_non_empty(spec_pairs, spec_text, option_text, source_title)
        summaries.append(f"{name} ({detail})" if detail else name)
    return " + ".join(summaries)


def summarize_single_sku_sources(sku_entry: dict[str, Any]) -> str:
    links = [link for link in sku_entry.get("sourceSkuLinks") or [] if isinstance(link, dict)]
    if not links:
        return "No explicit source SKU links"

    summaries: list[str] = []
    for link in links[:8]:
        source_title = clean_text(link.get("sourceTitle")) or "source product"
        spec_text = clean_text(link.get("specText"))
        option_text = clean_text(link.get("optionText"))
        summaries.append(f"{source_title}: {first_non_empty(spec_text, option_text, 'unspecified option')}")
    return "; ".join(summaries)


def generate_image_bytes(prompt: str, settings: OpenAISettings, *, user_id: str | None = None) -> bytes:
    assert_user_api_usage_allowed(user_id)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise CreativeGenerationError("缺少 Python 依赖 openai；请先执行 pip install -r backend/requirements.txt") from exc

    if settings.gateway_stage:
        attempt_limit = ai_gateway_scheduler.resolve_attempt_limit(settings.gateway_stage)
        excluded_credential_ids: set[str] = set()
        last_error: BaseException | None = None
        for _attempt in range(attempt_limit):
            candidate = ai_gateway_scheduler.acquire_candidate(
                settings.gateway_stage,
                task_type="image",
                excluded_credential_ids=excluded_credential_ids,
            )
            if not candidate:
                break
            excluded_credential_ids.add(str(candidate.get("credentialId") or ""))
            trial_settings = replace_settings_from_gateway_candidate(settings, candidate)
            started = time.monotonic()
            try:
                image_bytes = generate_image_bytes_once(prompt, trial_settings)
                ai_gateway_scheduler.finish_attempt(
                    candidate,
                    success=True,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                record_api_usage_safe(
                    provider="openai-compatible",
                    api_type="image",
                    stage="image",
                    model=trial_settings.image_model,
                    user_id=user_id,
                    channel_id=trial_settings.channel_id,
                    credential_id=trial_settings.credential_id,
                    credential_name=trial_settings.credential_name,
                    status="success",
                )
                return image_bytes
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                ai_gateway_scheduler.finish_attempt(
                    candidate,
                    success=False,
                    error_message=str(exc),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                record_api_usage_safe(
                    provider="openai-compatible",
                    api_type="image",
                    stage="image",
                    model=trial_settings.image_model,
                    user_id=user_id,
                    channel_id=trial_settings.channel_id,
                    credential_id=trial_settings.credential_id,
                    credential_name=trial_settings.credential_name,
                    status="failed",
                    error_message=str(exc),
                )
                continue
        if last_error is None:
            raise CreativeGenerationError(f"API 中枢没有可用生图渠道：{settings.gateway_stage}")
        raise CreativeGenerationError(f"所有 API 中枢生图候选都失败：{last_error}") from last_error

    try:
        image_bytes = generate_image_bytes_once(prompt, settings)
        record_api_usage_safe(
            provider="openai-compatible",
            api_type="image",
            stage="image",
            model=settings.image_model,
            user_id=user_id,
            channel_id=settings.channel_id,
            credential_id=settings.credential_id,
            credential_name=settings.credential_name,
            status="success",
        )
    except Exception as exc:
        record_api_usage_safe(
            provider="openai-compatible",
            api_type="image",
            stage="image",
            model=settings.image_model,
            user_id=user_id,
            channel_id=settings.channel_id,
            credential_id=settings.credential_id,
            credential_name=settings.credential_name,
            status="failed",
            error_message=str(exc),
        )
        raise
    return image_bytes


def generate_image_bytes_once(prompt: str, settings: OpenAISettings) -> bytes:
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


def replace_settings_from_gateway_candidate(settings: OpenAISettings, candidate: dict[str, Any]) -> OpenAISettings:
    model = str(candidate.get("model") or "").strip()
    return OpenAISettings(
        api_key=str(candidate.get("apiKey") or "").strip(),
        base_url=str(candidate.get("baseUrl") or settings.base_url).strip().rstrip("/"),
        text_model=model or settings.text_model,
        image_model=model if str(candidate.get("modelType") or "") == "image" else settings.image_model,
        image_quality=settings.image_quality,
        channel_id=str(candidate.get("channelId") or ""),
        credential_id=str(candidate.get("credentialId") or ""),
        credential_name=str(candidate.get("credentialName") or candidate.get("credentialId") or ""),
        gateway_stage=str(candidate.get("stage") or settings.gateway_stage),
        gateway_candidate=dict(candidate),
    )


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


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
