from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from app.core.config import UPLOADS_DIR, ensure_runtime_dirs
from app.core.database import (
    PRODUCT_CATALOG_SCOPE_ADMIN,
    PRODUCT_CATALOG_SCOPE_POOL_ONLY,
    ensure_product_identity_index,
    get_connection,
    merge_product_catalog_scope,
    normalize_product_catalog_scope,
    refresh_product_category_matches,
    utc_now_text,
)
from app.modules.recommendation.keyword_index import replace_product_keyword_index
from app.modules.sourcing_1688.link_importer import Link1688ImportError, extract_offer_id, normalize_1688_url
from app.modules.yunqi.collector import (
    insert_new_product,
    json_dumps,
    normalize_category_fields,
    normalize_status,
    parse_list_value,
    parse_url_list,
    to_datetime_text,
    to_float,
    to_int,
    to_json_safe,
    to_product_id,
    to_text,
    update_existing_product,
)


def normalize_record(
    record: dict[str, Any],
    *,
    source: str,
    source_row_index: int,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    source = normalize_source(source)
    source_url = first_text(
        record.get("source_url"),
        record.get("sourceUrl"),
        record.get("product_url"),
        record.get("productUrl"),
        record.get("url"),
        record.get("link"),
        record.get("href"),
    )
    if source == "1688" and source_url:
        try:
            source_url = normalize_1688_url(source_url)
        except Link1688ImportError as exc:
            raise ValueError(str(exc)) from exc

    source_product_id = first_text(
        record.get("source_product_id"),
        record.get("sourceProductId"),
        record.get("product_id"),
        record.get("productId"),
        record.get("offer_id"),
        record.get("offerId"),
        record.get("id"),
    )
    if not source_product_id and source == "1688" and source_url:
        source_product_id = extract_offer_id(source_url) or ""
    if not source_product_id and source_url:
        source_product_id = uuid.uuid5(uuid.NAMESPACE_URL, source_url).hex[:16]
    source_product_id = to_product_id(source_product_id)
    if not source_product_id:
        raise ValueError("missing product identity")

    gallery_image_urls = parse_url_list(
        first_present(
            record.get("gallery_image_urls"),
            record.get("galleryImageUrls"),
            record.get("gallery_images"),
            record.get("galleryImages"),
            record.get("image_urls"),
            record.get("imageUrls"),
            record.get("images"),
            record.get("sku_images"),
            record.get("skuImages"),
        )
    )
    main_image_url = first_text(
        record.get("main_image_url"),
        record.get("mainImageUrl"),
        record.get("main_image"),
        record.get("mainImage"),
        record.get("image_url"),
        record.get("imageUrl"),
        record.get("image"),
    ) or (gallery_image_urls[0] if gallery_image_urls else "")
    if main_image_url and main_image_url not in gallery_image_urls:
        gallery_image_urls = [main_image_url, *gallery_image_urls]

    title_cn = first_text(record.get("title_cn"), record.get("titleCn"), record.get("title_zh"), record.get("name_cn"))
    title_en = first_text(record.get("title_en"), record.get("titleEn"), record.get("name_en"))
    title = first_text(
        record.get("title"),
        record.get("product_title"),
        record.get("productTitle"),
        record.get("name"),
        record.get("subject"),
        title_cn,
        title_en,
    )
    if not title:
        raise ValueError("missing product title")
    if source == "1688" and not title_cn:
        title_cn = title

    category_path, category_level1, category_level2 = normalize_category_fields(
        first_present(
            record.get("source_category_path"),
            record.get("category_path"),
            record.get("categoryPath"),
            record.get("category"),
            record.get("category_name"),
            record.get("categoryName"),
            record.get("front_category"),
            record.get("frontCategory"),
        )
    )
    raw_data = {**record}
    if context:
        raw_data["_ingest_context"] = context

    return {
        "id": make_product_id(source, source_product_id),
        "source_type": source,
        "source_product_id": source_product_id,
        "source_row_index": to_int(record.get("source_row_index")) or source_row_index,
        "title_cn": title_cn or None,
        "title_en": title_en or None,
        "title": title,
        "main_image_url": main_image_url or None,
        "gallery_image_urls": gallery_image_urls,
        "video_url": first_text(record.get("video_url"), record.get("videoUrl"), record.get("video")) or None,
        "source_url": source_url or None,
        "category_path": category_path,
        "category_level1": category_level1,
        "category_level2": category_level2,
        "tags": parse_list_value(first_present(record.get("tags"), record.get("tag_list"), record.get("labels")))
        or [source],
        "price_usd": to_float(first_present(record.get("price_usd"), record.get("priceUsd"), record.get("price"))),
        "gmv_usd": to_float(first_present(record.get("gmv_usd"), record.get("gmvUsd"), record.get("gmv"))),
        "weekly_sales": to_int(first_present(record.get("weekly_sales"), record.get("weeklySales"))),
        "monthly_sales": to_int(first_present(record.get("monthly_sales"), record.get("monthlySales"))),
        "review_count": to_int(first_present(record.get("review_count"), record.get("reviewCount"), record.get("reviews"))),
        "listing_time": to_datetime_text(
            first_present(record.get("listing_time"), record.get("listingTime"), record.get("captured_at"), record.get("capturedAt"))
        ),
        "status": normalize_status(record.get("status")),
        "catalog_scope": normalize_product_catalog_scope(context.get("catalog_scope")),
        "raw_data": to_json_safe(raw_data),
        "in_product_pool": True,
    }


def upsert_products(
    products: list[dict[str, Any]],
    *,
    batch_id: str,
    source_filename: str,
    saved_path: str | Path | None,
    total_rows: int,
    failed_count: int = 0,
    error_message: str | None = None,
    rebuild_keywords: bool = True,
) -> dict[str, Any]:
    ensure_runtime_dirs()
    safe_saved_path = Path(saved_path) if saved_path else UPLOADS_DIR / f"{batch_id}_ingest_product.json"
    prepared_products = [prepare_product_for_db(product) for product in dedupe_products(products)]
    now = utc_now_text()

    with get_connection() as conn:
        ensure_product_identity_index(conn)
        conn.execute(
            """
            INSERT INTO upload_batches (
                id, source_filename, saved_path, file_type, total_rows,
                imported_count, failed_count, status, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total_rows = excluded.total_rows,
                imported_count = excluded.imported_count,
                failed_count = excluded.failed_count,
                status = excluded.status,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            """,
            (
                batch_id,
                Path(source_filename).name,
                str(safe_saved_path),
                "ingest-product",
                total_rows,
                len(prepared_products),
                failed_count,
                "imported",
                error_message,
                now,
                now,
            ),
        )

        existing = load_existing_products(conn, prepared_products)
        created_count = 0
        updated_count = 0
        indexed_products: list[dict[str, Any]] = []
        changed_products: list[dict[str, Any]] = []

        for product in prepared_products:
            identity = product_identity(product)
            existing_row = existing.get(identity)
            should_preserve_admin_product = (
                existing_row is not None
                and normalize_product_catalog_scope(existing_row["catalog_scope"]) == PRODUCT_CATALOG_SCOPE_ADMIN
                and normalize_product_catalog_scope(product.get("catalog_scope")) == PRODUCT_CATALOG_SCOPE_POOL_ONLY
            )
            db_product = {
                **product,
                "id": existing_row["id"] if existing_row else product["id"],
                "upload_batch_id": batch_id,
                "catalog_scope": merge_product_catalog_scope(
                    existing_row["catalog_scope"] if existing_row else None,
                    product.get("catalog_scope"),
                )
                if existing_row
                else product.get("catalog_scope"),
                "gallery_image_urls_json": json_dumps(product.get("gallery_image_urls", [])),
                "tags_json": json_dumps(product.get("tags", [])),
                "raw_data_json": json_dumps(product.get("raw_data", {})),
                "created_at": existing_row["created_at"] if existing_row else now,
                "updated_at": now,
            }
            if should_preserve_admin_product:
                indexed_products.append({**product, "id": db_product["id"]})
                continue
            if existing_row:
                update_existing_product(conn, db_product)
                updated_count += 1
            else:
                insert_new_product(conn, db_product)
                created_count += 1
            changed_products.append({**product, "id": db_product["id"]})
            indexed_products.append({**product, "id": db_product["id"]})

        keyword_count = 0
        if rebuild_keywords and changed_products:
            keyword_count = replace_product_keyword_index(conn, changed_products, now=now)
        if changed_products:
            refresh_product_category_matches(conn, changed_products, now=now)

        target_rows = []
        for product in indexed_products:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product["id"],)).fetchone()
            if row:
                target_rows.append(dict(row))

    return {
        "batch_id": batch_id,
        "imported_count": len(prepared_products),
        "created_count": created_count,
        "updated_count": updated_count,
        "keyword_count": keyword_count,
        "targets": target_rows,
    }


def prepare_product_for_db(product: dict[str, Any]) -> dict[str, Any]:
    source_type = normalize_source(product.get("source_type"))
    source_product_id = to_product_id(product.get("source_product_id"))
    if not source_product_id:
        raise ValueError("normalized product is missing source_product_id")

    title = to_text(product.get("title")) or to_text(product.get("title_cn")) or to_text(product.get("title_en"))
    if not title:
        raise ValueError("normalized product is missing title")

    category_path, category_level1, category_level2 = normalize_category_fields(product.get("category_path"))
    return {
        "id": to_text(product.get("id")) or make_product_id(source_type, source_product_id),
        "upload_batch_id": product.get("upload_batch_id"),
        "source_row_index": to_int(product.get("source_row_index")) or 1,
        "source_type": source_type,
        "source_product_id": source_product_id,
        "catalog_scope": normalize_product_catalog_scope(product.get("catalog_scope")),
        "title_cn": to_text(product.get("title_cn")) or None,
        "title_en": to_text(product.get("title_en")) or None,
        "title": title,
        "main_image_url": to_text(product.get("main_image_url")) or None,
        "gallery_image_urls": parse_url_list(product.get("gallery_image_urls")),
        "video_url": to_text(product.get("video_url")) or None,
        "source_url": to_text(product.get("source_url")) or None,
        "category_path": category_path,
        "category_level1": category_level1,
        "category_level2": category_level2,
        "tags": parse_list_value(product.get("tags")),
        "price_usd": to_float(product.get("price_usd")),
        "gmv_usd": to_float(product.get("gmv_usd")),
        "weekly_sales": to_int(product.get("weekly_sales")),
        "monthly_sales": to_int(product.get("monthly_sales")),
        "review_count": to_int(product.get("review_count")),
        "listing_time": to_datetime_text(product.get("listing_time")),
        "status": normalize_status(product.get("status")),
        "in_product_pool": 1 if product.get("in_product_pool", True) else 0,
        "raw_data": to_json_safe(product.get("raw_data") or {}),
    }


def load_existing_products(conn: Any, products: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    existing: dict[tuple[str, str], dict[str, Any]] = {}
    for product in products:
        row = conn.execute(
            """
            SELECT id, source_type, source_product_id, catalog_scope, created_at
            FROM products
            WHERE source_type = ? AND source_product_id = ?
            ORDER BY datetime(updated_at) DESC
            LIMIT 1
            """,
            (product["source_type"], product["source_product_id"]),
        ).fetchone()
        if row:
            existing[(row["source_type"], row["source_product_id"])] = dict(row)
    return existing


def dedupe_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for product in products:
        prepared_source = normalize_source(product.get("source_type"))
        source_product_id = to_product_id(product.get("source_product_id"))
        if not source_product_id:
            continue
        identity = (prepared_source, source_product_id)
        if identity not in by_identity:
            order.append(identity)
        by_identity[identity] = product
    return [by_identity[identity] for identity in order]


def product_identity(product: dict[str, Any]) -> tuple[str, str]:
    return (normalize_source(product.get("source_type")), to_product_id(product.get("source_product_id")))


def make_product_id(source: str, source_product_id: str) -> str:
    safe_source = normalize_source(source)
    safe_source_product_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", source_product_id).strip("-")
    if not safe_source_product_id:
        safe_source_product_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{safe_source}:{source_product_id}").hex[:16]
    return f"{safe_source}-{safe_source_product_id}"


def normalize_source(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_") or "external"


def first_present(*values: Any) -> Any:
    for value in values:
        if value is None or value == "":
            continue
        return value
    return None


def first_text(*values: Any) -> str:
    for value in values:
        text = to_text(value)
        if text:
            return text
    return ""
