import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core import database


class IngestApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.tmpdir.name) / "app.db"
        database.init_db()

        from app.main import create_app

        self.client = TestClient(create_app())
        response = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        self.tmpdir.cleanup()

    def test_yunqi_product_ingest_writes_products_and_raw_audit_items(self):
        response = self.client.post(
            "/api/ingest",
            json={
                "source": "yunqi",
                "entity_type": "product",
                "mode": "upsert",
                "idempotency_key": "yunqi-test-batch-1",
                "metadata": {"collector": "unit-test"},
                "records": [
                    {
                        "商品ID": "YQ-INGEST-1",
                        "商品标题（中文）": "户外露营睡袋",
                        "商品主图": "https://img.example.com/main.jpg",
                        "商品轮播图": ["https://img.example.com/1.jpg"],
                        "前台分类（中文）": "Sports & Outdoors > Camping & Hiking > Sleeping Bags",
                        "custom_raw_field": {"keep": True},
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["batch"]["status"], "completed")
        self.assertEqual(body["batch"]["successCount"], 1)
        self.assertEqual(body["items"][0]["targetTable"], "products")

        with database.get_connection() as conn:
            product = conn.execute(
                "SELECT * FROM products WHERE source_type = 'yunqi' AND source_product_id = 'YQ-INGEST-1'"
            ).fetchone()
            item = conn.execute("SELECT * FROM ingest_items WHERE batch_id = ?", (body["batch"]["id"],)).fetchone()

        self.assertIsNotNone(product)
        self.assertEqual(product["title_cn"], "户外露营睡袋")
        self.assertEqual(json.loads(product["raw_data_json"])["custom_raw_field"], {"keep": True})
        self.assertIsNotNone(item)
        self.assertEqual(item["status"], "processed")
        self.assertEqual(item["source_entity_id"], "YQ-INGEST-1")
        self.assertEqual(json.loads(item["raw_data_json"])["custom_raw_field"], {"keep": True})
        self.assertEqual(item["source_category_level1"], "Sports & Outdoors")

        replay = self.client.post(
            "/api/ingest",
            json={
                "source": "yunqi",
                "entity_type": "product",
                "idempotency_key": "yunqi-test-batch-1",
                "records": [{"商品ID": "YQ-INGEST-1", "商品标题（中文）": "重复请求"}],
            },
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertTrue(replay.json()["idempotent_replay"])

    def test_1688_product_without_category_inherits_related_product_category(self):
        self.seed_related_product_with_category()

        response = self.client.post(
            "/api/ingest",
            json={
                "source": "1688",
                "context": {"related_product_id": "related-product-1"},
                "records": [
                    {
                        "source_url": "https://detail.1688.com/offer/123456789.html",
                        "title": "户外睡袋工厂货源",
                        "main_image_url": "https://img.example.com/1688.jpg",
                        "price": "18.5",
                        "sku_list": [{"sku_id": "sku-1", "specs": {"颜色": "蓝色"}}],
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["batch"]["entityType"], "product")
        self.assertEqual(body["batch"]["targetTable"], "products")
        self.assertEqual(body["items"][0]["targetTable"], "products")
        self.assertEqual(body["items"][0]["categoryMatchStatus"], "inherited")
        self.assertEqual(body["items"][0]["canonicalCategoryPath"], "Sports & Outdoors/Camping & Hiking/Sleeping Bags")

        with database.get_connection() as conn:
            product = conn.execute(
                "SELECT * FROM products WHERE source_type = '1688' AND source_product_id = ?",
                ("123456789",),
            ).fetchone()
            item = conn.execute("SELECT * FROM ingest_items WHERE batch_id = ?", (body["batch"]["id"],)).fetchone()

        self.assertIsNotNone(product)
        self.assertEqual(product["source_url"], "https://detail.1688.com/offer/123456789.html")
        self.assertEqual(json.loads(product["raw_data_json"])["_ingest_context"]["related_product_id"], "related-product-1")
        self.assertEqual(item["category_match_status"], "inherited")
        self.assertEqual(item["source_category_path"], "Sports & Outdoors/Camping & Hiking/Sleeping Bags")

    def seed_related_product_with_category(self):
        database.insert_upload_batch(
            batch_id="related-batch",
            source_filename="related.json",
            saved_path=Path(self.tmpdir.name) / "related.json",
            file_type="json",
            total_rows=1,
            imported_count=1,
            failed_count=0,
        )
        database.replace_products(
            "related-batch",
            [
                {
                    "id": "related-product-1",
                    "source_row_index": 1,
                    "source_type": "yunqi",
                    "source_product_id": "YQ-RELATED-1",
                    "title_cn": "户外睡袋",
                    "title_en": None,
                    "title": "户外睡袋",
                    "main_image_url": None,
                    "gallery_image_urls": [],
                    "video_url": None,
                    "source_url": None,
                    "category_path": "Sports & Outdoors/Camping & Hiking/Sleeping Bags",
                    "category_level1": "Sports & Outdoors",
                    "category_level2": "Camping & Hiking",
                    "tags": [],
                    "price_usd": 10,
                    "gmv_usd": 0,
                    "weekly_sales": 0,
                    "monthly_sales": 0,
                    "review_count": 0,
                    "listing_time": None,
                    "status": "active",
                    "raw_data": {},
                }
            ],
            add_to_pool_user_id=None,
        )
        now = database.utc_now_text()
        with database.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO product_category_matches (
                    id, product_id, source_type, source_category_path, source_title,
                    canonical_category_id, canonical_category_path, match_score, match_method,
                    status, candidates_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    canonical_category_path = excluded.canonical_category_path,
                    match_score = excluded.match_score,
                    match_method = excluded.match_method,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    "match-related-product-1",
                    "related-product-1",
                    "yunqi",
                    "Sports & Outdoors/Camping & Hiking/Sleeping Bags",
                    "户外睡袋",
                    None,
                    "Sports & Outdoors/Camping & Hiking/Sleeping Bags",
                    1.0,
                    "manual-test",
                    "auto",
                    "[]",
                    now,
                    now,
                ),
            )


if __name__ == "__main__":
    unittest.main()
