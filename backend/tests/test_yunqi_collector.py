from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from app.core import database
from app.modules.yunqi.collector import collect_yunqi_excel_file, normalize_yunqi_record, upsert_yunqi_products


class YunqiCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.original_database_path = database.DATABASE_PATH
        database.DATABASE_PATH = self.db_path
        database.init_db()

    def tearDown(self) -> None:
        database.DATABASE_PATH = self.original_database_path
        self.temp_dir.cleanup()

    def test_normalizes_mock_yunqi_record(self):
        raw = {
            "商品ID": "YQ-1001",
            "商品标题（中文）": "加厚宠物猫窝",
            "商品标题（英文）": "Warm Cat Bed",
            "商品主图": "https://img.example.com/main.jpg",
            "商品轮播图": ["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"],
            "商品链接": "https://yunqi.example.com/products/YQ-1001",
            "前台分类（中文）": "宠物用品 > 猫用品 > 猫窝",
            "标签": "宠物, 冬季",
            "美元价格($)": "$12.30",
            "GMV($)": "1.5K",
            "周销量": "25",
            "月销量": "120",
            "总评论数": "8",
            "上架时间": "2026/06/01 12:30:00",
            "extra_nested": {"keep": True},
        }

        product = normalize_yunqi_record(raw, source_row_index=7)

        self.assertEqual(product["source_type"], "yunqi")
        self.assertEqual(product["source_product_id"], "YQ-1001")
        self.assertEqual(product["source_row_index"], 7)
        self.assertEqual(product["title_cn"], "加厚宠物猫窝")
        self.assertEqual(product["title_en"], "Warm Cat Bed")
        self.assertEqual(product["main_image_url"], "https://img.example.com/main.jpg")
        self.assertEqual(product["gallery_image_urls"], ["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"])
        self.assertEqual(product["category_path"], "宠物用品/猫用品/猫窝")
        self.assertEqual(product["category_level1"], "宠物用品")
        self.assertEqual(product["category_level2"], "猫用品")
        self.assertEqual(product["tags"], ["宠物", "冬季"])
        self.assertEqual(product["price_usd"], 12.3)
        self.assertEqual(product["gmv_usd"], 1500)
        self.assertEqual(product["weekly_sales"], 25)
        self.assertEqual(product["monthly_sales"], 120)
        self.assertEqual(product["review_count"], 8)
        self.assertEqual(product["listing_time"], "2026-06-01 12:30:00")
        self.assertEqual(product["raw_data"]["extra_nested"], {"keep": True})

    def test_upserts_same_source_product_without_duplicate_rows(self):
        first_product = normalize_yunqi_record(
            {
                "product_id": "YQ-2002",
                "title_cn": "初始标题",
                "gallery_image_urls": ["https://img.example.com/a.jpg"],
                "category_path": "宠物用品/狗用品",
                "price_usd": 9.99,
                "custom_field": "first",
            }
        )
        second_product = normalize_yunqi_record(
            {
                "product_id": "YQ-2002",
                "title_cn": "更新标题",
                "gallery_image_urls": ["https://img.example.com/b.jpg", "https://img.example.com/c.jpg"],
                "category_path": "宠物用品/狗用品/牵引绳",
                "price_usd": 12.5,
                "new_unknown_field": {"nested": [1, 2, 3]},
            }
        )

        with patch("app.modules.yunqi.collector.utc_now_text", return_value="2026-06-01 00:00:00"):
            first_result = upsert_yunqi_products(
                [first_product],
                batch_id="batch-1",
                source_filename="first.json",
                saved_path=Path(self.temp_dir.name) / "first.json",
                rebuild_keywords=False,
            )
        with patch("app.modules.yunqi.collector.utc_now_text", return_value="2026-06-02 00:00:00"):
            second_result = upsert_yunqi_products(
                [second_product],
                batch_id="batch-2",
                source_filename="second.json",
                saved_path=Path(self.temp_dir.name) / "second.json",
                rebuild_keywords=False,
            )

        self.assertEqual(first_result["created_count"], 1)
        self.assertEqual(first_result["updated_count"], 0)
        self.assertEqual(second_result["created_count"], 0)
        self.assertEqual(second_result["updated_count"], 1)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM products WHERE source_type = 'yunqi' AND source_product_id = 'YQ-2002'"
        ).fetchall()
        conn.close()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["title_cn"], "更新标题")
        self.assertEqual(row["price_usd"], 12.5)
        self.assertEqual(row["created_at"], "2026-06-01 00:00:00")
        self.assertEqual(row["updated_at"], "2026-06-02 00:00:00")
        self.assertEqual(json.loads(row["gallery_image_urls_json"]), ["https://img.example.com/b.jpg", "https://img.example.com/c.jpg"])
        self.assertEqual(row["category_path"], "宠物用品/狗用品/牵引绳")
        self.assertEqual(row["category_level1"], "宠物用品")
        self.assertEqual(row["category_level2"], "狗用品")
        self.assertEqual(json.loads(row["raw_data_json"])["new_unknown_field"], {"nested": [1, 2, 3]})

    def test_upsert_rebuilds_keyword_index_for_collected_products(self):
        product = normalize_yunqi_record(
            {
                "product_id": "YQ-3003",
                "title_cn": "宠物猫窝保暖垫",
                "category_path": "宠物用品/猫用品",
            }
        )

        result = upsert_yunqi_products(
            [product],
            batch_id="batch-keywords",
            source_filename="keywords.json",
            saved_path=Path(self.temp_dir.name) / "keywords.json",
        )

        conn = sqlite3.connect(self.db_path)
        keywords = [
            row[0]
            for row in conn.execute(
                """
                SELECT keyword
                FROM product_keywords
                WHERE product_id = ?
                ORDER BY keyword
                """,
                ("YQ-3003",),
            ).fetchall()
        ]
        conn.close()

        self.assertGreater(result["keyword_count"], 0)
        self.assertIn("宠物用品", keywords)

    def test_imports_exported_excel_with_upsert(self):
        excel_path = Path(self.temp_dir.name) / "yunqi_export.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Yunqi export"])
        sheet.append(["product_id", "title_cn", "gallery_image_urls", "category_path", "price_usd", "custom_raw"])
        sheet.append(
            [
                "YQ-XLSX-1",
                "Excel Product",
                "https://img.example.com/1.jpg,https://img.example.com/2.jpg",
                "Pets/Cats",
                "5.50",
                "keep-me",
            ]
        )
        workbook.save(excel_path)

        result = collect_yunqi_excel_file(excel_path, rebuild_keywords=False)

        self.assertEqual(result["source"], "yunqi-excel")
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["created_count"], 1)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM products WHERE source_product_id = 'YQ-XLSX-1'").fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["source_type"], "yunqi")
        self.assertEqual(row["title_cn"], "Excel Product")
        self.assertEqual(
            json.loads(row["gallery_image_urls_json"]),
            ["https://img.example.com/1.jpg", "https://img.example.com/2.jpg"],
        )
        self.assertEqual(row["category_path"], "Pets/Cats")
        self.assertEqual(row["category_level1"], "Pets")
        self.assertEqual(row["category_level2"], "Cats")
        self.assertEqual(json.loads(row["raw_data_json"])["custom_raw"], "keep-me")


if __name__ == "__main__":
    unittest.main()
