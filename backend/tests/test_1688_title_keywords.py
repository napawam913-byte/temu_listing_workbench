import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.modules.sourcing_1688.search_url import build_1688_search_url
from app.modules.sourcing_1688.title_keywords import (
    build_fallback_title_keywords,
    normalize_title_keyword_response,
    split_title_for_1688_search,
    split_title_with_gpt,
)


class CapturingResponses:
    def __init__(self, response=None) -> None:
        self.payload: dict | None = None
        self.response = response

    def create(self, **kwargs):
        self.payload = kwargs
        if self.response is not None:
            return self.response
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "primary_keyword": "纸飞机玩具",
                    "keywords": [
                        {
                            "keyword": "纸飞机玩具",
                            "intent": "core",
                            "reason": "英文标题已转换成适合 1688 搜索的中文采购词。",
                        }
                    ],
                    "removed_terms": ["3DPaperAirplaneF"],
                },
                ensure_ascii=False,
            )
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

    def test_gpt_prompt_requires_chinese_1688_keyword_conversion(self):
        responses = CapturingResponses()
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=responses))
        settings = SimpleNamespace(text_model="gpt-5.5")

        with patch("app.modules.sourcing_1688.title_keywords.build_openai_client", return_value=fake_client):
            result = split_title_with_gpt("3DPaperAirplaneF", "", settings)

        self.assertEqual(result["primary_keyword"], "纸飞机玩具")
        self.assertEqual(result["keywords"][0]["searchUrl"], build_1688_search_url("纸飞机玩具"))

        sent_prompt = json.dumps(responses.payload["messages"], ensure_ascii=False)
        self.assertIn("Simplified Chinese 1688 sourcing keywords", sent_prompt)
        self.assertIn("英文或中英混合标题必须先转成简体中文", sent_prompt)
        self.assertIn("3DPaperAirplaneF", sent_prompt)
        self.assertIn("纸飞机玩具", sent_prompt)
        self.assertIn("不能原样输出英文", sent_prompt)

    def test_gpt_accepts_plain_string_response_from_compatible_provider(self):
        responses = CapturingResponses(
            json.dumps(
                {
                    "primary_keyword": "纸飞机玩具",
                    "keywords": [{"keyword": "纸飞机玩具", "intent": "core", "reason": "中文搜索词"}],
                    "removed_terms": [],
                },
                ensure_ascii=False,
            )
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=responses))
        settings = SimpleNamespace(text_model="gpt-5.5")

        with patch("app.modules.sourcing_1688.title_keywords.build_openai_client", return_value=fake_client):
            result = split_title_with_gpt("3DPaperAirplaneF", "", settings)

        self.assertEqual(result["primary_keyword"], "纸飞机玩具")

    def test_gpt_rejects_raw_english_keyword_response(self):
        responses = CapturingResponses(
            json.dumps(
                {
                    "primary_keyword": "3DPaperAirplaneF",
                    "keywords": [{"keyword": "3DPaperAirplaneF", "intent": "core", "reason": "bad"}],
                    "removed_terms": [],
                },
                ensure_ascii=False,
            )
        )
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=responses))
        settings = SimpleNamespace(text_model="gpt-5.5")

        with patch("app.modules.sourcing_1688.title_keywords.build_openai_client", return_value=fake_client):
            with self.assertRaises(ValueError):
                split_title_with_gpt("3DPaperAirplaneF", "", settings)

    def test_split_does_not_silently_fallback_when_configured_api_fails(self):
        class FailingResponses:
            def create(self, **kwargs):
                raise RuntimeError("provider returned malformed response")

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FailingResponses()))
        settings = SimpleNamespace(api_key="sk-test", text_model="gpt-5.5", channel_id="chufan_ai")

        with (
            patch("app.modules.sourcing_1688.title_keywords.get_openai_settings", return_value=settings),
            patch("app.modules.sourcing_1688.title_keywords.assert_user_api_usage_allowed"),
            patch("app.modules.sourcing_1688.title_keywords.record_api_usage_safe"),
            patch("app.modules.sourcing_1688.title_keywords.build_openai_client", return_value=fake_client),
        ):
            with self.assertRaisesRegex(ValueError, "1688 中文关键词转换失败"):
                split_title_for_1688_search("3DPaperAirplaneF", user_id="user-1")


if __name__ == "__main__":
    unittest.main()
