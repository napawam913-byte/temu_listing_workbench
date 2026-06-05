from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import UPLOADS_DIR, ensure_runtime_dirs
from app.core.database import ensure_product_identity_index, get_connection, utc_now_text
from app.modules.recommendation.keyword_index import replace_product_keyword_index
from app.modules.yunqi.cleaner import clean_scalar
from app.modules.yunqi.importer import detect_file_type, read_yunqi_dataframe


SOURCE_TYPE = "yunqi"
DEFAULT_CATEGORY_PATH = "未分类"

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_product_id": (
        "source_product_id",
        "product_id",
        "productId",
        "goods_id",
        "goodsId",
        "item_id",
        "itemId",
        "spu_id",
        "spuId",
        "id",
        "商品ID",
        "商品 ID",
        "商品id",
    ),
    "source_row_index": ("source_row_index", "row_index", "rowIndex", "序号", "行号"),
    "title_cn": ("title_cn", "titleCn", "title_zh", "name_cn", "product_name_cn", "商品标题（中文）", "中文标题"),
    "title_en": ("title_en", "titleEn", "name_en", "product_name_en", "商品标题（英文）", "英文标题"),
    "title": ("title", "name", "product_name", "subject", "商品标题", "商品名称"),
    "main_image_url": (
        "main_image_url",
        "mainImageUrl",
        "main_image",
        "mainImage",
        "image_url",
        "imageUrl",
        "image",
        "商品主图",
        "主图",
    ),
    "gallery_image_urls": (
        "gallery_image_urls",
        "galleryImageUrls",
        "gallery_images",
        "galleryImages",
        "image_urls",
        "imageUrls",
        "images",
        "carousel_images",
        "carouselImages",
        "商品轮播图",
        "轮播图",
    ),
    "video_url": ("video_url", "videoUrl", "video", "商品视频", "视频"),
    "source_url": ("source_url", "sourceUrl", "product_url", "productUrl", "url", "link", "商品链接", "链接"),
    "category_path": (
        "category_path",
        "categoryPath",
        "category",
        "category_name",
        "categoryName",
        "front_category",
        "frontCategory",
        "前台分类（中文）",
        "前台分类",
        "类目",
        "分类",
    ),
    "tags": ("tags", "tag_list", "tagList", "labels", "label_list", "标签"),
    "price_usd": ("price_usd", "priceUsd", "usd_price", "usdPrice", "price", "美元价格($)", "美元价格", "价格"),
    "gmv_usd": ("gmv_usd", "gmvUsd", "gmv", "GMV($)", "GMV"),
    "weekly_sales": ("weekly_sales", "weeklySales", "week_sales", "weekSales", "周销量", "周销"),
    "monthly_sales": ("monthly_sales", "monthlySales", "month_sales", "monthSales", "月销量", "月销"),
    "review_count": ("review_count", "reviewCount", "reviews", "comment_count", "commentCount", "总评论数", "评论数"),
    "listing_time": ("listing_time", "listingTime", "listed_at", "listedAt", "created_time", "上架时间"),
    "status": ("status", "商品状态", "状态"),
}


class YunqiCollectorError(Exception):
    pass


@dataclass(frozen=True)
class YunqiCollectorConfig:
    base_url: str = ""
    username: str = ""
    password: str = ""
    cookie: str = ""
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls) -> "YunqiCollectorConfig":
        return cls(
            base_url=os.getenv("YUNQI_BASE_URL", "").strip().rstrip("/"),
            username=os.getenv("YUNQI_USERNAME", "").strip(),
            password=os.getenv("YUNQI_PASSWORD", "").strip(),
            cookie=os.getenv("YUNQI_COOKIE", "").strip(),
            timeout_seconds=to_int(os.getenv("YUNQI_TIMEOUT_SECONDS", "30")) or 30,
        )


class YunqiApiClient:
    """Interface placeholder for the future Yunqi HTTP/RPA connector."""

    def __init__(self, config: YunqiCollectorConfig | None = None) -> None:
        self.config = config or YunqiCollectorConfig.from_env()

    def initialize_session(self) -> None:
        if not self.config.base_url:
            raise YunqiCollectorError(
                "YUNQI_BASE_URL is not configured. Use --replay-json for local replay, "
                "or provide Yunqi connection settings in the environment."
            )
        raise YunqiCollectorError(
            "The real Yunqi login/session connector is not implemented yet. "
            "Use --replay-json now, then replace YunqiApiClient with HTTP or RPA logic."
        )

    def fetch_product_list(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        raise YunqiCollectorError("The real Yunqi product-list fetcher is not implemented yet.")

    def fetch_product_detail(self, source_product_id: str) -> dict[str, Any] | None:
        raise YunqiCollectorError(f"The real Yunqi detail fetcher is not implemented yet: {source_product_id}")


def collect_yunqi_products(
    *,
    replay_json_path: str | Path | None = None,
    fetch_details: bool = False,
    limit: int | None = None,
    rebuild_keywords: bool = True,
    client: YunqiApiClient | None = None,
) -> dict[str, Any]:
    ensure_runtime_dirs()

    if replay_json_path:
        replay_path = Path(replay_json_path)
        records = load_replay_records(replay_path)
        source_filename = replay_path.name
        source_label = "yunqi-replay-json"
    else:
        yunqi_client = client or YunqiApiClient()
        yunqi_client.initialize_session()
        records = yunqi_client.fetch_product_list(limit=limit)
        if fetch_details:
            records = [merge_detail_record(yunqi_client, record) for record in records]
        source_filename = "yunqi-api"
        source_label = "yunqi-api"

    if limit is not None:
        records = records[: max(0, limit)]

    products, errors = normalize_yunqi_records(records)
    if not products:
        raise YunqiCollectorError("No valid Yunqi products were found in this collection run.")

    batch_id = uuid.uuid4().hex
    snapshot_path = save_collection_snapshot(
        batch_id=batch_id,
        source_filename=source_filename,
        records=records,
        products=products,
        errors=errors,
    )
    upsert_result = upsert_yunqi_products(
        products,
        batch_id=batch_id,
        source_filename=source_filename,
        saved_path=snapshot_path,
        total_rows=len(records),
        failed_count=len(errors),
        error_message="\n".join(errors[:20]) if errors else None,
        rebuild_keywords=rebuild_keywords,
    )

    return {
        "batch_id": batch_id,
        "source": source_label,
        "source_filename": source_filename,
        "snapshot_path": str(snapshot_path),
        "total_rows": len(records),
        "imported_count": upsert_result["imported_count"],
        "created_count": upsert_result["created_count"],
        "updated_count": upsert_result["updated_count"],
        "failed_count": len(errors),
        "keyword_count": upsert_result["keyword_count"],
        "errors": errors[:20],
    }


def collect_yunqi_excel_file(
    excel_path: str | Path,
    *,
    limit: int | None = None,
    rebuild_keywords: bool = True,
) -> dict[str, Any]:
    ensure_runtime_dirs()
    path = Path(excel_path)
    if not path.exists():
        raise YunqiCollectorError(f"Yunqi Excel file does not exist: {path}")

    file_type = detect_file_type(path)
    df = read_yunqi_dataframe(path, file_type)
    records = dataframe_to_records(df)
    if limit is not None:
        records = records[: max(0, limit)]

    products, errors = normalize_yunqi_records(records)
    if not products:
        raise YunqiCollectorError("No valid Yunqi products were found in the exported Excel file.")

    batch_id = uuid.uuid4().hex
    upsert_result = upsert_yunqi_products(
        products,
        batch_id=batch_id,
        source_filename=path.name,
        saved_path=path,
        total_rows=len(records),
        failed_count=len(errors),
        error_message="\n".join(errors[:20]) if errors else None,
        rebuild_keywords=rebuild_keywords,
    )

    return {
        "batch_id": batch_id,
        "source": "yunqi-excel",
        "source_filename": path.name,
        "excel_path": str(path),
        "file_type": file_type,
        "total_rows": len(records),
        "imported_count": upsert_result["imported_count"],
        "created_count": upsert_result["created_count"],
        "updated_count": upsert_result["updated_count"],
        "failed_count": len(errors),
        "keyword_count": upsert_result["keyword_count"],
        "errors": errors[:20],
    }


def dataframe_to_records(df: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        record = {str(column).strip(): clean_scalar(row[column]) for column in df.columns}
        record["source_row_index"] = int(index) + 3
        records.append(record)
    return records


def merge_detail_record(client: YunqiApiClient, record: dict[str, Any]) -> dict[str, Any]:
    source_product_id = to_product_id(read_field(record, FIELD_ALIASES["source_product_id"]))
    if not source_product_id:
        return record
    detail = client.fetch_product_detail(source_product_id)
    if not detail:
        return record
    return {**detail, **record, "detail": detail}


def load_replay_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise YunqiCollectorError(f"Replay JSON file does not exist: {path}")

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    records = extract_records(payload)
    if not records:
        raise YunqiCollectorError(f"Replay JSON file does not contain product records: {path}")
    return records


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("products", "items", "records", "rows", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return extract_records(data)

    return []


def normalize_yunqi_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    products: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, record in enumerate(records, start=1):
        try:
            products.append(normalize_yunqi_record(record, source_row_index=index))
        except Exception as exc:  # noqa: BLE001 - keep importing the rest of the batch.
            errors.append(f"row {index}: {exc}")

    return dedupe_products(products), errors


def normalize_yunqi_record(record: dict[str, Any], *, source_row_index: int = 1) -> dict[str, Any]:
    raw_source_product_id = read_field(record, FIELD_ALIASES["source_product_id"])
    source_product_id = to_product_id(raw_source_product_id)
    if not source_product_id:
        raise YunqiCollectorError("missing source_product_id")

    row_index = to_int(read_field(record, FIELD_ALIASES["source_row_index"])) or source_row_index
    gallery_image_urls = parse_url_list(read_field(record, FIELD_ALIASES["gallery_image_urls"]))
    main_image_url = to_text(read_field(record, FIELD_ALIASES["main_image_url"])) or (
        gallery_image_urls[0] if gallery_image_urls else ""
    )
    title_cn = to_text(read_field(record, FIELD_ALIASES["title_cn"]))
    title_en = to_text(read_field(record, FIELD_ALIASES["title_en"]))
    raw_title = to_text(read_field(record, FIELD_ALIASES["title"]))
    title = title_cn or title_en or raw_title or f"Yunqi product {source_product_id}"
    category_path, category_level1, category_level2 = normalize_category_fields(
        read_field(record, FIELD_ALIASES["category_path"])
    )

    return {
        "id": source_product_id,
        "source_type": SOURCE_TYPE,
        "source_product_id": source_product_id,
        "source_row_index": row_index,
        "title_cn": title_cn or None,
        "title_en": title_en or None,
        "title": title,
        "main_image_url": main_image_url or None,
        "gallery_image_urls": gallery_image_urls,
        "video_url": to_text(read_field(record, FIELD_ALIASES["video_url"])) or None,
        "source_url": to_text(read_field(record, FIELD_ALIASES["source_url"])) or None,
        "category_path": category_path,
        "category_level1": category_level1,
        "category_level2": category_level2,
        "tags": parse_list_value(read_field(record, FIELD_ALIASES["tags"])),
        "price_usd": to_float(read_field(record, FIELD_ALIASES["price_usd"])),
        "gmv_usd": to_float(read_field(record, FIELD_ALIASES["gmv_usd"])),
        "weekly_sales": to_int(read_field(record, FIELD_ALIASES["weekly_sales"])),
        "monthly_sales": to_int(read_field(record, FIELD_ALIASES["monthly_sales"])),
        "review_count": to_int(read_field(record, FIELD_ALIASES["review_count"])),
        "listing_time": to_datetime_text(read_field(record, FIELD_ALIASES["listing_time"])),
        "status": normalize_status(read_field(record, FIELD_ALIASES["status"])),
        "raw_data": to_json_safe(record),
    }


def upsert_yunqi_products(
    products: list[dict[str, Any]],
    *,
    batch_id: str | None = None,
    source_filename: str = "yunqi-collector",
    saved_path: str | Path | None = None,
    total_rows: int | None = None,
    failed_count: int = 0,
    error_message: str | None = None,
    rebuild_keywords: bool = True,
) -> dict[str, int | str]:
    if not products:
        return {
            "batch_id": batch_id or "",
            "imported_count": 0,
            "created_count": 0,
            "updated_count": 0,
            "keyword_count": 0,
        }

    ensure_runtime_dirs()
    safe_batch_id = batch_id or uuid.uuid4().hex
    safe_saved_path = Path(saved_path) if saved_path else UPLOADS_DIR / f"{safe_batch_id}_yunqi_collector.json"
    prepared_products = [prepare_product_for_db(product) for product in dedupe_products(products)]
    now = utc_now_text()

    with get_connection() as conn:
        ensure_product_identity_index(conn)
        conn.execute(
            """
            INSERT INTO upload_batches (
                id, source_filename, saved_path, file_type, total_rows,
                imported_count, failed_count, status, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total_rows = excluded.total_rows,
                imported_count = excluded.imported_count,
                failed_count = excluded.failed_count,
                status = excluded.status,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            """,
            (
                safe_batch_id,
                Path(source_filename).name,
                str(safe_saved_path),
                "yunqi-collector",
                total_rows if total_rows is not None else len(products),
                len(prepared_products),
                failed_count,
                "imported",
                error_message,
                now,
                now,
            ),
        )

        existing = load_existing_yunqi_products(conn, [product["source_product_id"] for product in prepared_products])
        created_count = 0
        updated_count = 0
        indexed_products: list[dict[str, Any]] = []

        for product in prepared_products:
            existing_row = existing.get(product["source_product_id"])
            db_product = {
                **product,
                "id": existing_row["id"] if existing_row else product["id"],
                "upload_batch_id": safe_batch_id,
                "gallery_image_urls_json": json_dumps(product.get("gallery_image_urls", [])),
                "tags_json": json_dumps(product.get("tags", [])),
                "raw_data_json": json_dumps(product.get("raw_data", {})),
                "created_at": now,
                "updated_at": now,
            }
            if existing_row:
                update_existing_product(conn, db_product)
                updated_count += 1
            else:
                insert_new_product(conn, db_product)
                created_count += 1
            indexed_products.append({**product, "id": db_product["id"]})

        keyword_count = 0
        if rebuild_keywords:
            keyword_count = replace_product_keyword_index(conn, indexed_products, now=now)

    return {
        "batch_id": safe_batch_id,
        "imported_count": len(prepared_products),
        "created_count": created_count,
        "updated_count": updated_count,
        "keyword_count": keyword_count,
    }


def load_existing_yunqi_products(conn: Any, source_product_ids: list[str]) -> dict[str, dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    for source_product_id in source_product_ids:
        row = conn.execute(
            """
            SELECT id, source_product_id, created_at
            FROM products
            WHERE source_type = ? AND source_product_id = ?
            ORDER BY datetime(updated_at) DESC
            LIMIT 1
            """,
            (SOURCE_TYPE, source_product_id),
        ).fetchone()
        if row:
            existing[source_product_id] = dict(row)
    return existing


def insert_new_product(conn: Any, product: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO products (
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
        product,
    )


def update_existing_product(conn: Any, product: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE products
        SET
            upload_batch_id = :upload_batch_id,
            source_row_index = :source_row_index,
            title_cn = :title_cn,
            title_en = :title_en,
            title = :title,
            main_image_url = :main_image_url,
            gallery_image_urls_json = :gallery_image_urls_json,
            video_url = :video_url,
            source_url = :source_url,
            category_path = :category_path,
            category_level1 = :category_level1,
            category_level2 = :category_level2,
            tags_json = :tags_json,
            price_usd = :price_usd,
            gmv_usd = :gmv_usd,
            weekly_sales = :weekly_sales,
            monthly_sales = :monthly_sales,
            review_count = :review_count,
            listing_time = :listing_time,
            status = :status,
            in_product_pool = MAX(in_product_pool, :in_product_pool),
            raw_data_json = :raw_data_json,
            updated_at = :updated_at
        WHERE id = :id
        """,
        product,
    )


def prepare_product_for_db(product: dict[str, Any]) -> dict[str, Any]:
    source_product_id = to_product_id(product.get("source_product_id"))
    if not source_product_id:
        raise YunqiCollectorError("normalized product is missing source_product_id")

    title = to_text(product.get("title")) or to_text(product.get("title_cn")) or to_text(product.get("title_en"))
    if not title:
        title = f"Yunqi product {source_product_id}"

    category_path, category_level1, category_level2 = normalize_category_fields(product.get("category_path"))
    return {
        "id": to_text(product.get("id")) or source_product_id,
        "upload_batch_id": product.get("upload_batch_id"),
        "source_row_index": to_int(product.get("source_row_index")) or 1,
        "source_type": SOURCE_TYPE,
        "source_product_id": source_product_id,
        "title_cn": to_text(product.get("title_cn")) or None,
        "title_en": to_text(product.get("title_en")) or None,
        "title": title,
        "main_image_url": to_text(product.get("main_image_url")) or None,
        "gallery_image_urls": parse_url_list(product.get("gallery_image_urls")),
        "video_url": to_text(product.get("video_url")) or None,
        "source_url": to_text(product.get("source_url")) or None,
        "category_path": category_path,
        "category_level1": category_level1,
        "category_level2": category_level2,
        "tags": parse_list_value(product.get("tags")),
        "price_usd": to_float(product.get("price_usd")),
        "gmv_usd": to_float(product.get("gmv_usd")),
        "weekly_sales": to_int(product.get("weekly_sales")),
        "monthly_sales": to_int(product.get("monthly_sales")),
        "review_count": to_int(product.get("review_count")),
        "listing_time": to_datetime_text(product.get("listing_time")),
        "status": normalize_status(product.get("status")),
        "in_product_pool": 1 if product.get("in_product_pool") else 0,
        "raw_data": to_json_safe(product.get("raw_data") or {}),
    }


def save_collection_snapshot(
    *,
    batch_id: str,
    source_filename: str,
    records: list[dict[str, Any]],
    products: list[dict[str, Any]],
    errors: list[str],
) -> Path:
    safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(source_filename).stem).strip("_") or "yunqi"
    path = UPLOADS_DIR / f"{batch_id}_{safe_source}_yunqi_collection.json"
    payload = {
        "source_filename": source_filename,
        "total_rows": len(records),
        "normalized_count": len(products),
        "errors": errors,
        "records": records,
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
    return path


def read_field(record: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = record.get(alias)
        if not is_empty(value):
            return value

    normalized_aliases = {normalize_key(alias) for alias in aliases}
    for key, value in record.items():
        if normalize_key(str(key)) in normalized_aliases and not is_empty(value):
            return value
    return None


def normalize_key(value: str) -> str:
    return re.sub(r"[\s_\-()（）]+", "", value).lower()


def normalize_category_fields(value: Any) -> tuple[str, str, str | None]:
    parts = normalize_category_parts(value)
    if not parts:
        return DEFAULT_CATEGORY_PATH, DEFAULT_CATEGORY_PATH, None
    return "/".join(parts), parts[0], parts[1] if len(parts) > 1 else None


def normalize_category_parts(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_parts = [to_text(item) for item in value]
    else:
        text = to_text(value)
        raw_parts = re.split(r"\s*(?:/|>|»|›|\\|\||\u300b|->|—|–)\s*", text) if text else []

    parts: list[str] = []
    seen: set[str] = set()
    for raw_part in raw_parts:
        part = re.sub(r"\s+", " ", raw_part).strip()
        if not part or part in seen:
            continue
        seen.add(part)
        parts.append(part)
    return parts[:5]


def normalize_status(value: Any) -> str:
    status = to_text(value).lower()
    if status in {"deleted", "inactive", "off", "offline", "下架", "删除"}:
        return "deleted"
    if status == "sourced":
        return "sourced"
    return "active"


def to_product_id(value: Any) -> str:
    if is_empty(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = to_text(value)
    return text[:-2] if text.endswith(".0") else text


def to_text(value: Any) -> str:
    if is_empty(value):
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json_dumps(value)
    return str(value).strip()


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null"}
    return False


def to_float(value: Any) -> float:
    if is_empty(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(",", "")
    lower = text.lower()
    multiplier = 1.0
    if "万" in text:
        multiplier = 10000.0
    elif "k" in lower:
        multiplier = 1000.0
    elif "m" in lower:
        multiplier = 1000000.0

    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", "."}:
        return 0.0
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return 0.0


def to_int(value: Any) -> int:
    return int(round(to_float(value)))


def to_datetime_text(value: Any) -> str | None:
    if is_empty(value):
        return None

    if isinstance(value, (int, float)) and value > 0:
        timestamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None, microsecond=0).isoformat(sep=" ")

    text = to_text(value)
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.replace(microsecond=0).isoformat(sep=" ")
    except ValueError:
        pass

    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(microsecond=0).isoformat(sep=" ")
        except ValueError:
            continue
    return text


def parse_url_list(value: Any) -> list[str]:
    return [item for item in parse_list_value(value) if item.startswith(("http://", "https://", "//"))]


def parse_list_value(value: Any) -> list[str]:
    if is_empty(value):
        return []

    if isinstance(value, list):
        return unique_texts(stringify_list_item(item) for item in value)

    if isinstance(value, tuple):
        return unique_texts(stringify_list_item(item) for item in value)

    if isinstance(value, dict):
        return unique_texts([stringify_list_item(value)])

    text = to_text(value)
    if not text or text == "[]":
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, (list, tuple, dict)):
            return parse_list_value(parsed)
    except json.JSONDecodeError:
        pass

    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]

    parts = re.split(r"[\n,，;；|]+", text)
    return unique_texts(part.strip().strip("'\"") for part in parts)


def stringify_list_item(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("url", "src", "image_url", "imageUrl", "main_image_url", "mainImageUrl"):
            value = item.get(key)
            if not is_empty(value):
                return to_text(value)
        return ""
    return to_text(item)


def unique_texts(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = to_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def dedupe_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for product in products:
        source_product_id = to_product_id(product.get("source_product_id"))
        if not source_product_id:
            continue
        if source_product_id not in by_source_id:
            order.append(source_product_id)
        by_source_id[source_product_id] = product
    return [by_source_id[source_product_id] for source_product_id in order]


def to_json_safe(value: Any) -> Any:
    return json.loads(json_dumps(value))


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
