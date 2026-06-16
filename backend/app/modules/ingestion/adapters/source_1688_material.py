from __future__ import annotations

from typing import Any

from app.core.database import create_sourcing_material_1688
from app.modules.sourcing_1688.link_importer import Link1688ImportError, extract_offer_id, normalize_1688_url


def normalize_record(record: dict[str, Any], *, context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    product_url = first_text(
        record.get("product_url"),
        record.get("source_url"),
        record.get("url"),
        record.get("link"),
        record.get("href"),
    )
    if not product_url:
        raise ValueError("缺少 1688 商品链接")
    try:
        product_url = normalize_1688_url(product_url)
    except Link1688ImportError as exc:
        raise ValueError(str(exc)) from exc

    title = first_text(record.get("title"), record.get("product_title"), record.get("name"), record.get("subject"))
    if not title:
        raise ValueError("缺少 1688 商品标题")

    offer_id = first_text(record.get("offer_id"), record.get("offerId"), record.get("source_entity_id"))
    if not offer_id:
        offer_id = extract_offer_id(product_url) or ""

    return {
        "offer_id": offer_id or None,
        "product_url": product_url,
        "title": title,
        "main_image_url": first_text(
            record.get("main_image_url"),
            record.get("mainImageUrl"),
            record.get("image_url"),
            record.get("imageUrl"),
        )
        or None,
        "price": to_float(record.get("price")),
        "price_range": first_text(record.get("price_range"), record.get("priceRange")) or None,
        "moq": to_int(record.get("moq"), record.get("min_order_quantity"), record.get("minimumOrderQuantity")),
        "shop_name": first_text(record.get("shop_name"), record.get("shopName"), record.get("seller_name")) or None,
        "shop_url": first_text(record.get("shop_url"), record.get("shopUrl"), record.get("seller_url")) or None,
        "sku_list": record.get("sku_list") or record.get("skuList") or [],
        "raw_data": {
            **record,
            "_ingest_context": context,
        },
        "captured_at": first_text(record.get("captured_at"), record.get("capturedAt"), context.get("collected_at")) or None,
    }


def persist_record(material: dict[str, Any]) -> dict[str, Any]:
    return create_sourcing_material_1688(material)


def source_entity_id(material: dict[str, Any]) -> str:
    return first_text(material.get("offer_id"), material.get("product_url"))


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    for prefix in ("¥", "$", "￥", "CN¥"):
        text = text.replace(prefix, "")
    try:
        return float(text)
    except ValueError:
        return None


def to_int(*values: Any) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        if isinstance(value, int):
            return value
        text = str(value).strip().replace(",", "")
        try:
            return int(float(text))
        except ValueError:
            continue
    return None

