import json
import os
import sqlite3
import unittest

os.environ["OPENAI_API_KEY"] = ""

from app.modules.exports.product_attributes import (
    delete_failed_product_attribute_jobs,
    generate_complete_product_attributes,
    get_product_attribute_queue_summary_for_records,
    hash_attribute_input,
    load_product_context,
    normalize_product_attributes,
    resolve_category_for_record,
)
from app.core.database import ensure_export_product_attribute_schema


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

    def test_attribute_hash_changes_when_category_changes(self):
        base = {"productId": "p1", "productTitle": "Test", "skuEntries": [{"name": "Default"}]}
        self.assertNotEqual(
            hash_attribute_input({**base, "categoryPath": "A"}),
            hash_attribute_input({**base, "categoryPath": "B"}),
        )

    def test_queue_summary_for_records_ignores_unrelated_failed_jobs(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        ensure_export_product_attribute_schema(conn)
        current = {"id": "current-record", "productId": "p1", "productTitle": "Current", "skuEntries": [{"name": "Default"}]}
        now = "2026-06-13 12:00:00"
        conn.execute(
            """
            INSERT INTO export_product_attribute_jobs (
                id, user_id, link_record_id, product_id, product_title,
                record_hash, record_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-current",
                "u1",
                "current-record",
                "p1",
                "Current",
                hash_attribute_input(current),
                "{}",
                "done",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO export_product_attribute_jobs (
                id, user_id, link_record_id, product_id, product_title,
                record_hash, record_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-old-failed",
                "u1",
                "old-record",
                "p2",
                "Old",
                "old-hash",
                "{}",
                "failed",
                now,
                now,
            ),
        )

        summary = get_product_attribute_queue_summary_for_records(conn, user_id="u1", records=[current])

        self.assertEqual(summary["done"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["total"], 1)

    def test_delete_failed_product_attribute_jobs_keeps_success_cache(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        ensure_export_product_attribute_schema(conn)
        now = "2026-06-13 12:00:00"
        for job_id, status in (("job-done", "done"), ("job-failed", "failed")):
            conn.execute(
                """
                INSERT INTO export_product_attribute_jobs (
                    id, user_id, link_record_id, product_id, product_title,
                    record_hash, record_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "u1",
                    "record-1",
                    "p1",
                    "Product",
                    f"{status}-hash",
                    "{}",
                    status,
                    now,
                    now,
                ),
            )

        deleted = delete_failed_product_attribute_jobs(conn, user_id="u1", link_record_id="record-1")

        self.assertEqual(deleted, 1)
        rows = [dict(row) for row in conn.execute("SELECT id, status FROM export_product_attribute_jobs ORDER BY id")]
        self.assertEqual(rows, [{"id": "job-done", "status": "done"}])

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

    def test_resolves_existing_category_path_before_vector_guess(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        seed_category_snapshots(
            conn,
            [
                (
                    "bonsai",
                    ["\u5ead\u9662\u3001\u8349\u576a\u548c\u56ed\u827a", "\u7530\u56ed\u5de5\u5177\u548c\u8349\u576a\u62a4\u7406", "\u9c9c\u82b1\u3001\u7eff\u690d", "\u76c6\u683d"],
                ),
                (
                    "mailbox-cover",
                    ["\u5ead\u9662\u3001\u8349\u576a\u548c\u56ed\u827a", "\u6237\u5916\u9970\u54c1", "\u90ae\u7bb1\u7f69"],
                ),
            ],
        )

        result = resolve_category_for_record(
            conn,
            {
                "productId": "p1",
                "productTitle": "\u6a31\u82b1\u76c6\u666f\u6811\u79cd\u5b50 \u5bb6\u5c45\u88c5\u9970 \u56ed\u827a\u793c\u7269",
                "categoryPath": "\u5ead\u9662\u3001\u8349\u576a\u548c\u56ed\u827a > \u7530\u56ed\u5de5\u5177\u548c\u8349\u576a\u62a4\u7406 > \u9c9c\u82b1\u3001\u7eff\u690d > \u76c6\u683d",
                "skuEntries": [{"name": "Default"}],
            },
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["category_id"], "bonsai")

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
