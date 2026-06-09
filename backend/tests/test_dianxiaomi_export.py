import os
import unittest
from unittest.mock import patch

os.environ["ALIYUN_OSS_ENABLED"] = "0"
os.environ["OPENAI_API_KEY"] = ""

from app.modules.image_storage.aliyun_oss import ImageStorageError
from app.modules.exports.dianxiaomi_temu import build_rows_for_record


class DianxiaomiExportTest(unittest.TestCase):
    def test_export_uses_optimized_chinese_and_english_titles(self):
        with patch(
            "app.modules.exports.dianxiaomi_temu.optimize_listing_titles",
            return_value={
                "title_cn": "1个爱心字母钥匙扣包包挂件，流苏钥匙圈汽车装饰配件",
                "title_en": "1 PCS Heart Initial Keychain Bag Charm, Tassel Key Ring Car Decoration Accessory",
                "source": "ai",
            },
        ):
            rows = build_rows_for_record(
                {
                    "productId": "p1",
                    "productTitle": "原始中文标题",
                    "productTitleEn": "Original English Title",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                    "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
                }
            )

        self.assertEqual(rows[0][0], "1个爱心字母钥匙扣包包挂件，流苏钥匙圈汽车装饰配件")
        self.assertEqual(
            rows[0][1],
            "1 PCS Heart Initial Keychain Bag Charm, Tassel Key Ring Car Decoration Accessory",
        )

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
        self.assertEqual(rows[0][5], "Black")

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
        self.assertEqual(rows[0][5], "Default Option (1000 Pcs MOQ)")

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
        self.assertEqual(rows[0][5], "Default Option")

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
        self.assertEqual(rows[0][10], "")
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
        self.assertEqual(rows[0][2], rows[0][18])
        self.assertEqual(rows[0][8], "https://example.com/sku-source.jpg")
        self.assertEqual(rows[0][9], 300)
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
        self.assertEqual(rows[0][2], rows[0][18])
        self.assertEqual(rows[0][8], "https://example.com/sku-edited.jpg")
        self.assertEqual(rows[0][9], 300)
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
        self.assertEqual(rows[0][2], rows[0][18])
        self.assertEqual(rows[0][8], "https://oss.example.com/sku-edited.jpg")
        self.assertEqual(rows[0][9], 300)
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
        self.assertEqual(rows[0][2], rows[0][18])
        self.assertEqual(len(rows[0][2].split("\n")), 10)
        self.assertEqual(len(rows[0][19].split("\n")), 1)

    def test_sku_preview_falls_back_to_source_sku_image_before_main_image(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "娴嬭瘯鍟嗗搧",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "Default SKU",
                        "sourceSkuLinks": [{"imageUrl": "https://example.com/source-sku.jpg"}],
                        "componentSkus": [],
                    }
                ],
            },
            export_mode="distribution",
        )

        self.assertEqual(rows[0][8], "https://example.com/source-sku.jpg")

    def test_named_variant_does_not_create_extra_model_from_sku_name(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "Test Product",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {
                        "id": "sku-1",
                        "name": "C+B+C+B",
                        "imageAsset": {"sourceUrl": "https://example.com/sku.jpg"},
                        "componentSkus": [{"rawSpecs": {"颜色": "C+B"}}],
                    }
                ],
            }
        )

        self.assertEqual(rows[0][4], "颜色")
        self.assertEqual(rows[0][5], "C+B")
        self.assertEqual(rows[0][6], "")
        self.assertEqual(rows[0][7], "")

    def test_delivery_days_default_is_blank(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "componentSkus": []}],
            }
        )

        self.assertEqual(rows[0][25], "")

    def test_suggested_sale_price_is_blank(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "测试商品",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "默认款", "price": 9.99, "componentSkus": []}],
            }
        )

        self.assertEqual(rows[0][23], "")

    def test_http_image_mirror_failure_falls_back_to_original_url(self):
        with patch(
            "app.modules.exports.dianxiaomi_temu.mirror_export_image",
            side_effect=ImageStorageError("download failed"),
        ):
            rows = build_rows_for_record(
                {
                    "productId": "p1",
                    "productTitle": "Test Product",
                    "mainImage": {"sourceUrl": "https://img.example.com/main.jpg"},
                    "productMaterialImages": [{"sourceUrl": "https://img.example.com/material.jpg"}],
                    "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                    "skuEntries": [
                        {
                            "id": "sku-1",
                            "name": "Default SKU",
                            "imageAsset": {"sourceUrl": "https://img.example.com/sku.jpg"},
                            "componentSkus": [],
                        }
                    ],
                }
            )

        self.assertEqual(rows[0][8], "https://img.example.com/sku.jpg")
        self.assertEqual(rows[0][18], "https://img.example.com/material.jpg\nhttps://img.example.com/main.jpg")
        self.assertEqual(rows[0][19], "https://img.example.com/material.jpg")


if __name__ == "__main__":
    unittest.main()
