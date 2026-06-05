from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.core.config import STORAGE_DIR
from app.core.database import get_connection, init_db, utc_now_text


DEFAULT_CATEGORY_TREE_PATH = STORAGE_DIR / "yunqi_categories" / "yunqi_categories_latest.json"


class YunqiCategoryCatalogError(Exception):
    pass


def category_key_for_path(path_text: str) -> str:
    normalized = " > ".join(str(path_text or "").split()).strip()
    return hashlib.sha1(f"yunqi-category:{normalized}".encode("utf-8")).hexdigest()


def load_category_payload(path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = Path(path or DEFAULT_CATEGORY_TREE_PATH)
    if not resolved_path.exists():
        raise YunqiCategoryCatalogError(f"找不到云启类目文件：{resolved_path}")

    payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise YunqiCategoryCatalogError("云启类目 JSON 必须是对象。")
    if not isinstance(payload.get("tree"), list):
        raise YunqiCategoryCatalogError("云启类目 JSON 缺少 tree 数组。")
    payload["_source_path"] = str(resolved_path)
    return payload


def flatten_category_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], parent_path_text: str) -> None:
        label = str(node.get("label") or "").strip()
        path_text = str(node.get("path_text") or label).strip()
        if not label or not path_text:
            return

        path = node.get("path")
        if not isinstance(path, list) or not path:
            path = [part.strip() for part in path_text.split(">") if part.strip()]

        row = {
            "category_key": category_key_for_path(path_text),
            "parent_key": category_key_for_path(parent_path_text) if parent_path_text else None,
            "level": int(node.get("level") or len(path) or 1),
            "label": label,
            "label_en": clean_optional_text(node.get("label_en")),
            "label_cn": clean_optional_text(node.get("label_cn")),
            "path_text": path_text,
            "parent_path_text": parent_path_text or None,
            "path": [str(item).strip() for item in path if str(item).strip()],
            "node_id": clean_optional_text(node.get("node_id")),
            "aria_haspopup": bool(node.get("aria_haspopup")),
            "aria_owns": clean_optional_text(node.get("aria_owns")),
            "has_children": bool(node.get("has_children")),
            "selected": bool(node.get("selected")),
            "checked": bool(node.get("checked")),
            "disabled": bool(node.get("disabled")),
            "class_name": clean_optional_text(node.get("class_name")),
            "raw_data": node,
        }
        rows.append(row)

        children = node.get("children") or []
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    visit(child, path_text)

    for node in nodes:
        if isinstance(node, dict):
            visit(node, "")
    return rows


def import_yunqi_categories_from_json(path: str | Path | None = None) -> dict[str, Any]:
    payload = load_category_payload(path)
    rows = flatten_category_tree(payload["tree"])
    result = upsert_yunqi_categories(rows, source_snapshot_path=payload.get("_source_path"))
    return {
        **result,
        "source_path": payload.get("_source_path"),
        "generated_at": payload.get("generated_at"),
        "json_category_count": payload.get("category_count"),
    }


def upsert_yunqi_categories(rows: list[dict[str, Any]], *, source_snapshot_path: str | None = None) -> dict[str, Any]:
    init_db()
    now = utc_now_text()
    clean_rows = [row for row in rows if row.get("category_key") and row.get("path_text") and row.get("label")]

    with get_connection() as conn:
        conn.execute("UPDATE yunqi_categories SET is_active = 0, updated_at = ?", (now,))
        for row in clean_rows:
            category_key = str(row["category_key"])
            conn.execute(
                """
                INSERT INTO yunqi_categories (
                    id, source_type, category_key, parent_key, level, label, label_en, label_cn,
                    path_text, parent_path_text, path_json, node_id, aria_haspopup, aria_owns,
                    has_children, is_active, selected, checked, disabled, class_name,
                    source_snapshot_path, raw_data_json, first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (
                    :id, 'yunqi', :category_key, :parent_key, :level, :label, :label_en, :label_cn,
                    :path_text, :parent_path_text, :path_json, :node_id, :aria_haspopup, :aria_owns,
                    :has_children, 1, :selected, :checked, :disabled, :class_name,
                    :source_snapshot_path, :raw_data_json, :first_seen_at, :last_seen_at, :created_at, :updated_at
                )
                ON CONFLICT(category_key) DO UPDATE SET
                    parent_key = excluded.parent_key,
                    level = excluded.level,
                    label = excluded.label,
                    label_en = excluded.label_en,
                    label_cn = excluded.label_cn,
                    path_text = excluded.path_text,
                    parent_path_text = excluded.parent_path_text,
                    path_json = excluded.path_json,
                    node_id = excluded.node_id,
                    aria_haspopup = excluded.aria_haspopup,
                    aria_owns = excluded.aria_owns,
                    has_children = excluded.has_children,
                    is_active = 1,
                    selected = excluded.selected,
                    checked = excluded.checked,
                    disabled = excluded.disabled,
                    class_name = excluded.class_name,
                    source_snapshot_path = excluded.source_snapshot_path,
                    raw_data_json = excluded.raw_data_json,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                {
                    "id": category_key,
                    "category_key": category_key,
                    "parent_key": row.get("parent_key"),
                    "level": int(row.get("level") or 1),
                    "label": row.get("label"),
                    "label_en": row.get("label_en"),
                    "label_cn": row.get("label_cn"),
                    "path_text": row.get("path_text"),
                    "parent_path_text": row.get("parent_path_text"),
                    "path_json": json.dumps(row.get("path") or [], ensure_ascii=False),
                    "node_id": row.get("node_id"),
                    "aria_haspopup": 1 if row.get("aria_haspopup") else 0,
                    "aria_owns": row.get("aria_owns"),
                    "has_children": 1 if row.get("has_children") else 0,
                    "selected": 1 if row.get("selected") else 0,
                    "checked": 1 if row.get("checked") else 0,
                    "disabled": 1 if row.get("disabled") else 0,
                    "class_name": row.get("class_name"),
                    "source_snapshot_path": source_snapshot_path,
                    "raw_data_json": json.dumps(row.get("raw_data") or row, ensure_ascii=False),
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        active_count = conn.execute(
            "SELECT COUNT(*) FROM yunqi_categories WHERE source_type = 'yunqi' AND is_active = 1"
        ).fetchone()[0]
        total_count = conn.execute(
            "SELECT COUNT(*) FROM yunqi_categories WHERE source_type = 'yunqi'"
        ).fetchone()[0]

    return {
        "status": "imported",
        "imported_count": len(clean_rows),
        "active_count": active_count,
        "total_count": total_count,
    }


def list_yunqi_categories(*, active_only: bool = True, level: int | None = None) -> list[dict[str, Any]]:
    clauses = ["source_type = 'yunqi'"]
    params: list[Any] = []
    if active_only:
        clauses.append("is_active = 1")
    if level is not None:
        clauses.append("level = ?")
        params.append(level)
    where = " AND ".join(clauses)

    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM yunqi_categories
            WHERE {where}
            ORDER BY level ASC, path_text ASC
            """,
            params,
        ).fetchall()
    return [yunqi_category_row_to_dict(row) for row in rows]


def yunqi_category_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "category_key": row["category_key"],
        "parent_key": row["parent_key"],
        "level": row["level"],
        "label": row["label"],
        "label_en": row["label_en"],
        "label_cn": row["label_cn"],
        "path_text": row["path_text"],
        "parent_path_text": row["parent_path_text"],
        "path": json.loads(row["path_json"] or "[]"),
        "node_id": row["node_id"],
        "aria_haspopup": bool(row["aria_haspopup"]),
        "aria_owns": row["aria_owns"],
        "has_children": bool(row["has_children"]),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def clean_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
