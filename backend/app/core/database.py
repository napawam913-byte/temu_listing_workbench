from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import DATABASE_PATH, ensure_runtime_dirs


def utc_now_text() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    ensure_runtime_dirs()
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS upload_batches (
                id TEXT PRIMARY KEY,
                source_filename TEXT NOT NULL,
                saved_path TEXT NOT NULL,
                file_type TEXT NOT NULL,
                total_rows INTEGER NOT NULL DEFAULT 0,
                imported_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'imported',
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                upload_batch_id TEXT NOT NULL,
                source_row_index INTEGER NOT NULL,
                source_product_id TEXT NOT NULL,
                title_cn TEXT,
                title_en TEXT,
                title TEXT NOT NULL,
                main_image_url TEXT,
                gallery_image_urls_json TEXT NOT NULL DEFAULT '[]',
                video_url TEXT,
                source_url TEXT,
                category_path TEXT,
                category_level1 TEXT,
                category_level2 TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                price_usd REAL NOT NULL DEFAULT 0,
                gmv_usd REAL NOT NULL DEFAULT 0,
                weekly_sales INTEGER NOT NULL DEFAULT 0,
                monthly_sales INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                listing_time TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                raw_data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(upload_batch_id) REFERENCES upload_batches(id)
            );

            CREATE INDEX IF NOT EXISTS idx_products_batch ON products(upload_batch_id);
            CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
            CREATE INDEX IF NOT EXISTS idx_products_source_id ON products(source_product_id);
            CREATE INDEX IF NOT EXISTS idx_products_listing_time ON products(listing_time);
            CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_path);

            CREATE TABLE IF NOT EXISTS sourcing_capture_sessions (
                id TEXT PRIMARY KEY,
                temu_product_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(temu_product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS sourcing_candidates_1688 (
                id TEXT PRIMARY KEY,
                temu_product_id TEXT NOT NULL,
                offer_id TEXT,
                product_url TEXT NOT NULL,
                title TEXT NOT NULL,
                main_image_url TEXT,
                price REAL,
                price_range TEXT,
                moq INTEGER,
                shop_name TEXT,
                shop_url TEXT,
                sku_list_json TEXT NOT NULL DEFAULT '[]',
                raw_data_json TEXT NOT NULL DEFAULT '{}',
                captured_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(temu_product_id) REFERENCES products(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sourcing_candidates_product
                ON sourcing_candidates_1688(temu_product_id);
            CREATE INDEX IF NOT EXISTS idx_sourcing_candidates_url
                ON sourcing_candidates_1688(product_url);
            """
        )


def insert_upload_batch(
    *,
    batch_id: str,
    source_filename: str,
    saved_path: Path,
    file_type: str,
    total_rows: int,
    imported_count: int,
    failed_count: int,
    status: str = "imported",
    error_message: str | None = None,
) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO upload_batches (
                id, source_filename, saved_path, file_type, total_rows,
                imported_count, failed_count, status, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def replace_products(batch_id: str, products: list[dict[str, Any]]) -> None:
    now = utc_now_text()
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO products (
                id, upload_batch_id, source_row_index, source_product_id,
                title_cn, title_en, title, main_image_url, gallery_image_urls_json,
                video_url, source_url, category_path, category_level1, category_level2,
                tags_json, price_usd, gmv_usd, weekly_sales, monthly_sales,
                review_count, listing_time, status, raw_data_json, created_at, updated_at
            ) VALUES (
                :id, :upload_batch_id, :source_row_index, :source_product_id,
                :title_cn, :title_en, :title, :main_image_url, :gallery_image_urls_json,
                :video_url, :source_url, :category_path, :category_level1, :category_level2,
                :tags_json, :price_usd, :gmv_usd, :weekly_sales, :monthly_sales,
                :review_count, :listing_time, :status, :raw_data_json, :created_at, :updated_at
            )
            """,
            [
                {
                    **product,
                    "upload_batch_id": batch_id,
                    "gallery_image_urls_json": json.dumps(
                        product.get("gallery_image_urls", []), ensure_ascii=False
                    ),
                    "tags_json": json.dumps(product.get("tags", []), ensure_ascii=False),
                    "raw_data_json": json.dumps(product.get("raw_data", {}), ensure_ascii=False),
                    "created_at": now,
                    "updated_at": now,
                }
                for product in products
            ],
        )


def list_products(
    *,
    page: int,
    page_size: int,
    keyword: str | None = None,
    period: str | None = None,
    category: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    sales_min: int | None = None,
    sales_max: int | None = None,
    gmv_min: float | None = None,
    gmv_max: float | None = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    where, params = build_product_where(
        keyword=keyword,
        period=period,
        category=category,
        price_min=price_min,
        price_max=price_max,
        sales_min=sales_min,
        sales_max=sales_max,
        gmv_min=gmv_min,
        gmv_max=gmv_max,
        include_deleted=include_deleted,
    )

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    safe_page = max(1, page)
    safe_page_size = max(1, min(100, page_size))
    offset = (safe_page - 1) * safe_page_size

    with get_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM products {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT * FROM products
            {where_sql}
            ORDER BY datetime(listing_time) DESC, gmv_usd DESC
            LIMIT ? OFFSET ?
            """,
            [*params, safe_page_size, offset],
        ).fetchall()

    return {
        "items": [product_row_to_api(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
    }


def get_product_stats() -> dict[str, int]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN status != 'deleted' THEN 1 ELSE 0 END) AS active_count,
                SUM(
                    CASE
                        WHEN status != 'deleted'
                            AND listing_time IS NOT NULL
                            AND weekly_sales > 0
                            AND datetime(listing_time) >= datetime('now', '-7 days')
                        THEN 1 ELSE 0
                    END
                ) AS recent_7_count,
                SUM(
                    CASE
                        WHEN status != 'deleted'
                            AND listing_time IS NOT NULL
                            AND monthly_sales > 0
                            AND datetime(listing_time) >= datetime('now', '-30 days')
                        THEN 1 ELSE 0
                    END
                ) AS recent_30_count,
                SUM(CASE WHEN status = 'deleted' THEN 1 ELSE 0 END) AS deleted_count
            FROM products
            """
        ).fetchone()

    return {
        "active_count": int(row["active_count"] or 0),
        "recent_7_count": int(row["recent_7_count"] or 0),
        "recent_30_count": int(row["recent_30_count"] or 0),
        "deleted_count": int(row["deleted_count"] or 0),
    }


def get_product_categories() -> list[dict[str, Any]]:
    with get_connection() as conn:
        level1_rows = conn.execute(
            """
            SELECT category_level1 AS name, COUNT(*) AS count
            FROM products
            WHERE status != 'deleted'
                AND category_level1 IS NOT NULL
                AND category_level1 != ''
            GROUP BY category_level1
            ORDER BY count DESC, category_level1 ASC
            """
        ).fetchall()
        level2_rows = conn.execute(
            """
            SELECT category_level1, category_level2, category_path, COUNT(*) AS count
            FROM products
            WHERE status != 'deleted'
                AND category_level1 IS NOT NULL
                AND category_level1 != ''
                AND category_level2 IS NOT NULL
                AND category_level2 != ''
            GROUP BY category_level1, category_level2, category_path
            ORDER BY category_level1 ASC, count DESC, category_level2 ASC
            """
        ).fetchall()

    children_by_level1: dict[str, list[dict[str, Any]]] = {}
    for row in level2_rows:
        level1 = row["category_level1"]
        children_by_level1.setdefault(level1, []).append(
            {
                "value": row["category_path"],
                "label": row["category_level2"],
                "count": row["count"],
                "level": 2,
            }
        )

    return [
        {
            "value": row["name"],
            "label": row["name"],
            "count": row["count"],
            "level": 1,
            "children": children_by_level1.get(row["name"], []),
        }
        for row in level1_rows
    ]


def build_product_where(
    *,
    keyword: str | None = None,
    period: str | None = None,
    category: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    sales_min: int | None = None,
    sales_max: int | None = None,
    gmv_min: float | None = None,
    gmv_max: float | None = None,
    include_deleted: bool = False,
) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []

    if not include_deleted:
        where.append("status != 'deleted'")

    if keyword:
        like = f"%{keyword.strip()}%"
        where.append("(title LIKE ? OR title_cn LIKE ? OR title_en LIKE ? OR source_product_id LIKE ?)")
        params.extend([like, like, like, like])

    if category and category != "全部类目":
        normalized_category = category.strip()
        if "/" in normalized_category:
            where.append("category_path = ?")
            params.append(normalized_category)
        else:
            where.append("(category_level1 = ? OR category_level2 = ?)")
            params.extend([normalized_category, normalized_category])

    if period == "近7天":
        where.append("datetime(listing_time) >= datetime('now', '-7 days')")
    elif period == "近30天":
        where.append("datetime(listing_time) >= datetime('now', '-30 days')")

    add_range_filter(where, params, "price_usd", price_min, price_max)
    add_range_filter(where, params, "MAX(weekly_sales, monthly_sales)", sales_min, sales_max)
    add_range_filter(where, params, "gmv_usd", gmv_min, gmv_max)

    return where, params


def add_range_filter(
    where: list[str],
    params: list[Any],
    expression: str,
    minimum: int | float | None,
    maximum: int | float | None,
) -> None:
    if minimum is not None:
        where.append(f"{expression} >= ?")
        params.append(minimum)
    if maximum is not None:
        where.append(f"{expression} <= ?")
        params.append(maximum)


def set_active_sourcing_product(temu_product_id: str) -> dict[str, Any]:
    now = utc_now_text()
    with get_connection() as conn:
        product = conn.execute(
            "SELECT id, title, main_image_url FROM products WHERE id = ? AND status != 'deleted'",
            (temu_product_id,),
        ).fetchone()
        if not product:
            raise ValueError("商品不存在或已删除")

        conn.execute(
            """
            INSERT INTO sourcing_capture_sessions (id, temu_product_id, created_at, updated_at)
            VALUES ('active', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                temu_product_id = excluded.temu_product_id,
                updated_at = excluded.updated_at
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
    with get_connection() as conn:
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

    with get_connection() as conn:
        product = conn.execute(
            "SELECT id FROM products WHERE id = ? AND status != 'deleted'",
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                temu_product_id,
                payload.get("offer_id"),
                product_url,
                title,
                payload.get("main_image_url"),
                payload.get("price"),
                payload.get("price_range"),
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


def get_sourcing_candidate_1688(candidate_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sourcing_candidates_1688 WHERE id = ?",
            (candidate_id,),
        ).fetchone()

    if not row:
        raise ValueError("1688 候选货源不存在")

    return sourcing_candidate_row_to_api(row)


def list_sourcing_candidates_1688(temu_product_id: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sourcing_candidates_1688
            WHERE temu_product_id = ?
            ORDER BY datetime(captured_at) DESC, datetime(created_at) DESC
            """,
            (temu_product_id,),
        ).fetchall()

    return [sourcing_candidate_row_to_api(row) for row in rows]


def sourcing_candidate_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "temu_product_id": row["temu_product_id"],
        "offer_id": row["offer_id"],
        "product_url": row["product_url"],
        "title": row["title"],
        "main_image_url": row["main_image_url"],
        "price": row["price"],
        "price_range": row["price_range"],
        "moq": row["moq"],
        "shop_name": row["shop_name"],
        "shop_url": row["shop_url"],
        "sku_list": json.loads(row["sku_list_json"] or "[]"),
        "raw_data": json.loads(row["raw_data_json"] or "{}"),
        "captured_at": row["captured_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def soft_delete_product(product_id: str) -> bool:
    now = utc_now_text()
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE products SET status = 'deleted', updated_at = ? WHERE id = ?",
            (now, product_id),
        )
        return cursor.rowcount > 0


def product_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_product_id": row["source_product_id"],
        "title": row["title"],
        "title_cn": row["title_cn"],
        "title_en": row["title_en"],
        "main_image_url": row["main_image_url"],
        "gallery_image_urls": json.loads(row["gallery_image_urls_json"] or "[]"),
        "video_url": row["video_url"],
        "source_url": row["source_url"],
        "category_path": row["category_path"],
        "category_level1": row["category_level1"],
        "category_level2": row["category_level2"],
        "tags": json.loads(row["tags_json"] or "[]"),
        "price_usd": row["price_usd"],
        "gmv_usd": row["gmv_usd"],
        "weekly_sales": row["weekly_sales"],
        "monthly_sales": row["monthly_sales"],
        "review_count": row["review_count"],
        "listing_time": row["listing_time"],
        "status": row["status"],
        "source_row_index": row["source_row_index"],
    }
