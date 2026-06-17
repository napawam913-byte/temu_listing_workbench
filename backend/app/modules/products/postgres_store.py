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
    CANONICAL_CATEGORY_PROVIDER,
    DEFAULT_USER_ID,
    PRODUCT_CATALOG_SCOPE_ADMIN,
    category_path_parts_from_text,
    clean_text,
    is_all_category_filter,
    normalize_category_path_text,
    parse_category_path_parts,
    utc_now_text,
)


def is_enabled() -> bool:
    return True


def configured_url() -> str:
    return (
        os.getenv("PRODUCTS_DATABASE_URL", "").strip()
        or os.getenv("POSTGRES_DATABASE_URL", "").strip()
        or os.getenv("DATABASE_URL", "").strip()
    )


@contextmanager
def get_pg_connection() -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed; run python -m pip install -r requirements.txt")
    url = configured_url()
    if not url:
        raise RuntimeError("Product PostgreSQL backend requires PRODUCTS_DATABASE_URL, POSTGRES_DATABASE_URL, or DATABASE_URL")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn


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
        where.append("membership.user_id = %s")
        where.append("membership.status != 'deleted'")
        params.append(user_id)
        from_sql = """
            products
            JOIN product_pool_memberships AS membership
                ON membership.product_id = products.id
        """
    else:
        where.append("products.catalog_scope = %s")
        params.append(PRODUCT_CATALOG_SCOPE_ADMIN)
        from_sql = "products"

    safe_page = max(1, page)
    safe_page_size = max(1, min(100, page_size))
    offset = (safe_page - 1) * safe_page_size
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    order_sql = build_product_order_sql(sort_by, sort_order)

    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS count FROM {from_sql} {where_sql}", params)
            total = int(cur.fetchone()["count"] or 0)
            cur.execute(
                f"""
                SELECT products.*
                FROM {from_sql}
                {where_sql}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
                """,
                [*params, safe_page_size, offset],
            )
            rows = cur.fetchall()

    return {
        "items": [product_row_to_api(row) for row in rows],
        "total": total,
        "page": safe_page,
        "page_size": safe_page_size,
    }


def get_product_stats(scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> dict[str, int]:
    if scope == "pool":
        from_sql = """
            products
            JOIN product_pool_memberships AS membership
                ON membership.product_id = products.id
        """
        scope_where = "AND membership.user_id = %s AND membership.status != 'deleted'"
        params: list[Any] = [user_id]
    else:
        from_sql = "products"
        scope_where = "AND products.catalog_scope = %s"
        params = [PRODUCT_CATALOG_SCOPE_ADMIN]

    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    SUM(CASE WHEN products.status != 'deleted' THEN 1 ELSE 0 END) AS active_count,
                    SUM(
                        CASE
                            WHEN products.status != 'deleted'
                                AND products.listing_time IS NOT NULL
                                AND products.listing_time != ''
                                AND products.weekly_sales > 0
                                AND NULLIF(products.listing_time, '')::timestamp >= NOW() - INTERVAL '7 days'
                            THEN 1 ELSE 0
                        END
                    ) AS recent_7_count,
                    SUM(
                        CASE
                            WHEN products.status != 'deleted'
                                AND products.listing_time IS NOT NULL
                                AND products.listing_time != ''
                                AND products.monthly_sales > 0
                                AND NULLIF(products.listing_time, '')::timestamp >= NOW() - INTERVAL '30 days'
                            THEN 1 ELSE 0
                        END
                    ) AS recent_30_count,
                    SUM(CASE WHEN products.status = 'deleted' THEN 1 ELSE 0 END) AS deleted_count
                FROM {from_sql}
                WHERE 1 = 1 {scope_where}
                """,
                params,
            )
            row = cur.fetchone()

    return {
        "active_count": int(row["active_count"] or 0),
        "recent_7_count": int(row["recent_7_count"] or 0),
        "recent_30_count": int(row["recent_30_count"] or 0),
        "deleted_count": int(row["deleted_count"] or 0),
    }


def get_product_categories(scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
    canonical_options = get_canonical_category_options(scope=scope, user_id=user_id)
    if canonical_options:
        return canonical_options
    return get_product_categories_from_products(scope=scope, user_id=user_id)


def get_canonical_category_options(scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
    scope_join = ""
    scope_where = "AND products.catalog_scope = %s"
    scope_params: list[Any] = [PRODUCT_CATALOG_SCOPE_ADMIN]
    if scope == "pool":
        scope_join = """
        JOIN product_pool_memberships membership
            ON membership.product_id = products.id
        """
        scope_where = "AND membership.user_id = %s AND membership.status != 'deleted'"
        scope_params = [user_id]

    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, level, name, path_text, path_parts_json
                FROM canonical_categories
                WHERE provider = %s AND status = 'active'
                ORDER BY level ASC, path_text ASC
                """,
                (CANONICAL_CATEGORY_PROVIDER,),
            )
            category_rows = cur.fetchall()
            if not category_rows:
                return []

            cur.execute(
                f"""
                SELECT cc.path_text, COUNT(DISTINCT pcm.product_id) AS count
                FROM product_category_matches pcm
                JOIN canonical_categories cc ON cc.id = pcm.canonical_category_id
                JOIN products ON products.id = pcm.product_id
                {scope_join}
                WHERE cc.provider = %s
                    AND pcm.status IN ('auto', 'review')
                    AND products.status != 'deleted'
                    {scope_where}
                GROUP BY cc.path_text
                """,
                [CANONICAL_CATEGORY_PROVIDER, *scope_params],
            )
            matched_rows = cur.fetchall()
            source_category_rows: list[dict[str, Any]] = []
            if not matched_rows:
                cur.execute(
                    f"""
                    SELECT category_path, COUNT(*) AS count
                    FROM products
                    {scope_join}
                    WHERE products.status != 'deleted'
                        AND COALESCE(category_path, '') != ''
                        {scope_where}
                    GROUP BY category_path
                    """,
                    scope_params,
                )
                source_category_rows = cur.fetchall()

    prefix_counts: dict[str, int] = {}
    for row in matched_rows:
        add_prefix_counts(prefix_counts, row["path_text"], int(row["count"] or 0))
    if not matched_rows:
        for row in source_category_rows:
            add_prefix_counts(prefix_counts, row["category_path"], int(row["count"] or 0))

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
        nodes_by_path[path_text] = {
            "value": path_text,
            "label": clean_text(row["name"]) or parts[-1],
            "count": prefix_counts.get(path_text, 0),
            "level": min(level, 4),
            "children": [],
        }
        if len(parts) > 1:
            parent_path_by_path[path_text] = normalize_category_path_text("/".join(parts[:-1]))

    options: list[dict[str, Any]] = []
    for path_text, node in nodes_by_path.items():
        parent = nodes_by_path.get(parent_path_by_path.get(path_text, ""))
        if parent:
            parent.setdefault("children", []).append(node)
        elif int(node.get("level") or 1) <= 1:
            options.append(node)
    return sort_category_nodes(options)


def get_product_categories_from_products(scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
    scope_join = ""
    scope_where = "AND products.catalog_scope = %s"
    scope_params: list[Any] = [PRODUCT_CATALOG_SCOPE_ADMIN]
    if scope == "pool":
        scope_join = """
        JOIN product_pool_memberships membership
            ON membership.product_id = products.id
        """
        scope_where = "AND membership.user_id = %s AND membership.status != 'deleted'"
        scope_params = [user_id]

    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT category_level1 AS name, COUNT(*) AS count
                FROM products
                {scope_join}
                WHERE products.status != 'deleted'
                    AND category_level1 IS NOT NULL
                    AND category_level1 != ''
                    {scope_where}
                GROUP BY category_level1
                ORDER BY count DESC, category_level1 ASC
                """,
                scope_params,
            )
            level1_rows = cur.fetchall()
            cur.execute(
                f"""
                SELECT category_level1, category_level2, category_path, COUNT(*) AS count
                FROM products
                {scope_join}
                WHERE products.status != 'deleted'
                    AND category_level1 IS NOT NULL
                    AND category_level1 != ''
                    AND category_level2 IS NOT NULL
                    AND category_level2 != ''
                    {scope_where}
                GROUP BY category_level1, category_level2, category_path
                ORDER BY category_level1 ASC, count DESC, category_level2 ASC
                """,
                scope_params,
            )
            level2_rows = cur.fetchall()

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


def add_products_to_pool(product_ids: list[str], *, user_id: str = DEFAULT_USER_ID) -> int:
    clean_ids = [product_id.strip() for product_id in product_ids if product_id and product_id.strip()]
    if not clean_ids:
        return 0
    now = utc_now_text()
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            rows = [(user_id, product_id, now, now) for product_id in clean_ids]
            cur.executemany(
                """
                INSERT INTO product_pool_memberships (user_id, product_id, status, created_at, updated_at)
                VALUES (%s, %s, 'active', %s, %s)
                ON CONFLICT (user_id, product_id) DO UPDATE SET
                    status = 'active',
                    updated_at = EXCLUDED.updated_at
                """,
                rows,
            )
            return len(rows)


def soft_delete_product(product_id: str, scope: str = "pool", *, user_id: str = DEFAULT_USER_ID) -> bool:
    now = utc_now_text()
    with get_pg_connection() as conn:
        with conn.cursor() as cur:
            if scope == "pool":
                cur.execute(
                    """
                    UPDATE product_pool_memberships
                    SET status = 'deleted', updated_at = %s
                    WHERE user_id = %s AND product_id = %s AND status != 'deleted'
                    """,
                    (now, user_id, product_id),
                )
            else:
                cur.execute(
                    "UPDATE products SET status = 'deleted', updated_at = %s WHERE id = %s",
                    (now, product_id),
                )
            return cur.rowcount > 0


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
            "(products.title ILIKE %s OR products.title_cn ILIKE %s OR products.title_en ILIKE %s OR products.source_product_id ILIKE %s)"
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
                        AND cc.provider = %s
                        AND (cc.path_text = %s OR cc.path_text LIKE %s)
                )
                OR products.category_path = %s
                OR products.category_path = %s
                OR products.category_level1 = %s
                OR products.category_level1 = %s
                OR products.category_level2 = %s
                OR products.category_level2 = %s
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

    if period == "\u8fd17\u5929":
        where.append("NULLIF(products.listing_time, '')::timestamp >= NOW() - INTERVAL '7 days'")
    elif period == "\u8fd130\u5929":
        where.append("NULLIF(products.listing_time, '')::timestamp >= NOW() - INTERVAL '30 days'")

    add_range_filter(where, params, "products.price_usd", price_min, price_max)
    add_range_filter(where, params, "GREATEST(COALESCE(products.weekly_sales, 0), COALESCE(products.monthly_sales, 0))", sales_min, sales_max)
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
        where.append(f"{expression} >= %s")
        params.append(minimum)
    if maximum is not None:
        where.append(f"{expression} <= %s")
        params.append(maximum)


def build_product_order_sql(sort_by: str | None, sort_order: str | None) -> str:
    direction = "ASC" if sort_order == "asc" else "DESC"
    listing_time = "NULLIF(products.listing_time, '')::timestamp DESC NULLS LAST"
    if sort_by == "price":
        return f"products.price_usd {direction}, {listing_time}, products.gmv_usd DESC"
    if sort_by == "gmv":
        return f"products.gmv_usd {direction}, {listing_time}, products.price_usd ASC"
    return f"{listing_time}, products.gmv_usd DESC"


def add_prefix_counts(prefix_counts: dict[str, int], path_value: Any, count: int) -> None:
    path_text = normalize_category_path_text(path_value)
    parts = category_path_parts_from_text(path_text)
    for index in range(1, len(parts) + 1):
        prefix = normalize_category_path_text("/".join(parts[:index]))
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + count


def sort_category_nodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_items = sorted(items, key=lambda item: (-int(item["count"] or 0), str(item["label"])))
    for item in sorted_items:
        item["children"] = sort_category_nodes(item.get("children") or [])
    return sorted_items


def product_row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_type": row.get("source_type") or "yunqi",
        "source_product_id": row.get("source_product_id"),
        "catalog_scope": row.get("catalog_scope") or PRODUCT_CATALOG_SCOPE_ADMIN,
        "title": row.get("title"),
        "title_cn": row.get("title_cn"),
        "title_en": row.get("title_en"),
        "main_image_url": row.get("main_image_url"),
        "gallery_image_urls": parse_json_list(row.get("gallery_image_urls_json")),
        "video_url": row.get("video_url"),
        "source_url": row.get("source_url"),
        "category_path": row.get("category_path"),
        "category_level1": row.get("category_level1"),
        "category_level2": row.get("category_level2"),
        "tags": parse_json_list(row.get("tags_json")),
        "price_usd": row.get("price_usd"),
        "gmv_usd": row.get("gmv_usd"),
        "weekly_sales": row.get("weekly_sales"),
        "monthly_sales": row.get("monthly_sales"),
        "review_count": row.get("review_count"),
        "listing_time": row.get("listing_time"),
        "status": row.get("status"),
        "in_product_pool": bool(row.get("in_product_pool", True)),
        "source_row_index": row.get("source_row_index"),
    }


def parse_json_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []
