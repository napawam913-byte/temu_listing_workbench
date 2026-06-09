from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.modules.yunqi.collector import YunqiCollectorError


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def rename_export_for_filter_config(
    download_path: str | Path,
    filter_config: dict[str, Any],
    *,
    date_text: str | None = None,
) -> Path:
    category_path, path_text = extract_category_export_name(filter_config)
    return rename_export_for_category(
        download_path,
        category_path=category_path,
        path_text=path_text,
        date_text=date_text,
    )


def extract_category_export_name(filter_config: dict[str, Any]) -> tuple[list[str], str]:
    for key in ("_category_path", "category_path"):
        path = clean_path_items(filter_config.get(key))
        if path:
            return path, str(filter_config.get("_path_text") or filter_config.get("path_text") or " > ".join(path))

    for action_group_key in ("category_actions", "actions"):
        actions = filter_config.get(action_group_key)
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            path = clean_path_items(action.get("path"))
            if path:
                return path, " > ".join(path)

    export_stem = str(filter_config.get("export_filename_stem") or filter_config.get("_name") or "").strip()
    if export_stem:
        return [export_stem], export_stem
    return ["yunqi_export"], "yunqi_export"


def rename_export_for_category(
    download_path: str | Path,
    *,
    category_path: list[str],
    path_text: str = "",
    date_text: str | None = None,
) -> Path:
    source_path = Path(download_path)
    if not source_path.exists() or not source_path.is_file():
        return source_path

    suffix = source_path.suffix or ".xlsx"
    resolved_date = date_text or datetime.now().strftime("%Y-%m-%d")
    raw_name = path_text or " > ".join(category_path)
    stem = safe_category_export_stem(raw_name, max_length=180 - len(resolved_date) - len(suffix) - 1)
    target_path = next_available_export_path(source_path.parent / f"{stem}_{resolved_date}{suffix}", source_path)
    if target_path == source_path:
        return source_path
    source_path.rename(target_path)
    remove_source_export_file(source_path, target_path)
    return target_path


def safe_category_export_stem(value: str, *, max_length: int = 160) -> str:
    raw_parts = [part.strip() for part in re.split(r"\s*>\s*", str(value or "").strip()) if part.strip()]
    safe_parts = []
    for part in raw_parts:
        cleaned = INVALID_FILENAME_CHARS.sub("_", part)
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
        if cleaned:
            safe_parts.append(cleaned)
    text = "__".join(safe_parts)
    if len(text) > max_length:
        text = text[:max_length].rstrip(" ._")
    return text or "yunqi_category"


def next_available_export_path(target_path: Path, source_path: Path) -> Path:
    if same_path(target_path, source_path):
        return source_path
    if not target_path.exists():
        return target_path

    suffix = target_path.suffix
    stem = target_path.stem
    for counter in range(2, 10000):
        candidate = target_path.with_name(f"{stem}_{counter}{suffix}")
        if same_path(candidate, source_path):
            return source_path
        if not candidate.exists():
            return candidate
    raise YunqiCollectorError(f"Could not generate a unique category export filename: {target_path}")


def same_path(left: Path, right: Path) -> bool:
    return str(left.resolve()).lower() == str(right.resolve()).lower()


def remove_source_export_file(source_path: Path, target_path: Path) -> None:
    if same_path(source_path, target_path):
        return
    if source_path.exists() and source_path.is_file():
        source_path.unlink()


def clean_path_items(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
