from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.database import get_connection, refresh_product_category_matches
from app.modules.yunqi.collector import normalize_yunqi_record, upsert_yunqi_products


def normalize_record(record: dict[str, Any], *, source_row_index: int) -> dict[str, Any]:
    return normalize_yunqi_record(record, source_row_index=source_row_index)


def persist_records(
    products: list[dict[str, Any]],
    *,
    batch_id: str,
    source_filename: str,
    saved_path: str | Path,
    total_rows: int,
    failed_count: int,
    error_message: str | None = None,
    rebuild_keywords: bool = True,
) -> dict[str, Any]:
    result = upsert_yunqi_products(
        products,
        batch_id=batch_id,
        source_filename=source_filename,
        saved_path=saved_path,
        total_rows=total_rows,
        failed_count=failed_count,
        error_message=error_message,
        rebuild_keywords=rebuild_keywords,
    )
    targets = load_target_products(products)
    if targets:
        with get_connection() as conn:
            refresh_product_category_matches(conn, targets)
    return {**result, "targets": targets}


def load_target_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_product_ids = [str(product.get("source_product_id") or "").strip() for product in products]
    source_product_ids = [value for value in source_product_ids if value]
    if not source_product_ids:
        return []

    rows: list[dict[str, Any]] = []
    with get_connection() as conn:
        for source_product_id in source_product_ids:
            row = conn.execute(
                """
                SELECT *
                FROM products
                WHERE source_type = 'yunqi' AND source_product_id = ?
                ORDER BY datetime(updated_at) DESC
                LIMIT 1
                """,
                (source_product_id,),
            ).fetchone()
            if row:
                rows.append(dict(row))
    return rows

