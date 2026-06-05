from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any


DOMAIN_TERMS = [
    "钥匙扣",
    "钥匙链",
    "挂件",
    "挂饰",
    "吊坠",
    "流苏",
    "字母",
    "爱心",
    "汽车钥匙",
    "包包",
    "收纳盒",
    "药盒",
    "药片盒",
    "分药盒",
    "包装盒",
    "礼品袋",
    "耳环",
    "项链",
    "手链",
    "发饰",
    "发圈",
    "吊牌",
    "手机壳",
    "贴纸",
    "宠物",
    "厨房",
    "文具",
    "玩具",
    "服装",
    "汽车",
    "户外",
]

MATERIAL_TERMS = [
    "金属",
    "不锈钢",
    "合金",
    "滴胶",
    "亚克力",
    "塑料",
    "硅胶",
    "陶瓷",
    "木质",
    "玻璃",
    "棉",
    "皮革",
    "PVC",
    "树脂",
]

SHAPE_TERMS = [
    "圆形",
    "方形",
    "长方形",
    "心形",
    "爱心",
    "字母",
    "卡通",
    "动物",
    "花朵",
    "星星",
    "迷你",
    "透明",
    "分格",
]

SCENE_TERMS = [
    "汽车",
    "车钥匙",
    "包包",
    "旅行",
    "宿舍",
    "厨房",
    "办公室",
    "学校",
    "礼品",
    "派对",
    "婚礼",
    "宠物",
]

STOP_TERMS = {
    "1688",
    "temu",
    "商品",
    "采集",
    "采集素材",
    "素材",
    "跨境",
    "热销",
    "批发",
    "厂家",
    "现货",
    "包邮",
    "新款",
    "专供",
    "外贸",
    "一件代发",
    "广告",
    "for",
    "and",
    "the",
    "with",
    "new",
    "product",
    "newproduct",
    "bestseller",
    "bestsellers",
    "未分类",
}


def ensure_recommendation_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS product_keywords (
            id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            keyword TEXT NOT NULL,
            keyword_type TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'rule',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_product_keywords_unique
            ON product_keywords(product_id, keyword, keyword_type);
        CREATE INDEX IF NOT EXISTS idx_product_keywords_keyword
            ON product_keywords(keyword);
        CREATE INDEX IF NOT EXISTS idx_product_keywords_product
            ON product_keywords(product_id);
        CREATE INDEX IF NOT EXISTS idx_product_keywords_type
            ON product_keywords(keyword_type);

        CREATE TABLE IF NOT EXISTS product_ai_analysis_cache (
            product_id TEXT PRIMARY KEY,
            title_hash TEXT NOT NULL,
            analysis_json TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )


def replace_product_keyword_index(
    conn: sqlite3.Connection,
    products: list[dict[str, Any]],
    *,
    now: str,
) -> int:
    ensure_recommendation_schema(conn)
    product_ids = [clean_text(product.get("id")) for product in products if clean_text(product.get("id"))]
    if not product_ids:
        return 0

    conn.executemany("DELETE FROM product_keywords WHERE product_id = ?", [(product_id,) for product_id in product_ids])

    records: list[dict[str, Any]] = []
    for product in products:
        records.extend(build_product_keyword_records(product, now=now))

    if not records:
        return 0

    conn.executemany(
        """
        INSERT OR REPLACE INTO product_keywords (
            id, product_id, keyword, keyword_type, weight, source, created_at, updated_at
        ) VALUES (
            :id, :product_id, :keyword, :keyword_type, :weight, :source, :created_at, :updated_at
        )
        """,
        records,
    )
    return len(records)


def rebuild_all_product_keyword_index() -> dict[str, int]:
    from app.core.database import get_connection, utc_now_text

    now = utc_now_text()
    with get_connection() as conn:
        ensure_recommendation_schema(conn)
        rows = conn.execute(
            """
            SELECT
                id, title, title_cn, title_en, category_path, category_level1, category_level2,
                tags_json, raw_data_json, source_type
            FROM products
            WHERE status != 'deleted'
            """
        ).fetchall()
        products = [row_to_product_dict(row) for row in rows]
        indexed_count = replace_product_keyword_index(conn, products, now=now)
        return {"product_count": len(products), "keyword_count": indexed_count}


def build_product_keyword_records(product: dict[str, Any], *, now: str) -> list[dict[str, Any]]:
    product_id = clean_text(product.get("id"))
    if not product_id:
        return []

    weighted_terms: dict[tuple[str, str], float] = {}

    def add_terms(keyword_type: str, values: list[str], weight: float) -> None:
        for value in values:
            keyword = normalize_keyword(value)
            if not is_valid_keyword(keyword):
                continue
            key = (keyword, keyword_type)
            weighted_terms[key] = max(weighted_terms.get(key, 0), weight)

    title_text = clean_text(join_text_values(product.get("title"), product.get("title_cn"), product.get("title_en")))
    category_text = clean_text(
        join_text_values(product.get("category_path"), product.get("category_level1"), product.get("category_level2"))
    )
    tags = to_string_list(product.get("tags"))
    raw_data = product.get("raw_data") if isinstance(product.get("raw_data"), dict) else {}
    raw_text = clean_text(" ".join(str(value) for key, value in raw_data.items() if key and value and len(str(value)) < 120))

    add_terms("category", split_category_terms(category_text), 12)
    add_terms("title", extract_text_terms(title_text), 5)
    add_terms("tag", tags, 4)
    add_terms("material", find_known_terms(title_text, MATERIAL_TERMS), 8)
    add_terms("shape", find_known_terms(title_text, SHAPE_TERMS), 7)
    add_terms("scene", find_known_terms(f"{title_text} {category_text}", SCENE_TERMS), 7)
    add_terms("domain", find_known_terms(f"{title_text} {category_text}", DOMAIN_TERMS), 10)
    add_terms("raw", find_known_terms(raw_text, [*DOMAIN_TERMS, *MATERIAL_TERMS, *SHAPE_TERMS, *SCENE_TERMS]), 2)

    records: list[dict[str, Any]] = []
    for (keyword, keyword_type), weight in sorted(weighted_terms.items(), key=lambda item: (-item[1], item[0][0]))[:80]:
        records.append(
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"product-keyword:{product_id}:{keyword_type}:{keyword}").hex,
                "product_id": product_id,
                "keyword": keyword,
                "keyword_type": keyword_type,
                "weight": weight,
                "source": "rule",
                "created_at": now,
                "updated_at": now,
            }
        )
    return records


def split_category_terms(value: str) -> list[str]:
    parts = re.split(r"[/>\-|,，;；\s]+", clean_text(value))
    return [part for part in parts if is_valid_keyword(normalize_keyword(part))]


def extract_text_terms(value: str) -> list[str]:
    text = clean_text(value).lower()
    terms: list[str] = []

    terms.extend(find_known_terms(text, [*DOMAIN_TERMS, *MATERIAL_TERMS, *SHAPE_TERMS, *SCENE_TERMS]))

    for chunk in re.findall("[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text):
        normalized = normalize_keyword(chunk)
        if not is_valid_keyword(normalized):
            continue
        if re.fullmatch("[\u4e00-\u9fff]+", normalized) and len(normalized) > 6:
            terms.extend(build_chinese_ngrams(normalized))
        else:
            terms.append(normalized)

    return unique_terms(terms)[:60]


def build_chinese_ngrams(value: str) -> list[str]:
    terms: list[str] = []
    max_size = min(6, len(value))
    for size in range(max_size, 1, -1):
        for index in range(0, len(value) - size + 1):
            term = normalize_keyword(value[index : index + size])
            if is_valid_keyword(term):
                terms.append(term)
    return terms[:50]


def find_known_terms(text: str, terms: list[str]) -> list[str]:
    clean = clean_text(text).lower()
    return [term for term in terms if normalize_keyword(term) in clean]


def normalize_keyword(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub("[^\u4e00-\u9fffA-Za-z0-9+#.]+", "", text)
    return text.strip()


def is_valid_keyword(value: str) -> bool:
    if not value or value in STOP_TERMS:
        return False
    if len(value) < 2 or len(value) > 24:
        return False
    if value.isdigit():
        return False
    return True


def unique_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        keyword = normalize_keyword(value)
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        result.append(keyword)
    return result


def to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [clean_text(item) for item in parsed if clean_text(item)]
        except json.JSONDecodeError:
            return [item for item in re.split(r"[,，;；\s]+", value) if item]
    return []


def row_to_product_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "title_cn": row["title_cn"],
        "title_en": row["title_en"],
        "category_path": row["category_path"],
        "category_level1": row["category_level1"],
        "category_level2": row["category_level2"],
        "tags": safe_json_loads(row["tags_json"], []),
        "raw_data": safe_json_loads(row["raw_data_json"], {}),
        "source_type": row["source_type"],
    }


def safe_json_loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def join_text_values(*values: Any) -> str:
    return " ".join(clean_text(value) for value in values if clean_text(value))
