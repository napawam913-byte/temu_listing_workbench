import json
import unittest
from unittest.mock import patch

from app.modules.creative_generation import listing_title_optimizer as optimizer


class ListingTitleOptimizerClientTest(unittest.TestCase):
    def test_generate_titles_uses_compatible_text_json_client(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )

        with patch.object(
            optimizer,
            "request_text_json",
            return_value={"title_cn": "AI Chinese Title", "title_en": "AI English Title"},
        ) as request:
            result = optimizer.generate_titles_with_ai(
                {"productId": "p1", "productTitle": "Source title", "skuEntries": []},
                {"title_cn": "Fallback CN", "title_en": "Fallback EN"},
                settings,
            )

        self.assertEqual(result["title_cn"], "AI Chinese Title")
        self.assertEqual(result["title_en"], "AI English Title")
        self.assertEqual(request.call_args.kwargs["api_url"], "https://example.test/v1/chat/completions")
        self.assertEqual(request.call_args.kwargs["model"], "gpt-5.4")
        payload = json.loads(request.call_args.kwargs["instruction"])
        self.assertIn("listing_optimization_rules", payload)
        self.assertIn("required_json", payload)

    def test_generate_variant_values_uses_compatible_text_json_client(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )

        with patch.object(
            optimizer,
            "request_text_json",
            return_value={"values": [{"source": "source value", "value_en": "Translated Value"}]},
        ) as request:
            result = optimizer.generate_variant_values_with_ai(["source value"], settings)

        self.assertEqual(result, {"source value": "Translated Value"})
        self.assertEqual(request.call_args.kwargs["api_url"], "https://example.test/v1/chat/completions")
        self.assertEqual(request.call_args.kwargs["temperature"], 0.05)
        payload = json.loads(request.call_args.kwargs["instruction"])
        self.assertEqual(payload["source_values"], ["source value"])
        self.assertIn("required_json", payload)
        self.assertTrue(any("48 characters" in item for item in payload["requirements"]))
        self.assertTrue(any("Never output full product titles" in item for item in payload["requirements"]))

    def test_generate_variant_values_uses_multimodal_context_when_images_are_present(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )
        context = {
            "title_en": "12/24pcs Random Color Confetti Popper",
            "image_urls": ["https://img.example.com/main.jpg"],
            "sku_items": [
                {
                    "sku_name": "Mix, Quantity: 12pcs",
                    "variant_fields": [{"name": "颜色", "value": "Mix Quantity 12pcs+Mix"}],
                }
            ],
        }

        with patch.object(
            optimizer,
            "request_json",
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"values": [{"source": "Mix Quantity 12pcs+Mix", "value_en": "Mix"}]},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        ) as request:
            result = optimizer.generate_variant_values_with_ai(
                ["Mix Quantity 12pcs+Mix"],
                settings,
                context=context,
            )

        self.assertEqual(result, {"Mix Quantity 12pcs+Mix": "Mix"})
        payload = request.call_args.args[2]
        content = payload["messages"][0]["content"]
        instruction = json.loads(content[0]["text"])
        self.assertEqual(instruction["product_context"]["title_en"], "12/24pcs Random Color Confetti Popper")
        self.assertEqual(instruction["source_values"], ["Mix Quantity 12pcs+Mix"])
        self.assertEqual(content[1]["image_url"]["url"], "https://img.example.com/main.jpg")

    def test_translate_variant_values_uses_ai_for_english_values_when_context_is_present(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )
        context = {
            "title_en": "12/24pcs Random Color Confetti Popper",
            "image_urls": ["https://img.example.com/main.jpg"],
        }

        with (
            patch.object(optimizer, "get_title_optimizer_settings", return_value=settings),
            patch.object(optimizer, "assert_user_api_usage_allowed"),
            patch.object(optimizer, "record_title_optimizer_usage"),
            patch.object(
                optimizer,
                "generate_variant_values_with_ai",
                return_value={"Mix Quantity 12pcs+Mix": "Mix"},
            ) as generate,
        ):
            result = optimizer.translate_variant_values_to_english(
                ["Mix Quantity 12pcs+Mix"],
                context=context,
                strict=True,
            )

        self.assertEqual(result["Mix Quantity 12pcs+Mix"], "Mix")
        generate.assert_called_once()
        self.assertEqual(generate.call_args.kwargs["context"], context)

    def test_translate_variant_values_trims_long_ai_sku_labels(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )
        long_label = (
            "12/24pcs Random Color Confetti Popper Handheld Party Streamers "
            "Vibrant Colors And Silent Interaction"
        )

        with (
            patch.object(optimizer, "get_title_optimizer_settings", return_value=settings),
            patch.object(optimizer, "assert_user_api_usage_allowed"),
            patch.object(optimizer, "record_title_optimizer_usage"),
            patch.object(
                optimizer,
                "generate_variant_values_with_ai",
                return_value={"dirty sku": long_label},
            ),
        ):
            result = optimizer.translate_variant_values_to_english(
                ["dirty sku"],
                context={"title_en": "Confetti Popper", "image_urls": ["https://img.example.com/main.jpg"]},
                strict=True,
            )

        self.assertLessEqual(len(result["dirty sku"]), optimizer.MAX_VARIANT_VALUE_LENGTH)
        self.assertNotIn("Vibrant Colors", result["dirty sku"])

    def test_optimize_listing_titles_does_not_reuse_memory_cache(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )
        record = {"productId": "p1", "productTitle": "Source title", "skuEntries": []}

        with (
            patch.object(optimizer, "get_title_optimizer_settings", return_value=settings),
            patch.object(optimizer, "assert_user_api_usage_allowed"),
            patch.object(optimizer, "record_title_optimizer_usage"),
            patch.object(
                optimizer,
                "generate_titles_with_ai",
                side_effect=[
                    {"title_cn": "中文标题一", "title_en": "English Title One"},
                    {"title_cn": "中文标题二", "title_en": "English Title Two"},
                ],
            ) as generate,
        ):
            first = optimizer.optimize_listing_titles(
                record,
                fallback_title_cn="原始标题",
                fallback_title_en="Original Title",
                strict=True,
            )
            second = optimizer.optimize_listing_titles(
                record,
                fallback_title_cn="原始标题",
                fallback_title_en="Original Title",
                strict=True,
            )

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(first["title_cn"], "中文标题一")
        self.assertEqual(second["title_cn"], "中文标题二")

    def test_translate_variant_values_does_not_reuse_memory_cache(self):
        settings = optimizer.TitleOptimizerSettings(
            api_key="sk-test",
            base_url="https://example.test/v1",
            text_model="gpt-5.4",
        )

        with (
            patch.object(optimizer, "get_title_optimizer_settings", return_value=settings),
            patch.object(optimizer, "assert_user_api_usage_allowed"),
            patch.object(optimizer, "record_title_optimizer_usage"),
            patch.object(
                optimizer,
                "generate_variant_values_with_ai",
                side_effect=[
                    {"红色": "Red One"},
                    {"红色": "Red Two"},
                ],
            ) as generate,
        ):
            first = optimizer.translate_variant_values_to_english(["红色"])
            second = optimizer.translate_variant_values_to_english(["红色"])

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(first["红色"], "Red One")
        self.assertEqual(second["红色"], "Red Two")


if __name__ == "__main__":
    unittest.main()
