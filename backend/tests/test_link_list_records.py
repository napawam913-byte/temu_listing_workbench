import tempfile
import unittest
from pathlib import Path

from app.core import database


class LinkListRecordsTest(unittest.TestCase):
    def test_upsert_list_update_and_delete_link_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()

                record = {
                    "id": "link-record-1",
                    "createdAt": "2026-06-04T10:00:00",
                    "productId": "product-1",
                    "productTitle": "Test Product",
                    "sourceLinks": [
                        {
                            "id": "source-1",
                            "title": "1688 Source",
                            "productUrl": "https://detail.1688.com/offer/1.html",
                        }
                    ],
                    "skuEntries": [
                        {
                            "id": "sku-1",
                            "order": 1,
                            "kind": "single",
                            "name": "Black",
                            "componentSkus": [{"name": "Black", "specText": "Black"}],
                        }
                    ],
                    "componentSkuCount": 1,
                }

                saved = database.upsert_link_list_record(record)
                self.assertEqual(saved["id"], "link-record-1")
                self.assertEqual(saved["productTitle"], "Test Product")

                records = database.list_link_list_records()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["sourceLinks"][0]["productUrl"], "https://detail.1688.com/offer/1.html")

                saved["productTitle"] = "Updated Product"
                saved["skuEntries"].append(
                    {
                        "id": "sku-2",
                        "order": 2,
                        "kind": "single",
                        "name": "White",
                        "componentSkus": [{"name": "White", "specText": "White"}],
                    }
                )
                saved["componentSkuCount"] = 2
                database.upsert_link_list_record(saved)

                updated = database.list_link_list_records()[0]
                self.assertEqual(updated["productTitle"], "Updated Product")
                self.assertEqual(len(updated["skuEntries"]), 2)

                batch_records = database.upsert_link_list_records(
                    [
                        {
                            "id": "link-record-2",
                            "createdAt": "2026-06-04T11:00:00",
                            "productId": "product-2",
                            "productTitle": "Second Product",
                            "sourceLinks": [],
                            "skuEntries": [],
                            "componentSkuCount": 0,
                        }
                    ]
                )
                self.assertEqual(batch_records[0]["id"], "link-record-2")
                self.assertEqual(len(database.list_link_list_records()), 2)

                self.assertTrue(database.soft_delete_link_list_record("link-record-1"))
                self.assertEqual([item["id"] for item in database.list_link_list_records()], ["link-record-2"])
                self.assertEqual(len(database.list_link_list_records(include_deleted=True)), 2)
            finally:
                database.DATABASE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
