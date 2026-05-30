from __future__ import annotations

from urllib.parse import quote_from_bytes

SEARCH_1688_URL = "https://s.1688.com/selloffer/offer_search.htm"


def encode_1688_keyword(keyword: str) -> str:
    clean_keyword = keyword.strip()
    if not clean_keyword:
        raise ValueError("1688 搜索词不能为空")

    return quote_from_bytes(clean_keyword.encode("gbk", errors="replace"))


def build_1688_search_url(keyword: str) -> str:
    return f"{SEARCH_1688_URL}?keywords={encode_1688_keyword(keyword)}"
