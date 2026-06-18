import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["ALIYUN_OSS_ENABLED"] = "0"
os.environ["OPENAI_API_KEY"] = ""

from app.modules.image_storage.aliyun_oss import ImageStorageError
from app.core import database
from app.core.database import DEFAULT_USER_ID
from app.modules.exports.dianxiaomi_export_tasks import (
    create_dianxiaomi_export_task,
    get_completed_export_task_path,
    get_dianxiaomi_export_task,
    run_dianxiaomi_export_task,
)
from app.modules.exports.dianxiaomi_temu import (
    DianxiaomiExportError,
    build_rows_for_record,
    build_template_rows,
    build_template_rows_for_export_records,
)


class DianxiaomiExportTest(unittest.TestCase):
    def setUp(self):
        self.attribute_patcher = patch(
            "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
            return_value={"category_id": "31075", "product_attribute_text": "[]"},
        )
        self.image_processing_patcher = patch(
            "app.modules.exports.dianxiaomi_temu.export_image_processing_enabled",
            return_value=False,
        )
        self.attribute_patcher.start()
        self.image_processing_patcher.start()

    def tearDown(self):
        self.image_processing_patcher.stop()
        self.attribute_patcher.stop()

    def test_export_uses_visual_generated_chinese_and_english_titles(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "Original raw title",
                "productTitleEn": "Original English Title",
                "visualGeneratedTitleCn": "1个爱心字母钥匙扣包包挂件，流苏钥匙圈汽车装饰配件",
                "visualGeneratedTitleEn": "1 PCS Heart Initial Keychain Bag Charm, Tassel Key Ring Car Decoration Accessory",
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

    def test_template_rows_uses_visual_generated_title_without_title_api(self):
        rows = build_template_rows(
            {
                "id": "record-visual-title",
                "productId": "p1",
                "productTitle": "Original Title",
                "productTitleEn": "Original English Title",
                "visualGeneratedTitleCn": "阶段一中文标题",
                "visualGeneratedTitleEn": "Stage One English Title",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "Black", "componentSkus": []}],
            },
            translate_variants=False,
            user_id="user-1",
        )

        self.assertEqual(rows[0]["product_title"], "阶段一中文标题")
        self.assertEqual(rows[0]["product_title_en"], "Stage One English Title")

    def test_template_rows_passes_final_titles_to_product_attributes(self):
        with patch(
            "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
            return_value={"category_id": "31075", "product_attribute_text": "[]"},
        ) as attribute_getter:
            build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "原始采集标题",
                    "productTitleEn": "Original scraped title",
                    "visualGeneratedTitleCn": "最终中文标题 宠物喂食垫",
                    "visualGeneratedTitleEn": "Final English Pet Feeding Mat Title",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                    "skuEntries": [{"id": "sku-1", "name": "Black", "componentSkus": []}],
                },
                translate_variants=False,
                user_id="user-1",
            )

        self.assertEqual(attribute_getter.call_args.kwargs["title_context"]["title_cn"], "最终中文标题 宠物喂食垫")
        self.assertEqual(attribute_getter.call_args.kwargs["title_context"]["title_en"], "Final English Pet Feeding Mat Title")
        self.assertIs(attribute_getter.call_args.kwargs["strict"], True)

    def test_template_rows_uses_original_title_when_visual_title_missing(self):
        rows = build_template_rows(
            {
                "id": "record-1",
                "productId": "p1",
                "productTitle": "Original Title",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "Black", "componentSkus": []}],
            },
            translate_variants=False,
            user_id="user-1",
        )

        self.assertEqual(rows[0]["product_title"], "Original Title")

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

    def test_carousel_http_images_are_processed_when_oss_processing_is_enabled(self):
        with (
            patch("app.modules.exports.dianxiaomi_temu.export_image_processing_enabled", return_value=True),
            patch(
                "app.modules.exports.dianxiaomi_temu.mirror_listing_square_image",
                side_effect=lambda _url, key_hint: f"https://oss.example.com/{key_hint}.jpg",
            ) as processor,
        ):
            rows = build_rows_for_record(
                {
                    "productId": "p1",
                    "productTitle": "Test Product",
                    "mainImage": {"sourceUrl": "https://img.example.com/main.jpg"},
                    "productMaterialImages": [{"sourceUrl": "https://img.example.com/material.jpg"}],
                    "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                    "skuEntries": [{"id": "sku-1", "name": "Default SKU", "componentSkus": []}],
                }
            )

        self.assertIn("https://oss.example.com/p1/material-1.jpg", rows[0][18])
        self.assertNotIn("https://img.example.com/material.jpg", rows[0][18])
        self.assertGreaterEqual(processor.call_count, 2)

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

    def test_mixed_variant_attribute_names_are_normalized_to_model(self):
        rows = build_rows_for_record(
            {
                "productId": "p1",
                "productTitle": "Pet Bowl Set",
                "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [
                    {"id": "sku-1", "name": "灰色花边餐垫（硅胶）", "componentSkus": []},
                    {"id": "sku-2", "name": "亮光纯色飞碟碗（蜜桃红色）", "componentSkus": []},
                    {
                        "id": "sku-3",
                        "name": "灰色花边餐垫（硅胶）+亮光纯色飞碟碗（蜜桃红色）",
                        "componentSkus": [
                            {"rawSpecs": {"型号": "灰色花边餐垫（硅胶）"}},
                            {"rawSpecs": {"颜色": "蜜桃红色"}},
                        ],
                    },
                ],
            }
        )

        self.assertEqual([row[4] for row in rows], ["型号", "型号", "型号"])
        self.assertEqual([row[6] for row in rows], ["", "", ""])
        self.assertEqual([row[7] for row in rows], ["", "", ""])
        self.assertTrue(all(row[5] for row in rows))

    def test_combo_sku_uses_model_with_spec_and_source_title(self):
        with patch(
            "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
            return_value={"category_id": "31075", "product_attribute_text": "[]"},
        ):
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "Combo Product",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [
                        {"id": "source-a", "title": "Pet Bowl", "productUrl": "https://detail.1688.com/offer/1.html"},
                        {"id": "source-b", "title": "Feeding Mat", "productUrl": "https://detail.1688.com/offer/2.html"},
                    ],
                    "skuEntries": [
                        {
                            "id": "sku-combo-1",
                            "kind": "combo",
                            "name": "1pc+Black",
                            "componentSkus": [
                                {
                                    "name": "1pc",
                                    "specText": "Spec: 1pc",
                                    "sourceId": "source-a",
                                    "sourceTitle": "Supplier A",
                                    "rawSpecs": {"Spec": "1pc"},
                                },
                                {
                                    "name": "Black",
                                    "specText": "Color: Black",
                                    "sourceId": "source-b",
                                    "sourceTitle": "Supplier B",
                                    "rawSpecs": {"Color": "Black"},
                                },
                            ],
                        }
                    ],
                },
                optimize_titles=False,
                translate_variants=False,
            )

        self.assertEqual(rows[0]["variant_name"], "1pc Pet Bowl+Black Feeding Mat")
        self.assertEqual(rows[0]["variant_attr_name_1"], "\u578b\u53f7")
        self.assertEqual(rows[0]["variant_attr_value_1"], "1pc Pet Bowl+Black Feeding Mat")
        self.assertEqual(rows[0]["variant_attr_name_2"], "")
        self.assertEqual(rows[0]["variant_attr_value_2"], "")

    def test_combo_sku_strips_promotional_source_title_noise(self):
        noisy_title = (
            "1 Pack.IVW Wood Dice Suitable for Valentines Day Gifts, Date Night Games "
            "& Couples Board - Twelve-Sided D12 Dice with Original Wood Grain for RPGs, "
            "Tabletop Role-Playing Games, and Activities+6pcsBest Seller341 sold from this store 5.0"
        )

        with patch(
            "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
            return_value={"category_id": "31075", "product_attribute_text": "[]"},
        ):
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "Wood Dice",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [
                        {"id": "source-a", "title": noisy_title, "productUrl": "https://detail.1688.com/offer/1.html"},
                    ],
                    "skuEntries": [
                        {
                            "id": "sku-combo-1",
                            "kind": "combo",
                            "componentSkus": [
                                {
                                    "sourceId": "source-a",
                                    "rawSpecs": {"Pack": "1 Pack"},
                                },
                            ],
                        }
                    ],
                },
                optimize_titles=False,
                translate_variants=False,
            )

        sku_value = rows[0]["variant_attr_value_1"]
        self.assertIn("IVW Wood Dice", sku_value)
        self.assertIn("D12 Dice", sku_value)
        self.assertLessEqual(len(sku_value), 48)
        self.assertNotIn("Best Seller", sku_value)
        self.assertNotIn("popular S", sku_value)
        self.assertNotIn("sold from this store", sku_value)
        self.assertNotIn("5.0", sku_value)
        self.assertNotIn("Valentines Day", sku_value)
        self.assertNotIn("Date Night", sku_value)
        self.assertFalse(sku_value.startswith("1 Pack1 Pack"))

    def test_combo_sku_uses_source_titles_when_migrated_components_only_have_quantity(self):
        captured_values: list[str] = []

        def fake_translate(values, **_kwargs):
            captured_values.extend(values)
            return {values[0]: "2pcs Six-Sided Dice+1pc Wooden D12 Dice"}

        with (
            patch(
                "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
                return_value={"category_id": "31075", "product_attribute_text": "[]"},
            ),
            patch(
                "app.modules.exports.dianxiaomi_temu.translate_variant_values_to_english",
                side_effect=fake_translate,
            ) as translator,
        ):
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "Dice Combo",
                    "productTitleEn": "Dice Combo",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [
                        {
                            "id": "source-white",
                            "title": (
                                "No import charges2pcs Lover's Date Game Dice Stainless Steel "
                                "Decision-making Dices - Perfect Gift for Couples"
                            ),
                            "imageUrl": "https://img.example.com/white-dice.jpg",
                            "productUrl": "https://example.com/white-dice.html",
                        },
                        {
                            "id": "source-wood",
                            "title": (
                                "1 Pack.IVW Wood Dice Suitable for Valentines Day Gifts - "
                                "Twelve-Sided D12 Dice with Original Wood Grain"
                            ),
                            "imageUrl": "https://img.example.com/wood-d12.jpg",
                            "productUrl": "https://example.com/wood-d12.html",
                        },
                    ],
                    "skuEntries": [
                        {
                            "id": "sku-combo-1",
                            "kind": "combo",
                            "name": "2pcs+1 Pack",
                            # Simulates migrated rows where only quantity specs survived on components.
                            "componentSkus": [
                                {"rawSpecs": {"Quantity": "2pcs"}},
                                {"rawSpecs": {"Pack": "1 Pack"}},
                            ],
                        }
                    ],
                },
                optimize_titles=False,
            )

        translator.assert_called_once()
        self.assertEqual(rows[0]["variant_name"], "2pcs Six-Sided Dice+1pc Wooden D12 Dice")
        self.assertEqual(rows[0]["variant_attr_name_1"], "\u578b\u53f7")
        self.assertEqual(rows[0]["variant_attr_value_1"], "2pcs Six-Sided Dice+1pc Wooden D12 Dice")
        self.assertTrue(captured_values)
        self.assertNotEqual(captured_values[0], "2pcs+1 Pack")
        self.assertIn("Decision", captured_values[0])
        self.assertIn("D12 Dice", captured_values[0])

    def test_visual_generated_sku_name_bypasses_export_variant_rewrite(self):
        with (
            patch(
                "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
                return_value={"category_id": "31075", "product_attribute_text": "[]"},
            ),
            patch("app.modules.exports.dianxiaomi_temu.translate_variant_values_to_english") as translator,
        ):
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "Dice Combo",
                    "productTitleEn": "Dice Combo",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "skuEntries": [
                        {
                            "id": "sku-white",
                            "kind": "single",
                            "name": "2pcs White Printed Six-Sided Dice",
                            "originalName": "2pcs",
                            "visualGeneratedName": "2pcs White Printed Six-Sided Dice",
                            "componentSkus": [
                                {"name": "2pcs", "rawSpecs": {"Quantity": "2pcs"}, "specText": "Quantity: 2pcs"}
                            ],
                        },
                        {
                            "id": "sku-wood",
                            "kind": "single",
                            "name": "1 Pack Wooden D12 Die",
                            "originalName": "1 Pack",
                            "visualGeneratedName": "1 Pack Wooden D12 Die",
                            "componentSkus": [
                                {"name": "1 Pack", "rawSpecs": {"Pack": "1 Pack"}, "specText": "Pack: 1 Pack"}
                            ],
                        },
                    ],
                },
                optimize_titles=False,
            )

        translator.assert_not_called()
        self.assertEqual(rows[0]["variant_attr_name_1"], "\u578b\u53f7")
        self.assertEqual(rows[0]["variant_attr_value_1"], "2pcs White Printed Six-Sided Dice")
        self.assertEqual(rows[1]["variant_attr_value_1"], "1 Pack Wooden D12 Die")

    def test_visual_product_identity_supplies_titles_and_sku_names_for_export(self):
        with (
            patch(
                "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
                return_value={"category_id": "31075", "product_attribute_text": "[]"},
            ) as attribute_getter,
            patch("app.modules.exports.dianxiaomi_temu.translate_variant_values_to_english") as translator,
        ):
            rows = build_template_rows(
                {
                    "id": "record-visual-identity",
                    "productId": "p-visual-identity",
                    "productTitle": "Old raw title",
                    "productTitleEn": "Old raw title",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "visualProductIdentity": {
                        "product_type": "Dice Set",
                        "title_cn": "木质十二面骰子与白色印花六面骰子组合套装",
                        "title_en": "Wooden D12 Die and White Printed Six-Sided Dice Set",
                        "skus": [
                            {"sku_index": 1, "standard_name": "2pcs White Printed Six-Sided Dice"},
                            {"sku_index": 2, "standard_name": "1 Pack Wooden D12 Die"},
                        ],
                    },
                    "skuEntries": [
                        {"id": "sku-white", "name": "2pcs"},
                        {"id": "sku-wood", "name": "1 Pack"},
                    ],
                },
            )

        translator.assert_not_called()
        attribute_getter.assert_called_once()
        self.assertEqual(rows[0]["product_title"], "木质十二面骰子与白色印花六面骰子组合套装")
        self.assertEqual(rows[0]["product_title_en"], "Wooden D12 Die and White Printed Six-Sided Dice Set")
        self.assertEqual(rows[0]["variant_attr_value_1"], "2pcs White Printed Six-Sided Dice")
        self.assertEqual(rows[1]["variant_attr_value_1"], "1 Pack Wooden D12 Die")

    def test_combo_sku_translates_model_value_and_variant_name(self):
        raw_combo_value = "\u4e00\u4ef6\u5ba0\u7269\u7897+\u9ed1\u8272\u5582\u98df\u57ab"
        translated_combo_value = "1pc Pet Bowl+Black Feeding Mat"

        with (
            patch(
                "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
                return_value={"category_id": "31075", "product_attribute_text": "[]"},
            ),
            patch(
                "app.modules.exports.dianxiaomi_temu.translate_variant_values_to_english",
                return_value={raw_combo_value: translated_combo_value},
            ) as translator,
        ):
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "Combo Product",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [
                        {
                            "id": "source-a",
                            "title": "\u5ba0\u7269\u7897",
                            "productUrl": "https://detail.1688.com/offer/1.html",
                        },
                        {
                            "id": "source-b",
                            "title": "\u5582\u98df\u57ab",
                            "productUrl": "https://detail.1688.com/offer/2.html",
                        },
                    ],
                    "skuEntries": [
                        {
                            "id": "sku-combo-1",
                            "kind": "combo",
                            "componentSkus": [
                                {
                                    "sourceId": "source-a",
                                    "rawSpecs": {"\u89c4\u683c": "\u4e00\u4ef6"},
                                },
                                {
                                    "sourceId": "source-b",
                                    "rawSpecs": {"\u989c\u8272": "\u9ed1\u8272"},
                                },
                            ],
                        }
                    ],
                },
                optimize_titles=False,
            )

        translator.assert_called_once()
        self.assertIn(raw_combo_value, translator.call_args.args[0])
        self.assertEqual(rows[0]["variant_name"], translated_combo_value)
        self.assertEqual(rows[0]["variant_attr_name_1"], "\u578b\u53f7")
        self.assertEqual(rows[0]["variant_attr_value_1"], translated_combo_value)

    def test_sku_generation_uses_title_and_image_context_to_clean_mixed_quantity_option(self):
        with (
            patch(
                "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
                return_value={"category_id": "31075", "product_attribute_text": "[]"},
            ),
            patch(
                "app.modules.exports.dianxiaomi_temu.translate_variant_values_to_english",
                return_value={
                    "Mix Quantity 12pcs+Mix": "Mix",
                    "12pcs": "12pcs",
                },
            ) as translator,
        ):
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "12/24pcs Random Color Confetti Popper Handheld Party Streamers",
                    "productTitleEn": "12/24pcs Random Color Confetti Popper Handheld Party Streamers",
                    "mainImage": {"sourceUrl": "https://img.example.com/main-confetti.jpg"},
                    "productMaterialImages": [{"sourceUrl": "https://img.example.com/detail-confetti.jpg"}],
                    "sourceLinks": [
                        {
                            "id": "source-a",
                            "title": "Random Color Confetti Popper",
                            "imageUrl": "https://img.example.com/source-confetti.jpg",
                            "productUrl": "https://www.temu.com/confetti.html",
                        }
                    ],
                    "skuEntries": [
                        {
                            "id": "sku-1",
                            "name": "Mix, Quantity: 12pcs",
                            "imageUrl": "https://img.example.com/sku-confetti.jpg",
                            "componentSkus": [
                                {
                                    "rawSpecs": {"\u989c\u8272": "Mix Quantity 12pcs"},
                                    "specText": "Quantity: 12pcs",
                                }
                            ],
                            "sourceSkuLinks": [{"optionText": "Color: Mix", "imageUrl": "https://img.example.com/source-sku.jpg"}],
                        }
                    ],
                },
                optimize_titles=False,
            )

        self.assertEqual(rows[0]["variant_name"], "Mix, Quantity: 12pcs")
        self.assertEqual(rows[0]["variant_attr_name_1"], "\u989c\u8272")
        self.assertEqual(rows[0]["variant_attr_value_1"], "Mix")
        self.assertEqual(rows[0]["variant_attr_name_2"], "\u6570\u91cf")
        self.assertEqual(rows[0]["variant_attr_value_2"], "12pcs")
        translator.assert_called_once()
        self.assertIn("Mix Quantity 12pcs+Mix", translator.call_args.args[0])
        context = translator.call_args.kwargs["context"]
        self.assertEqual(context["title_en"], "12/24pcs Random Color Confetti Popper Handheld Party Streamers")
        self.assertIn("https://img.example.com/main-confetti.jpg", context["image_urls"])
        self.assertIn("https://img.example.com/sku-confetti.jpg", context["image_urls"])
        variant_fields = context["sku_items"][0]["variant_fields"]
        self.assertIn({"name": "\u989c\u8272", "value": "Mix Quantity 12pcs+Mix"}, variant_fields)

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

    def test_template_rows_include_generated_product_attributes(self):
        attribute_text = '[{"propName":"适用人种","refPid":3700,"pid":1752,"templatePid":1829634,"numberInputValue":"","valueUnit":"","vid":"63440","propValue":"适用各种人种"}]'
        with patch(
            "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
            return_value={"category_id": "31075", "product_attribute_text": attribute_text},
        ) as getter:
            rows = build_template_rows(
                {
                    "id": "record-1",
                    "productId": "p1",
                    "productTitle": "Test Product",
                    "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                    "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                    "skuEntries": [
                        {"id": "sku-1", "name": "Black", "componentSkus": []},
                        {"id": "sku-2", "name": "Coffee", "componentSkus": []},
                    ],
                },
                optimize_titles=False,
                translate_variants=False,
                user_id="user-1",
            )

        getter.assert_called_once()
        self.assertIs(getter.call_args.kwargs.get("strict"), True)
        self.assertEqual([row["category_id"] for row in rows], ["31075", "31075"])
        self.assertEqual([row["product_attributes"] for row in rows], [attribute_text, attribute_text])
        self.assertEqual([row["origin"] for row in rows], ["\u4e2d\u56fd-\u6d59\u6c5f\u7701", "\u4e2d\u56fd-\u6d59\u6c5f\u7701"])

    def test_template_rows_fail_when_product_attributes_are_unavailable(self):
        with patch(
            "app.modules.exports.dianxiaomi_temu.get_product_attribute_for_export_record",
            side_effect=ValueError("Product category/attributes unavailable for export: Test Product"),
        ):
            with self.assertRaisesRegex(DianxiaomiExportError, "Product category/attributes unavailable"):
                build_template_rows(
                    {
                        "id": "record-1",
                        "productId": "p1",
                        "productTitle": "Test Product",
                        "mainImage": {"sourceUrl": "https://example.com/main.jpg"},
                        "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
                        "skuEntries": [{"id": "sku-1", "name": "Black", "componentSkus": []}],
                    },
                    optimize_titles=False,
                    translate_variants=False,
                    user_id="user-1",
                )

    def test_export_records_use_member_concurrency_limit_and_keep_order(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_build(record, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return [{"product_title": record["productTitle"]}]

        records = [{"productTitle": f"Product {index}", "skuEntries": [{"id": f"sku-{index}"}]} for index in range(4)]
        with (
            patch("app.modules.exports.dianxiaomi_temu.get_runtime_setting", return_value="2"),
            patch("app.modules.exports.dianxiaomi_temu.build_template_rows_for_export_record", side_effect=fake_build),
        ):
            rows = build_template_rows_for_export_records(records, user_id="user-1")

        self.assertEqual(max_active, 2)
        self.assertEqual([row["product_title"] for row in rows], ["Product 0", "Product 1", "Product 2", "Product 3"])

    def test_export_task_runs_to_completed_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            export_path = Path(tmpdir) / "export.xlsx"
            export_path.write_bytes(b"fake-excel")
            try:
                database.init_db()
                task = create_dianxiaomi_export_task(
                    [
                        {
                            "id": "record-1",
                            "productId": "p1",
                            "productTitle": "Queued Product",
                            "skuEntries": [{"id": "sku-1", "name": "Black"}],
                        }
                    ],
                    user_id=DEFAULT_USER_ID,
                )
                with patch(
                    "app.modules.exports.dianxiaomi_export_tasks.export_dianxiaomi_temu_template",
                    return_value=export_path,
                ) as exporter:
                    run_dianxiaomi_export_task(task_id=task["id"], user_id=DEFAULT_USER_ID)

                exporter.assert_called_once()
                completed = get_dianxiaomi_export_task(task_id=task["id"], user_id=DEFAULT_USER_ID)
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(completed["filename"], "export.xlsx")
                self.assertEqual(get_completed_export_task_path(task_id=task["id"], user_id=DEFAULT_USER_ID), export_path)
            finally:
                database.DATABASE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
