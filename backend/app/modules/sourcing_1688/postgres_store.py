from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from app.core.database import (
    DEFAULT_USER_ID,
    PRODUCT_CATALOG_SCOPE_ADMIN,
    PRODUCT_CATALOG_SCOPE_POOL_ONLY,
    UPLOADS_DIR,
    category_fields_from_1688_raw_data,
    clean_marketplace_price_text,
    clean_temu_marketplace_title,
    is_temu_marketplace_payload,
    merge_product_catalog_scope,
    normalize_product_catalog_scope,
    normalize_temu_marketplace_skus,
    product_row_to_api,
    source_product_id_from_marketplace_material,
    sourcing_candidate_row_to_api,
    sourcing_material_row_to_api,
    utc_now_text,
)
from app.core.postgres_pool import get_postgres_connection


def is_enabled() -> bool:
    return True


def configured_url() -> str:
    return (
        os.getenv("SOURCING_DATABASE_URL", "").strip()
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


@contextmanager
def get_pg_connection() -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")
    url = configured_url()
    if not url:
        raise RuntimeError("Sourcing PostgreSQL backend requires SOURCING_DATABASE_URL, POSTGRES_DATABASE_URL, or DATABASE_URL")
    with get_postgres_connection(url) as conn:
        yield conn


def set_active_sourcing_product(temu_product_id: str) -> dict[str, Any]:
    now = utc_now_text()
    with get_pg_connection() as conn:
        product = conn.execute(
            "SELECT id, title, main_image_url FROM products WHERE id = %s AND status != 'deleted'",
            (temu_product_id,),
        ).fetchone()
        if not product:
            raise ValueError("商品不存在或已删除")

        conn.execute(
            """
            INSERT INTO sourcing_capture_sessions (id, temu_product_id, created_at, updated_at)
            VALUES ('active', %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                temu_product_id = EXCLUDED.temu_product_id,
                updated_at = EXCLUDED.updated_at
            """,
            (temu_product_id, now, now),
        )

    return {
        "temu_product_id": product["id"],
        "title": product["title"],
        "main_image_url": product["main_image_url"],
        "updated_at": now,
    }


def get_active_sourcing_product() -> dict[str, Any] | None:
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            SELECT
                s.temu_product_id,
                s.updated_at,
                p.title,
                p.main_image_url
            FROM sourcing_capture_sessions s
            JOIN products p ON p.id = s.temu_product_id
            WHERE s.id = 'active'
            """
        ).fetchone()

    if not row:
        return None

    return {
        "temu_product_id": row["temu_product_id"],
        "title": row["title"],
        "main_image_url": row["main_image_url"],
        "updated_at": row["updated_at"],
    }


def create_sourcing_candidate_1688(payload: dict[str, Any]) -> dict[str, Any]:
    temu_product_id = payload.get("temu_product_id")
    if not temu_product_id:
        active_session = get_active_sourcing_product()
        if not active_session:
            raise ValueError("请先在工作台选择要绑定的 Temu 商品")
        temu_product_id = active_session["temu_product_id"]

    product_url = str(payload.get("product_url") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not product_url:
        raise ValueError("缺少 1688 商品链接")
    if not title:
        raise ValueError("缺少 1688 商品标题")

    now = utc_now_text()
    candidate_id = uuid.uuid4().hex
    sku_list = payload.get("sku_list") or []
    raw_data = payload.get("raw_data") or payload
    if is_temu_marketplace_payload(product_url, raw_data if isinstance(raw_data, dict) else {}):
        title = clean_temu_marketplace_title(title)
        price_range = clean_marketplace_price_text(payload.get("price_range"))
        sku_list = normalize_temu_marketplace_skus(
            sku_list,
            raw_data if isinstance(raw_data, dict) else {},
            price=payload.get("price"),
            image_url=payload.get("main_image_url"),
        )
    else:
        price_range = payload.get("price_range")

    with get_pg_connection() as conn:
        product = conn.execute(
            "SELECT id FROM products WHERE id = %s AND status != 'deleted'",
            (temu_product_id,),
        ).fetchone()
        if not product:
            raise ValueError("绑定的 Temu 商品不存在或已删除")

        conn.execute(
            """
            INSERT INTO sourcing_candidates_1688 (
                id, temu_product_id, offer_id, product_url, title, main_image_url,
                price, price_range, moq, shop_name, shop_url, sku_list_json,
                raw_data_json, captured_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                candidate_id,
                temu_product_id,
                payload.get("offer_id"),
                product_url,
                title,
                payload.get("main_image_url"),
                payload.get("price"),
                price_range,
                payload.get("moq"),
                payload.get("shop_name"),
                payload.get("shop_url"),
                json.dumps(sku_list, ensure_ascii=False),
                json.dumps(raw_data, ensure_ascii=False),
                payload.get("captured_at") or now,
                now,
                now,
            ),
        )

    return get_sourcing_candidate_1688(candidate_id)


def upsert_sourcing_candidate_from_material(
    material: dict[str, Any],
    temu_product_id: str,
    *,
    source_role: str = "product_self_sku",
) -> dict[str, Any] | None:
    product_url = str(material.get("product_url") or "").strip()
    raw_data = material.get("raw_data") if isinstance(material.get("raw_data"), dict) else {}
    title = str(material.get("title") or "").strip()
    sku_list = material.get("sku_list") or []
    if is_temu_marketplace_payload(product_url, raw_data):
        title = clean_temu_marketplace_title(title)
        sku_list = normalize_temu_marketplace_skus(
            sku_list,
            raw_data,
            price=material.get("price"),
            image_url=material.get("main_image_url"),
        )
    if not product_url or not title or not sku_list:
        return None

    now = utc_now_text()
    candidate_id = uuid.uuid4().hex
    candidate_raw_data = {
        **raw_data,
        "material_id": material.get("id"),
        "source_role": source_role,
        "source_site": raw_data.get("source_site") or ("temu" if "temu.com" in product_url.lower() else "1688"),
        "product_list_product_id": temu_product_id,
    }

    with get_pg_connection() as conn:
        product = conn.execute(
            "SELECT id FROM products WHERE id = %s AND status != 'deleted'",
            (temu_product_id,),
        ).fetchone()
        if not product:
            raise ValueError("绑定的 Temu 商品不存在或已删除")

        existing = conn.execute(
            """
            SELECT id
            FROM sourcing_candidates_1688
            WHERE temu_product_id = %s AND product_url = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (temu_product_id, product_url),
        ).fetchone()
        if existing:
            candidate_id = existing["id"]

        conn.execute(
            """
            INSERT INTO sourcing_candidates_1688 (
                id, temu_product_id, offer_id, product_url, title, main_image_url,
                price, price_range, moq, shop_name, shop_url, sku_list_json,
                raw_data_json, captured_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                temu_product_id = EXCLUDED.temu_product_id,
                offer_id = EXCLUDED.offer_id,
                product_url = EXCLUDED.product_url,
                title = EXCLUDED.title,
                main_image_url = EXCLUDED.main_image_url,
                price = EXCLUDED.price,
                price_range = EXCLUDED.price_range,
                moq = EXCLUDED.moq,
                shop_name = EXCLUDED.shop_name,
                shop_url = EXCLUDED.shop_url,
                sku_list_json = EXCLUDED.sku_list_json,
                raw_data_json = EXCLUDED.raw_data_json,
                captured_at = EXCLUDED.captured_at,
                updated_at = EXCLUDED.updated_at
            """,
            (
                candidate_id,
                temu_product_id,
                material.get("offer_id"),
                product_url,
                title,
                material.get("main_image_url"),
                material.get("price"),
                material.get("price_range"),
                material.get("moq"),
                material.get("shop_name"),
                material.get("shop_url"),
                json.dumps(sku_list, ensure_ascii=False),
                json.dumps(candidate_raw_data, ensure_ascii=False),
                material.get("captured_at") or now,
                now,
                now,
            ),
        )

    return get_sourcing_candidate_1688(candidate_id)


def get_sourcing_candidate_1688(candidate_id: str) -> dict[str, Any]:
    with get_pg_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sourcing_candidates_1688 WHERE id = %s",
            (candidate_id,),
        ).fetchone()

    if not row:
        raise ValueError("1688 候选货源不存在")

    return sourcing_candidate_row_to_api(row)


def list_sourcing_candidates_1688(temu_product_id: str) -> list[dict[str, Any]]:
    with get_pg_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sourcing_candidates_1688
            WHERE temu_product_id = %s
            ORDER BY captured_at DESC, created_at DESC
            """,
            (temu_product_id,),
        ).fetchall()

    return [sourcing_candidate_row_to_api(row) for row in rows]


def delete_sourcing_candidate_1688(candidate_id: str) -> bool:
    with get_pg_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM sourcing_candidates_1688 WHERE id = %s",
            (candidate_id,),
        )
        return cursor.rowcount > 0


def create_sourcing_material_1688(payload: dict[str, Any]) -> dict[str, Any]:
    product_url = str(payload.get("product_url") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not product_url:
        raise ValueError("缺少 1688 商品链接")
    if not title:
        raise ValueError("缺少 1688 商品标题")

    now = utc_now_text()
    material_id = uuid.uuid4().hex
    sku_list = payload.get("sku_list") or []
    raw_data = payload.get("raw_data") or payload
    if is_temu_marketplace_payload(product_url, raw_data if isinstance(raw_data, dict) else {}):
        title = clean_temu_marketplace_title(title)
        price_range = clean_marketplace_price_text(payload.get("price_range"))
        sku_list = normalize_temu_marketplace_skus(
            sku_list,
            raw_data if isinstance(raw_data, dict) else {},
            price=payload.get("price"),
            image_url=payload.get("main_image_url"),
        )
    else:
        price_range = payload.get("price_range")

    with get_pg_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM sourcing_materials_1688 WHERE product_url = %s",
            (product_url,),
        ).fetchone()
        if existing:
            material_id = existing["id"]

        conn.execute(
            """
            INSERT INTO sourcing_materials_1688 (
                id, offer_id, product_url, title, main_image_url, price, price_range,
                moq, shop_name, shop_url, sku_list_json, raw_data_json, captured_at,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                offer_id = EXCLUDED.offer_id,
                product_url = EXCLUDED.product_url,
                title = EXCLUDED.title,
                main_image_url = EXCLUDED.main_image_url,
                price = EXCLUDED.price,
                price_range = EXCLUDED.price_range,
                moq = EXCLUDED.moq,
                shop_name = EXCLUDED.shop_name,
                shop_url = EXCLUDED.shop_url,
                sku_list_json = EXCLUDED.sku_list_json,
                raw_data_json = EXCLUDED.raw_data_json,
                captured_at = EXCLUDED.captured_at,
                updated_at = EXCLUDED.updated_at
            """,
            (
                material_id,
                payload.get("offer_id"),
                product_url,
                title,
                payload.get("main_image_url"),
                payload.get("price"),
                price_range,
                payload.get("moq"),
                payload.get("shop_name"),
                payload.get("shop_url"),
                json.dumps(sku_list, ensure_ascii=False),
                json.dumps(raw_data, ensure_ascii=False),
                payload.get("captured_at") or now,
                now,
                now,
            ),
        )

    return get_sourcing_material_1688(material_id)


def get_sourcing_material_1688(material_id: str) -> dict[str, Any]:
    with get_pg_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sourcing_materials_1688 WHERE id = %s",
            (material_id,),
        ).fetchone()

    if not row:
        raise ValueError("1688 采集素材不存在")

    return sourcing_material_row_to_api(row)


def list_sourcing_materials_1688(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(300, limit))
    with get_pg_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sourcing_materials_1688
            ORDER BY captured_at DESC, updated_at DESC
            LIMIT %s
            """,
            (safe_limit,),
        ).fetchall()

    return [sourcing_material_row_to_api(row) for row in rows]


def delete_sourcing_material_1688(material_id: str) -> bool:
    with get_pg_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM sourcing_materials_1688 WHERE id = %s",
            (material_id,),
        )
        return cursor.rowcount > 0


def assign_sourcing_material_1688(material_id: str, temu_product_id: str) -> dict[str, Any]:
    material = get_sourcing_material_1688(material_id)
    candidate = create_sourcing_candidate_1688({**material, "temu_product_id": temu_product_id})
    now = utc_now_text()
    with get_pg_connection() as conn:
        conn.execute(
            """
            UPDATE sourcing_materials_1688
            SET assigned_product_id = %s, assigned_at = %s, updated_at = %s
            WHERE id = %s
            """,
            (temu_product_id, now, now, material_id),
        )
    return candidate


def create_product_from_sourcing_material_1688(
    material_id: str,
    *,
    add_to_pool_user_id: str | None = DEFAULT_USER_ID,
) -> dict[str, Any]:
    material = get_sourcing_material_1688(material_id)
    offer_id = material.get("offer_id")
    product_url = material["product_url"]
    raw_data = material.get("raw_data", {})
    source_site = str(raw_data.get("source_site") or "").strip().lower()
    if source_site not in {"temu", "1688"}:
        source_site = "temu" if "temu.com" in product_url.lower() else "1688"
    source_label = "Temu" if source_site == "temu" else "1688"
    source_product_id = source_product_id_from_marketplace_material(source_site, raw_data, offer_id, product_url)
    product_id = f"{source_site}-{source_product_id}"
    product_title = clean_temu_marketplace_title(material["title"]) if source_site == "temu" else material["title"]
    sku_list = material.get("sku_list") or []
    if source_site == "temu":
        sku_list = normalize_temu_marketplace_skus(
            sku_list,
            raw_data,
            price=material.get("price"),
            image_url=material.get("main_image_url"),
        )
    now = utc_now_text()
    batch_id = uuid.uuid4().hex
    saved_path = UPLOADS_DIR / f"{batch_id}_{source_product_id}_{source_site}_material.json"
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    saved_path.write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
    category_fields = category_fields_from_1688_raw_data(raw_data, "未采集类目")

    product = {
        "id": product_id,
        "source_row_index": 1,
        "source_type": source_site,
        "source_product_id": source_product_id,
        "title_cn": product_title,
        "title_en": None,
        "title": product_title,
        "main_image_url": material.get("main_image_url"),
        "gallery_image_urls": material.get("gallery_image_urls", []),
        "video_url": None,
        "source_url": product_url,
        **category_fields,
        "tags": [f"{source_label}采集器"],
        "price_usd": float(material.get("price") or 0),
        "gmv_usd": 0,
        "weekly_sales": 0,
        "monthly_sales": 0,
        "review_count": 0,
        "listing_time": now,
        "status": "active",
        "raw_data": {
            **raw_data,
            "material_id": material_id,
            "source_site": source_site,
            "sku_list": sku_list,
            "sku_count": len(sku_list),
        },
    }

    with get_pg_connection() as conn:
        insert_upload_batch(
            conn,
            batch_id=batch_id,
            source_filename=f"{source_product_id}_{source_site}_material.json",
            saved_path=saved_path,
            file_type=f"{source_site}-material",
            total_rows=1,
            imported_count=1,
            failed_count=0,
            now=now,
        )
        product_id = upsert_product(conn, batch_id, product, add_to_pool_user_id=add_to_pool_user_id, now=now)
        conn.execute(
            """
            UPDATE sourcing_materials_1688
            SET product_list_product_id = %s, updated_at = %s
            WHERE id = %s
            """,
            (product_id, utc_now_text(), material_id),
        )
        row = conn.execute("SELECT * FROM products WHERE id = %s", (product_id,)).fetchone()

    upsert_sourcing_candidate_from_material(material, product_id)
    if not row:
        raise ValueError("1688 商品创建失败")
    return product_row_to_api(row)


def insert_upload_batch(
    conn: Any,
    *,
    batch_id: str,
    source_filename: str,
    saved_path: Path,
    file_type: str,
    total_rows: int,
    imported_count: int,
    failed_count: int,
    now: str,
    status: str = "imported",
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO upload_batches (
            id, source_filename, saved_path, file_type, total_rows,
            imported_count, failed_count, status, error_message, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            batch_id,
            source_filename,
            str(saved_path),
            file_type,
            total_rows,
            imported_count,
            failed_count,
            status,
            error_message,
            now,
            now,
        ),
    )


def upsert_product(
    conn: Any,
    batch_id: str,
    product: dict[str, Any],
    *,
    add_to_pool_user_id: str | None,
    now: str,
) -> str:
    requested_scope = normalize_product_catalog_scope(
        PRODUCT_CATALOG_SCOPE_POOL_ONLY if add_to_pool_user_id else product.get("catalog_scope") or PRODUCT_CATALOG_SCOPE_ADMIN
    )
    existing = conn.execute(
        """
        SELECT id, catalog_scope
        FROM products
        WHERE source_type = %s AND source_product_id = %s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (product.get("source_type"), product.get("source_product_id")),
    ).fetchone()
    existing_scope = existing["catalog_scope"] if existing else None
    product_id = existing["id"] if existing else product["id"]
    final_scope = merge_product_catalog_scope(existing_scope, requested_scope) if existing else requested_scope
    should_preserve_admin_product = (
        existing is not None
        and normalize_product_catalog_scope(existing_scope) == PRODUCT_CATALOG_SCOPE_ADMIN
        and requested_scope == PRODUCT_CATALOG_SCOPE_POOL_ONLY
    )

    if not should_preserve_admin_product:
        conn.execute(
            """
            INSERT INTO products (
                id, upload_batch_id, source_row_index, source_type, source_product_id, catalog_scope,
                title_cn, title_en, title, main_image_url, gallery_image_urls_json,
                video_url, source_url, category_path, category_level1, category_level2,
                tags_json, price_usd, gmv_usd, weekly_sales, monthly_sales,
                review_count, listing_time, status, in_product_pool, raw_data_json, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                upload_batch_id = EXCLUDED.upload_batch_id,
                source_row_index = EXCLUDED.source_row_index,
                source_type = EXCLUDED.source_type,
                source_product_id = EXCLUDED.source_product_id,
                catalog_scope = EXCLUDED.catalog_scope,
                title_cn = EXCLUDED.title_cn,
                title_en = EXCLUDED.title_en,
                title = EXCLUDED.title,
                main_image_url = EXCLUDED.main_image_url,
                gallery_image_urls_json = EXCLUDED.gallery_image_urls_json,
                video_url = EXCLUDED.video_url,
                source_url = EXCLUDED.source_url,
                category_path = EXCLUDED.category_path,
                category_level1 = EXCLUDED.category_level1,
                category_level2 = EXCLUDED.category_level2,
                tags_json = EXCLUDED.tags_json,
                price_usd = EXCLUDED.price_usd,
                gmv_usd = EXCLUDED.gmv_usd,
                weekly_sales = EXCLUDED.weekly_sales,
                monthly_sales = EXCLUDED.monthly_sales,
                review_count = EXCLUDED.review_count,
                listing_time = EXCLUDED.listing_time,
                status = EXCLUDED.status,
                in_product_pool = EXCLUDED.in_product_pool,
                raw_data_json = EXCLUDED.raw_data_json,
                updated_at = EXCLUDED.updated_at
            """,
            (
                product_id,
                batch_id,
                product.get("source_row_index") or 1,
                product.get("source_type") or "1688",
                product.get("source_product_id"),
                final_scope,
                product.get("title_cn"),
                product.get("title_en"),
                product.get("title"),
                product.get("main_image_url"),
                json.dumps(product.get("gallery_image_urls", []), ensure_ascii=False),
                product.get("video_url"),
                product.get("source_url"),
                product.get("category_path"),
                product.get("category_level1"),
                product.get("category_level2"),
                json.dumps(product.get("tags", []), ensure_ascii=False),
                product.get("price_usd") or 0,
                product.get("gmv_usd") or 0,
                product.get("weekly_sales") or 0,
                product.get("monthly_sales") or 0,
                product.get("review_count") or 0,
                product.get("listing_time"),
                product.get("status") or "active",
                1,
                json.dumps(product.get("raw_data", {}), ensure_ascii=False),
                now,
                now,
            ),
        )

    if add_to_pool_user_id:
        conn.execute(
            """
            INSERT INTO product_pool_memberships (user_id, product_id, status, created_at, updated_at)
            VALUES (%s, %s, 'active', %s, %s)
            ON CONFLICT (user_id, product_id) DO UPDATE SET
                status = 'active',
                updated_at = EXCLUDED.updated_at
            """,
            (add_to_pool_user_id, product_id, now, now),
        )
    return product_id
