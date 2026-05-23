from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd


YUNQI_FIELD_ALIASES = {
    "listing_time": ["上架时间"],
    "source_product_id": ["商品ID"],
    "title_cn": ["商品标题（中文）"],
    "title_en": ["商品标题（英文）"],
    "main_image_url": ["商品主图"],
    "gallery_image_urls": ["商品轮播图"],
    "video_url": ["商品视频"],
    "source_url": ["商品链接"],
    "category_path": ["前台分类（中文）"],
    "tags": ["标签"],
    "price_usd": ["美元价格($)"],
    "gmv_usd": ["GMV($)"],
    "weekly_sales": ["周销量"],
    "monthly_sales": ["月销量"],
    "review_count": ["总评论数"],
}


def normalize_yunqi_dataframe(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    column_map = build_column_map(df)

    for index, row in df.iterrows():
        source_row_index = int(index) + 3
        try:
            raw = {str(column): clean_scalar(row[column]) for column in df.columns}
            product_id = to_product_id(get_value(row, column_map, "source_product_id"))
            if not product_id:
                errors.append(f"第 {source_row_index} 行缺少商品ID，已跳过")
                continue

            title_cn = to_text(get_value(row, column_map, "title_cn"))
            title_en = to_text(get_value(row, column_map, "title_en"))
            title = title_cn or title_en or f"未命名商品 {product_id}"

            category_path = to_text(get_value(row, column_map, "category_path")) or "未分类"
            category_parts = [part.strip() for part in category_path.split("/") if part.strip()]

            listing_time = to_datetime_text(get_value(row, column_map, "listing_time"))
            gallery_images = parse_list_text(get_value(row, column_map, "gallery_image_urls"))
            tags = parse_list_text(get_value(row, column_map, "tags"))

            normalized.append(
                {
                    "id": product_id,
                    "source_row_index": source_row_index,
                    "source_product_id": product_id,
                    "title_cn": title_cn,
                    "title_en": title_en,
                    "title": title,
                    "main_image_url": to_text(get_value(row, column_map, "main_image_url")),
                    "gallery_image_urls": gallery_images,
                    "video_url": to_text(get_value(row, column_map, "video_url")) or None,
                    "source_url": to_text(get_value(row, column_map, "source_url")) or None,
                    "category_path": category_path,
                    "category_level1": category_parts[0] if category_parts else "未分类",
                    "category_level2": category_parts[1] if len(category_parts) > 1 else None,
                    "tags": tags,
                    "price_usd": to_float(get_value(row, column_map, "price_usd")),
                    "gmv_usd": to_float(get_value(row, column_map, "gmv_usd")),
                    "weekly_sales": to_int(get_value(row, column_map, "weekly_sales")),
                    "monthly_sales": to_int(get_value(row, column_map, "monthly_sales")),
                    "review_count": to_int(get_value(row, column_map, "review_count")),
                    "listing_time": listing_time,
                    "status": "active",
                    "raw_data": raw,
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep importing other rows.
            errors.append(f"第 {source_row_index} 行清洗失败：{exc}")

    return normalized, errors


def build_column_map(df: pd.DataFrame) -> dict[str, str | None]:
    columns = [str(column).strip() for column in df.columns]
    result: dict[str, str | None] = {}
    for standard_field, aliases in YUNQI_FIELD_ALIASES.items():
        matched = next((column for column in columns if column in aliases), None)
        result[standard_field] = matched
    return result


def get_value(row: pd.Series, column_map: dict[str, str | None], field: str) -> Any:
    column = column_map.get(field)
    if not column:
        return None
    return row.get(column)


def clean_scalar(value: Any) -> Any:
    if is_empty(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return bool(pd.isna(value)) if not isinstance(value, (list, tuple, dict)) else False


def to_text(value: Any) -> str:
    if is_empty(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def to_product_id(value: Any) -> str:
    if is_empty(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def to_float(value: Any) -> float:
    if is_empty(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        cleaned = re.sub(r"[^0-9.\-]", "", str(value))
        return float(cleaned) if cleaned else 0.0


def to_int(value: Any) -> int:
    if is_empty(value):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        cleaned = re.sub(r"[^0-9.\-]", "", str(value))
        return int(float(cleaned)) if cleaned else 0


def to_datetime_text(value: Any) -> str | None:
    if is_empty(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(microsecond=0).isoformat(sep=" ")


def parse_list_text(value: Any) -> list[str]:
    text = to_text(value)
    if not text or text == "[]":
        return []

    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]

    parts = [part.strip().strip("'\"") for part in text.split(",")]
    return [part for part in parts if part]
