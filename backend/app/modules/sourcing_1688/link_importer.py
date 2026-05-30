from __future__ import annotations

import html
import json
import re
import uuid
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse, urlunparse
from urllib.request import Request, urlopen

from app.core.config import UPLOADS_DIR, ensure_runtime_dirs
from app.core.database import insert_upload_batch, replace_products, utc_now_text


class Link1688ImportError(Exception):
    pass


PageFetcher = Callable[[str], str]


def import_1688_links(product_urls: list[str], fetch_page: PageFetcher | None = None) -> dict[str, object]:
    ensure_runtime_dirs()
    batch_id = uuid.uuid4().hex
    fetcher = fetch_page or fetch_1688_page
    products: list[dict[str, object]] = []
    errors: list[str] = []
    records: list[dict[str, object]] = []

    normalized_urls = normalize_input_urls(product_urls)
    if not normalized_urls:
        raise Link1688ImportError("请至少填写一个 1688 商品链接")

    for index, product_url in enumerate(normalized_urls, start=1):
        try:
            html_text = fetcher(product_url)
            product = build_product_from_1688_page(product_url, html_text, index)
            products.append(product)
            records.append({"url": product_url, "status": "imported", "product": product})
        except Exception as exc:  # noqa: BLE001
            fallback = build_fallback_product(product_url, index, str(exc))
            products.append(fallback)
            errors.append(f"{product_url}：页面采集不完整，已按链接导入（{exc}）")
            records.append({"url": product_url, "status": "fallback", "error": str(exc), "product": fallback})

    saved_path = save_import_record(batch_id, records)
    insert_upload_batch(
        batch_id=batch_id,
        source_filename=saved_path.name,
        saved_path=saved_path,
        file_type="1688-url",
        total_rows=len(normalized_urls),
        imported_count=len(products),
        failed_count=0,
        status="imported",
        error_message="\n".join(errors[:20]) if errors else None,
    )
    replace_products(batch_id, products)

    return {
        "batch_id": batch_id,
        "source_filename": saved_path.name,
        "file_type": "1688-url",
        "total_rows": len(normalized_urls),
        "imported_count": len(products),
        "failed_count": 0,
        "errors": errors[:20],
    }


def normalize_input_urls(product_urls: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized_urls: list[str] = []
    for raw_url in product_urls:
        if not raw_url:
            continue
        for part in re.split(r"[\s,，]+", raw_url):
            clean_url = part.strip()
            if not clean_url:
                continue
            normalized_url = normalize_1688_url(clean_url)
            if normalized_url not in seen:
                seen.add(normalized_url)
                normalized_urls.append(normalized_url)
    return normalized_urls


def normalize_1688_url(raw_url: str) -> str:
    url = raw_url.strip()
    if url.startswith("//"):
        url = f"https:{url}"
    elif not re.match(r"^https?://", url):
        url = f"https://{url}"

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if not host.endswith("1688.com"):
        raise Link1688ImportError("只支持 1688 商品链接")

    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned)


def extract_offer_id(product_url: str) -> str | None:
    parsed = urlparse(product_url)
    match = re.search(r"/offer/(\d+)\.html", parsed.path)
    if match:
        return match.group(1)

    query = parse_qs(parsed.query)
    for key in ("offerId", "offer_id", "id"):
        value = query.get(key, [None])[0]
        if value and value.isdigit():
            return value
    return None


def fetch_1688_page(product_url: str) -> str:
    request = Request(
        product_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310
            content = response.read(2_500_000)
            content_type = response.headers.get("content-type", "")
    except HTTPError as exc:
        raise Link1688ImportError(f"1688 返回 HTTP {exc.code}") from exc
    except URLError as exc:
        raise Link1688ImportError(f"无法访问 1688 页面：{exc.reason}") from exc

    return decode_html(content, content_type)


def decode_html(content: bytes, content_type: str = "") -> str:
    charset_match = re.search(r"charset=([\w-]+)", content_type, re.I)
    candidates = [charset_match.group(1)] if charset_match else []
    candidates.extend(["utf-8", "gb18030"])

    for encoding in candidates:
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def build_product_from_1688_page(product_url: str, html_text: str, source_row_index: int) -> dict[str, object]:
    offer_id = extract_offer_id(product_url)
    title = first_non_empty(
        extract_meta_content(html_text, "og:title"),
        extract_json_string(html_text, "subject"),
        extract_json_string(html_text, "title"),
        extract_title_tag(html_text),
    )
    if not title:
        raise Link1688ImportError("页面里没有识别到商品标题")

    gallery_urls = extract_image_urls(html_text)
    main_image_url = first_non_empty(
        extract_meta_content(html_text, "og:image"),
        extract_json_string(html_text, "mainPicUrl"),
        extract_json_string(html_text, "imageUrl"),
        gallery_urls[0] if gallery_urls else None,
    )
    price = extract_price(html_text)
    category_parts = extract_category_parts(html_text)
    category_path = "/".join(category_parts) if category_parts else "未采集类目"

    return product_payload(
        product_url=product_url,
        offer_id=offer_id,
        title=clean_text(title),
        main_image_url=main_image_url,
        gallery_image_urls=gallery_urls,
        price=price,
        category_path=category_path,
        source_row_index=source_row_index,
        raw_data={
            "source": "1688-url",
            "offer_id": offer_id,
            "product_url": product_url,
            "price_cny": price,
            "category_path": category_path,
            "category_parts": category_parts,
            "captured_by": "server_link_import",
        },
    )


def build_fallback_product(product_url: str, source_row_index: int, reason: str) -> dict[str, object]:
    offer_id = extract_offer_id(product_url)
    title = f"1688 商品 {offer_id}" if offer_id else "1688 链接商品"
    return product_payload(
        product_url=product_url,
        offer_id=offer_id,
        title=title,
        main_image_url=None,
        gallery_image_urls=[],
        price=None,
        category_path="未采集类目",
        source_row_index=source_row_index,
        raw_data={
            "source": "1688-url",
            "offer_id": offer_id,
            "product_url": product_url,
            "fallback_reason": reason,
            "captured_by": "server_link_import",
        },
    )


def product_payload(
    *,
    product_url: str,
    offer_id: str | None,
    title: str,
    main_image_url: str | None,
    gallery_image_urls: list[str],
    price: float | None,
    category_path: str,
    source_row_index: int,
    raw_data: dict[str, object],
) -> dict[str, object]:
    source_product_id = offer_id or uuid.uuid5(uuid.NAMESPACE_URL, product_url).hex[:16]
    now = utc_now_text()
    category_parts = [part.strip() for part in category_path.split("/") if part.strip()]
    return {
        "id": f"1688-{source_product_id}",
        "source_row_index": source_row_index,
        "source_type": "1688",
        "source_product_id": source_product_id,
        "title_cn": title,
        "title_en": None,
        "title": title,
        "main_image_url": main_image_url,
        "gallery_image_urls": gallery_image_urls,
        "video_url": None,
        "source_url": product_url,
        "category_path": category_path,
        "category_level1": category_parts[0] if category_parts else "未采集类目",
        "category_level2": category_parts[1] if len(category_parts) > 1 else None,
        "tags": ["1688链接采集"],
        "price_usd": float(price or 0),
        "gmv_usd": 0,
        "weekly_sales": 0,
        "monthly_sales": 0,
        "review_count": 0,
        "listing_time": now,
        "status": "active",
        "raw_data": raw_data,
    }


def save_import_record(batch_id: str, records: list[dict[str, object]]) -> Path:
    saved_path = UPLOADS_DIR / f"{batch_id}_1688_links.json"
    with saved_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
    return saved_path


def extract_meta_content(html_text: str, property_name: str) -> str | None:
    patterns = [
        rf"<meta[^>]+property=[\"']{re.escape(property_name)}[\"'][^>]+content=[\"']([^\"']+)[\"']",
        rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']{re.escape(property_name)}[\"']",
        rf"<meta[^>]+name=[\"']{re.escape(property_name)}[\"'][^>]+content=[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I)
        if match:
            return html.unescape(match.group(1))
    return None


def extract_title_tag(html_text: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1))
    title = re.sub(r"[-_]\s*阿里巴巴.*$", "", title)
    return html.unescape(title.strip())


def extract_json_string(html_text: str, key: str) -> str | None:
    match = re.search(rf"[\"']{re.escape(key)}[\"']\s*:\s*[\"']([^\"']+)[\"']", html_text)
    if not match:
        return None
    return html.unescape(match.group(1).replace("\\/", "/"))


def extract_image_urls(html_text: str) -> list[str]:
    image_urls = re.findall(r"https?:\\?/\\?/[^\"'\\\s]+(?:alicdn|1688)[^\"'\\\s]+\.(?:jpg|jpeg|png|webp)", html_text, re.I)
    return unique_strings(html.unescape(url.replace("\\/", "/")) for url in image_urls)[:12]


def extract_price(html_text: str) -> float | None:
    for pattern in (
        r"[\"']price[\"']\s*:\s*[\"']?(\d+(?:\.\d+)?)",
        r"[\"']priceRange[\"']\s*:\s*[\"']?(\d+(?:\.\d+)?)",
        r"¥\s*(\d+(?:\.\d+)?)",
    ):
        match = re.search(pattern, html_text)
        if match:
            return float(match.group(1))
    return None


def extract_category_parts(html_text: str) -> list[str]:
    json_path = first_non_empty(
        extract_json_string(html_text, "categoryPath"),
        extract_json_string(html_text, "catPath"),
        extract_json_string(html_text, "catePath"),
    )
    parts = normalize_category_parts(split_category_text(json_path or ""))
    if parts:
        return parts

    crumb_patterns = [
        r"<(?:div|nav|ul|ol)[^>]+class=[\"'][^\"']*(?:breadcrumb|crumb|category)[^\"']*[\"'][^>]*>(.*?)</(?:div|nav|ul|ol)>",
    ]
    for pattern in crumb_patterns:
        for match in re.finditer(pattern, html_text, re.I | re.S):
            text = re.sub(r"<[^>]+>", ">", match.group(1))
            parts = normalize_category_parts(split_category_text(text))
            if len(parts) >= 2:
                return parts

    category_names = [
        clean_text(match.group(1))
        for match in re.finditer(r"[\"'](?:categoryName|catName|cateName)[\"']\s*:\s*[\"']([^\"']+)[\"']", html_text)
    ]
    return normalize_category_parts(category_names)


def split_category_text(value: str) -> list[str]:
    return re.split(r"\s*(?:>|›|»|/|\\|｜|\|)\s*", html.unescape(value.replace("\\/", "/")))


def normalize_category_parts(values: list[str]) -> list[str]:
    blocked = {"首页", "阿里巴巴", "1688", "商品详情", "全部商品", "所有分类"}
    parts: list[str] = []
    seen: set[str] = set()
    for value in values:
        part = clean_text(value)
        part = re.sub(r"^[当前位置所在类目分类：:\s]+", "", part)
        part = re.sub(r"\s*批发价格.*$", "", part)
        if not part or part in blocked or len(part) > 32 or part in seen:
            continue
        if re.fullmatch(r"\d+", part) or re.search(r"[¥￥$]\s*\d", part):
            continue
        parts.append(part)
        seen.add(part)
    return parts[:5]


def first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def unique_strings(values: object) -> list[str]:
    items: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in items:
            items.append(value)
    return items
