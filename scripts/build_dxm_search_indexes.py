from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path(r"D:\learning\temu_listing_workbench\backend\data\app.db")


def choose_fts_tokenizer(conn: sqlite3.Connection) -> str:
    for tokenizer in ("trigram", "unicode61"):
        try:
            conn.execute("DROP TABLE IF EXISTS temp.__fts_probe")
            conn.execute(f"CREATE VIRTUAL TABLE temp.__fts_probe USING fts5(x, tokenize='{tokenizer}')")
            conn.execute("DROP TABLE temp.__fts_probe")
            return tokenizer
        except sqlite3.DatabaseError:
            continue
    raise RuntimeError("SQLite FTS5 is not available in this Python runtime.")


def option_text(options_json: str) -> str:
    try:
        options = json.loads(options_json or "[]")
    except Exception:
        return ""
    if not isinstance(options, list):
        return ""
    values: list[str] = []
    for item in options:
        if not isinstance(item, dict):
            continue
        for key in ("label", "value", "en", "vid"):
            value = str(item.get(key) or "").strip()
            if value:
                values.append(value)
    return " ".join(dict.fromkeys(values))


def rebuild_indexes(conn: sqlite3.Connection, *, tokenizer: str) -> dict[str, Any]:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_snapshots_path
            ON dxm_temu_category_attr_snapshots(category_path_text);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_snapshots_status
            ON dxm_temu_category_attr_snapshots(collection_status);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_path_label
            ON dxm_temu_category_attr_fields(category_path_text, field_label);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_category_label
            ON dxm_temu_category_attr_fields(category_id, field_label);
        CREATE INDEX IF NOT EXISTS idx_dxm_temu_category_attr_fields_component
            ON dxm_temu_category_attr_fields(component);

        DROP TABLE IF EXISTS dxm_temu_category_search_fts;
        DROP TABLE IF EXISTS dxm_temu_attr_search_fts;
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE dxm_temu_category_search_fts USING fts5(
            category_id UNINDEXED,
            category_path_text,
            level1_name,
            level2_name,
            level3_name,
            level4_name,
            level5_name,
            level6_name,
            leaf_name,
            collection_status UNINDEXED,
            attr_count UNINDEXED,
            required_count UNINDEXED,
            tokenize='{tokenizer}'
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE dxm_temu_attr_search_fts USING fts5(
            category_id UNINDEXED,
            category_path_text,
            field_label,
            component,
            option_text,
            required UNINDEXED,
            option_count UNINDEXED,
            tokenize='{tokenizer}'
        )
        """
    )
    conn.execute(
        """
        INSERT INTO dxm_temu_category_search_fts (
            category_id, category_path_text,
            level1_name, level2_name, level3_name, level4_name, level5_name, level6_name,
            leaf_name, collection_status, attr_count, required_count
        )
        SELECT
            category_id, category_path_text,
            level1_name, level2_name, level3_name, level4_name, level5_name, level6_name,
            leaf_name, collection_status, attr_count, required_count
        FROM dxm_temu_category_attr_snapshots
        """
    )
    fields = conn.execute(
        """
        SELECT category_id, category_path_text, field_label, component, options_json, required, option_count
        FROM dxm_temu_category_attr_fields
        """
    )
    batch: list[tuple[str, str, str, str, str, int, int]] = []
    inserted = 0
    for row in fields:
        batch.append((row[0], row[1], row[2], row[3], option_text(row[4]), row[5], row[6]))
        if len(batch) >= 5000:
            conn.executemany(
                """
                INSERT INTO dxm_temu_attr_search_fts (
                    category_id, category_path_text, field_label, component, option_text, required, option_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
            inserted += len(batch)
            batch.clear()
    if batch:
        conn.executemany(
            """
            INSERT INTO dxm_temu_attr_search_fts (
                category_id, category_path_text, field_label, component, option_text, required, option_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        inserted += len(batch)
    conn.commit()
    return {
        "tokenizer": tokenizer,
        "category_fts_rows": conn.execute("SELECT count(*) FROM dxm_temu_category_search_fts").fetchone()[0],
        "attr_fts_rows": conn.execute("SELECT count(*) FROM dxm_temu_attr_search_fts").fetchone()[0],
        "attr_inserted": inserted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build fast local search indexes for Dxm Temu category attributes.")
    parser.add_argument("--database-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args()
    db_path = Path(args.database_path)
    with sqlite3.connect(db_path) as conn:
        tokenizer = choose_fts_tokenizer(conn)
        result = rebuild_indexes(conn, tokenizer=tokenizer)
    print(json.dumps({"ok": True, "database": str(db_path), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
