import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core import database
from app.modules.creative_generation.chatgpt_listing import OpenAISettings
from app.modules.sourcing_1688.smart_recommendations import (
    analyze_with_chatgpt,
    build_fallback_analysis,
    generate_smart_1688_keywords,
    score_local_candidates,
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
                    "summary": "纸飞机玩具",
                    "strategy": "围绕手工玩具场景寻找相邻类目和搭配品。",
                    "keywords": [
                        {
                            "keyword": "折纸材料包",
                            "intent": "adjacent-category",
                            "reason": "与纸飞机玩具同属儿童手工场景，可作为搭配采购方向。",
                        }
                    ],
                },
                ensure_ascii=False,
            )
        )


class SmartRecommendationsTest(unittest.TestCase):
    def test_keyword_analysis_uses_database_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                product = {
                    "id": "product-1",
                    "sourceType": "yunqi",
                    "sourceProductId": "YQ-1",
                    "title": "情侣爱心钥匙扣挂件",
                    "categoryPath": "珠宝和配饰 女士钥匙圈",
                    "mainImageUrl": "https://example.com/main.jpg",
                }
                settings = OpenAISettings(
                    api_key="",
                    base_url="",
                    text_model="gpt-4o-mini",
                    image_model="gpt-image-1",
                    image_quality="medium",
                )

                with patch("app.modules.sourcing_1688.smart_recommendations.get_openai_settings", return_value=settings):
                    first = generate_smart_1688_keywords(product)
                    second = generate_smart_1688_keywords(product)

                self.assertFalse(first["cache"]["hit"])
                self.assertTrue(second["cache"]["hit"])
                self.assertEqual(first["keywords"], second["keywords"])
            finally:
                database.DATABASE_PATH = original_path

    def test_filters_weakly_related_keychain_recommendations(self):
        product = {
            "id": "product-1",
            "title": "情侣爱心钥匙扣挂件",
            "categoryPath": "珠宝和配饰 女士钥匙圈",
        }
        keywords = [
            {
                "keyword": "情侣钥匙扣",
                "intent": "情侣同用途找货",
                "reason": "需要情侣相关款式",
            }
        ]
        candidates = [
            {
                "id": "ordinary",
                "title": "女士钥匙圈普通包包挂件",
                "category_path": "珠宝和配饰 女士钥匙圈",
                "keyword_score": 80,
                "matched_keywords": "钥匙扣",
                "weekly_sales": 100,
                "gmv_usd": 1000,
            },
            {
                "id": "couple",
                "title": "情侣爱心钥匙扣一对挂件",
                "category_path": "珠宝和配饰 女士钥匙圈",
                "keyword_score": 8,
                "matched_keywords": "情侣钥匙扣",
                "weekly_sales": 10,
                "gmv_usd": 100,
            },
        ]

        scored = score_local_candidates(candidates, product, keywords)

        self.assertEqual([item["id"] for item in scored], ["couple"])

    def test_recommendation_prompt_requires_adjacent_category_expansion(self):
        responses = CapturingResponses()
        fake_client = SimpleNamespace(responses=responses)
        settings = SimpleNamespace(text_model="gpt-5.5")

        with patch("app.modules.sourcing_1688.smart_recommendations.build_openai_client", return_value=fake_client):
            result = analyze_with_chatgpt(
                title="3DPaperAirplaneF",
                category="",
                main_image_url="",
                settings=settings,
            )

        self.assertEqual(result["keywords"][0]["keyword"], "折纸材料包")

        sent_prompt = json.dumps(responses.payload["input"], ensure_ascii=False)
        self.assertIn("adjacent categories", sent_prompt)
        self.assertIn("complementary products", sent_prompt)
        self.assertIn("所有 keyword 必须是简体中文", sent_prompt)
        self.assertIn("勺子", sent_prompt)
        self.assertIn("陶瓷碗", sent_prompt)
        self.assertIn("3DPaperAirplaneF", sent_prompt)
        self.assertIn("不要只围绕原商品本身扩词", sent_prompt)

    def test_recommendation_accepts_plain_string_response_from_compatible_provider(self):
        responses = CapturingResponses(
            json.dumps(
                {
                    "summary": "纸飞机玩具",
                    "strategy": "寻找相邻类目。",
                    "keywords": [{"keyword": "儿童手工材料", "intent": "adjacent-category", "reason": "同场景搭配"}],
                },
                ensure_ascii=False,
            )
        )
        fake_client = SimpleNamespace(responses=responses)
        settings = SimpleNamespace(text_model="gpt-5.5")

        with patch("app.modules.sourcing_1688.smart_recommendations.build_openai_client", return_value=fake_client):
            result = analyze_with_chatgpt(
                title="3DPaperAirplaneF",
                category="",
                main_image_url="",
                settings=settings,
            )

        self.assertEqual(result["keywords"][0]["keyword"], "儿童手工材料")

    def test_fallback_recommends_adjacent_categories_for_spoon(self):
        result = build_fallback_analysis("不锈钢儿童勺子", "")

        keyword_values = [item["keyword"] for item in result["keywords"]]
        self.assertIn("陶瓷碗", keyword_values)
        self.assertIn("餐盘", keyword_values)
        self.assertNotIn("不锈钢儿童勺子 批发", keyword_values)
        self.assertNotIn("不锈钢儿童勺子 不同款", keyword_values)

    def test_recommendation_rejects_raw_english_keywords(self):
        responses = CapturingResponses(
            json.dumps(
                {
                    "summary": "paper airplane",
                    "strategy": "bad",
                    "keywords": [{"keyword": "3DPaperAirplaneF", "intent": "core", "reason": "bad"}],
                },
                ensure_ascii=False,
            )
        )
        fake_client = SimpleNamespace(responses=responses)
        settings = SimpleNamespace(text_model="gpt-5.5")

        with patch("app.modules.sourcing_1688.smart_recommendations.build_openai_client", return_value=fake_client):
            with self.assertRaises(ValueError):
                analyze_with_chatgpt(
                    title="3DPaperAirplaneF",
                    category="",
                    main_image_url="",
                    settings=settings,
                )


if __name__ == "__main__":
    unittest.main()
