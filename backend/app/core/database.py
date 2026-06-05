from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.modules.creative_generation.sensitive_terms_catalog import DEFAULT_SENSITIVE_TERMS
from app.modules.recommendation.keyword_index import ensure_recommendation_schema, replace_product_keyword_index

from .config import DATABASE_PATH, UPLOADS_DIR, ensure_runtime_dirs


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
                source_type TEXT NOT NULL DEFAULT 'yunqi',
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

            CREATE TABLE IF NOT EXISTS product_pool_products (
                id TEXT PRIMARY KEY,
                upload_batch_id TEXT NOT NULL,
                source_row_index INTEGER NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'yunqi',
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

            CREATE INDEX IF NOT EXISTS idx_product_pool_status ON product_pool_products(status);
            CREATE INDEX IF NOT EXISTS idx_product_pool_source_id ON product_pool_products(source_product_id);
            CREATE INDEX IF NOT EXISTS idx_product_pool_listing_time ON product_pool_products(listing_time);
            CREATE INDEX IF NOT EXISTS idx_product_pool_category ON product_pool_products(category_path);

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

            CREATE TABLE IF NOT EXISTS sourcing_materials_1688 (
                id TEXT PRIMARY KEY,
                offer_id TEXT,
                product_url TEXT NOT NULL UNIQUE,
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
                assigned_product_id TEXT,
                assigned_at TEXT,
                product_list_product_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(assigned_product_id) REFERENCES products(id),
                FOREIGN KEY(product_list_product_id) REFERENCES products(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sourcing_materials_created
                ON sourcing_materials_1688(created_at);
            CREATE INDEX IF NOT EXISTS idx_sourcing_materials_assigned_product
                ON sourcing_materials_1688(assigned_product_id);

            CREATE TABLE IF NOT EXISTS sensitive_terms (
                id TEXT PRIMARY KEY,
                term TEXT NOT NULL,
                normalized_term TEXT NOT NULL UNIQUE,
                language TEXT NOT NULL DEFAULT 'mixed',
                category TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'block',
                match_type TEXT NOT NULL DEFAULT 'contains',
                replacement TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'system',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sensitive_terms_enabled
                ON sensitive_terms(enabled);
            CREATE INDEX IF NOT EXISTS idx_sensitive_terms_category
                ON sensitive_terms(category);
            """
        )
        ensure_column(conn, "products", "source_type", "source_type TEXT NOT NULL DEFAULT 'yunqi'")
        ensure_column(conn, "products", "in_product_pool", "in_product_pool INTEGER NOT NULL DEFAULT 1")
        ensure_link_list_schema(conn)
        ensure_product_identity_index(conn)
        ensure_yunqi_category_schema(conn)
        seed_product_pool_from_legacy_flag(conn)
        ensure_recommendation_schema(conn)
        seed_default_sensitive_terms(conn)


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def ensure_link_list_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS link_list_records (
            id TEXT PRIMARY KEY,
            product_id TEXT,
            product_title TEXT,
            product_title_en TEXT,
            source_product_url TEXT,
            source_count INTEGER NOT NULL DEFAULT 0,
            sku_count INTEGER NOT NULL DEFAULT 0,
            component_sku_count INTEGER NOT NULL DEFAULT 0,
            record_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_link_list_records_status
            ON link_list_records(status);
        CREATE INDEX IF NOT EXISTS idx_link_list_records_product
            ON link_list_records(product_id);
        CREATE INDEX IF NOT EXISTS idx_link_list_records_updated
            ON link_list_records(updated_at);
        """
    )


def ensure_product_identity_index(conn: sqlite3.Connection) -> None:
    duplicate = conn.execute(
        """
        SELECT 1
        FROM products
        GROUP BY source_type, source_product_id
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate:
        return

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_products_source_identity
            ON products(source_type, source_product_id)
        """
    )


def ensure_yunqi_category_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS yunqi_categories (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL DEFAULT 'yunqi',
            category_key TEXT NOT NULL UNIQUE,
            parent_key TEXT,
            level INTEGER NOT NULL,
            label TEXT NOT NULL,
            label_en TEXT,
            label_cn TEXT,
            path_text TEXT NOT NULL,
            parent_path_text TEXT,
            path_json TEXT NOT NULL DEFAULT '[]',
            node_id TEXT,
            aria_haspopup INTEGER NOT NULL DEFAULT 0,
            aria_owns TEXT,
            has_children INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            selected INTEGER NOT NULL DEFAULT 0,
            checked INTEGER NOT NULL DEFAULT 0,
            disabled INTEGER NOT NULL DEFAULT 0,
            class_name TEXT,
            source_snapshot_path TEXT,
            raw_data_json TEXT NOT NULL DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_yunqi_categories_path
            ON yunqi_categories(source_type, path_text);
        CREATE INDEX IF NOT EXISTS idx_yunqi_categories_parent
            ON yunqi_categories(parent_key);
        CREATE INDEX IF NOT EXISTS idx_yunqi_categories_level
            ON yunqi_categories(level);
        CREATE INDEX IF NOT EXISTS idx_yunqi_categories_label_cn
            ON yunqi_categories(label_cn);
        CREATE INDEX IF NOT EXISTS idx_yunqi_categories_label_en
            ON yunqi_categories(label_en);
        """
    )
    ensure_column(conn, "yunqi_categories", "is_active", "is_active INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "yunqi_categories", "source_snapshot_path", "source_snapshot_path TEXT")


def seed_product_pool_from_legacy_flag(conn: sqlite3.Connection) -> None:
    existing_count = conn.execute("SELECT COUNT(*) FROM product_pool_products").fetchone()[0]
    if existing_count:
        return

    product_ids = [
        row["id"]
        for row in conn.execute(
            """
            SELECT id
            FROM products
            WHERE status != 'deleted'
                AND COALESCE(in_product_pool, 0) = 1
            """
        ).fetchall()
    ]
    copy_products_to_pool(conn, product_ids)


def normalize_sensitive_term(term: str) -> str:
    return " ".join(str(term or "").lower().split()).strip()


def seed_default_sensitive_terms(conn: sqlite3.Connection) -> None:
    now = utc_now_text()
    for item in DEFAULT_SENSITIVE_TERMS:
        term = str(item["term"]).strip()
        normalized_term = normalize_sensitive_term(term)
        conn.execute(
            """
            INSERT INTO sensitive_terms (
                id, term, normalized_term, language, category, severity, match_type,
                replacement, enabled, source, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_term) DO NOTHING
            """,
            (
                uuid.uuid5(uuid.NAMESPACE_URL, f"sensitive-term:{normalized_term}").hex,
                term,
                normalized_term,
                item.get("language", "mixed"),
                item.get("category", "general"),
                item.get("severity", "block"),
                item.get("match_type", "contains"),
                item.get("replacement", ""),
                1 if item.get("enabled", True) else 0,
                item.get("source", "system"),
                item.get("notes"),
                now,
                now,
            ),
        )


def ensure_sensitive_terms_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sensitive_terms (
            id TEXT PRIMARY KEY,
            term TEXT NOT NULL,
            normalized_term TEXT NOT NULL UNIQUE,
            language TEXT NOT NULL DEFAULT 'mixed',
            category TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'block',
            match_type TEXT NOT NULL DEFAULT 'contains',
            replacement TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'system',
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sensitive_terms_enabled
            ON sensitive_terms(enabled);
        CREATE INDEX IF NOT EXISTS idx_sensitive_terms_category
            ON sensitive_terms(category);
        """
    )
    seed_default_sensitive_terms(conn)


def list_enabled_sensitive_terms() -> list[dict[str, Any]]:
    with get_connection() as conn:
        ensure_sensitive_terms_schema(conn)
        rows = conn.execute(
            """
            SELECT *
            FROM sensitive_terms
            WHERE enabled = 1
            ORDER BY length(term) DESC, term ASC
            """
        ).fetchall()

    return [sensitive_term_row_to_api(row) for row in rows]


def list_sensitive_terms(*, enabled: bool | None = None, category: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if enabled is not None:
        clauses.append("enabled = ?")
        params.append(1 if enabled else 0)
    if category:
        clauses.append("category = ?")
        params.append(category)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection() as conn:
        ensure_sensitive_terms_schema(conn)
        rows = conn.execute(
            f"""
            SELECT *
            FROM sensitive_terms
            {where_sql}
            ORDER BY category ASC, length(term) DESC, term ASC
            """,
            params,
        ).fetchall()

    return [sensitive_term_row_to_api(row) for row in rows]


def sensitive_term_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "term": row["term"],
        "normalized_term": row["normalized_term"],
        "language": row["language"],
        "category": row["category"],
        "severity": row["severity"],
        "match_type": row["match_type"],
        "replacement": row["replacement"],
        "enabled": bool(row["enabled"]),
        "source": row["source"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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
                id, upload_batch_id, source_row_index, source_type, source_product_id,
                title_cn, title_en, title, main_image_url, gallery_image_urls_json,
                video_url, source_url, category_path, category_level1, category_level2,
                tags_json, price_usd, gmv_usd, weekly_sales, monthly_sales,
                review_count, listing_time, status, in_product_pool, raw_data_json, created_at, updated_at
            ) VALUES (
                :id, :upload_batch_id, :source_row_index, :source_type, :source_product_id,
                :title_cn, :title_en, :title, :main_image_url, :gallery_image_urls_json,
                :video_url, :source_url, :category_path, :category_level1, :category_level2,
                :tags_json, :price_usd, :gmv_usd, :weekly_sales, :monthly_sales,
                :review_count, :listing_time, :status, :in_product_pool, :raw_data_json, :created_at, :updated_at
            )
            """,
            [
                {
                    **product,
                    "upload_batch_id": batch_id,
                    "source_type": product.get("source_type") or "yunqi",
                    "in_product_pool": 1 if product.get("in_product_pool", True) else 0,
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
        replace_product_keyword_index(conn, products, now=now)
        copy_products_to_pool(conn, [product["id"] for product in products], now=now)


def product_table_for_scope(scope: str) -> str:
    return "products" if scope == "all" else "product_pool_products"


def copy_products_to_pool(conn: sqlite3.Connection, product_ids: list[str], *, now: str | None = None) -> int:
    clean_ids = [product_id.strip() for product_id in product_ids if product_id and product_id.strip()]
    if not clean_ids:
        return 0

    timestamp = now or utc_now_text()
    placeholders = ",".join("?" for _ in clean_ids)
    cursor = conn.execute(
        f"""
        INSERT OR REPLACE INTO product_pool_products (
            id, upload_batch_id, source_row_index, source_type, source_product_id,
            title_cn, title_en, title, main_image_url, gallery_image_urls_json,
            video_url, source_url, category_path, category_level1, category_level2,
            tags_json, price_usd, gmv_usd, weekly_sales, monthly_sales,
            review_count, listing_time, status, raw_data_json, created_at, updated_at
        )
        SELECT
            id, upload_batch_id, source_row_index, source_type, source_product_id,
            title_cn, title_en, title, main_image_url, gallery_image_urls_json,
            video_url, source_url, category_path, category_level1, category_level2,
            tags_json, price_usd, gmv_usd, weekly_sales, monthly_sales,
            review_count, listing_time, status, raw_data_json, ?, ?
        FROM products
        WHERE id IN ({placeholders})
            AND status != 'deleted'
        """,
        [timestamp, timestamp, *clean_ids],
    )
    return cursor.rowcount


def list_link_list_records(*, include_deleted: bool = False, limit: int = 500) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 500), 1000))
    where_sql = "" if include_deleted else "WHERE status != 'deleted'"
    with get_connection() as conn:
        ensure_link_list_schema(conn)
        rows = conn.execute(
            f"""
            SELECT *
            FROM link_list_records
            {where_sql}
            ORDER BY datetime(created_at) DESC, datetime(updated_at) DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    return [link_list_record_row_to_api(row) for row in rows]


def upsert_link_list_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("链接记录格式不正确")

    normalized = normalize_link_list_record(record)
    now = utc_now_text()
    created_at = _clean_record_text(normalized.get("createdAt")) or now
    metadata = link_list_record_metadata(normalized)
    with get_connection() as conn:
        ensure_link_list_schema(conn)
        conn.execute(
            """
            INSERT INTO link_list_records (
                id, product_id, product_title, product_title_en, source_product_url,
                source_count, sku_count, component_sku_count, record_json, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                product_id = excluded.product_id,
                product_title = excluded.product_title,
                product_title_en = excluded.product_title_en,
                source_product_url = excluded.source_product_url,
                source_count = excluded.source_count,
                sku_count = excluded.sku_count,
                component_sku_count = excluded.component_sku_count,
                record_json = excluded.record_json,
                status = 'active',
                updated_at = excluded.updated_at
            """,
            (
                normalized["id"],
                metadata["product_id"],
                metadata["product_title"],
                metadata["product_title_en"],
                metadata["source_product_url"],
                metadata["source_count"],
                metadata["sku_count"],
                metadata["component_sku_count"],
                json.dumps(normalized, ensure_ascii=False),
                created_at,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM link_list_records WHERE id = ?", (normalized["id"],)).fetchone()

    return link_list_record_row_to_api(row)


def upsert_link_list_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError("链接记录列表格式不正确")
    return [upsert_link_list_record(record) for record in records if isinstance(record, dict)]


def soft_delete_link_list_record(record_id: str) -> bool:
    clean_id = _clean_record_text(record_id)
    if not clean_id:
        return False

    now = utc_now_text()
    with get_connection() as conn:
        ensure_link_list_schema(conn)
        cursor = conn.execute(
            """
            UPDATE link_list_records
            SET status = 'deleted', updated_at = ?
            WHERE id = ? AND status != 'deleted'
            """,
            (now, clean_id),
        )
    return cursor.rowcount > 0


def normalize_link_list_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    record_id = _clean_record_text(normalized.get("id")) or uuid.uuid4().hex
    normalized["id"] = record_id
    normalized.setdefault("schemaVersion", 3)
    normalized["createdAt"] = _clean_record_text(normalized.get("createdAt")) or utc_now_text()
    normalized.setdefault("sourceLinks", [])
    normalized.setdefault("skuEntries", [])
    normalized["componentSkuCount"] = safe_record_int(normalized.get("componentSkuCount"), count_component_skus(normalized))
    return normalized


def count_component_skus(record: dict[str, Any]) -> int:
    count = 0
    for entry in record.get("skuEntries") or []:
        if isinstance(entry, dict):
            component_skus = entry.get("componentSkus") or []
            count += len(component_skus) if isinstance(component_skus, list) else 0
    return count


def link_list_record_metadata(record: dict[str, Any]) -> dict[str, Any]:
    source_links = record.get("sourceLinks") if isinstance(record.get("sourceLinks"), list) else []
    sku_entries = record.get("skuEntries") if isinstance(record.get("skuEntries"), list) else []
    first_source = next((source for source in source_links if isinstance(source, dict)), {})
    return {
        "product_id": _clean_record_text(record.get("productId")),
        "product_title": _clean_record_text(record.get("productTitle")),
        "product_title_en": _clean_record_text(record.get("productTitleEn")),
        "source_product_url": _clean_record_text(first_source.get("productUrl")) if isinstance(first_source, dict) else "",
        "source_count": len(source_links),
        "sku_count": len(sku_entries),
        "component_sku_count": safe_record_int(record.get("componentSkuCount"), count_component_skus(record)),
    }


def link_list_record_row_to_api(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        raise ValueError("链接记录不存在")
    try:
        record = json.loads(row["record_json"] or "{}")
    except json.JSONDecodeError:
        record = {}
    if not isinstance(record, dict):
        record = {}
    record.setdefault("id", row["id"])
    record.setdefault("createdAt", row["created_at"])
    record.setdefault("productId", row["product_id"] or "")
    record.setdefault("productTitle", row["product_title"] or "")
    record.setdefault("productTitleEn", row["product_title_en"] or "")
    record.setdefault("sourceLinks", [])
    record.setdefault("skuEntries", [])
    record.setdefault("componentSkuCount", row["component_sku_count"] or 0)
    return record


def _clean_record_text(value: Any) -> str:
    return str(value or "").strip()


def safe_record_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


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
    scope: str = "pool",
    include_deleted: bool = False,
) -> dict[str, Any]:
    table_name = product_table_for_scope(scope)
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
        total = conn.execute(f"SELECT COUNT(*) FROM {table_name} {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT * FROM {table_name}
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


def get_product_stats(scope: str = "pool") -> dict[str, int]:
    table_name = product_table_for_scope(scope)
    with get_connection() as conn:
        row = conn.execute(
            f"""
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
            FROM {table_name}
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


def delete_sourcing_candidate_1688(candidate_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM sourcing_candidates_1688 WHERE id = ?",
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

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM sourcing_materials_1688 WHERE product_url = ?",
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_url) DO UPDATE SET
                offer_id = excluded.offer_id,
                title = excluded.title,
                main_image_url = excluded.main_image_url,
                price = excluded.price,
                price_range = excluded.price_range,
                moq = excluded.moq,
                shop_name = excluded.shop_name,
                shop_url = excluded.shop_url,
                sku_list_json = excluded.sku_list_json,
                raw_data_json = excluded.raw_data_json,
                captured_at = excluded.captured_at,
                updated_at = excluded.updated_at
            """,
            (
                material_id,
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

    return get_sourcing_material_1688(material_id)


def get_sourcing_material_1688(material_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM sourcing_materials_1688 WHERE id = ?",
            (material_id,),
        ).fetchone()

    if not row:
        raise ValueError("1688 采集素材不存在")

    return sourcing_material_row_to_api(row)


def list_sourcing_materials_1688(limit: int = 100) -> list[dict[str, Any]]:
    safe_limit = max(1, min(300, limit))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM sourcing_materials_1688
            ORDER BY datetime(captured_at) DESC, datetime(updated_at) DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()

    return [sourcing_material_row_to_api(row) for row in rows]


def delete_sourcing_material_1688(material_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM sourcing_materials_1688 WHERE id = ?",
            (material_id,),
        )
        return cursor.rowcount > 0


def assign_sourcing_material_1688(material_id: str, temu_product_id: str) -> dict[str, Any]:
    material = get_sourcing_material_1688(material_id)
    candidate = create_sourcing_candidate_1688({**material, "temu_product_id": temu_product_id})
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE sourcing_materials_1688
            SET assigned_product_id = ?, assigned_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (temu_product_id, now, now, material_id),
        )
    return candidate


def category_fields_from_1688_raw_data(raw_data: dict[str, Any] | None, fallback_category: str) -> dict[str, str | None]:
    category_parts = normalize_1688_category_parts((raw_data or {}).get("category_parts"))
    if not category_parts:
        category_parts = normalize_1688_category_parts((raw_data or {}).get("category_path"))

    if not category_parts:
        return {
            "category_path": fallback_category,
            "category_level1": fallback_category,
            "category_level2": None,
        }

    return {
        "category_path": "/".join(category_parts),
        "category_level1": category_parts[0],
        "category_level2": category_parts[1] if len(category_parts) > 1 else None,
    }


def normalize_1688_category_parts(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_parts = [str(item) for item in value]
    elif isinstance(value, str):
        raw_parts = [part for part in value.replace(">", "/").replace("›", "/").replace("»", "/").split("/")]
    else:
        raw_parts = []

    parts: list[str] = []
    seen: set[str] = set()
    blocked = {"首页", "阿里巴巴", "1688", "商品详情", "全部商品", "所有分类", "采集素材", "链接导入"}
    for raw_part in raw_parts:
        part = " ".join(raw_part.split()).strip()
        if not part or part in blocked or len(part) > 32 or part in seen:
            continue
        seen.add(part)
        parts.append(part)
    return parts[:5]


def create_product_from_sourcing_material_1688(material_id: str) -> dict[str, Any]:
    material = get_sourcing_material_1688(material_id)
    offer_id = material.get("offer_id")
    product_url = material["product_url"]
    source_product_id = str(offer_id or uuid.uuid5(uuid.NAMESPACE_URL, product_url).hex[:16])
    product_id = f"1688-{source_product_id}"
    now = utc_now_text()
    batch_id = uuid.uuid4().hex
    saved_path = UPLOADS_DIR / f"{batch_id}_{source_product_id}_1688_material.json"
    with saved_path.open("w", encoding="utf-8") as file:
        json.dump(material, file, ensure_ascii=False, indent=2)
    raw_data = material.get("raw_data", {})
    category_fields = category_fields_from_1688_raw_data(raw_data, "未采集类目")

    product = {
        "id": product_id,
        "source_row_index": 1,
        "source_type": "1688",
        "source_product_id": source_product_id,
        "title_cn": material["title"],
        "title_en": None,
        "title": material["title"],
        "main_image_url": material.get("main_image_url"),
        "gallery_image_urls": material.get("gallery_image_urls", []),
        "video_url": None,
        "source_url": product_url,
        **category_fields,
        "tags": ["1688采集器"],
        "price_usd": float(material.get("price") or 0),
        "gmv_usd": 0,
        "weekly_sales": 0,
        "monthly_sales": 0,
        "review_count": 0,
        "listing_time": now,
        "status": "active",
        "raw_data": {**raw_data, "material_id": material_id},
    }
    insert_upload_batch(
        batch_id=batch_id,
        source_filename=f"{source_product_id}_1688_material.json",
        saved_path=saved_path,
        file_type="1688-material",
        total_rows=1,
        imported_count=1,
        failed_count=0,
    )
    replace_products(batch_id, [product])

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE sourcing_materials_1688
            SET product_list_product_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (product_id, utc_now_text(), material_id),
        )

    with get_connection() as conn:
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not row:
        raise ValueError("1688 商品创建失败")
    return product_row_to_api(row)


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


def sourcing_material_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    raw_data = json.loads(row["raw_data_json"] or "{}")
    return {
        "id": row["id"],
        "offer_id": row["offer_id"],
        "product_url": row["product_url"],
        "title": row["title"],
        "main_image_url": row["main_image_url"],
        "gallery_image_urls": raw_data.get("gallery_image_urls", []),
        "price": row["price"],
        "price_range": row["price_range"],
        "moq": row["moq"],
        "shop_name": row["shop_name"],
        "shop_url": row["shop_url"],
        "sku_list": json.loads(row["sku_list_json"] or "[]"),
        "raw_data": raw_data,
        "captured_at": row["captured_at"],
        "assigned_product_id": row["assigned_product_id"],
        "assigned_at": row["assigned_at"],
        "product_list_product_id": row["product_list_product_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def soft_delete_product(product_id: str, scope: str = "pool") -> bool:
    now = utc_now_text()
    table_name = product_table_for_scope(scope)
    with get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE {table_name} SET status = 'deleted', updated_at = ? WHERE id = ?",
            (now, product_id),
        )
        return cursor.rowcount > 0


def add_products_to_pool(product_ids: list[str]) -> int:
    clean_ids = [product_id.strip() for product_id in product_ids if product_id and product_id.strip()]
    if not clean_ids:
        return 0

    with get_connection() as conn:
        return copy_products_to_pool(conn, clean_ids)


def product_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "source_type": row["source_type"] or "yunqi",
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
        "in_product_pool": True if "in_product_pool" not in keys else bool(row["in_product_pool"]),
        "source_row_index": row["source_row_index"],
    }
