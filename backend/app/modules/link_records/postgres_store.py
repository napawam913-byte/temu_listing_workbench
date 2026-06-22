from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - optional runtime dependency
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

from app.core.database import (
    DEFAULT_USER_ID,
    _clean_record_text,
    link_list_record_metadata,
    link_list_record_row_to_api,
    normalize_link_list_record,
    scoped_link_record_id,
    utc_now_text,
)
from app.core.postgres_pool import get_postgres_connection


def is_enabled() -> bool:
    return True


def configured_url() -> str:
    return (
        os.getenv("LINK_RECORDS_DATABASE_URL", "").strip()
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


@contextmanager
def get_pg_connection() -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")
    url = configured_url()
    if not url:
        raise RuntimeError(
            "Link records PostgreSQL backend requires LINK_RECORDS_DATABASE_URL, POSTGRES_DATABASE_URL, or DATABASE_URL"
        )
    with get_postgres_connection(url) as conn:
        yield conn


def list_link_list_records(
    *,
    user_id: str = DEFAULT_USER_ID,
    include_deleted: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 500), 1000))
    where = ["user_id = %s"]
    params: list[Any] = [user_id]
    if not include_deleted:
        where.append("status != 'deleted'")
    where_sql = f"WHERE {' AND '.join(where)}"
    with get_pg_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM link_list_records
            {where_sql}
            ORDER BY created_at DESC, updated_at DESC
            LIMIT %s
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
    with get_pg_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO link_list_records (
                id, user_id, product_id, product_title, product_title_en, source_product_url,
                source_count, sku_count, component_sku_count, record_json, status,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                product_id = EXCLUDED.product_id,
                product_title = EXCLUDED.product_title,
                product_title_en = EXCLUDED.product_title_en,
                source_product_url = EXCLUDED.source_product_url,
                source_count = EXCLUDED.source_count,
                sku_count = EXCLUDED.sku_count,
                component_sku_count = EXCLUDED.component_sku_count,
                record_json = EXCLUDED.record_json,
                status = 'active',
                updated_at = EXCLUDED.updated_at
            RETURNING *
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
    with get_pg_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE link_list_records
            SET status = 'deleted', updated_at = %s
            WHERE id = %s AND user_id = %s AND status != 'deleted'
            """,
            (now, db_record_id, user_id),
        )
    return cursor.rowcount > 0
