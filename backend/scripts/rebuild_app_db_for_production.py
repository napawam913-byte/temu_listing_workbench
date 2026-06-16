from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
BACKEND_DIR = SCRIPT_PATH.parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


FINAL_TABLES = {
    "api_usage_logs",
    "app_settings",
    "canonical_categories",
    "creative_image_jobs",
    "dxm_temu_attr_search_fts",
    "dxm_temu_category_attr_fields",
    "dxm_temu_category_attr_snapshots",
    "dxm_temu_category_search_fts",
    "export_product_attribute_jobs",
    "ingest_batches",
    "ingest_items",
    "link_list_records",
    "product_ai_analysis_cache",
    "product_category_matches",
    "product_keywords",
    "product_pool_memberships",
    "product_pool_products",
    "products",
    "sensitive_terms",
    "smart_1688_search_items",
    "smart_1688_search_tasks",
    "source_category_mappings",
    "sourcing_candidates_1688",
    "sourcing_capture_sessions",
    "sourcing_materials_1688",
    "team_members",
    "teams",
    "upload_batches",
    "user_api_settings",
    "user_sessions",
    "users",
    "visual_generation_modules",
    "visual_generation_tasks",
    "yunqi_categories",
}


UNCATEGORIZED_CATEGORY = "\u672a\u91c7\u96c6\u7c7b\u76ee"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up app.db and rebuild it with the production schema/data set."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=BACKEND_DIR / "data" / "app.db",
        help="Path to the active app.db.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=BACKEND_DIR / "data" / "backups",
        help="Directory for the source database backup.",
    )
    parser.add_argument(
        "--keep-legacy-material-rows",
        action="store_true",
        help="Keep rows in sourcing_materials_1688 instead of moving those rows into products and emptying the legacy table.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate a temporary database but do not replace the active app.db.",
    )
    args = parser.parse_args()

    database_path = args.database.resolve()
    if not database_path.exists():
        raise SystemExit(f"Database not found: {database_path}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = args.backup_dir.resolve() / f"app_backup_before_rebuild_{timestamp}.db"
    tmp_path = database_path.with_name(f".app_rebuild_{timestamp}.db")

    print(f"Source: {database_path}")
    print(f"Backup: {backup_path}")
    print(f"Temp:   {tmp_path}")
    if args.dry_run:
        print("Mode:   dry run")

    args.backup_dir.mkdir(parents=True, exist_ok=True)
    copy_sqlite_database(database_path, backup_path)
    print("Backup complete.")

    if tmp_path.exists():
        tmp_path.unlink()

    build_rebuilt_database(
        source_path=backup_path,
        target_path=tmp_path,
        keep_legacy_material_rows=args.keep_legacy_material_rows,
    )
    summary = validate_database(tmp_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.dry_run:
        print(f"Dry run database kept at: {tmp_path}")
        return

    replace_active_database(database_path, tmp_path)
    print(f"Rebuild complete: {database_path}")


def copy_sqlite_database(source: Path, target: Path) -> None:
    if target.exists():
        raise SystemExit(f"Backup already exists: {target}")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_conn:
        with sqlite3.connect(target) as target_conn:
            source_conn.backup(target_conn)


def build_rebuilt_database(
    *,
    source_path: Path,
    target_path: Path,
    keep_legacy_material_rows: bool,
) -> None:
    os.environ["TEMU_WORKBENCH_DATABASE_PATH"] = str(target_path)
    from app.core.database import init_db

    init_db()

    target_conn = sqlite3.connect(target_path)
    target_conn.row_factory = sqlite3.Row
    source_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source_conn.row_factory = sqlite3.Row
    try:
        copy_final_tables(source_conn, target_conn)
        migrate_legacy_1688_materials(source_conn, target_conn)
        if not keep_legacy_material_rows:
            target_conn.execute("DELETE FROM sourcing_materials_1688")
        normalize_ingest_product_targets(target_conn)
        rebuild_indexes(target_conn)
        target_conn.commit()
        vacuum_database(target_conn)
    finally:
        source_conn.close()
        target_conn.close()


def copy_final_tables(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection) -> None:
    source_tables = set(table_names(source_conn))
    target_tables = set(table_names(target_conn))
    for table in sorted(FINAL_TABLES):
        if table not in source_tables or table not in target_tables:
            if table not in source_tables:
                continue
            create_table_from_source(source_conn, target_conn, table)
            target_tables.add(table)
        if is_fts_shadow_table(table):
            continue
        if is_virtual_table(source_conn, table):
            copy_virtual_table(source_conn, target_conn, table)
        else:
            copy_table_rows(source_conn, target_conn, table)
        create_indexes_from_source(source_conn, target_conn, table)


def table_names(conn: sqlite3.Connection) -> list[str]:
    return [
        str(row["name"])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    ]


def create_table_from_source(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, table: str) -> None:
    row = source_conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    sql = str(row["sql"] or "").strip() if row else ""
    if sql:
        target_conn.execute(sql)


def create_indexes_from_source(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, table: str) -> None:
    rows = source_conn.execute(
        """
        SELECT name, sql
        FROM sqlite_master
        WHERE type = 'index'
            AND tbl_name = ?
            AND sql IS NOT NULL
        ORDER BY name
        """,
        (table,),
    ).fetchall()
    for row in rows:
        sql = str(row["sql"] or "").strip()
        if sql:
            try:
                target_conn.execute(sql)
            except sqlite3.OperationalError as exc:
                if "already exists" not in str(exc).lower():
                    raise


def is_fts_shadow_table(table: str) -> bool:
    return table.endswith(("_config", "_content", "_data", "_docsize", "_idx"))


def is_virtual_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    sql = str(row["sql"] or "").lower() if row else ""
    return "create virtual table" in sql


def copy_virtual_table(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, table: str) -> None:
    columns = [row["name"] for row in source_conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    if not columns:
        return
    target_conn.execute(f'DELETE FROM "{table}"')
    column_sql = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})'
    cursor = source_conn.execute(f'SELECT {column_sql} FROM "{table}"')
    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break
        target_conn.executemany(insert_sql, [tuple(row[column] for column in columns) for row in rows])


def copy_table_rows(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection, table: str) -> None:
    source_columns = [row["name"] for row in source_conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    target_columns = [row["name"] for row in target_conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
    columns = [column for column in target_columns if column in source_columns]
    if not columns:
        return
    target_conn.execute(f'DELETE FROM "{table}"')
    column_sql = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    insert_sql = f'INSERT OR REPLACE INTO "{table}" ({column_sql}) VALUES ({placeholders})'
    cursor = source_conn.execute(f'SELECT {column_sql} FROM "{table}"')
    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break
        target_conn.executemany(insert_sql, [tuple(row[column] for column in columns) for row in rows])


def migrate_legacy_1688_materials(source_conn: sqlite3.Connection, target_conn: sqlite3.Connection) -> None:
    if "sourcing_materials_1688" not in table_names(source_conn):
        return
    now = utc_now_text()
    batch_id = "legacy-1688-materials-migrated"
    target_conn.execute(
        """
        INSERT INTO upload_batches (
            id, source_filename, saved_path, file_type, total_rows, imported_count,
            failed_count, status, error_message, created_at, updated_at
        ) VALUES (?, 'legacy_sourcing_materials_1688', '', 'legacy-1688-material-migration', 0, 0, 0, 'imported', NULL, ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (batch_id, now, now),
    )
    rows = source_conn.execute("SELECT * FROM sourcing_materials_1688 ORDER BY created_at ASC").fetchall()
    inserted = 0
    inserted_product_ids: list[str] = []
    for index, row in enumerate(rows, start=1):
        raw_data = parse_json(row["raw_data_json"], {})
        existing_product_id = str(row["product_list_product_id"] or "").strip()
        if existing_product_id and product_exists(target_conn, existing_product_id):
            continue
        assigned_product_id = str(row["assigned_product_id"] or "").strip()
        if assigned_product_id and product_exists(target_conn, assigned_product_id):
            continue

        source_type = source_type_from_material(row, raw_data)
        source_url = str(row["product_url"] or "").strip()
        source_product_id = source_product_identity(row["offer_id"], raw_data, source_url)
        if not source_product_id:
            continue
        exists = target_conn.execute(
            """
            SELECT id FROM products
            WHERE source_type = ? AND source_product_id = ?
            LIMIT 1
            """,
            (source_type, source_product_id),
        ).fetchone()
        if exists:
            continue

        category_path, category_level1, category_level2 = category_fields(raw_data)
        gallery_images = list_from_value(raw_data.get("gallery_image_urls"))
        main_image = str(row["main_image_url"] or "").strip() or (gallery_images[0] if gallery_images else None)
        if main_image and main_image not in gallery_images:
            gallery_images.insert(0, main_image)
        product_id = f"{source_type}-{safe_identifier(source_product_id)}"
        raw_product_data = {
            **raw_data,
            "_legacy_table": "sourcing_materials_1688",
            "_legacy_material_id": row["id"],
            "offer_id": row["offer_id"],
            "product_url": source_url,
            "shop_name": row["shop_name"],
            "shop_url": row["shop_url"],
            "price_range": row["price_range"],
            "moq": row["moq"],
        }
        target_conn.execute(
            """
            INSERT INTO products (
                id, upload_batch_id, source_row_index, source_type, source_product_id,
                catalog_scope, title_cn, title_en, title, main_image_url,
                gallery_image_urls_json, video_url, source_url, category_path,
                category_level1, category_level2, tags_json, price_usd, gmv_usd,
                weekly_sales, monthly_sales, review_count, listing_time, status,
                in_product_pool, raw_data_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pool_only', ?, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?, 'active', 1, ?, ?, ?)
            """,
            (
                product_id,
                batch_id,
                index,
                source_type,
                source_product_id,
                row["title"],
                row["title"],
                main_image,
                json.dumps(gallery_images, ensure_ascii=False),
                source_url,
                category_path,
                category_level1,
                category_level2,
                json.dumps(["1688", "legacy-material"], ensure_ascii=False),
                to_float(row["price"]),
                row["captured_at"] or row["created_at"] or now,
                json.dumps(raw_product_data, ensure_ascii=False),
                row["created_at"] or now,
                now,
            ),
        )
        inserted += 1
        inserted_product_ids.append(product_id)
    if inserted:
        target_conn.execute(
            """
            UPDATE upload_batches
            SET total_rows = ?, imported_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (inserted, inserted, now, batch_id),
        )
        add_products_to_default_pool(target_conn, inserted_product_ids, now)


def utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0, tzinfo=None).isoformat(sep=" ")


def product_exists(conn: sqlite3.Connection, product_id: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM products WHERE id = ? LIMIT 1", (product_id,)).fetchone())


def source_type_from_material(row: sqlite3.Row, raw_data: dict[str, Any]) -> str:
    source_site = str(raw_data.get("source_site") or "").strip().lower()
    if source_site in {"temu", "1688"}:
        return source_site
    product_url = str(row["product_url"] or "").lower()
    if "temu.com" in product_url:
        return "temu"
    return "1688"


def source_product_identity(offer_id: Any, raw_data: dict[str, Any], source_url: str) -> str:
    text = str(offer_id or raw_data.get("goods_id") or raw_data.get("product_id") or "").strip()
    if text:
        return text
    if source_url:
        return uuid.uuid5(uuid.NAMESPACE_URL, source_url).hex[:16]
    return ""


def add_products_to_default_pool(conn: sqlite3.Connection, product_ids: list[str], now: str) -> None:
    clean_ids = [product_id for product_id in product_ids if product_id]
    if not clean_ids:
        return
    conn.executemany(
        """
        INSERT INTO product_pool_memberships (user_id, product_id, status, created_at, updated_at)
        VALUES ('default-user', ?, 'active', ?, ?)
        ON CONFLICT(user_id, product_id) DO UPDATE SET
            status = 'active',
            updated_at = excluded.updated_at
        """,
        [(product_id, now, now) for product_id in clean_ids],
    )
    placeholders = ", ".join("?" for _ in clean_ids)
    conn.execute(
        f"""
        INSERT OR REPLACE INTO product_pool_products (
            id, upload_batch_id, source_row_index, source_type, source_product_id,
            catalog_scope, title_cn, title_en, title, main_image_url,
            gallery_image_urls_json, video_url, source_url, category_path,
            category_level1, category_level2, tags_json, price_usd, gmv_usd,
            weekly_sales, monthly_sales, review_count, listing_time, status,
            raw_data_json, created_at, updated_at
        )
        SELECT
            id, upload_batch_id, source_row_index, source_type, source_product_id,
            catalog_scope, title_cn, title_en, title, main_image_url,
            gallery_image_urls_json, video_url, source_url, category_path,
            category_level1, category_level2, tags_json, price_usd, gmv_usd,
            weekly_sales, monthly_sales, review_count, listing_time, status,
            raw_data_json, ?, ?
        FROM products
        WHERE id IN ({placeholders})
        """,
        [now, now, *clean_ids],
    )


def safe_identifier(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value).strip("-")
    return safe or uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:16]


def category_fields(raw_data: dict[str, Any]) -> tuple[str, str, str | None]:
    for key in ("category_parts", "category_path"):
        parts = list_from_value(raw_data.get(key))
        if parts:
            cleaned = [str(part).strip() for part in parts if str(part).strip()]
            if cleaned:
                return "/".join(cleaned), cleaned[0], cleaned[1] if len(cleaned) > 1 else None
    return UNCATEGORIZED_CATEGORY, UNCATEGORIZED_CATEGORY, None


def list_from_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            loaded = json.loads(text)
            if isinstance(loaded, list):
                return [str(item).strip() for item in loaded if str(item).strip()]
        except ValueError:
            pass
        separator = "/" if "/" in text else ">"
        return [part.strip() for part in text.split(separator) if part.strip()]
    return []


def parse_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except ValueError:
        return fallback


def to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def normalize_ingest_product_targets(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE ingest_items
        SET entity_type = 'product',
            target_table = CASE
                WHEN target_table = 'sourcing_materials_1688' THEN 'products'
                ELSE target_table
            END
        WHERE entity_type IN ('sourcing_material', 'sourcing_materials', 'material', 'materials')
           OR target_table = 'sourcing_materials_1688'
        """
    )
    conn.execute(
        """
        UPDATE ingest_batches
        SET entity_type = 'product',
            target_table = CASE
                WHEN target_table = 'sourcing_materials_1688' THEN 'products'
                ELSE target_table
            END
        WHERE entity_type IN ('sourcing_material', 'sourcing_materials', 'material', 'materials')
           OR target_table = 'sourcing_materials_1688'
        """
    )


def rebuild_indexes(conn: sqlite3.Connection) -> None:
    from app.core.database import refresh_product_category_matches
    from app.modules.recommendation.keyword_index import replace_product_keyword_index, row_to_product_dict

    now = utc_now_text()
    rows = conn.execute(
        """
        SELECT
            id, title, title_cn, title_en, category_path, category_level1,
            category_level2, tags_json, raw_data_json, source_type
        FROM products
        WHERE status != 'deleted'
        """
    ).fetchall()
    products = [row_to_product_dict(row) for row in rows]
    replace_product_keyword_index(conn, products, now=now)
    refresh_product_category_matches(conn, products, now=now)


def vacuum_database(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA optimize")
    conn.execute("VACUUM")


def replace_active_database(database_path: Path, tmp_path: Path) -> None:
    sidecar_paths = [
        database_path.with_suffix(database_path.suffix + "-wal"),
        database_path.with_suffix(database_path.suffix + "-shm"),
    ]
    for sidecar in sidecar_paths:
        if sidecar.exists():
            sidecar.unlink()
    replace_backup = database_path.with_name(
        f"{database_path.stem}.pre_replace_{datetime.now().strftime('%Y%m%d_%H%M%S')}{database_path.suffix}"
    )
    shutil.move(str(database_path), str(replace_backup))
    try:
        move_with_retries(tmp_path, database_path)
    except Exception:
        if not database_path.exists() and replace_backup.exists():
            shutil.move(str(replace_backup), str(database_path))
        raise
    print(f"Original active DB moved to: {replace_backup}")


def move_with_retries(source: Path, target: Path) -> None:
    last_error: Exception | None = None
    for _ in range(10):
        try:
            shutil.move(str(source), str(target))
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error:
        raise last_error


def validate_database(path: Path) -> dict[str, Any]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        counts = {}
        for table in sorted(FINAL_TABLES):
            if table in table_names(conn):
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        product_sources = [
            dict(row)
            for row in conn.execute(
                """
                SELECT source_type, catalog_scope, COUNT(*) AS count
                FROM products
                GROUP BY source_type, catalog_scope
                ORDER BY source_type, catalog_scope
                """
            ).fetchall()
        ]
        source_specific_product_rows = counts.get("sourcing_materials_1688", 0)
        return {
            "path": str(path),
            "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
            "integrity_check": integrity,
            "table_count": len(table_names(conn)),
            "counts": counts,
            "product_sources": product_sources,
            "legacy_sourcing_material_rows": source_specific_product_rows,
        }


if __name__ == "__main__":
    main()
