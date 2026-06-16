import json
import unittest
from unittest.mock import patch

from app.modules.exports import product_attributes as attrs


class ProductAttributeAiClientTest(unittest.TestCase):
    def test_category_intent_uses_chat_completions_url(self):
        with (
            patch.object(
                attrs,
                "get_ai_stage_settings",
                return_value={
                    "api_key": "sk-test",
                    "base_url": "https://example.test/v1",
                    "model": "gpt-5.4",
                },
            ),
            patch.object(attrs, "assert_user_api_usage_allowed"),
            patch.object(attrs, "record_product_attribute_usage"),
            patch.object(attrs, "request_text_json", return_value={"product_type": "test product"}) as request,
        ):
            result = attrs.request_category_intent_ai(
                {"productTitle": "source title", "skuEntries": []},
                {},
                user_id="user-1",
            )

        self.assertEqual(result["product_type"], "test product")
        self.assertEqual(request.call_args.kwargs["api_url"], "https://example.test/v1/chat/completions")

    def test_category_branch_uses_chat_completions_url(self):
        with (
            patch.object(
                attrs,
                "get_ai_stage_settings",
                return_value={
                    "api_key": "sk-test",
                    "base_url": "https://example.test/v1",
                    "model": "gpt-5.4",
                },
            ),
            patch.object(attrs, "assert_user_api_usage_allowed"),
            patch.object(attrs, "record_product_attribute_usage"),
            patch.object(attrs, "request_text_json", return_value={"selected_index": 1, "confidence": 0.9}) as request,
        ):
            result = attrs.request_category_branch_ai(
                record={"productTitle": "source title", "skuEntries": []},
                intent={"product_type": "test product"},
                current_path=["Root"],
                candidates=[{"category_id": "1", "category_path_text": "Root > Leaf", "leaf_name": "Leaf"}],
                task="Pick a branch.",
                user_id="user-1",
            )

        self.assertEqual(result["selected_index"], 1)
        self.assertEqual(request.call_args.kwargs["api_url"], "https://example.test/v1/chat/completions")

    def test_product_attribute_prompt_uses_final_export_title(self):
        with (
            patch.object(
                attrs,
                "get_ai_stage_settings",
                return_value={
                    "api_key": "sk-test",
                    "base_url": "https://example.test/v1",
                    "model": "gpt-5.4",
                },
            ),
            patch.object(attrs, "assert_user_api_usage_allowed"),
            patch.object(attrs, "record_product_attribute_usage"),
            patch.object(attrs, "request_text_json", return_value={"attributes": []}) as request,
        ):
            attrs.request_product_attribute_ai(
                {
                    "productTitle": "最终中文标题 硅胶宠物喂食垫",
                    "productTitleEn": "Final Silicone Pet Feeding Mat Title",
                    "attributeTitle": "最终中文标题 硅胶宠物喂食垫",
                    "attributeTitleEn": "Final Silicone Pet Feeding Mat Title",
                    "originalProductTitle": "原始采集标题",
                    "originalProductTitleEn": "Original scraped title",
                    "skuEntries": [{"name": "Default"}],
                },
                {"category_id": "cat-1", "category_path_text": "Pet > Feeding Mats"},
                [
                    {
                        "field_key": "Material",
                        "field_label": "Material",
                        "required": 1,
                        "component": "ant-select",
                        "raw": {"pid": "1", "templatePid": "2", "refPid": "3"},
                        "options": [{"label": "Silicone", "vid": "10"}],
                    }
                ],
                user_id="user-1",
            )

        payload = json.loads(request.call_args.kwargs["instruction"])
        self.assertEqual(payload["product"]["title"], "最终中文标题 硅胶宠物喂食垫")
        self.assertEqual(payload["product"]["title_en"], "Final Silicone Pet Feeding Mat Title")
        self.assertEqual(payload["product"]["final_export_title_cn"], "最终中文标题 硅胶宠物喂食垫")
        self.assertEqual(payload["product"]["final_export_title_en"], "Final Silicone Pet Feeding Mat Title")
        self.assertEqual(payload["product"]["source_original_title_cn"], "原始采集标题")
        self.assertEqual(payload["product"]["source_original_title_en"], "Original scraped title")


if __name__ == "__main__":
    unittest.main()
