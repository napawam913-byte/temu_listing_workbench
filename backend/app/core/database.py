from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import sqlite3
import secrets
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from app.modules.creative_generation.sensitive_terms_catalog import DEFAULT_SENSITIVE_TERMS
from app.modules.recommendation.keyword_index import ensure_recommendation_schema, replace_product_keyword_index

from . import config as app_config
from .config import DATABASE_PATH, UPLOADS_DIR, WORKBENCH_DEFAULT_PASSWORD, WORKBENCH_DEFAULT_USERNAME, ensure_runtime_dirs


DEFAULT_USER_ID = "default-user"
CANONICAL_CATEGORY_PROVIDER = "dxm_temu"
CATEGORY_AUTO_THRESHOLD = 0.82
CATEGORY_REVIEW_THRESHOLD = 0.65
MAPPING_STOP_TERMS = {
    "and",
    "or",
    "the",
    "with",
    "for",
    "other",
    "others",
    "\u5176\u4ed6",
    "\u7528\u54c1",
    "\u4ea7\u54c1",
    "\u5546\u54c1",
    "\u914d\u4ef6",
    "\u7c7b",
}


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

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_user_sessions_user
                ON user_sessions(user_id, status);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'general',
                label TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                is_secret INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT,
                FOREIGN KEY(updated_by) REFERENCES users(id)
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

            CREATE TABLE IF NOT EXISTS product_pool_memberships (
                user_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, product_id),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(product_id) REFERENCES products(id)
            );

            CREATE INDEX IF NOT EXISTS idx_product_pool_memberships_user_status
                ON product_pool_memberships(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_product_pool_memberships_product
                ON product_pool_memberships(product_id);

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
        ensure_api_usage_schema(conn)
        ensure_column(conn, "products", "source_type", "source_type TEXT NOT NULL DEFAULT 'yunqi'")
        ensure_column(conn, "products", "in_product_pool", "in_product_pool INTEGER NOT NULL DEFAULT 1")
        ensure_link_list_schema(conn)
        ensure_export_product_attribute_schema(conn)
        seed_default_user(conn)
        ensure_product_identity_index(conn)
        ensure_yunqi_category_schema(conn)
        ensure_category_mapping_schema(conn)
        sync_canonical_categories_from_dxm(conn)
        seed_product_pool_from_legacy_flag(conn)
        seed_product_pool_memberships_from_legacy(conn)
        ensure_recommendation_schema(conn)
        seed_default_sensitive_terms(conn)


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def ensure_api_usage_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS api_usage_logs (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            provider TEXT NOT NULL DEFAULT '',
            api_type TEXT NOT NULL DEFAULT '',
            stage TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            call_count INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'success',
            source TEXT NOT NULL DEFAULT 'runtime-log',
            related_id TEXT,
            error_message TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_model
            ON api_usage_logs(provider, api_type, stage, model);
        CREATE INDEX IF NOT EXISTS idx_api_usage_logs_created
            ON api_usage_logs(created_at);
        """
    )


def record_api_usage(
    *,
    provider: str,
    api_type: str,
    stage: str,
    model: str,
    user_id: str | None = None,
    call_count: int = 1,
    status: str = "success",
    source: str = "runtime-log",
    related_id: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now_text()
    usage_id = uuid.uuid4().hex
    clean_status = str(status or "success").strip().lower()
    if clean_status not in {"success", "failed"}:
        clean_status = "success"
    with get_connection() as conn:
        ensure_api_usage_schema(conn)
        conn.execute(
            """
            INSERT INTO api_usage_logs (
                id, user_id, provider, api_type, stage, model, call_count, status, source,
                related_id, error_message, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                usage_id,
                clean_text(user_id),
                clean_text(provider),
                clean_text(api_type),
                clean_text(stage),
                clean_text(model) or "unknown",
                max(1, int(call_count or 1)),
                clean_status,
                clean_text(source) or "runtime-log",
                clean_text(related_id),
                clean_text(error_message)[:2000] or None,
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM api_usage_logs WHERE id = ?", (usage_id,)).fetchone()
    return api_usage_log_row_to_api(row)


def get_api_usage_summary() -> dict[str, Any]:
    with get_connection() as conn:
        ensure_api_usage_schema(conn)
        exact_rows = conn.execute(
            """
            SELECT
                provider,
                api_type,
                stage,
                model,
                source,
                SUM(call_count) AS call_count,
                SUM(CASE WHEN status = 'success' THEN call_count ELSE 0 END) AS success_count,
                SUM(CASE WHEN status = 'failed' THEN call_count ELSE 0 END) AS failed_count,
                MAX(updated_at) AS last_called_at
            FROM api_usage_logs
            GROUP BY provider, api_type, stage, model, source
            """
        ).fetchall()
        items = [api_usage_summary_row_to_api(row, is_inferred=False) for row in exact_rows]
        items.extend(infer_api_usage_summary(conn))

    merged = merge_api_usage_items(items)
    total_calls = sum(int(item["callCount"] or 0) for item in merged)
    exact_calls = sum(int(item["callCount"] or 0) for item in merged if not item["isInferred"])
    inferred_calls = total_calls - exact_calls
    return {
        "items": merged,
        "totalCalls": total_calls,
        "exactCalls": exact_calls,
        "inferredCalls": inferred_calls,
    }


def infer_api_usage_summary(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if sqlite_table_exists(conn, "product_ai_analysis_cache"):
        rows = conn.execute(
            """
            SELECT model, COUNT(*) AS call_count, MAX(updated_at) AS last_called_at
            FROM product_ai_analysis_cache
            WHERE model != '' AND model != 'rule-fallback'
            GROUP BY model
            """
        ).fetchall()
        for row in rows:
            items.append(
                make_api_usage_summary_item(
                    provider="openai-compatible",
                    api_type="chat",
                    stage="recommendation",
                    model=row["model"],
                    call_count=int(row["call_count"] or 0),
                    success_count=int(row["call_count"] or 0),
                    failed_count=0,
                    last_called_at=row["last_called_at"],
                    source="inferred-cache",
                    is_inferred=True,
                    notes="from product_ai_analysis_cache rows",
                )
            )

    if sqlite_table_exists(conn, "visual_generation_tasks"):
        visual_counts = infer_visual_task_api_usage(conn)
        items.extend(visual_counts)
    return items


def infer_visual_task_api_usage(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    settings = read_setting_values(conn)
    analysis_model = runtime_setting_value(settings, "OPENAI_VISUAL_ANALYSIS_MODEL", "OPENAI_TEXT_MODEL", "gpt-5.5")
    prompt_model = runtime_setting_value(settings, "OPENAI_VISUAL_PROMPT_MODEL", "OPENAI_TEXT_MODEL", "gpt-5.5")
    image_model = runtime_setting_value(settings, "OPENAI_IMAGE_MODEL", "", "gpt-image-2")
    rows = conn.execute(
        """
        SELECT status, analysis_json, mother_image_path, mother_image_url, updated_at
        FROM visual_generation_tasks
        WHERE status != 'draft'
        """
    ).fetchall()
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        last_called_at = row["updated_at"]
        analysis = parse_json_text(row["analysis_json"], {})
        if isinstance(analysis, dict) and analysis:
            add_inferred_usage_count(counts, "visual-analysis", analysis_model, last_called_at)
            add_inferred_usage_count(counts, "visual-prompt", prompt_model, last_called_at)
        if row["mother_image_path"] or row["mother_image_url"] or row["status"] in {"split", "completed"}:
            add_inferred_usage_count(counts, "visual-image", image_model, last_called_at, api_type="image")

    return [
        make_api_usage_summary_item(
            provider="openai-compatible",
            api_type=value["apiType"],
            stage=stage,
            model=model,
            call_count=value["callCount"],
            success_count=value["callCount"],
            failed_count=0,
            last_called_at=value["lastCalledAt"],
            source="inferred-visual-task",
            is_inferred=True,
            notes="from visual_generation_tasks state",
        )
        for (stage, model), value in counts.items()
    ]


def add_inferred_usage_count(
    counts: dict[tuple[str, str], dict[str, Any]],
    stage: str,
    model: str,
    last_called_at: str | None,
    *,
    api_type: str = "chat",
) -> None:
    key = (stage, model or "unknown")
    current = counts.setdefault(key, {"apiType": api_type, "callCount": 0, "lastCalledAt": None})
    current["callCount"] += 1
    if last_called_at and (not current["lastCalledAt"] or last_called_at > current["lastCalledAt"]):
        current["lastCalledAt"] = last_called_at


def merge_api_usage_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = (
            item["provider"],
            item["apiType"],
            item["stage"],
            item["model"],
            item["source"],
        )
        current = merged.get(key)
        if not current:
            merged[key] = dict(item)
            continue
        current["callCount"] += item["callCount"]
        current["successCount"] += item["successCount"]
        current["failedCount"] += item["failedCount"]
        last_called_at = item.get("lastCalledAt")
        if last_called_at and (not current.get("lastCalledAt") or last_called_at > current["lastCalledAt"]):
            current["lastCalledAt"] = last_called_at
    return sorted(
        merged.values(),
        key=lambda item: (-int(item["callCount"] or 0), item["model"], item["stage"], item["source"]),
    )


def api_usage_log_row_to_api(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "provider": row["provider"],
        "apiType": row["api_type"],
        "stage": row["stage"],
        "model": row["model"],
        "callCount": int(row["call_count"] or 0),
        "status": row["status"],
        "source": row["source"],
        "relatedId": row["related_id"],
        "errorMessage": row["error_message"],
        "metadata": parse_json_text(row["metadata_json"], {}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def api_usage_summary_row_to_api(row: sqlite3.Row, *, is_inferred: bool) -> dict[str, Any]:
    return make_api_usage_summary_item(
        provider=row["provider"],
        api_type=row["api_type"],
        stage=row["stage"],
        model=row["model"],
        call_count=int(row["call_count"] or 0),
        success_count=int(row["success_count"] or 0),
        failed_count=int(row["failed_count"] or 0),
        last_called_at=row["last_called_at"],
        source=row["source"],
        is_inferred=is_inferred,
    )


def make_api_usage_summary_item(
    *,
    provider: str,
    api_type: str,
    stage: str,
    model: str,
    call_count: int,
    success_count: int,
    failed_count: int,
    last_called_at: str | None,
    source: str,
    is_inferred: bool,
    notes: str = "",
) -> dict[str, Any]:
    return {
        "id": "|".join([provider or "unknown", api_type or "unknown", stage or "unknown", model or "unknown", source or "unknown"]),
        "provider": provider or "unknown",
        "apiType": api_type or "unknown",
        "stage": stage or "unknown",
        "model": model or "unknown",
        "callCount": int(call_count or 0),
        "successCount": int(success_count or 0),
        "failedCount": int(failed_count or 0),
        "lastCalledAt": last_called_at,
        "source": source or "runtime-log",
        "isInferred": is_inferred,
        "notes": notes,
    }


def sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def read_setting_values(conn: sqlite3.Connection) -> dict[str, str]:
    if not sqlite_table_exists(conn, "app_settings"):
        return {}
    rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: str(row["value"] or "") for row in rows}


def runtime_setting_value(settings: dict[str, str], key: str, fallback_key: str, default: str) -> str:
    value = settings.get(key) or os.getenv(key, "").strip()
    if value:
        return value
    if fallback_key:
        value = settings.get(fallback_key) or os.getenv(fallback_key, "").strip() or str(getattr(app_config, fallback_key, "") or "")
        if value:
            return value
    return str(getattr(app_config, key, "") or default).strip() or default


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def parse_json_text(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


def ensure_link_list_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS link_list_records (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default-user',
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
    ensure_column(conn, "link_list_records", "user_id", "user_id TEXT NOT NULL DEFAULT 'default-user'")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_link_list_records_user_status
            ON link_list_records(user_id, status)
        """
    )


def ensure_export_product_attribute_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS export_product_attribute_jobs (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL DEFAULT 'default-user',
            link_record_id TEXT NOT NULL,
            product_id TEXT,
            product_title TEXT,
            category_id TEXT,
            category_path TEXT,
            product_attribute_text TEXT NOT NULL DEFAULT '',
            product_attributes_json TEXT NOT NULL DEFAULT '{}',
            record_hash TEXT NOT NULL DEFAULT '',
            record_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'queued',
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_export_attr_jobs_user_status
            ON export_product_attribute_jobs(user_id, status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_export_attr_jobs_record
            ON export_product_attribute_jobs(user_id, link_record_id, record_hash);
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


def ensure_category_mapping_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS canonical_categories (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'dxm_temu',
            external_category_id TEXT NOT NULL DEFAULT '',
            parent_id TEXT,
            level INTEGER NOT NULL DEFAULT 1,
            name TEXT NOT NULL,
            path_text TEXT NOT NULL,
            path_parts_json TEXT NOT NULL DEFAULT '[]',
            embedding_text TEXT NOT NULL DEFAULT '',
            embedding_json TEXT NOT NULL DEFAULT '{}',
            attr_count INTEGER NOT NULL DEFAULT 0,
            required_count INTEGER NOT NULL DEFAULT 0,
            source_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_categories_provider_path
            ON canonical_categories(provider, path_text);
        CREATE INDEX IF NOT EXISTS idx_canonical_categories_parent
            ON canonical_categories(parent_id);
        CREATE INDEX IF NOT EXISTS idx_canonical_categories_provider_status
            ON canonical_categories(provider, status);
        CREATE INDEX IF NOT EXISTS idx_canonical_categories_external_id
            ON canonical_categories(provider, external_category_id);

        CREATE TABLE IF NOT EXISTS product_category_matches (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT '',
            source_category_path TEXT NOT NULL DEFAULT '',
            source_title TEXT NOT NULL DEFAULT '',
            canonical_category_id TEXT,
            canonical_category_path TEXT NOT NULL DEFAULT '',
            match_score REAL NOT NULL DEFAULT 0,
            match_method TEXT NOT NULL DEFAULT 'unmatched',
            status TEXT NOT NULL DEFAULT 'unmatched',
            candidates_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id),
            FOREIGN KEY(canonical_category_id) REFERENCES canonical_categories(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_product_category_matches_product
            ON product_category_matches(product_id);
        CREATE INDEX IF NOT EXISTS idx_product_category_matches_category
            ON product_category_matches(canonical_category_id, status);
        CREATE INDEX IF NOT EXISTS idx_product_category_matches_status
            ON product_category_matches(status);
        """
    )


def sync_canonical_categories_from_dxm(conn: sqlite3.Connection, *, force: bool = False) -> int:
    ensure_category_mapping_schema(conn)
    if not force and canonical_category_count(conn) > 0:
        return 0
    if not sqlite_table_exists(conn, "dxm_temu_category_attr_snapshots"):
        return 0

    try:
        rows = conn.execute(
            """
            SELECT
                category_id, category_path_text, category_path_json, node_path_id,
                category_depth, level1_id, level1_name, level2_id, level2_name,
                level3_id, level3_name, level4_id, level4_name, level5_id,
                level5_name, level6_id, level6_name, leaf_name, attr_count,
                required_count, collection_status
            FROM dxm_temu_category_attr_snapshots
            WHERE category_path_text IS NOT NULL
                AND category_path_text != ''
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return 0

    now = utc_now_text()
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        parts = dxm_snapshot_path_parts(row)
        if not parts:
            continue
        path_ids = dxm_snapshot_path_ids(row)
        leaf_level = len(parts)
        for index in range(leaf_level):
            level = index + 1
            prefix_parts = parts[:level]
            path_text = normalize_category_path_text("/".join(prefix_parts))
            if not path_text:
                continue
            category_id = canonical_category_id(CANONICAL_CATEGORY_PROVIDER, path_text)
            parent_path = normalize_category_path_text("/".join(prefix_parts[:-1])) if level > 1 else ""
            parent_id = canonical_category_id(CANONICAL_CATEGORY_PROVIDER, parent_path) if parent_path else None
            external_id = path_ids[index] if index < len(path_ids) else ""
            if level == leaf_level:
                external_id = clean_text(row["category_id"]) or external_id
            attr_count = int(row["attr_count"] or 0) if level == leaf_level else 0
            required_count = int(row["required_count"] or 0) if level == leaf_level else 0
            embedding_text = build_category_embedding_text(prefix_parts, row if level == leaf_level else None)
            existing = records.get(category_id)
            if existing:
                existing["attr_count"] = max(int(existing["attr_count"] or 0), attr_count)
                existing["required_count"] = max(int(existing["required_count"] or 0), required_count)
                if external_id and not existing["external_category_id"]:
                    existing["external_category_id"] = external_id
                continue

            records[category_id] = {
                "id": category_id,
                "provider": CANONICAL_CATEGORY_PROVIDER,
                "external_category_id": external_id,
                "parent_id": parent_id,
                "level": level,
                "name": clean_text(prefix_parts[-1]),
                "path_text": path_text,
                "path_parts_json": json.dumps(prefix_parts, ensure_ascii=False),
                "embedding_text": embedding_text,
                "embedding_json": json.dumps(build_text_vector(embedding_text), ensure_ascii=False, sort_keys=True),
                "attr_count": attr_count,
                "required_count": required_count,
                "source_hash": hashlib.sha1(
                    f"{CANONICAL_CATEGORY_PROVIDER}:{path_text}:{external_id}".encode("utf-8")
                ).hexdigest(),
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }

    if not records:
        return 0

    conn.executemany(
        """
        INSERT INTO canonical_categories (
            id, provider, external_category_id, parent_id, level, name, path_text,
            path_parts_json, embedding_text, embedding_json, attr_count, required_count,
            source_hash, status, created_at, updated_at
        ) VALUES (
            :id, :provider, :external_category_id, :parent_id, :level, :name, :path_text,
            :path_parts_json, :embedding_text, :embedding_json, :attr_count, :required_count,
            :source_hash, :status, :created_at, :updated_at
        )
        ON CONFLICT(id) DO UPDATE SET
            external_category_id = CASE
                WHEN excluded.external_category_id != '' THEN excluded.external_category_id
                ELSE canonical_categories.external_category_id
            END,
            parent_id = excluded.parent_id,
            level = excluded.level,
            name = excluded.name,
            path_text = excluded.path_text,
            path_parts_json = excluded.path_parts_json,
            embedding_text = excluded.embedding_text,
            embedding_json = excluded.embedding_json,
            attr_count = MAX(canonical_categories.attr_count, excluded.attr_count),
            required_count = MAX(canonical_categories.required_count, excluded.required_count),
            source_hash = excluded.source_hash,
            status = 'active',
            updated_at = excluded.updated_at
        """,
        list(records.values()),
    )
    return len(records)


def canonical_category_count(conn: sqlite3.Connection) -> int:
    if not sqlite_table_exists(conn, "canonical_categories"):
        return 0
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM canonical_categories
        WHERE provider = ? AND status = 'active'
        """,
        (CANONICAL_CATEGORY_PROVIDER,),
    ).fetchone()
    return int(row["count"] or 0) if row else 0


def canonical_category_id(provider: str, path_text: str) -> str:
    normalized = normalize_category_path_text(path_text)
    return uuid.uuid5(uuid.NAMESPACE_URL, f"canonical-category:{provider}:{normalized}").hex


def dxm_snapshot_path_parts(row: sqlite3.Row) -> list[str]:
    parts = parse_category_path_parts(row["category_path_json"], row["category_path_text"])
    if not parts:
        parts = [clean_text(row[f"level{level}_name"]) for level in range(1, 7) if clean_text(row[f"level{level}_name"])]
    return [part for part in parts if part]


def dxm_snapshot_path_ids(row: sqlite3.Row) -> list[str]:
    node_path_id = clean_text(row["node_path_id"])
    parts = [part for part in re.split(r"[/>\s,]+", node_path_id) if clean_text(part)]
    if parts:
        return parts
    return [clean_text(row[f"level{level}_id"]) for level in range(1, 7) if clean_text(row[f"level{level}_id"])]


def build_category_embedding_text(path_parts: list[str], row: sqlite3.Row | None = None) -> str:
    values = list(path_parts)
    if row is not None:
        values.extend(
            [
                clean_text(row["leaf_name"]),
                clean_text(row["category_id"]),
                f"attr_count:{int(row['attr_count'] or 0)}",
                f"required_count:{int(row['required_count'] or 0)}",
            ]
        )
    return clean_text(" ".join(value for value in values if clean_text(value)))


def normalize_category_path_text(value: Any) -> str:
    return "/".join(category_path_parts_from_text(value))


def category_path_parts_from_text(value: Any) -> list[str]:
    return [part for part in re.split(r"[/>\u203a\u300b]+", clean_text(value)) if clean_text(part)]


def build_text_vector(value: Any) -> dict[str, float]:
    terms = extract_mapping_terms(value)
    vector: dict[str, float] = {}
    for term in terms:
        vector[term] = vector.get(term, 0.0) + 1.0
    for alias_group in CATEGORY_ALIAS_GROUPS:
        if any(term in vector for term in alias_group):
            for alias in alias_group:
                vector[alias] = max(vector.get(alias, 0.0), 0.35)
    return vector


CATEGORY_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("garden", "gardening", "lawn", "yard", "patio", "\u82b1\u56ed", "\u56ed\u827a", "\u5ead\u9662", "\u8349\u576a"),
    ("pet", "pets", "dog", "cat", "bird", "\u5ba0\u7269", "\u72d7", "\u732b", "\u9e1f"),
    ("home", "household", "decor", "decoration", "\u5bb6\u5c45", "\u88c5\u9970", "\u6446\u4ef6"),
    ("jewelry", "necklace", "bracelet", "ring", "\u9970\u54c1", "\u9996\u9970", "\u9879\u94fe", "\u624b\u94fe", "\u6212\u6307"),
    ("kitchen", "cook", "cooking", "\u53a8\u623f", "\u70f9\u996a"),
    ("baby", "kids", "children", "\u5a74\u513f", "\u513f\u7ae5", "\u5b69\u5b50"),
    ("office", "school", "book", "media", "\u529e\u516c", "\u5b66\u6821", "\u4e66\u7c4d", "\u5a92\u4f53"),
    ("health", "beauty", "\u5065\u5eb7", "\u7f8e\u5bb9"),
)


def extract_mapping_terms(value: Any) -> list[str]:
    text = clean_text(value).lower()
    terms: list[str] = []
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9][a-z0-9&+.#-]{1,}", text):
        term = normalize_mapping_term(chunk)
        if not term:
            continue
        terms.append(term)
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 4:
            terms.extend(chinese_mapping_ngrams(term))
    return unique_mapping_terms(terms)


def chinese_mapping_ngrams(value: str) -> list[str]:
    terms: list[str] = []
    max_size = min(6, len(value))
    for size in range(max_size, 1, -1):
        for index in range(0, len(value) - size + 1):
            term = normalize_mapping_term(value[index : index + size])
            if term:
                terms.append(term)
    return terms[:50]


def normalize_mapping_term(value: Any) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9&+.#-]+", "", clean_text(value).lower()).strip()


def unique_mapping_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        term = normalize_mapping_term(value)
        if not term or term in seen or len(term) > 40:
            continue
        seen.add(term)
        result.append(term)
    return result


def seed_default_user(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if existing:
        return

    salt, password_hash = hash_password(WORKBENCH_DEFAULT_PASSWORD)
    now = utc_now_text()
    conn.execute(
        """
        INSERT INTO users (
            id, username, display_name, password_hash, password_salt, role, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'admin', 'active', ?, ?)
        """,
        (
            DEFAULT_USER_ID,
            WORKBENCH_DEFAULT_USERNAME,
            WORKBENCH_DEFAULT_USERNAME,
            password_hash,
            salt,
            now,
            now,
        ),
    )


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    clean_password = str(password or "")
    password_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", clean_password.encode("utf-8"), password_salt.encode("utf-8"), 120_000)
    return password_salt, digest.hex()


def verify_password(password: str, *, salt: str, password_hash: str) -> bool:
    _, candidate_hash = hash_password(password, salt)
    return hmac.compare_digest(candidate_hash, password_hash)


def public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"] or row["username"],
        "role": row["role"],
        "status": row["status"],
    }


def create_user(username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    clean_username = " ".join(str(username or "").split()).strip()
    if len(clean_username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")

    salt, password_hash = hash_password(password)
    now = utc_now_text()
    user_id = uuid.uuid4().hex
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, password_salt, role, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'user', 'active', ?, ?)
                """,
                (
                    user_id,
                    clean_username,
                    " ".join(str(display_name or clean_username).split()).strip(),
                    password_hash,
                    salt,
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise ValueError("用户名已存在") from exc

    return public_user(row)


def list_users() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                users.*,
                COUNT(CASE WHEN user_sessions.status = 'active' THEN 1 END) AS active_session_count
            FROM users
            LEFT JOIN user_sessions ON user_sessions.user_id = users.id
            GROUP BY users.id
            ORDER BY users.created_at ASC
            """
        ).fetchall()
    return [admin_public_user(row) for row in rows]


def admin_public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"] or row["username"],
        "role": row["role"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "activeSessionCount": int(row["active_session_count"] or 0) if "active_session_count" in row.keys() else 0,
    }


def create_managed_user(
    *,
    username: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
    status: str = "active",
) -> dict[str, Any]:
    clean_username = " ".join(str(username or "").split()).strip()
    if len(clean_username) < 2:
        raise ValueError("用户名至少需要 2 个字符")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")
    clean_role = normalize_user_role(role)
    clean_status = normalize_user_status(status)

    salt, password_hash = hash_password(password)
    now = utc_now_text()
    user_id = uuid.uuid4().hex
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (
                    id, username, display_name, password_hash, password_salt, role, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    clean_username,
                    " ".join(str(display_name or clean_username).split()).strip(),
                    password_hash,
                    salt,
                    clean_role,
                    clean_status,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT users.*, 0 AS active_session_count
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise ValueError("用户名已存在") from exc

    return admin_public_user(row)


def update_managed_user(
    user_id: str,
    *,
    display_name: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        raise ValueError("缺少用户 ID")

    updates: list[str] = []
    params: list[Any] = []
    if display_name is not None:
        updates.append("display_name = ?")
        params.append(" ".join(str(display_name).split()).strip())
    if role is not None:
        clean_role = normalize_user_role(role)
        updates.append("role = ?")
        params.append(clean_role)
    if status is not None:
        clean_status = normalize_user_status(status)
        updates.append("status = ?")
        params.append(clean_status)
    if not updates:
        with get_connection() as conn:
            row = fetch_admin_user_row(conn, clean_user_id)
        if not row:
            raise ValueError("用户不存在")
        return admin_public_user(row)

    now = utc_now_text()
    updates.append("updated_at = ?")
    params.append(now)
    params.append(clean_user_id)

    with get_connection() as conn:
        existing = conn.execute("SELECT * FROM users WHERE id = ?", (clean_user_id,)).fetchone()
        if not existing:
            raise ValueError("用户不存在")
        next_role = normalize_user_role(role) if role is not None else existing["role"]
        next_status = normalize_user_status(status) if status is not None else existing["status"]
        if existing["role"] == "admin" and (next_role != "admin" or next_status != "active"):
            active_admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active'"
            ).fetchone()[0]
            if active_admin_count <= 1:
                raise ValueError("至少需要保留一个启用中的管理员")

        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        if status is not None and next_status != "active":
            conn.execute(
                "UPDATE user_sessions SET status = 'revoked', updated_at = ? WHERE user_id = ? AND status = 'active'",
                (now, clean_user_id),
            )
        row = fetch_admin_user_row(conn, clean_user_id)
    return admin_public_user(row)


def reset_managed_user_password(user_id: str, password: str) -> dict[str, Any]:
    clean_user_id = str(user_id or "").strip()
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")

    salt, password_hash = hash_password(password)
    now = utc_now_text()
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id = ?", (clean_user_id,)).fetchone()
        if not existing:
            raise ValueError("用户不存在")
        conn.execute(
            """
            UPDATE users
            SET password_salt = ?, password_hash = ?, updated_at = ?
            WHERE id = ?
            """,
            (salt, password_hash, now, clean_user_id),
        )
        conn.execute(
            "UPDATE user_sessions SET status = 'revoked', updated_at = ? WHERE user_id = ? AND status = 'active'",
            (now, clean_user_id),
        )
        row = fetch_admin_user_row(conn, clean_user_id)
    return admin_public_user(row)


def fetch_admin_user_row(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            users.*,
            COUNT(CASE WHEN user_sessions.status = 'active' THEN 1 END) AS active_session_count
        FROM users
        LEFT JOIN user_sessions ON user_sessions.user_id = users.id
        WHERE users.id = ?
        GROUP BY users.id
        """,
        (user_id,),
    ).fetchone()


def normalize_user_role(value: str) -> str:
    clean_value = str(value or "user").strip().lower()
    if clean_value not in {"admin", "user"}:
        raise ValueError("角色只能是 admin 或 user")
    return clean_value


def normalize_user_status(value: str) -> str:
    clean_value = str(value or "active").strip().lower()
    if clean_value not in {"active", "disabled"}:
        raise ValueError("状态只能是 active 或 disabled")
    return clean_value


def get_app_settings_map() -> dict[str, dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM app_settings").fetchall()
    return {
        row["key"]: {
            "key": row["key"],
            "value": row["value"],
            "category": row["category"],
            "label": row["label"],
            "description": row["description"],
            "isSecret": bool(row["is_secret"]),
            "updatedAt": row["updated_at"],
            "updatedBy": row["updated_by"],
        }
        for row in rows
    }


def get_app_setting_value(key: str, default: str = "") -> str:
    clean_key = str(key or "").strip()
    if not clean_key:
        return default
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (clean_key,)).fetchone()
    except sqlite3.Error:
        return default
    return str(row["value"]) if row else default


def upsert_app_setting(
    *,
    key: str,
    value: str,
    category: str = "general",
    label: str = "",
    description: str = "",
    is_secret: bool = False,
    updated_by: str | None = None,
) -> dict[str, Any]:
    clean_key = str(key or "").strip()
    if not clean_key:
        raise ValueError("缺少配置 key")
    now = utc_now_text()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, category, label, description, is_secret, created_at, updated_at, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                category = excluded.category,
                label = excluded.label,
                description = excluded.description,
                is_secret = excluded.is_secret,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                clean_key,
                str(value or ""),
                str(category or "general"),
                str(label or ""),
                str(description or ""),
                1 if is_secret else 0,
                now,
                now,
                updated_by,
            ),
        )
        row = conn.execute("SELECT * FROM app_settings WHERE key = ?", (clean_key,)).fetchone()
    return {
        "key": row["key"],
        "value": row["value"],
        "category": row["category"],
        "label": row["label"],
        "description": row["description"],
        "isSecret": bool(row["is_secret"]),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
    }


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    clean_username = " ".join(str(username or "").split()).strip()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? AND status = 'active'",
            (clean_username,),
        ).fetchone()
    if not row:
        return None
    if not verify_password(password, salt=row["password_salt"], password_hash=row["password_hash"]):
        return None
    return public_user(row)


def create_user_session(user_id: str) -> dict[str, Any]:
    token = secrets.token_urlsafe(32)
    now = utc_now_text()
    with get_connection() as conn:
        user_row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
        if not user_row:
            raise ValueError("用户不存在或已停用")
        conn.execute(
            """
            INSERT INTO user_sessions (token, user_id, status, created_at, updated_at, last_seen_at)
            VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (token, user_id, now, now, now),
        )
    return {"token": token, "user": public_user(user_row)}


def get_user_by_session_token(token: str) -> dict[str, Any] | None:
    clean_token = str(token or "").strip()
    if not clean_token:
        return None

    now = utc_now_text()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT users.*
            FROM user_sessions
            JOIN users ON users.id = user_sessions.user_id
            WHERE user_sessions.token = ?
                AND user_sessions.status = 'active'
                AND users.status = 'active'
            """,
            (clean_token,),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE user_sessions
                SET last_seen_at = ?, updated_at = ?
                WHERE token = ?
                """,
                (now, now, clean_token),
            )
    return public_user(row) if row else None


def revoke_user_session(token: str) -> bool:
    clean_token = str(token or "").strip()
    if not clean_token:
        return False
    now = utc_now_text()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE user_sessions
            SET status = 'revoked', updated_at = ?
            WHERE token = ? AND status = 'active'
            """,
            (now, clean_token),
        )
    return cursor.rowcount > 0


def seed_product_pool_memberships_from_legacy(conn: sqlite3.Connection) -> None:
    existing_count = conn.execute("SELECT COUNT(*) FROM product_pool_memberships").fetchone()[0]
    if existing_count:
        return

    legacy_ids = [
        row["id"]
        for row in conn.execute(
            """
            SELECT id
            FROM product_pool_products
            WHERE status != 'deleted'
            """
        ).fetchall()
    ]
    if not legacy_ids:
        legacy_ids = [
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
    copy_products_to_pool(conn, legacy_ids, user_id=DEFAULT_USER_ID)


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


def replace_products(batch_id: str, products: list[dict[str, Any]], *, add_to_pool_user_id: str | None = DEFAULT_USER_ID) -> None:
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
        refresh_product_category_matches(conn, products, now=now)
        if add_to_pool_user_id:
            copy_products_to_pool(conn, [product["id"] for product in products], user_id=add_to_pool_user_id, now=now)


def product_table_for_scope(scope: str) -> str:
    return "products" if scope == "all" else "product_pool_products"


def copy_products_to_pool(
    conn: sqlite3.Connection,
    product_ids: list[str],
    *,
    user_id: str = DEFAULT_USER_ID,
    now: str | None = None,
) -> int:
    clean_ids = [product_id.strip() for product_id in product_ids if product_id and product_id.strip()]
    if not clean_ids:
        return 0

    timestamp = now or utc_now_text()
    placeholders = ",".join("?" for _ in clean_ids)
    membership_cursor = conn.executemany(
        """
        INSERT INTO product_pool_memberships (user_id, product_id, status, created_at, updated_at)
        VALUES (?, ?, 'active', ?, ?)
        ON CONFLICT(user_id, product_id) DO UPDATE SET
            status = 'active',
            updated_at = excluded.updated_at
        """,
        [(user_id, product_id, timestamp, timestamp) for product_id in clean_ids],
    )
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
    return membership_cursor.rowcount if membership_cursor.rowcount != -1 else cursor.rowcount


def list_link_list_records(
    *,
    user_id: str = DEFAULT_USER_ID,
    include_deleted: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 500), 1000))
    where = ["user_id = ?"]
    params: list[Any] = [user_id]
    if not include_deleted:
        where.append("status != 'deleted'")
    where_sql = f"WHERE {' AND '.join(where)}"
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
            [*params, safe_limit],
        ).fetchall()

    return [link_list_record_row_to_api(row) for row in rows]


def upsert_link_list_record(record: dict[str, Any], *, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("链接记录格式不正确")

    normalized = normalize_link_list_record(record)
    normalized["userId"] = user_id
    db_record_id = scoped_link_record_id(user_id, normalized["id"])
    now = utc_now_text()
    created_at = _clean_record_text(normalized.get("createdAt")) or now
    metadata = link_list_record_metadata(normalized)
    with get_connection() as conn:
        ensure_link_list_schema(conn)
        conn.execute(
            """
            INSERT INTO link_list_records (
                id, user_id, product_id, product_title, product_title_en, source_product_url,
                source_count, sku_count, component_sku_count, record_json, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id = excluded.user_id,
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
                db_record_id,
                user_id,
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
        row = conn.execute(
            "SELECT * FROM link_list_records WHERE id = ? AND user_id = ?",
            (db_record_id, user_id),
        ).fetchone()

    return link_list_record_row_to_api(row)


def upsert_link_list_records(records: list[dict[str, Any]], *, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError("链接记录列表格式不正确")
    return [upsert_link_list_record(record, user_id=user_id) for record in records if isinstance(record, dict)]


def soft_delete_link_list_record(record_id: str, *, user_id: str = DEFAULT_USER_ID) -> bool:
    clean_id = _clean_record_text(record_id)
    if not clean_id:
        return False

    db_record_id = scoped_link_record_id(user_id, clean_id)
    now = utc_now_text()
    with get_connection() as conn:
        ensure_link_list_schema(conn)
        cursor = conn.execute(
            """
            UPDATE link_list_records
            SET status = 'deleted', updated_at = ?
            WHERE id = ? AND user_id = ? AND status != 'deleted'
            """,
            (now, db_record_id, user_id),
        )
    return cursor.rowcount > 0


def scoped_link_record_id(user_id: str, record_id: str) -> str:
    clean_user_id = _clean_record_text(user_id) or DEFAULT_USER_ID
    clean_record_id = _clean_record_text(record_id)
    if clean_user_id == DEFAULT_USER_ID:
        return clean_record_id
    return f"{clean_user_id}:{clean_record_id}"


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
    record.setdefault("userId", row["user_id"] if "user_id" in row.keys() else DEFAULT_USER_ID)
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
    sort_by: str | None = None,
    sort_order: str | None = None,
    include_deleted: bool = False,
    user_id: str = DEFAULT_USER_ID,
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
    if scope == "pool":
        where.append("membership.user_id = ?")
        where.append("membership.status != 'deleted'")
        params.append(user_id)
        from_sql = """
            products
            JOIN product_pool_memberships AS membership
                ON membership.product_id = products.id
        """
    else:
        from_sql = "products"

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    safe_page = max(1, page)
    safe_page_size = max(1, min(100, page_size))
    offset = (safe_page - 1) * safe_page_size
    order_sql = build_product_order_sql(sort_by, sort_order)

    with get_connection() as conn:
        ensure_category_mapping_ready(conn, backfill_products=False)
        total = conn.execute(f"SELECT COUNT(*) FROM {from_sql} {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT products.*
            FROM {from_sql}
            {where_sql}
            ORDER BY {order_sql}
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


def build_product_order_sql(sort_by: str | None, sort_order: str | None) -> str:
    direction = "ASC" if sort_order == "asc" else "DESC"
    if sort_by == "price":
        return f"products.price_usd {direction}, datetime(products.listing_time) DESC, products.gmv_usd DESC"
    if sort_by == "gmv":
        return f"products.gmv_usd {direction}, datetime(products.listing_time) DESC, products.price_usd ASC"
    return "datetime(products.listing_time) DESC, products.gmv_usd DESC"


def get_product_stats(scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> dict[str, int]:
    if scope == "pool":
        from_sql = """
            products
            JOIN product_pool_memberships AS membership
                ON membership.product_id = products.id
        """
        user_filter = "AND membership.user_id = ? AND membership.status != 'deleted'"
        params: list[Any] = [user_id]
    else:
        from_sql = "products"
        user_filter = ""
        params = []

    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN products.status != 'deleted' THEN 1 ELSE 0 END) AS active_count,
                SUM(
                    CASE
                        WHEN products.status != 'deleted'
                            AND products.listing_time IS NOT NULL
                            AND products.weekly_sales > 0
                            AND datetime(products.listing_time) >= datetime('now', '-7 days')
                        THEN 1 ELSE 0
                    END
                ) AS recent_7_count,
                SUM(
                    CASE
                        WHEN products.status != 'deleted'
                            AND products.listing_time IS NOT NULL
                            AND products.monthly_sales > 0
                            AND datetime(products.listing_time) >= datetime('now', '-30 days')
                        THEN 1 ELSE 0
                    END
                ) AS recent_30_count,
                SUM(CASE WHEN products.status = 'deleted' THEN 1 ELSE 0 END) AS deleted_count
            FROM {from_sql}
            WHERE 1 = 1 {user_filter}
            """,
            params,
        ).fetchone()

    return {
        "active_count": int(row["active_count"] or 0),
        "recent_7_count": int(row["recent_7_count"] or 0),
        "recent_30_count": int(row["recent_30_count"] or 0),
        "deleted_count": int(row["deleted_count"] or 0),
    }


def ensure_category_mapping_ready(conn: sqlite3.Connection, *, backfill_products: bool = False) -> None:
    ensure_category_mapping_schema(conn)
    if canonical_category_count(conn) == 0:
        sync_canonical_categories_from_dxm(conn)
    if backfill_products:
        refresh_product_category_matches(conn)


def get_product_categories() -> list[dict[str, Any]]:
    canonical_options = get_canonical_category_options()
    if canonical_options:
        return canonical_options
    yunqi_options = get_yunqi_category_options()
    if yunqi_options:
        return yunqi_options
    return get_product_categories_from_products()


def get_canonical_category_options() -> list[dict[str, Any]]:
    with get_connection() as conn:
        ensure_category_mapping_ready(conn, backfill_products=False)
        category_rows = conn.execute(
            """
            SELECT id, level, name, path_text, path_parts_json
            FROM canonical_categories
            WHERE provider = ? AND status = 'active'
            ORDER BY level ASC, path_text ASC
            """,
            (CANONICAL_CATEGORY_PROVIDER,),
        ).fetchall()
        if not category_rows:
            return []

        matched_rows = conn.execute(
            """
            SELECT cc.path_text, COUNT(DISTINCT pcm.product_id) AS count
            FROM product_category_matches pcm
            JOIN canonical_categories cc ON cc.id = pcm.canonical_category_id
            JOIN products ON products.id = pcm.product_id
            WHERE cc.provider = ?
                AND pcm.status IN ('auto', 'review')
                AND products.status != 'deleted'
            GROUP BY cc.path_text
            """,
            (CANONICAL_CATEGORY_PROVIDER,),
        ).fetchall()
        source_category_rows = []
        if not matched_rows:
            source_category_rows = conn.execute(
                """
                SELECT category_path, COUNT(*) AS count
                FROM products
                WHERE status != 'deleted'
                    AND COALESCE(category_path, '') != ''
                GROUP BY category_path
                """
            ).fetchall()

    prefix_counts: dict[str, int] = {}
    for row in matched_rows:
        path_text = normalize_category_path_text(row["path_text"])
        count = int(row["count"] or 0)
        parts = category_path_parts_from_text(path_text)
        for index in range(1, len(parts) + 1):
            prefix = normalize_category_path_text("/".join(parts[:index]))
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + count
    if not matched_rows:
        for row in source_category_rows:
            path_text = normalize_category_path_text(row["category_path"])
            count = int(row["count"] or 0)
            parts = category_path_parts_from_text(path_text)
            for index in range(1, len(parts) + 1):
                prefix = normalize_category_path_text("/".join(parts[:index]))
                prefix_counts[prefix] = prefix_counts.get(prefix, 0) + count

    nodes_by_path: dict[str, dict[str, Any]] = {}
    parent_path_by_path: dict[str, str] = {}
    for row in category_rows:
        path_text = normalize_category_path_text(row["path_text"])
        parts = parse_category_path_parts(row["path_parts_json"], path_text)
        if not parts:
            continue
        level = int(row["level"] or len(parts) or 1)
        if level > 4 or len(parts) > 4:
            continue
        count = prefix_counts.get(path_text, 0)
        label = clean_text(row["name"]) or parts[-1]
        nodes_by_path[path_text] = {
            "value": path_text,
            "label": label,
            "count": count,
            "level": min(level, 4),
            "children": [],
        }
        if len(parts) > 1:
            parent_path_by_path[path_text] = normalize_category_path_text("/".join(parts[:-1]))

    options: list[dict[str, Any]] = []
    for path_text, node in nodes_by_path.items():
        parent_path = parent_path_by_path.get(path_text)
        parent = nodes_by_path.get(parent_path or "")
        if parent:
            parent.setdefault("children", []).append(node)
        elif int(node.get("level") or 1) <= 1:
            options.append(node)

    def sort_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sorted_items = sorted(items, key=lambda item: (-int(item["count"] or 0), str(item["label"])))
        for item in sorted_items:
            item["children"] = sort_nodes(item.get("children") or [])
        return sorted_items

    return sort_nodes(options)


def refresh_product_category_matches(
    conn: sqlite3.Connection,
    products: list[dict[str, Any]] | None = None,
    *,
    now: str | None = None,
) -> int:
    ensure_category_mapping_schema(conn)
    sync_canonical_categories_from_dxm(conn)
    categories = load_matchable_canonical_categories(conn)
    if not categories:
        return 0

    timestamp = now or utc_now_text()
    if products is None:
        product_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT products.*
                FROM products
                LEFT JOIN product_category_matches pcm
                    ON pcm.product_id = products.id
                WHERE products.status != 'deleted'
                    AND (
                        pcm.product_id IS NULL
                        OR pcm.updated_at IS NULL
                        OR datetime(pcm.updated_at) < datetime(products.updated_at)
                    )
                ORDER BY datetime(products.updated_at) DESC
                """
            ).fetchall()
        ]
    else:
        product_rows = [dict(product) for product in products if clean_text(product.get("id"))]

    for product in product_rows:
        if clean_text(product.get("status") or "active") == "deleted":
            continue
        match = build_product_category_match(product, categories, now=timestamp)
        upsert_product_category_match(conn, match)
    return len(product_rows)


def load_matchable_canonical_categories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, external_category_id, level, name, path_text, path_parts_json, embedding_text, embedding_json
        FROM canonical_categories
        WHERE provider = ? AND status = 'active'
        ORDER BY level DESC, path_text ASC
        """,
        (CANONICAL_CATEGORY_PROVIDER,),
    ).fetchall()
    categories: list[dict[str, Any]] = []
    for row in rows:
        vector = parse_json_text(row["embedding_json"], {})
        if not isinstance(vector, dict) or not vector:
            vector = build_text_vector(row["embedding_text"] or row["path_text"])
        clean_vector = {str(key): float(value) for key, value in vector.items() if str(key)}
        parts = parse_category_path_parts(row["path_parts_json"], row["path_text"])
        categories.append(
            {
                "id": row["id"],
                "external_category_id": row["external_category_id"],
                "level": int(row["level"] or len(parts) or 1),
                "name": row["name"],
                "path_text": normalize_category_path_text(row["path_text"]),
                "path_parts": parts,
                "path_terms": set(extract_mapping_terms(" ".join(parts))),
                "vector": clean_vector,
            }
        )
    return categories


def build_product_category_match(
    product: dict[str, Any],
    categories: list[dict[str, Any]],
    *,
    now: str,
) -> dict[str, Any]:
    product_id = clean_text(product.get("id"))
    source_category_path = product_source_category_path(product)
    source_title = clean_text(product.get("title") or product.get("title_cn") or product.get("title_en"))
    source_text = clean_text(
        " ".join(
            [
                source_title,
                clean_text(product.get("title_cn")),
                clean_text(product.get("title_en")),
                source_category_path,
                clean_text(product.get("category_level1")),
                clean_text(product.get("category_level2")),
            ]
        )
    )
    source_vector = build_text_vector(source_text)
    source_path = normalize_category_path_text(source_category_path)
    source_parts = category_path_parts_from_text(source_category_path)
    source_part_terms = {normalize_mapping_term(part) for part in source_parts if normalize_mapping_term(part)}

    candidates: list[dict[str, Any]] = []
    for category in categories:
        score, method = score_category_candidate(
            source_path=source_path,
            source_part_terms=source_part_terms,
            source_vector=source_vector,
            category=category,
        )
        if score <= 0:
            continue
        candidates.append(
            {
                "id": category["id"],
                "path": category["path_text"],
                "name": category["name"],
                "level": category["level"],
                "score": round(score, 4),
                "method": method,
            }
        )

    candidates.sort(key=lambda item: (float(item["score"]), int(item["level"] or 0)), reverse=True)
    best = candidates[0] if candidates else None
    best_score = float(best["score"]) if best else 0.0
    status = "unmatched"
    if best and best_score >= CATEGORY_AUTO_THRESHOLD:
        status = "auto"
    elif best and best_score >= CATEGORY_REVIEW_THRESHOLD:
        status = "review"

    use_best = best if status != "unmatched" else None
    return {
        "id": uuid.uuid5(uuid.NAMESPACE_URL, f"product-category-match:{product_id}").hex,
        "product_id": product_id,
        "source_type": clean_text(product.get("source_type")) or "yunqi",
        "source_category_path": source_category_path,
        "source_title": source_title,
        "canonical_category_id": use_best["id"] if use_best else None,
        "canonical_category_path": use_best["path"] if use_best else "",
        "match_score": best_score,
        "match_method": best["method"] if best else "unmatched",
        "status": status,
        "candidates_json": json.dumps(candidates[:10], ensure_ascii=False),
        "created_at": now,
        "updated_at": now,
    }


def score_category_candidate(
    *,
    source_path: str,
    source_part_terms: set[str],
    source_vector: dict[str, float],
    category: dict[str, Any],
) -> tuple[float, str]:
    category_path = normalize_category_path_text(category["path_text"])
    category_terms = set(category.get("path_terms") or set())
    if source_path and source_path == category_path:
        return 1.0, "exact"

    score = 0.0
    method = "vector"
    if source_path and (source_path in category_path or category_path in source_path):
        score = 0.9
        method = "rule"

    matched_parts = source_part_terms & category_terms
    if matched_parts:
        part_score = min(0.88, 0.62 + 0.08 * len(matched_parts))
        if part_score > score:
            score = part_score
            method = "rule"

    vector_score = cosine_similarity(source_vector, category.get("vector") or {})
    if vector_score > score:
        score = vector_score
        method = "vector"

    if 0 < score < 1.0:
        score = min(0.99, score + min(0.04, max(0, int(category.get("level") or 1) - 1) * 0.01))
    return score, method


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(float(value) * float(right.get(key, 0.0)) for key, value in left.items())
    if dot <= 0:
        return 0.0
    left_norm = sum(float(value) * float(value) for value in left.values()) ** 0.5
    right_norm = sum(float(value) * float(value) for value in right.values()) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def product_source_category_path(product: dict[str, Any]) -> str:
    parts = category_path_parts_from_text(product.get("category_path"))
    if not parts:
        parts = [
            clean_text(product.get("category_level1")),
            clean_text(product.get("category_level2")),
        ]
    return normalize_category_path_text("/".join(part for part in parts if part))


def upsert_product_category_match(conn: sqlite3.Connection, match: dict[str, Any]) -> None:
    if not match.get("product_id"):
        return
    conn.execute(
        """
        INSERT INTO product_category_matches (
            id, product_id, source_type, source_category_path, source_title,
            canonical_category_id, canonical_category_path, match_score, match_method,
            status, candidates_json, created_at, updated_at
        ) VALUES (
            :id, :product_id, :source_type, :source_category_path, :source_title,
            :canonical_category_id, :canonical_category_path, :match_score, :match_method,
            :status, :candidates_json, :created_at, :updated_at
        )
        ON CONFLICT(product_id) DO UPDATE SET
            source_type = excluded.source_type,
            source_category_path = excluded.source_category_path,
            source_title = excluded.source_title,
            canonical_category_id = excluded.canonical_category_id,
            canonical_category_path = excluded.canonical_category_path,
            match_score = excluded.match_score,
            match_method = excluded.match_method,
            status = excluded.status,
            candidates_json = excluded.candidates_json,
            updated_at = excluded.updated_at
        """,
        match,
    )


def is_all_category_filter(value: str | None) -> bool:
    normalized = clean_text(value).lower()
    return normalized in {"", "all", "__all__", "\u5168\u90e8", "\u5168\u90e8\u7c7b\u76ee"}


def get_yunqi_category_options() -> list[dict[str, Any]]:
    with get_connection() as conn:
        category_rows = conn.execute(
            """
            SELECT category_key, parent_key, level, label, label_cn, path_text, path_json
            FROM yunqi_categories
            WHERE source_type = 'yunqi' AND is_active = 1
            ORDER BY level ASC, path_text ASC
            """
        ).fetchall()
        if not category_rows:
            return []

        product_rows = conn.execute(
            """
            SELECT category_level1, category_level2, category_path, COUNT(*) AS count
            FROM products
            WHERE status != 'deleted'
                AND category_level1 IS NOT NULL
                AND category_level1 != ''
            GROUP BY category_level1, category_level2, category_path
            """
        ).fetchall()

    level1_counts: dict[str, int] = {}
    path_counts: dict[str, int] = {}
    for row in product_rows:
        count = int(row["count"] or 0)
        level1 = str(row["category_level1"] or "").strip()
        if level1:
            level1_counts[level1] = level1_counts.get(level1, 0) + count
        category_path = normalize_category_option_path(row["category_path"])
        if category_path:
            path_counts[category_path] = path_counts.get(category_path, 0) + count

    top_rows: list[dict[str, Any]] = []
    children_by_top: dict[str, list[dict[str, Any]]] = {}
    for row in category_rows:
        path_parts = parse_category_path_parts(row["path_json"], row["path_text"])
        if not path_parts:
            continue

        label = str(row["label_cn"] or row["label"] or path_parts[-1]).strip()
        value = "/".join(path_parts)
        level = int(row["level"] or len(path_parts) or 1)
        top_label = path_parts[0]
        if level <= 1 or len(path_parts) == 1:
            count = level1_counts.get(label, level1_counts.get(top_label, path_counts.get(value, 0)))
            top_rows.append(
                {
                    "value": top_label,
                    "label": label or top_label,
                    "count": count,
                    "level": 1,
                    "children": [],
                    "_top_key": top_label,
                }
            )
            continue

        count = path_counts.get(value, 0)
        child_label = " / ".join(path_parts[1:])
        children_by_top.setdefault(top_label, []).append(
            {
                "value": value,
                "label": child_label or label,
                "count": count,
                "level": min(level, 2),
            }
        )

    seen_top: set[str] = set()
    options: list[dict[str, Any]] = []
    for row in sorted(top_rows, key=lambda item: (-int(item["count"] or 0), str(item["label"]))):
        if row["value"] in seen_top:
            continue
        seen_top.add(row["value"])
        raw_children = children_by_top.get(str(row.get("_top_key") or row["label"]), [])
        row["children"] = sorted(raw_children, key=lambda item: (-int(item["count"] or 0), str(item["label"])))
        row.pop("_top_key", None)
        options.append(row)

    return options


def parse_category_path_parts(path_json: str | None, path_text: str | None) -> list[str]:
    parts: list[str] = []
    try:
        loaded = json.loads(path_json or "[]")
        if isinstance(loaded, list):
            parts = [str(item).strip() for item in loaded if str(item).strip()]
    except (TypeError, ValueError):
        parts = []
    if not parts:
        parts = [part.strip() for part in str(path_text or "").replace("/", ">").split(">") if part.strip()]
    return parts


def normalize_category_option_path(value: Any) -> str:
    return "/".join(part.strip() for part in str(value or "").replace(">", "/").split("/") if part.strip())


def get_product_categories_from_products() -> list[dict[str, Any]]:
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
        where.append("products.status != 'deleted'")

    if keyword:
        like = f"%{keyword.strip()}%"
        where.append(
            "(products.title LIKE ? OR products.title_cn LIKE ? OR products.title_en LIKE ? OR products.source_product_id LIKE ?)"
        )
        params.extend([like, like, like, like])

    if category and not is_all_category_filter(category):
        raw_category = category.strip()
        normalized_category = normalize_category_path_text(raw_category)
        where.append(
            """
            (
                EXISTS (
                    SELECT 1
                    FROM product_category_matches pcm
                    JOIN canonical_categories cc
                        ON cc.id = pcm.canonical_category_id
                    WHERE pcm.product_id = products.id
                        AND pcm.status IN ('auto', 'review')
                        AND cc.provider = ?
                        AND (cc.path_text = ? OR cc.path_text LIKE ?)
                )
                OR products.category_path = ?
                OR products.category_path = ?
                OR products.category_level1 = ?
                OR products.category_level1 = ?
                OR products.category_level2 = ?
                OR products.category_level2 = ?
            )
            """
        )
        params.extend(
            [
                CANONICAL_CATEGORY_PROVIDER,
                normalized_category,
                f"{normalized_category}/%",
                raw_category,
                normalized_category,
                raw_category,
                normalized_category,
                raw_category,
                normalized_category,
            ]
        )

    if period == "近7天":
        where.append("datetime(products.listing_time) >= datetime('now', '-7 days')")
    elif period == "近30天":
        where.append("datetime(products.listing_time) >= datetime('now', '-30 days')")

    add_range_filter(where, params, "products.price_usd", price_min, price_max)
    add_range_filter(where, params, "MAX(products.weekly_sales, products.monthly_sales)", sales_min, sales_max)
    add_range_filter(where, params, "products.gmv_usd", gmv_min, gmv_max)

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


def create_product_from_sourcing_material_1688(
    material_id: str,
    *,
    add_to_pool_user_id: str | None = DEFAULT_USER_ID,
) -> dict[str, Any]:
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
    replace_products(batch_id, [product], add_to_pool_user_id=add_to_pool_user_id)

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


def soft_delete_product(product_id: str, scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> bool:
    now = utc_now_text()
    with get_connection() as conn:
        if scope == "pool":
            cursor = conn.execute(
                """
                UPDATE product_pool_memberships
                SET status = 'deleted', updated_at = ?
                WHERE user_id = ? AND product_id = ? AND status != 'deleted'
                """,
                (now, user_id, product_id),
            )
        else:
            cursor = conn.execute(
                "UPDATE products SET status = 'deleted', updated_at = ? WHERE id = ?",
                (now, product_id),
            )
        return cursor.rowcount > 0


def add_products_to_pool(product_ids: list[str], *, user_id: str = DEFAULT_USER_ID) -> int:
    clean_ids = [product_id.strip() for product_id in product_ids if product_id and product_id.strip()]
    if not clean_ids:
        return 0

    with get_connection() as conn:
        return copy_products_to_pool(conn, clean_ids, user_id=user_id)


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
