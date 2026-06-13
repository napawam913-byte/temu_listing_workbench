import json
import tempfile
import unittest
from pathlib import Path

from app.core import database


GARDEN_TOP = "\u5ead\u9662\u3001\u8349\u576a\u548c\u56ed\u827a"
GARDEN_CHILD = "Garden Sculptures(\u82b1\u56ed\u96d5\u5851)"
PET_TOP = "\u5ba0\u7269\u7528\u54c1"
PET_CHILD = "Bird & Wildlife Care(\u5ead\u9662\u5582\u9e1f\u7528\u54c1)"


class CategoryMappingMvpTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.tmpdir.name) / "app.db"
        database.init_db()
        self.seed_dxm_categories()

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        self.tmpdir.cleanup()

    def seed_dxm_categories(self):
        with database.get_connection() as conn:
            conn.executescript(
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
                );
                """
            )
            for index, (category_id, top, child) in enumerate(
                [
                    ("garden-sculptures", GARDEN_TOP, GARDEN_CHILD),
                    ("bird-care", PET_TOP, PET_CHILD),
                ],
                start=1,
            ):
                conn.execute(
                    """
                    INSERT INTO dxm_temu_category_attr_snapshots (
                        id, category_id, category_path_text, category_path_json,
                        node_path_id, category_depth, level1_id, level1_name,
                        level2_id, level2_name, leaf_name, attr_count,
                        required_count, collection_status
                    ) VALUES (?, ?, ?, ?, ?, 2, ?, ?, ?, ?, ?, 8, 3, 'ok')
                    """,
                    (
                        f"snapshot-{index}",
                        category_id,
                        f"{top} > {child}",
                        json.dumps([top, child], ensure_ascii=False),
                        f"top-{index}/{category_id}",
                        f"top-{index}",
                        top,
                        category_id,
                        child,
                        child,
                    ),
                )

    def insert_batch(self):
        database.insert_upload_batch(
            batch_id="batch-1",
            source_filename="test.csv",
            saved_path=Path(self.tmpdir.name) / "test.csv",
            file_type="csv",
            total_rows=1,
            imported_count=1,
            failed_count=0,
        )

    def product_payload(self, product_id: str = "product-1"):
        return {
            "id": product_id,
            "source_row_index": 1,
            "source_type": "yunqi",
            "source_product_id": "source-1",
            "title_cn": "\u592a\u9633\u80fd\u82b1\u56ed\u96d5\u5851\u6446\u4ef6",
            "title_en": None,
            "title": "\u592a\u9633\u80fd\u82b1\u56ed\u96d5\u5851\u6446\u4ef6",
            "main_image_url": None,
            "gallery_image_urls": [],
            "video_url": None,
            "source_url": None,
            "category_path": "\u56ed\u827a/\u82b1\u56ed\u96d5\u5851",
            "category_level1": "\u56ed\u827a",
            "category_level2": "\u82b1\u56ed\u96d5\u5851",
            "tags": [],
            "price_usd": 9.9,
            "gmv_usd": 0,
            "weekly_sales": 1,
            "monthly_sales": 3,
            "review_count": 0,
            "listing_time": "2026-06-01",
            "status": "active",
            "raw_data": {},
        }

    def test_replace_products_creates_category_match(self):
        self.insert_batch()
        database.replace_products("batch-1", [self.product_payload()], add_to_pool_user_id=None)

        with database.get_connection() as conn:
            row = conn.execute(
                """
                SELECT status, canonical_category_path, match_score
                FROM product_category_matches
                WHERE product_id = 'product-1'
                """
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertIn(row["status"], {"auto", "review"})
        self.assertIn(GARDEN_CHILD, row["canonical_category_path"])
        self.assertGreaterEqual(row["match_score"], database.CATEGORY_REVIEW_THRESHOLD)

    def test_categories_use_dxm_tree_and_filter_products_by_mapping(self):
        self.insert_batch()
        database.replace_products("batch-1", [self.product_payload()], add_to_pool_user_id=None)

        categories = database.get_product_categories()
        garden = next(item for item in categories if item["label"] == GARDEN_TOP)
        pet = next(item for item in categories if item["label"] == PET_TOP)

        self.assertEqual(garden["count"], 1)
        self.assertEqual(pet["count"], 0)
        self.assertTrue(any(child["label"] == GARDEN_CHILD and child["count"] == 1 for child in garden["children"]))

        garden_products = database.list_products(
            page=1,
            page_size=10,
            scope="all",
            category=garden["value"],
        )
        pet_products = database.list_products(
            page=1,
            page_size=10,
            scope="all",
            category=pet["value"],
        )

        self.assertEqual(garden_products["total"], 1)
        self.assertEqual(garden_products["items"][0]["id"], "product-1")
        self.assertEqual(pet_products["total"], 0)


if __name__ == "__main__":
    unittest.main()
