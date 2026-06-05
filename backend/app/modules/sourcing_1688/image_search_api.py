from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from app.core.config import TMAPI_API_TOKEN, TMAPI_BASE_URL


class ImageSearchConfigError(Exception):
    pass


class ImageSearchApiError(Exception):
    pass


def search_1688_by_image_url(*, image_url: str, keyword: str = "", limit: int = 20) -> dict[str, Any]:
    clean_image_url = str(image_url or "").strip()
    if not clean_image_url:
        raise ValueError("缺少图片 URL")
    if not clean_image_url.startswith(("http://", "https://")):
        raise ValueError("图片 URL 必须是 http 或 https 地址")

    safe_limit = max(1, min(20, int(limit or 20)))
    converted_url = convert_image_url_for_tmapi(clean_image_url)
    raw_response = tmapi_get(
        "/1688/search/image",
        {
            "img_url": converted_url,
            "page": 1,
            "page_size": safe_limit,
            "sort": "default",
        },
    )
    items = normalize_tmapi_search_items(raw_response, keyword=keyword, limit=safe_limit)
    return {
        "provider": "tmapi",
        "image_url": clean_image_url,
        "query_image_url": converted_url,
        "items": items,
        "raw": raw_response,
    }


def convert_image_url_for_tmapi(image_url: str) -> str:
    if is_alibaba_image_url(image_url):
        return image_url

    body = tmapi_post(
        "/1688/tools/image/convert_url",
        {"url": image_url, "search_api_endpoint": "/search/image"},
    )
    data = body.get("data") if isinstance(body, dict) else {}
    converted = ""
    if isinstance(data, dict):
        converted = str(data.get("image_url") or data.get("url") or "").strip()
    if not converted:
        raise ImageSearchApiError("图片链接转换失败，1688 搜图 API 未返回可用图片地址")
    return converted


def is_alibaba_image_url(image_url: str) -> bool:
    host = urlparse(image_url).netloc.lower()
    return any(domain in host for domain in ("alicdn.com", "aliimg.com", "1688.com"))


def tmapi_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    return tmapi_request("GET", path, query=params)


def tmapi_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    return tmapi_request("POST", path, payload=payload)


def tmapi_request(method: str, path: str, query: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not TMAPI_API_TOKEN:
        raise ImageSearchConfigError("未配置 TMAPI_API_TOKEN，无法直接调用 1688 搜图 API")
    if not TMAPI_BASE_URL:
        raise ImageSearchConfigError("未配置 TMAPI_BASE_URL")

    query_params = {"apiToken": TMAPI_API_TOKEN}
    if query:
        query_params.update({key: value for key, value in query.items() if value is not None and value != ""})

    url = f"{TMAPI_BASE_URL}{path}?{urlencode(query_params)}"
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=45) as response:  # noqa: S310 - controlled API endpoint from local config.
            body = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        raise ImageSearchApiError(f"1688 搜图 API 请求失败：{exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ImageSearchApiError("1688 搜图 API 返回的不是 JSON") from exc

    if isinstance(parsed, dict):
        code = parsed.get("code")
        if code not in (None, 0, 200, "0", "200"):
            message = parsed.get("msg") or parsed.get("message") or parsed.get("error") or "调用失败"
            raise ImageSearchApiError(f"1688 搜图 API 返回错误：{message}")
        return parsed

    raise ImageSearchApiError("1688 搜图 API 返回结构异常")


def normalize_tmapi_search_items(raw_response: dict[str, Any], *, keyword: str, limit: int) -> list[dict[str, Any]]:
    raw_items = extract_items(raw_response)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            continue
        offer_id = pick_first(raw_item, "offerId", "offer_id", "item_id", "itemId", "num_iid", "numIid")
        product_url = pick_product_url(raw_item, offer_id)
        if not product_url or product_url in seen:
            continue
        seen.add(product_url)
        title = pick_first(raw_item, "title", "subject", "subjectTrans", "name", "item_title") or f"1688 图搜结果 {index}"
        image = pick_first(raw_item, "pic_url", "picUrl", "image_url", "imageUrl", "main_image_url", "mainImageUrl")
        shop_name = pick_first(raw_item, "shop_name", "shopName", "sellerNick", "seller_name", "companyName")
        items.append(
            {
                "id": f"tmapi-{offer_id or index}",
                "offer_id": str(offer_id or ""),
                "title": str(title),
                "main_image_url": str(image or ""),
                "product_url": product_url,
                "price": pick_price(raw_item),
                "shop_name": str(shop_name or ""),
                "sales": pick_first(raw_item, "monthSold", "monthly_sales", "sales", "sold"),
                "keyword": keyword,
                "raw_data": raw_item,
            }
        )
        if len(items) >= limit:
            break
    return items


def extract_items(raw_response: dict[str, Any]) -> list[Any]:
    data = raw_response.get("data")
    candidates = [
        data,
        data.get("data") if isinstance(data, dict) else None,
        data.get("items") if isinstance(data, dict) else None,
        data.get("list") if isinstance(data, dict) else None,
        data.get("result") if isinstance(data, dict) else None,
        raw_response.get("items"),
        raw_response.get("result"),
    ]
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    return []


def pick_first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return None


def pick_product_url(item: dict[str, Any], offer_id: Any) -> str:
    direct_url = pick_first(item, "detail_url", "detailUrl", "product_url", "productUrl", "item_url", "itemUrl", "url", "promotionURL")
    if direct_url:
        return str(direct_url)
    if offer_id:
        return f"https://detail.1688.com/offer/{offer_id}.html"
    return ""


def pick_price(item: dict[str, Any]) -> str:
    price_info = item.get("priceInfo")
    if isinstance(price_info, dict):
        value = pick_first(price_info, "price", "jxhyPrice", "pfJxhyPrice")
        if value is not None:
            return str(value)
    value = pick_first(item, "price", "price_text", "priceText", "salePrice")
    return str(value or "")
