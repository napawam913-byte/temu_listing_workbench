import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import database
from app.modules.creative_generation.chatgpt_listing import OpenAISettings
from app.modules.sourcing_1688.smart_recommendations import (
    generate_smart_1688_keywords,
    score_local_candidates,
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
                    "categoryPath": "珠宝和配饰/女士钥匙圈",
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
            "categoryPath": "珠宝和配饰/女士钥匙圈",
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
                "category_path": "珠宝和配饰/女士钥匙圈",
                "keyword_score": 80,
                "matched_keywords": "钥匙扣",
                "weekly_sales": 100,
                "gmv_usd": 1000,
            },
            {
                "id": "couple",
                "title": "情侣爱心钥匙扣一对挂件",
                "category_path": "珠宝和配饰/女士钥匙圈",
                "keyword_score": 8,
                "matched_keywords": "情侣钥匙扣",
                "weekly_sales": 10,
                "gmv_usd": 100,
            },
        ]

        scored = score_local_candidates(candidates, product, keywords)

        self.assertEqual([item["id"] for item in scored], ["couple"])


if __name__ == "__main__":
    unittest.main()
