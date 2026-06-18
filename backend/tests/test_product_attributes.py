import json
import os
import sqlite3
import unittest
from unittest.mock import patch

os.environ["OPENAI_API_KEY"] = ""

from app.modules.exports.product_attributes import (
    generate_complete_product_attributes,
    generate_product_attribute_for_record,
    get_product_attribute_for_export_record,
    get_product_attribute_queue_summary,
    get_product_attribute_queue_summary_for_records,
    hash_attribute_input,
    load_product_context,
    normalize_product_attributes,
    prepare_product_attribute_jobs,
    request_category_branch_ai,
    request_category_intent_ai,
    request_product_attribute_ai,
    resolve_category_for_record,
)


def choice_field(
    label,
    *,
    pid,
    template_pid,
    ref_pid,
    options,
    component="ant-select",
    choose_max_num=1,
    extra_raw=None,
):
    raw = {
        "pid": str(pid),
        "templatePid": str(template_pid),
        "refPid": str(ref_pid),
        "chooseMaxNum": choose_max_num,
        "valueUnits": [""],
    }
    raw.update(extra_raw or {})
    return {
        "field_key": label,
        "field_label": label,
        "required": 1,
        "component": component,
        "options": options,
        "raw": raw,
    }


def option(vid, label, en=""):
    return {"vid": str(vid), "value": label, "label": label, "en": en}


class ProductAttributesTest(unittest.TestCase):
    def test_normalizes_select_attribute_to_dianxiaomi_json_shape(self):
        fields = [
            choice_field(
                "适用人种",
                pid=1752,
                template_pid=1829634,
                ref_pid=3700,
                options=[option("63440", "适用各种人种", "Suitable For All People")],
            )
        ]

        result = normalize_product_attributes(
            {"attributes": [{"field_label": "适用人种", "prop_value": "Suitable For All People"}]},
            fields,
        )

        self.assertEqual(
            result,
            [
                {
                    "propName": "适用人种",
                    "refPid": 3700,
                    "pid": 1752,
                    "templatePid": 1829634,
                    "numberInputValue": "",
                    "valueUnit": "",
                    "vid": "63440",
                    "propValue": "适用各种人种",
                }
            ],
        )

    def test_normalizes_checkbox_group_as_multiple_legal_values(self):
        fields = [
            choice_field(
                "颜色",
                pid=13,
                template_pid=1252607,
                ref_pid=13,
                component="checkbox-group",
                choose_max_num=3,
                options=[option("377", "红色", "Red"), option("378", "黑色", "Black")],
            )
        ]

        result = normalize_product_attributes(
            {"attributes": [{"field_label": "颜色", "prop_values": ["Red", "黑色"]}]},
            fields,
        )

        self.assertEqual([item["vid"] for item in result], ["377", "378"])
        self.assertEqual([item["propValue"] for item in result], ["红色", "黑色"])
        self.assertEqual({item["propName"] for item in result}, {"颜色"})

    def test_parent_dependent_options_fall_back_to_allowed_child_value(self):
        fields = [
            choice_field(
                "使用群体是否为成人",
                pid=2753,
                template_pid=1829632,
                ref_pid=8540,
                options=[option("542595", "是", "Yes"), option("542597", "否", "No")],
            ),
            choice_field(
                "适用年龄段",
                pid=1141,
                template_pid=1829633,
                ref_pid=1117,
                options=[option("73667", "0+"), option("87187", "18+")],
                extra_raw={
                    "parentTemplatePid": 1829632,
                    "templatePropertyValueParent": json.dumps(
                        [
                            {"parentVidList": [542595], "vidList": [87187]},
                            {"parentVidList": [542597], "vidList": [73667]},
                        ]
                    ),
                },
            ),
        ]

        result = normalize_product_attributes(
            {
                "attributes": [
                    {"field_label": "使用群体是否为成人", "prop_value": "是"},
                    {"field_label": "适用年龄段", "prop_value": "0+"},
                ]
            },
            fields,
        )

        self.assertEqual([item["propValue"] for item in result], ["是", "18+"])
        self.assertEqual([item["vid"] for item in result], ["542595", "87187"])

    def test_numeric_input_uses_number_input_value_and_unit(self):
        fields = [
            {
                "field_key": "刀刃长度",
                "field_label": "刀刃长度",
                "required": 1,
                "component": "input",
                "options": [],
                "raw": {
                    "pid": "1996",
                    "templatePid": "1524893",
                    "refPid": "7543",
                    "valueRule": 2,
                    "valueUnits": ["cm"],
                },
            }
        ]

        result = normalize_product_attributes(
            {"attributes": [{"field_label": "刀刃长度", "number_input_value": "10"}]},
            fields,
        )

        self.assertEqual(result[0]["numberInputValue"], "10")
        self.assertEqual(result[0]["valueUnit"], "cm")
        self.assertEqual(result[0]["propValue"], "")

    def test_numeric_input_strips_unit_from_number_input_value(self):
        label = "\u5e73\u65b9\u7c73\u514b\u91cd\uff08g/\u33a1\uff09"
        fields = [
            {
                "field_key": label,
                "field_label": label,
                "required": 1,
                "component": "input",
                "options": [],
                "raw": {
                    "pid": "3101",
                    "templatePid": "3102",
                    "refPid": "3103",
                    "valueRule": 2,
                    "valueUnits": ["g/\u33a1"],
                },
            }
        ]

        result = normalize_product_attributes(
            {"attributes": [{"field_label": label, "number_input_value": "250g/\u33a1"}]},
            fields,
        )

        self.assertEqual(result[0]["numberInputValue"], "250")
        self.assertEqual(result[0]["valueUnit"], "g/\u33a1")
        self.assertEqual(result[0]["propValue"], "")

    def test_select_percent_replaces_high_percent_other_fiber(self):
        label = "\u6210\u5206"
        fields = [
            choice_field(
                label,
                pid=4101,
                template_pid=4102,
                ref_pid=4103,
                component="select-percent",
                options=[
                    option("36254", "\u5176\u4ed6\u7ea4\u7ef4", "Other Fibers"),
                    option("46248", "\u805a\u916f\u7ea4\u7ef4(\u6da4\u7eb6\uff09", "Polyester"),
                ],
                extra_raw={"valueUnits": ["%"], "valueRule": 1},
            )
        ]

        result = normalize_product_attributes(
            {"attributes": [{"field_label": label, "prop_value": "Other Fibers", "number_input_value": "100%"}]},
            fields,
        )

        self.assertEqual(result[0]["propValue"], "\u805a\u916f\u7ea4\u7ef4(\u6da4\u7eb6\uff09")
        self.assertEqual(result[0]["vid"], "46248")
        self.assertEqual(result[0]["numberInputValue"], "100")
        self.assertEqual(result[0]["valueUnit"], "%")

    def test_complete_attributes_fill_every_visible_field_when_ai_is_partial(self):
        fields = [
            choice_field(
                "\u690d\u7269\u683c\u5f0f",
                pid=588,
                template_pid=178896,
                ref_pid=643,
                options=[option("17229", "\u690d\u7269\u79cd\u5b50"), option("17230", "\u76c6\u683d")],
            ),
            choice_field(
                "\u6750\u6599\u7279\u5f81",
                pid=91,
                template_pid=17238,
                ref_pid=7194,
                options=[option("8001", "\u73af\u4fdd\u6750\u6599"), option("8002", "\u5176\u4ed6")],
            ),
            choice_field(
                "\u54c1\u724c\u540d",
                pid=100,
                template_pid=101,
                ref_pid=102,
                options=[option("9001", "\u65e0\u54c1\u724c"), option("9002", "\u5176\u4ed6")],
            ),
            choice_field(
                "\u989c\u8272",
                pid=13,
                template_pid=1394525,
                ref_pid=63,
                component="checkbox-group",
                options=[option("438", "\u7c89\u7ea2\u8272"), option("437", "\u767d\u8272")],
            ),
        ]

        result = generate_complete_product_attributes(
            {"productTitle": "\u7c89\u7ea2\u8272\u591a\u8089\u76c6\u683d\u690d\u7269"},
            fields,
            {"attributes": [{"field_label": "\u690d\u7269\u683c\u5f0f", "prop_value": "\u690d\u7269\u79cd\u5b50"}]},
        )

        self.assertEqual([item["propName"] for item in result], ["\u690d\u7269\u683c\u5f0f", "\u6750\u6599\u7279\u5f81", "\u54c1\u724c\u540d", "\u989c\u8272"])
        self.assertEqual(result[1]["propValue"], "\u5176\u4ed6")
        self.assertEqual(result[2]["propValue"], "\u65e0\u54c1\u724c")
        self.assertEqual(result[3]["propValue"], "\u7c89\u7ea2\u8272")

    def test_complete_attributes_respect_parent_dependent_fallback_options(self):
        fields = [
            choice_field(
                "\u7236\u7ea7\u5c5e\u6027",
                pid=1,
                template_pid=100,
                ref_pid=10,
                options=[option("1", "A"), option("2", "B")],
            ),
            choice_field(
                "\u5b50\u7ea7\u5c5e\u6027",
                pid=2,
                template_pid=101,
                ref_pid=11,
                options=[option("11", "A1"), option("22", "B1")],
                extra_raw={
                    "parentTemplatePid": 100,
                    "templatePropertyValueParent": json.dumps(
                        [
                            {"parentVidList": [1], "vidList": [11]},
                            {"parentVidList": [2], "vidList": [22]},
                        ]
                    ),
                },
            ),
        ]

        result = generate_complete_product_attributes(
            {"productTitle": "test"},
            fields,
            {"attributes": [{"field_label": "\u7236\u7ea7\u5c5e\u6027", "prop_value": "B"}]},
        )

        self.assertEqual([item["propValue"] for item in result], ["B", "B1"])
        self.assertEqual([item["vid"] for item in result], ["2", "22"])

    def test_complete_attributes_skip_red_line_battery_and_plug_child_fields(self):
        fields = [
            choice_field(
                "\u662f\u5426\u5e26\u7535\u6c60",
                pid=1427,
                template_pid=525339,
                ref_pid=1563,
                options=[option("36639", "\u662f"), option("36640", "\u5426")],
            ),
            choice_field(
                "\u53ef\u5145\u7535\u7535\u6c60",
                pid=1535,
                template_pid=958335,
                ref_pid=2147,
                options=[option("52045", "\u9502\u7cfb\u7535\u6c60")],
            ),
            choice_field(
                "\u5de5\u4f5c\u7535\u538b",
                pid=1155,
                template_pid=1378401,
                ref_pid=1132,
                options=[option("28317", "36V\u53ca\u4ee5\u4e0b")],
            ),
            choice_field(
                "\u63d2\u5934\u89c4\u683c",
                pid=1404,
                template_pid=1378402,
                ref_pid=1485,
                options=[option("36261", "\u7f8e\u89c4")],
            ),
        ]

        result = generate_complete_product_attributes(
            {"productTitle": "\u5ba0\u7269\u7845\u80f6\u9910\u57ab \u4e0d\u5e26\u7535"},
            fields,
            {
                "attributes": [
                    {"field_label": "\u662f\u5426\u5e26\u7535\u6c60", "prop_value": "\u5426"},
                    {"field_label": "\u53ef\u5145\u7535\u7535\u6c60", "prop_value": "\u9502\u7cfb\u7535\u6c60"},
                    {"field_label": "\u5de5\u4f5c\u7535\u538b", "prop_value": "36V\u53ca\u4ee5\u4e0b"},
                    {"field_label": "\u63d2\u5934\u89c4\u683c", "prop_value": "\u7f8e\u89c4"},
                ]
            },
        )

        self.assertEqual([item["propName"] for item in result], ["\u662f\u5426\u5e26\u7535\u6c60"])
        self.assertEqual(result[0]["propValue"], "\u5426")

    def test_attribute_hash_ignores_scraped_category_fields(self):
        base = {"productId": "p1", "productTitle": "Test", "skuEntries": [{"name": "Default"}]}
        self.assertEqual(
            hash_attribute_input({**base, "categoryPath": "A"}),
            hash_attribute_input({**base, "categoryPath": "B"}),
        )

    def test_product_attribute_prepare_and_status_are_noop_when_cache_disabled(self):
        record = {"id": "current-record", "productId": "p1", "productTitle": "Current", "skuEntries": [{"name": "Default"}]}

        prepared = prepare_product_attribute_jobs([record], user_id="u1", process_now=True)
        summary = get_product_attribute_queue_summary(user_id="u1", records=[record])
        record_summary = get_product_attribute_queue_summary_for_records(None, user_id="u1", records=[record])

        for payload in (prepared, summary, record_summary):
            self.assertEqual(payload["queued"], 0)
            self.assertEqual(payload["running"], 0)
            self.assertEqual(payload["done"], 0)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["total"], 0)
        self.assertEqual(prepared["queuedNow"], 0)
        self.assertEqual(prepared["reused"], 0)

    def test_load_product_context_falls_back_to_record_category_path(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        for table in ("products", "product_pool_products"):
            conn.execute(
                f"""
                CREATE TABLE {table} (
                    id TEXT,
                    source_product_id TEXT,
                    title TEXT,
                    title_cn TEXT,
                    source_url TEXT,
                    category_path TEXT,
                    category_level1 TEXT,
                    category_level2 TEXT,
                    raw_data_json TEXT
                )
                """
            )

        result = load_product_context(
            conn,
            {
                "productId": "missing",
                "categoryPath": "\u5bb6\u5c45/\u9910\u57ab",
                "categoryLevel1": "\u5bb6\u5c45",
                "categoryLevel2": "\u9910\u57ab",
            },
        )

        self.assertEqual(result["category_path"], "\u5bb6\u5c45/\u9910\u57ab")
        self.assertEqual(result["category_level1"], "\u5bb6\u5c45")
        self.assertEqual(result["category_level2"], "\u9910\u57ab")

    def test_load_product_context_matches_product_by_source_url(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        for table in ("products", "product_pool_products"):
            conn.execute(
                f"""
                CREATE TABLE {table} (
                    id TEXT,
                    source_product_id TEXT,
                    title TEXT,
                    title_cn TEXT,
                    source_url TEXT,
                    category_path TEXT,
                    category_level1 TEXT,
                    category_level2 TEXT,
                    raw_data_json TEXT
                )
                """
            )
        conn.execute(
            """
            INSERT INTO products (
                id, source_product_id, title, title_cn, source_url,
                category_path, category_level1, category_level2, raw_data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "p1",
                "sp1",
                "\u5ba0\u7269\u9910\u57ab",
                "\u5ba0\u7269\u9910\u57ab",
                "https://detail.1688.com/offer/1.html",
                "\u5ba0\u7269\u7528\u54c1/\u9910\u57ab",
                "\u5ba0\u7269\u7528\u54c1",
                "\u9910\u57ab",
                "{}",
            ),
        )

        result = load_product_context(
            conn,
            {
                "productId": "different-id",
                "productTitle": "\u5ba0\u7269\u9910\u57ab",
                "sourceLinks": [{"productUrl": "https://detail.1688.com/offer/1.html"}],
            },
        )

        self.assertEqual(result["category_path"], "\u5ba0\u7269\u7528\u54c1/\u9910\u57ab")

    def test_resolves_category_by_title_vector_without_category_id(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                (
                    "pet-feeding-mat",
                    ["\u5ba0\u7269\u7528\u54c1", "\u732b\u7528\u54c1", "\u732b\u5582\u98df\u3001\u5582\u6c34\u7528\u5177", "\u732b\u7528\u7897\u789f"],
                ),
                (
                    "smart-pet-feeder",
                    ["\u7535\u5b50", "\u667a\u80fd\u8bbe\u5907", "\u667a\u80fd\u5ba0\u7269\u5582\u98df\u673a"],
                ),
                (
                    "home-placemat",
                    ["\u5bb6\u5c45\u3001\u53a8\u623f\u7528\u54c1", "\u53a8\u623f\u548c\u9910\u5385", "\u9910\u53a8\u5e03\u827a", "\u9910\u57ab"],
                ),
            ],
        )

        result = resolve_category_for_record(
            conn,
            {
                "productId": "missing-product",
                "productTitle": "\u5ba0\u7269\u9910\u57ab\u98de\u789f\u7897\u732b\u7897\u72d7\u7897 \u9632\u6ed1\u6613\u6e05\u6d01",
                "skuEntries": [{"name": "\u7070\u8272\u82b1\u8fb9\u9910\u57ab"}],
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "pet-feeding-mat")

    def test_ignores_existing_category_path_and_uses_title_vector(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                (
                    "bonsai",
                    ["Garden", "Plants", "Bonsai Seeds"],
                ),
                (
                    "mailbox-cover",
                    ["Garden", "Outdoor Decor", "Mailbox Covers"],
                ),
            ],
        )

        result = resolve_category_for_record(
            conn,
            {
                "productId": "p1",
                "productTitle": "Bonsai seeds garden plant gift",
                "categoryPath": "Garden > Outdoor Decor > Mailbox Covers",
                "skuEntries": [{"name": "Default"}],
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "bonsai")

    def test_ignores_explicit_category_id_and_uses_title_vector(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                (
                    "finger-cymbals",
                    ["Musical Instruments", "Drums & Percussions", "Finger Cymbals"],
                ),
                (
                    "dice",
                    ["Toys & Games", "Games & Accessories", "Dice"],
                ),
            ],
        )

        result = resolve_category_for_record(
            conn,
            {
                "productId": "wood-dice",
                "productTitle": "Wood Dice D12 Dice for RPG Tabletop Games",
                "categoryId": "finger-cymbals",
                "skuEntries": [{"name": "Wood dice"}],
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "dice")

    def test_ignores_noisy_source_category_path_before_vector_match(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                (
                    "finger-cymbals",
                    ["Musical Instruments", "Drums & Percussions", "Finger Cymbals"],
                ),
                (
                    "dice",
                    ["Toys & Games", "Games & Accessories", "Dice"],
                ),
            ],
        )

        result = resolve_category_for_record(
            conn,
            {
                "productId": "wood-dice",
                "productTitle": "Wood Dice D12 Dice for RPG Tabletop Games",
                "categoryPath": "company_info/Musical Instruments/Drums & Percussions/Set of 6 Shiny Metal Finger.../Categories",
                "skuEntries": [{"name": "Wood dice"}],
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "dice")

    def test_export_attribute_lookup_strict_failure_raises(self):
        record = {
            "id": "record-1",
            "productId": "product-1",
            "productTitle": "Wood Dice",
            "skuEntries": [{"name": "Default"}],
        }

        with patch(
            "app.modules.exports.product_attributes.generate_product_attribute_for_record",
            side_effect=ValueError("No matching category"),
        ):
            with self.assertRaisesRegex(ValueError, "Product category/attributes unavailable"):
                get_product_attribute_for_export_record(record, user_id="u1", strict=True)

    def test_export_attribute_lookup_generates_fresh_result_with_api_required(self):
        record = {
            "id": "record-1",
            "productId": "product-1",
            "productTitle": "Wood Dice",
            "skuEntries": [{"name": "Default"}],
        }

        with patch(
            "app.modules.exports.product_attributes.generate_product_attribute_for_record",
            return_value={
                "category_id": "fresh-category",
                "category_path": "Fresh > Category",
                "product_attributes": [{"propName": "Brand", "propValue": "No Brand"}],
            },
        ) as generator:
            result = get_product_attribute_for_export_record(record, user_id="u1", strict=True)

        self.assertEqual(result["category_id"], "fresh-category")
        self.assertIn("No Brand", result["product_attribute_text"])
        self.assertIs(generator.call_args.kwargs.get("require_api"), True)

    def test_export_attribute_lookup_uses_final_export_title_context(self):
        record = {
            "id": "record-1",
            "productId": "product-1",
            "productTitle": "原始采集标题",
            "productTitleEn": "Original scraped title",
            "skuEntries": [{"name": "Default"}],
        }

        with patch(
            "app.modules.exports.product_attributes.generate_product_attribute_for_record",
            return_value={
                "category_id": "fresh-category",
                "category_path": "Fresh > Category",
                "product_attributes": [{"propName": "Material", "propValue": "Silicone"}],
            },
        ) as generator:
            get_product_attribute_for_export_record(
                record,
                user_id="u1",
                strict=True,
                title_context={
                    "title_cn": "最终中文标题 硅胶宠物喂食垫",
                    "title_en": "Final Silicone Pet Feeding Mat Title",
                },
            )

        api_record = generator.call_args.args[0]
        self.assertEqual(api_record["productTitle"], "最终中文标题 硅胶宠物喂食垫")
        self.assertEqual(api_record["productTitleEn"], "Final Silicone Pet Feeding Mat Title")
        self.assertEqual(api_record["originalProductTitle"], "原始采集标题")
        self.assertEqual(api_record["originalProductTitleEn"], "Original scraped title")
        self.assertEqual(api_record["attributeTitle"], "最终中文标题 硅胶宠物喂食垫")

    def test_strict_attribute_generation_requires_api_configuration(self):
        with patch(
            "app.modules.exports.product_attributes.is_product_attribute_ai_configured",
            return_value=False,
        ):
            with self.assertRaisesRegex(ValueError, "Product attribute API is not configured"):
                generate_product_attribute_for_record(
                    {"productTitle": "Wood Dice", "skuEntries": [{"name": "Default"}]},
                    user_id="u1",
                    require_api=True,
                )

    def test_strict_category_resolution_calls_category_intent_api(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                ("dice", ["Toys & Games", "Games & Accessories", "Dice"]),
                ("finger-cymbals", ["Musical Instruments", "Drums & Percussions", "Finger Cymbals"]),
            ],
        )

        with (
            patch("app.modules.exports.product_attributes.is_product_attribute_ai_configured", return_value=True),
            patch(
                "app.modules.exports.product_attributes.request_category_intent_ai",
                return_value={"product_type": "dice", "core_keywords": ["dice", "tabletop game"]},
            ) as intent_api,
            patch(
                "app.modules.exports.product_attributes.request_category_branch_ai",
                return_value={"selected_index": 1, "confidence": 0.9},
            ),
        ):
            result = resolve_category_for_record(
                conn,
                {
                    "productId": "wood-dice",
                    "productTitle": "Wood Dice D12 Dice for RPG Tabletop Games",
                    "skuEntries": [{"name": "Wood dice"}],
                },
                user_id="u1",
                require_api=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "dice")
        intent_api.assert_called_once()

    def test_strict_category_resolution_uses_ai_tree_selection_not_vector_winner(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                ("storage-box", ["Home, Kitchen & Household", "Storage & Organization", "Storage Boxes"]),
                ("party-favor-bag", ["Toys & Games", "Party Supplies", "Kids Party Favor Bags"]),
            ],
        )

        def biased_score(leaves, _query_vector, _query_text):
            scored = []
            for leaf in leaves:
                path = leaf.get("path_text") or ""
                score = 0.95 if "Storage Boxes" in path else 0.45
                scored.append({**leaf, "score": score, "matched_terms": []})
            scored.sort(key=lambda item: item["score"], reverse=True)
            return scored

        def choose_party_branch(**kwargs):
            for index, candidate in enumerate(kwargs["candidates"], start=1):
                path = candidate.get("path_text") or ""
                if "Toys" in path or "Party" in path or "Favor" in path:
                    return {"selected_index": index, "confidence": 0.92}
            return {"selected_index": 1, "confidence": 0.92}

        with (
            patch("app.modules.exports.product_attributes.is_product_attribute_ai_configured", return_value=True),
            patch(
                "app.modules.exports.product_attributes.request_category_intent_ai",
                return_value={
                    "product_identity": "children party favor gift bag",
                    "product_type": "party favor bag",
                    "visual_subject": "colorful small party favor bags",
                    "core_keywords": ["kids party favor bag", "party supplies"],
                    "exclude_keywords": ["storage box", "organizer"],
                },
            ),
            patch("app.modules.exports.product_attributes.score_category_leaves", side_effect=biased_score),
            patch("app.modules.exports.product_attributes.request_category_branch_ai", side_effect=choose_party_branch) as branch_api,
        ):
            result = resolve_category_for_record(
                conn,
                {
                    "productId": "party-bag",
                    "productTitle": "Children party favor gift bags with colorful design",
                    "productTitleEn": "Kids Party Favor Gift Bags",
                    "mainImage": {"sourceUrl": "https://img.example.com/party-bag.jpg"},
                    "sourceLinks": [{"title": "storage box party gift bag", "imageUrl": "https://img.example.com/source.jpg"}],
                    "skuEntries": [{"name": "Mixed Color"}],
                },
                user_id="u1",
                require_api=True,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "party-favor-bag")
        self.assertGreaterEqual(branch_api.call_count, 1)
        candidate_sets = [call.kwargs["candidates"] for call in branch_api.call_args_list]
        self.assertTrue(
            any(
                any("Home, Kitchen & Household" in candidate.get("path_text", "") for candidate in candidates)
                for candidates in candidate_sets
            )
        )
        self.assertTrue(
            any(
                any("Toys & Games" in candidate.get("path_text", "") for candidate in candidates)
                for candidates in candidate_sets
            )
        )

    def test_non_strict_ai_category_resolution_uses_tree_selection_not_vector_winner(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                ("storage-box", ["Home, Kitchen & Household", "Storage & Organization", "Storage Boxes"]),
                ("party-favor-bag", ["Toys & Games", "Party Supplies", "Kids Party Favor Bags"]),
            ],
        )

        def biased_score(leaves, _query_vector, _query_text):
            scored = []
            for leaf in leaves:
                path = leaf.get("path_text") or ""
                score = 0.96 if "Storage Boxes" in path else 0.42
                scored.append({**leaf, "score": score, "matched_terms": []})
            scored.sort(key=lambda item: item["score"], reverse=True)
            return scored

        def choose_party_branch(**kwargs):
            for index, candidate in enumerate(kwargs["candidates"], start=1):
                path = candidate.get("path_text") or ""
                if "Toys" in path or "Party" in path or "Favor" in path:
                    return {"selected_index": index, "confidence": 0.9}
            return {"selected_index": 1, "confidence": 0.9}

        with (
            patch("app.modules.exports.product_attributes.is_product_attribute_ai_configured", return_value=True),
            patch(
                "app.modules.exports.product_attributes.request_category_intent_ai",
                return_value={
                    "product_identity": "children party favor gift bag",
                    "product_type": "party favor bag",
                    "visual_subject": "colorful party favor bags",
                    "core_keywords": ["party favor bag", "party supplies"],
                    "exclude_keywords": ["storage box", "organizer"],
                },
            ) as intent_api,
            patch("app.modules.exports.product_attributes.score_category_leaves", side_effect=biased_score),
            patch("app.modules.exports.product_attributes.request_category_branch_ai", side_effect=choose_party_branch) as branch_api,
        ):
            result = resolve_category_for_record(
                conn,
                {
                    "productId": "party-bag",
                    "productTitle": "Children party favor gift bags with colorful design",
                    "mainImage": {"sourceUrl": "https://img.example.com/party-bag.jpg"},
                    "sourceLinks": [{"title": "storage box party gift bag", "imageUrl": "https://img.example.com/source.jpg"}],
                    "skuEntries": [{"name": "Mixed Color"}],
                },
                user_id="u1",
                require_api=False,
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "party-favor-bag")
        intent_api.assert_called_once()
        self.assertGreaterEqual(branch_api.call_count, 1)

    def test_category_intent_ai_uses_title_and_images_as_multimodal_context(self):
        with (
            patch(
                "app.modules.exports.product_attributes.get_ai_stage_settings",
                return_value={
                    "api_key": "test-key",
                    "base_url": "https://api.example.com/v1",
                    "model": "vision-model",
                    "channel_id": "",
                },
            ),
            patch("app.modules.exports.product_attributes.assert_user_api_usage_allowed"),
            patch("app.modules.exports.product_attributes.record_product_attribute_usage"),
            patch(
                "app.modules.exports.product_attributes.request_json",
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"product_type": "tote bag", "core_keywords": ["tote bag"]},
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            ) as request_json_mock,
        ):
            result = request_category_intent_ai(
                {
                    "productTitle": "5pcs pale mini tote bag set with zipper closure",
                    "productTitleEn": "5PCS Pale Mini Tote Bag Set",
                    "mainImage": {"sourceUrl": "https://img.example.com/main-tote.jpg"},
                    "productMaterialImages": [{"sourceUrl": "https://img.example.com/detail-tote.jpg"}],
                    "sourceLinks": [{"title": "Mini tote bag", "imageUrl": "https://img.example.com/source-tote.jpg"}],
                    "skuEntries": [{"name": "Pale tote", "imageUrl": "https://img.example.com/sku-tote.jpg"}],
                },
                {},
                user_id="u1",
            )

        self.assertEqual(result["product_type"], "tote bag")
        payload = request_json_mock.call_args.args[2]
        content = payload["messages"][0]["content"]
        instruction = json.loads(content[0]["text"])
        self.assertIn("First identify the real product", instruction["task"])
        self.assertIn("product_identity", instruction["output_schema"])
        self.assertTrue(any("images and final export title as primary evidence" in rule for rule in instruction["rules"]))
        self.assertTrue(any("storage container" in rule for rule in instruction["rules"]))
        self.assertEqual(instruction["product"]["title_en"], "5PCS Pale Mini Tote Bag Set")
        self.assertIn(
            {"role": "main_image", "url": "https://img.example.com/main-tote.jpg"},
            instruction["product"]["reference_images"],
        )
        image_urls = [item["image_url"]["url"] for item in content[1:]]
        self.assertIn("https://img.example.com/main-tote.jpg", image_urls)
        self.assertIn("https://img.example.com/detail-tote.jpg", image_urls)

    def test_category_branch_ai_uses_images_when_selecting_candidates(self):
        with (
            patch(
                "app.modules.exports.product_attributes.get_ai_stage_settings",
                return_value={
                    "api_key": "test-key",
                    "base_url": "https://api.example.com/v1",
                    "model": "vision-model",
                    "channel_id": "",
                },
            ),
            patch("app.modules.exports.product_attributes.assert_user_api_usage_allowed"),
            patch("app.modules.exports.product_attributes.record_product_attribute_usage"),
            patch(
                "app.modules.exports.product_attributes.request_json",
                return_value={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {"selected_index": 1, "confidence": 0.91},
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            ) as request_json_mock,
        ):
            result = request_category_branch_ai(
                record={
                    "productTitle": "5pcs pale mini tote bag set with zipper closure",
                    "productTitleEn": "5PCS Pale Mini Tote Bag Set",
                    "mainImage": {"sourceUrl": "https://img.example.com/main-tote.jpg"},
                },
                intent={"product_type": "tote bag", "core_keywords": ["bag", "tote"]},
                current_path=[],
                candidates=[
                    {"name": "Tote Bags", "path_text": "Bags > Women Bags > Tote Bags", "score": 0.7},
                    {"name": "Game Boy Color", "path_text": "Video Games > Game Boy Color", "score": 0.6},
                ],
                task="Choose the final leaf category that best fits the product.",
                user_id="u1",
            )

        self.assertEqual(result["selected_index"], 1)
        payload = request_json_mock.call_args.args[2]
        content = payload["messages"][0]["content"]
        instruction = json.loads(content[0]["text"])
        self.assertTrue(any("First identify the real product" in rule for rule in instruction["rules"]))
        self.assertTrue(any("storage/organizer/container" in rule for rule in instruction["rules"]))
        self.assertEqual(instruction["product"]["title_cn"], "5pcs pale mini tote bag set with zipper closure")
        self.assertEqual(instruction["candidates"][1]["path"], "Video Games > Game Boy Color")
        self.assertEqual(content[1]["image_url"]["url"], "https://img.example.com/main-tote.jpg")

    def test_product_attribute_ai_uses_final_title_and_images(self):
        with (
            patch(
                "app.modules.exports.product_attributes.get_ai_stage_settings",
                return_value={
                    "api_key": "test-key",
                    "base_url": "https://api.example.com/v1",
                    "model": "vision-model",
                    "channel_id": "",
                },
            ),
            patch("app.modules.exports.product_attributes.assert_user_api_usage_allowed"),
            patch("app.modules.exports.product_attributes.record_product_attribute_usage"),
            patch(
                "app.modules.exports.product_attributes.request_category_json",
                return_value={"attributes": [{"field_label": "Material", "prop_value": "Paper"}]},
            ) as request_json_mock,
        ):
            result = request_product_attribute_ai(
                {
                    "productTitle": "彩色派对拉花",
                    "productTitleEn": "Colorful Confetti Popper",
                    "attributeTitle": "最终中文标题 彩色派对拉花",
                    "attributeTitleEn": "Final English Colorful Confetti Popper",
                    "mainImage": {"sourceUrl": "https://img.example.com/main-confetti.jpg"},
                    "productMaterialImages": [{"sourceUrl": "https://img.example.com/detail-confetti.jpg"}],
                    "skuEntries": [{"name": "Mix, Quantity: 12pcs"}],
                },
                {"category_id": "party", "category_path_text": "Party Supplies > Confetti Poppers"},
                [
                    {
                        "field_key": "material",
                        "field_label": "Material",
                        "component": "ant-select",
                        "required": True,
                        "raw": {"pid": "1", "templatePid": "2", "refPid": "3"},
                        "options": [{"label": "Paper", "vid": "paper"}],
                    }
                ],
                user_id="u1",
            )

        self.assertEqual(result["attributes"][0]["prop_value"], "Paper")
        instruction = json.loads(request_json_mock.call_args.kwargs["instruction"])
        self.assertEqual(instruction["product"]["final_export_title_en"], "Final English Colorful Confetti Popper")
        self.assertIn(
            {"role": "main_image", "url": "https://img.example.com/main-confetti.jpg"},
            instruction["product"]["reference_images"],
        )
        self.assertTrue(any("battery" in rule.lower() for rule in instruction["red_line_rules"]))
        self.assertTrue(any("plug" in rule.lower() for rule in instruction["red_line_rules"]))
        self.assertIn("https://img.example.com/main-confetti.jpg", request_json_mock.call_args.kwargs["image_refs"])

def seed_category_snapshots(conn: sqlite3.Connection, categories: list[tuple[str, list[str]]]) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dxm_temu_category_attr_snapshots (
            id TEXT PRIMARY KEY,
            category_id TEXT NOT NULL DEFAULT '',
            category_path_text TEXT NOT NULL,
            category_path_json TEXT NOT NULL,
            node_path_id TEXT NOT NULL DEFAULT '',
            category_depth INTEGER NOT NULL DEFAULT 0,
            level1_id TEXT NOT NULL DEFAULT '',
            level1_name TEXT NOT NULL DEFAULT '',
            level2_id TEXT NOT NULL DEFAULT '',
            level2_name TEXT NOT NULL DEFAULT '',
            level3_id TEXT NOT NULL DEFAULT '',
            level3_name TEXT NOT NULL DEFAULT '',
            level4_id TEXT NOT NULL DEFAULT '',
            level4_name TEXT NOT NULL DEFAULT '',
            level5_id TEXT NOT NULL DEFAULT '',
            level5_name TEXT NOT NULL DEFAULT '',
            level6_id TEXT NOT NULL DEFAULT '',
            level6_name TEXT NOT NULL DEFAULT '',
            leaf_name TEXT NOT NULL,
            attr_count INTEGER NOT NULL DEFAULT 0,
            required_count INTEGER NOT NULL DEFAULT 0,
            collection_status TEXT NOT NULL DEFAULT 'ok'
        )
        """
    )
    for index, (category_id, parts) in enumerate(categories, start=1):
        ids = [f"{category_id}-level-{level}" for level in range(1, len(parts) + 1)]
        values = {
            "id": f"snapshot-{index}",
            "category_id": category_id,
            "category_path_text": " > ".join(parts),
            "category_path_json": json.dumps(parts, ensure_ascii=False),
            "node_path_id": "/".join(ids),
            "category_depth": len(parts),
            "leaf_name": parts[-1],
            "attr_count": 12,
            "required_count": 4,
        }
        for level in range(1, 7):
            values[f"level{level}_id"] = ids[level - 1] if level <= len(ids) else ""
            values[f"level{level}_name"] = parts[level - 1] if level <= len(parts) else ""
        conn.execute(
            """
            INSERT INTO dxm_temu_category_attr_snapshots (
                id, category_id, category_path_text, category_path_json, node_path_id,
                category_depth, level1_id, level1_name, level2_id, level2_name,
                level3_id, level3_name, level4_id, level4_name, level5_id,
                level5_name, level6_id, level6_name, leaf_name, attr_count,
                required_count, collection_status
            ) VALUES (
                :id, :category_id, :category_path_text, :category_path_json, :node_path_id,
                :category_depth, :level1_id, :level1_name, :level2_id, :level2_name,
                :level3_id, :level3_name, :level4_id, :level4_name, :level5_id,
                :level5_name, :level6_id, :level6_name, :leaf_name, :attr_count,
                :required_count, 'ok'
            )
            """,
            values,
        )


if __name__ == "__main__":
    unittest.main()
