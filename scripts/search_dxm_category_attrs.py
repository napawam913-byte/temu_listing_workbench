from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path(r"D:\learning\temu_listing_workbench\backend\data\app.db")


def quote_match_query(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def search_categories(conn: sqlite3.Connection, keyword: str, limit: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT category_id, category_path_text, collection_status, attr_count, required_count
        FROM dxm_temu_category_search_fts
        WHERE dxm_temu_category_search_fts MATCH ?
        LIMIT ?
        """,
        (quote_match_query(keyword), limit),
    ).fetchall()
    return [
        {
            "category_id": row[0],
            "category_path": row[1],
            "status": row[2],
            "attr_count": row[3],
            "required_count": row[4],
        }
        for row in rows
    ]


def search_attrs(conn: sqlite3.Connection, keyword: str, limit: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT category_id, category_path_text, field_label, component, required, option_count
        FROM dxm_temu_attr_search_fts
        WHERE dxm_temu_attr_search_fts MATCH ?
        LIMIT ?
        """,
        (quote_match_query(keyword), limit),
    ).fetchall()
    return [
        {
            "category_id": row[0],
            "category_path": row[1],
            "field": row[2],
            "component": row[3],
            "required": bool(row[4]),
            "option_count": row[5],
        }
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Dxm Temu category and product attribute indexes.")
    parser.add_argument("keyword")
    parser.add_argument("--database-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--type", choices=["all", "category", "attr"], default="all")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    with sqlite3.connect(args.database_path) as conn:
        result: dict[str, object] = {"keyword": args.keyword}
        if args.type in {"all", "category"}:
            result["categories"] = search_categories(conn, args.keyword, args.limit)
        if args.type in {"all", "attr"}:
            result["attrs"] = search_attrs(conn, args.keyword, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
