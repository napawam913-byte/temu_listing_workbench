import tempfile
import unittest
from pathlib import Path

from app.core import database
from app.modules.sourcing_1688.link_importer import import_1688_links


class ProductCatalogScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        database.DATABASE_PATH = Path(self.tmpdir.name) / "app.db"
        database.init_db()
        user = database.create_user(username="buyer", password="secret123", display_name="Buyer")
        self.user_id = user["id"]

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        self.tmpdir.cleanup()

    def test_pool_only_import_is_hidden_from_data_desk_but_visible_in_pool(self):
        self.insert_batch("batch-pool")
        database.replace_products(
            "batch-pool",
            [self.product_payload("pool-product", "POOL-1")],
            add_to_pool_user_id=self.user_id,
            catalog_scope=database.PRODUCT_CATALOG_SCOPE_POOL_ONLY,
        )

        data_desk = database.list_products(page=1, page_size=20, scope="all", user_id=self.user_id)
        pool = database.list_products(page=1, page_size=20, scope="pool", user_id=self.user_id)

        self.assertEqual(data_desk["total"], 0)
        self.assertEqual(pool["total"], 1)
        self.assertEqual(pool["items"][0]["catalog_scope"], database.PRODUCT_CATALOG_SCOPE_POOL_ONLY)

    def test_admin_catalog_product_can_be_added_to_pool_without_leaving_data_desk(self):
        self.insert_batch("batch-admin")
        database.replace_products(
            "batch-admin",
            [self.product_payload("admin-product", "ADMIN-1")],
            add_to_pool_user_id=None,
            catalog_scope=database.PRODUCT_CATALOG_SCOPE_ADMIN,
        )

        data_desk_before = database.list_products(page=1, page_size=20, scope="all", user_id=self.user_id)
        pool_before = database.list_products(page=1, page_size=20, scope="pool", user_id=self.user_id)

        self.assertEqual(data_desk_before["total"], 1)
        self.assertEqual(pool_before["total"], 0)

        added_count = database.add_products_to_pool(["admin-product"], user_id=self.user_id)
        pool_after = database.list_products(page=1, page_size=20, scope="pool", user_id=self.user_id)

        self.assertEqual(added_count, 1)
        self.assertEqual(pool_after["total"], 1)
        self.assertEqual(pool_after["items"][0]["catalog_scope"], database.PRODUCT_CATALOG_SCOPE_ADMIN)

    def test_pool_import_does_not_downgrade_existing_admin_catalog_product(self):
        self.insert_batch("batch-admin")
        database.replace_products(
            "batch-admin",
            [self.product_payload("admin-product", "SAME-1", title="Admin Product")],
            add_to_pool_user_id=None,
            catalog_scope=database.PRODUCT_CATALOG_SCOPE_ADMIN,
        )

        self.insert_batch("batch-pool")
        database.replace_products(
            "batch-pool",
            [self.product_payload("pool-copy", "SAME-1", title="Pool Copy")],
            add_to_pool_user_id=self.user_id,
            catalog_scope=database.PRODUCT_CATALOG_SCOPE_POOL_ONLY,
        )

        data_desk = database.list_products(page=1, page_size=20, scope="all", user_id=self.user_id)
        pool = database.list_products(page=1, page_size=20, scope="pool", user_id=self.user_id)

        self.assertEqual(data_desk["total"], 1)
        self.assertEqual(pool["total"], 1)
        self.assertEqual(data_desk["items"][0]["id"], "admin-product")
        self.assertEqual(pool["items"][0]["id"], "admin-product")
        self.assertEqual(data_desk["items"][0]["title"], "Admin Product")
        self.assertEqual(pool["items"][0]["title"], "Admin Product")
        self.assertEqual(data_desk["items"][0]["catalog_scope"], database.PRODUCT_CATALOG_SCOPE_ADMIN)
        self.assertEqual(pool["items"][0]["catalog_scope"], database.PRODUCT_CATALOG_SCOPE_ADMIN)

    def test_1688_upload_import_goes_to_pool_only(self):
        result = import_1688_links(
            ["https://detail.1688.com/offer/987654321.html"],
            fetch_page=lambda _url: """
                <html>
                  <head>
                    <title>Factory Outdoor Sleeping Bag - 阿里巴巴</title>
                    <meta property="og:image" content="https://img.example.com/1688.jpg" />
                  </head>
                </html>
            """,
            add_to_pool_user_id=self.user_id,
        )

        self.assertEqual(result["imported_count"], 1)
        data_desk = database.list_products(page=1, page_size=20, scope="all", user_id=self.user_id)
        pool = database.list_products(page=1, page_size=20, scope="pool", user_id=self.user_id)

        self.assertEqual(data_desk["total"], 0)
        self.assertEqual(pool["total"], 1)
        self.assertEqual(pool["items"][0]["source_type"], "1688")
        self.assertEqual(pool["items"][0]["catalog_scope"], database.PRODUCT_CATALOG_SCOPE_POOL_ONLY)

    def insert_batch(self, batch_id: str):
        database.insert_upload_batch(
            batch_id=batch_id,
            source_filename=f"{batch_id}.json",
            saved_path=Path(self.tmpdir.name) / f"{batch_id}.json",
            file_type="json",
            total_rows=1,
            imported_count=1,
            failed_count=0,
        )

    def product_payload(self, product_id: str, source_product_id: str, *, title: str = "Test Product"):
        return {
            "id": product_id,
            "source_row_index": 1,
            "source_type": "yunqi",
            "source_product_id": source_product_id,
            "title_cn": title,
            "title_en": None,
            "title": title,
            "main_image_url": None,
            "gallery_image_urls": [],
            "video_url": None,
            "source_url": None,
            "category_path": "Sports & Outdoors/Camping & Hiking",
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


if __name__ == "__main__":
    unittest.main()
