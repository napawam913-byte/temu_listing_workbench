from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from app.core.config import BACKEND_DIR


DEFAULT_START_URL = "https://www.yunqishuju.com/temu/semiy2/"
DEFAULT_DYNAMIC_FILTER_DIR = BACKEND_DIR / "runtime" / "yunqi_dynamic_filters"


def stable_filter_key(value: str) -> str:
    normalized = " > ".join(str(value or "").split()).strip()
    return hashlib.sha1(f"yunqi-filter:{normalized}".encode("utf-8")).hexdigest()


def build_yunqi_category_filter_payload(
    *,
    category_path: Iterable[str],
    path_text: str = "",
    start_url: str = DEFAULT_START_URL,
    listing_date_text: str = "3月内",
    site_label: str = "国家",
    site_text: str = "美国站",
) -> dict[str, Any]:
    clean_path = [str(item).strip() for item in category_path if str(item).strip()]
    if not clean_path:
        raise ValueError("category_path must not be empty")

    resolved_path_text = path_text or " > ".join(clean_path)
    return {
        "_name": f"yunqi_db_category_{stable_filter_key(resolved_path_text)}",
        "_description": f"从 yunqi_categories 表动态生成：{resolved_path_text}",
        "start_url": start_url,
        "setup_actions": [{"type": "assert_min_viewport", "width": 1400}],
        "site_actions": [
            {
                "type": "select_labeled_option",
                "label": site_label,
                "text": site_text,
                "exact": True,
            }
        ],
        "category_actions": [
            {
                "type": "cascader_path",
                "placeholder": "分类筛选",
                "path": clean_path,
            }
        ],
        "listing_date_actions": [
            {
                "type": "select_labeled_option",
                "label": "上架时间",
                "text": listing_date_text,
                "exact": True,
            }
        ],
        "search_action": {
            "type": "dom_click_text",
            "selector": "button",
            "text": "搜索",
            "exact": True,
        },
        "after_search_actions": [{"type": "wait", "milliseconds": 3000}],
        "before_export_actions": [{"type": "wait", "milliseconds": 1000}],
        "export_mode": "modal",
        "export_action": {
            "type": "dom_click_text",
            "selector": "button",
            "text": "导出",
            "exact": True,
        },
        "export_modal": {
            "start_text": "立即导出",
            "download_text": "下载",
            "timeout_ms": 120000,
            "confirm_timeout_ms": 15000,
            "download_response_timeout_ms": 60000,
            "fallback_existing_after_ms": 30000,
        },
    }


def write_yunqi_category_filter_config(
    *,
    category_key: str | None,
    category_path: Iterable[str],
    path_text: str = "",
    output_dir: str | Path | None = None,
    start_url: str = DEFAULT_START_URL,
    listing_date_text: str = "3月内",
    site_label: str = "国家",
    site_text: str = "美国站",
) -> Path:
    clean_path = [str(item).strip() for item in category_path if str(item).strip()]
    resolved_path_text = path_text or " > ".join(clean_path)
    resolved_key = str(category_key or "").strip() or stable_filter_key(resolved_path_text)
    config_dir = Path(output_dir or DEFAULT_DYNAMIC_FILTER_DIR)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"yunqi_category_{resolved_key}.json"
    payload = build_yunqi_category_filter_payload(
        category_path=clean_path,
        path_text=resolved_path_text,
        start_url=start_url,
        listing_date_text=listing_date_text,
        site_label=site_label,
        site_text=site_text,
    )
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path
