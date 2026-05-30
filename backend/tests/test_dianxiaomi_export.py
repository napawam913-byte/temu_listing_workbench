import os
import unittest

os.environ["ALIYUN_OSS_ENABLED"] = "0"

from app.modules.exports.dianxiaomi_temu import build_rows_for_record


class DianxiaomiExportTest(unittest.TestCase):
    def test_uses_allowed_variant_name_from_raw_specs(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "黑色",
                        "imageAsset": {"sourceUrl": "https://example.com/sku.jpg"},
                        "componentSkus": [{"rawSpecs": {"颜色分类": "黑色"}}],
                    }
                ],
            }
        )

        self.assertEqual(rows[0][4], "颜色")
        self.assertEqual(rows[0][5], "黑色")

    def test_infers_quantity_variant_when_value_contains_piece_count(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "默认款（1000件起订）",
                        "componentSkus": [{"rawSpecs": {"规格": "默认款（1000件起订）"}}],
                    }
                ],
            }
        )

        self.assertEqual(rows[0][4], "数量")
        self.assertEqual(rows[0][5], "默认款（1000件起订）")

    def test_falls_back_to_model_variant(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            }
        )

        self.assertEqual(rows[0][4], "型号")
        self.assertEqual(rows[0][5], "默认款")

    def test_product_code_and_external_link_are_blank(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "productSourceUrl": "https://example.com/product",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            }
        )

        self.assertEqual(rows[0][3], "")
        self.assertEqual(rows[0][17], "")

    def test_uses_existing_english_title_when_available(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "productTitleEn": "Custom Keychain Set",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            }
        )

        self.assertEqual(rows[0][1], "Custom Keychain Set")

    def test_translates_chinese_title_with_local_glossary(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "龙之宇定制PVC软胶立体娃娃钥匙扣套装可爱创意书包小挂件钥匙链",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            }
        )

        self.assertNotRegex(rows[0][1], r"[\u4e00-\u9fff]")
        self.assertIn("Custom", rows[0][1])
        self.assertIn("Keychain", rows[0][1])

    def test_distribution_mode_uses_original_images_and_material_description(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {
                    "sourceUrl": "https://example.com/main-source.jpg",
                    "displayUrl": "https://example.com/main-display.jpg",
                    "editedUrl": "https://example.com/main-edited.jpg",
                },
                "productMaterialImages": [
                    {
                        "sourceUrl": "https://example.com/material-source.jpg",
                        "displayUrl": "https://example.com/material-display.jpg",
                        "editedUrl": "https://example.com/material-edited.jpg",
                    }
                ],
                "sourceLinks": [
                    {
                        "productUrl": "https://detail.1688.com/offer/1.html",
                        "imageUrl": "https://example.com/source-main.jpg",
                    }
                ],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "默认款",
                        "imageAsset": {
                            "sourceUrl": "https://example.com/sku-source.jpg",
                            "displayUrl": "https://example.com/sku-display.jpg",
                            "editedUrl": "https://example.com/sku-edited.jpg",
                        },
                        "componentSkus": [],
                    }
                ],
            },
            export_mode="distribution",
        )

        self.assertIn("https://example.com/material-source.jpg", rows[0][2])
        self.assertEqual(rows[0][8], "https://example.com/sku-source.jpg")
        self.assertEqual(rows[0][18], "https://example.com/material-source.jpg\nhttps://example.com/source-main.jpg")
        self.assertEqual(rows[0][19], "https://example.com/material-source.jpg")

    def test_curated_mode_prefers_edited_images(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {
                    "sourceUrl": "https://example.com/main-source.jpg",
                    "displayUrl": "https://example.com/main-display.jpg",
                    "editedUrl": "https://example.com/main-edited.jpg",
                },
                "productMaterialImages": [
                    {
                        "sourceUrl": "https://example.com/material-source.jpg",
                        "displayUrl": "https://example.com/material-display.jpg",
                        "editedUrl": "https://example.com/material-edited.jpg",
                    }
                ],
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "默认款",
                        "imageAsset": {
                            "sourceUrl": "https://example.com/sku-source.jpg",
                            "displayUrl": "https://example.com/sku-display.jpg",
                            "editedUrl": "https://example.com/sku-edited.jpg",
                        },
                        "componentSkus": [],
                    }
                ],
            },
            export_mode="curated",
        )

        self.assertIn("https://example.com/material-edited.jpg", rows[0][2])
        self.assertEqual(rows[0][8], "https://example.com/sku-edited.jpg")
        self.assertEqual(rows[0][18], "https://example.com/material-edited.jpg\nhttps://example.com/main-edited.jpg")
        self.assertEqual(rows[0][19], "https://example.com/material-edited.jpg")

    def test_image_cloud_urls_are_preferred_before_source_urls(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {
                    "sourceUrl": "https://example.com/main-source.jpg",
                    "sourceCloudUrl": "https://oss.example.com/main-source.jpg",
                    "editedUrl": "https://example.com/main-edited.jpg",
                    "editedCloudUrl": "https://oss.example.com/main-edited.jpg",
                },
                "productMaterialImages": [
                    {
                        "sourceUrl": "https://example.com/material-source.jpg",
                        "sourceCloudUrl": "https://oss.example.com/material-source.jpg",
                        "editedUrl": "https://example.com/material-edited.jpg",
                        "editedCloudUrl": "https://oss.example.com/material-edited.jpg",
                    }
                ],
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "默认款",
                        "imageAsset": {
                            "sourceUrl": "https://example.com/sku-source.jpg",
                            "sourceCloudUrl": "https://oss.example.com/sku-source.jpg",
                            "editedUrl": "https://example.com/sku-edited.jpg",
                            "editedCloudUrl": "https://oss.example.com/sku-edited.jpg",
                        },
                        "componentSkus": [],
                    }
                ],
            },
            export_mode="curated",
        )

        self.assertIn("https://oss.example.com/material-edited.jpg", rows[0][2])
        self.assertEqual(rows[0][8], "https://oss.example.com/sku-edited.jpg")
        self.assertEqual(rows[0][18], "https://oss.example.com/material-edited.jpg\nhttps://oss.example.com/main-edited.jpg")
        self.assertEqual(rows[0][19], "https://oss.example.com/material-edited.jpg")

    def test_carousel_and_product_material_columns_respect_dianxiaomi_limits(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "productMaterialImages": [
                    {"sourceUrl": f"https://example.com/material-{index}.jpg"} for index in range(1, 13)
                ],
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            },
            export_mode="distribution",
        )

        self.assertEqual(len(rows[0][18].split("\n")), 10)
        self.assertEqual(len(rows[0][19].split("\n")), 1)

    def test_delivery_days_default_is_16(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            }
        )

        self.assertEqual(rows[0][25], 16)


if __name__ == "__main__":
    unittest.main()
