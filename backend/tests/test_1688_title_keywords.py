import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.sourcing_1688.search_url import build_1688_search_url
from app.modules.sourcing_1688.title_keywords import (
    build_fallback_title_keywords,
    normalize_title_keyword_response,
    split_title_for_1688_search,
)


class TitleKeywordSplitTest(unittest.TestCase):
    def test_fallback_extracts_precise_seed_keyword(self):
        result = build_fallback_title_keywords(
            "500+个日式樱花盆景树种子，粉色樱花，适合DIY园艺、家居装饰，是园丁的完美礼物"
        )

        self.assertEqual(result["primary_keyword"], "樱花盆景种子")
        self.assertEqual(result["keywords"][0]["searchUrl"], build_1688_search_url("樱花盆景种子"))

    def test_normalize_prioritizes_primary_keyword(self):
        result = normalize_title_keyword_response(
            {
                "primary_keyword": "樱花盆景种子 1688",
                "keywords": [
                    {"keyword": "日式樱花种子", "intent": "attribute", "reason": "保留风格和主体"},
                    {"keyword": "樱花盆景种子", "intent": "core", "reason": "重复词应去重"},
                ],
                "removed_terms": ["500+个", "家居装饰"],
            },
            "测试标题",
        )

        self.assertEqual([item["keyword"] for item in result["keywords"]], ["樱花盆景种子", "日式樱花种子"])
        self.assertEqual(result["removed_terms"], ["500+个", "家居装饰"])

    def test_split_uses_rule_fallback_without_api_key(self):
        with patch(
            "app.modules.sourcing_1688.title_keywords.get_openai_settings",
            return_value=SimpleNamespace(api_key="", text_model="gpt-5.5"),
        ):
            result = split_title_for_1688_search("粉色樱花盆景树种子")

        self.assertEqual(result["source"], "rule-fallback")
        self.assertEqual(result["primary_keyword"], "樱花盆景种子")


if __name__ == "__main__":
    unittest.main()
