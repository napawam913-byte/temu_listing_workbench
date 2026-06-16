import json
import tempfile
import unittest
from pathlib import Path

from app.core import database


class TemuMaterialProductSkuTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_path = database.DATABASE_PATH
        self.original_uploads_dir = database.UPLOADS_DIR
        database.DATABASE_PATH = Path(self.tmpdir.name) / "app.db"
        database.UPLOADS_DIR = Path(self.tmpdir.name) / "uploads"
        database.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        database.init_db()
        user = database.create_user(username="buyer", password="secret123", display_name="Buyer")
        self.user_id = user["id"]

    def tearDown(self):
        database.DATABASE_PATH = self.original_path
        database.UPLOADS_DIR = self.original_uploads_dir
        self.tmpdir.cleanup()

    def test_temu_material_added_to_product_list_keeps_sku_for_selection(self):
        material = database.create_sourcing_material_1688(
            {
                "product_url": "https://www.temu.com/sample-product-g-605654827796853.html?goods_id=1",
                "title": "Temu tote bag",
                "main_image_url": "https://img.example.com/main.jpg",
                "price": 24.07,
                "shop_name": "Vela Gifts",
                "sku_list": [
                    {
                        "sku_id": "1 set (5 bags)",
                        "specs": {"颜色": "1 set (5 bags)"},
                        "price": 24.07,
                        "image_url": "https://img.example.com/sku.jpg",
                    }
                ],
                "raw_data": {
                    "source_site": "temu",
                    "goods_id": "1",
                    "gallery_image_urls": ["https://img.example.com/main.jpg"],
                },
            }
        )

        product = database.create_product_from_sourcing_material_1688(
            material["id"],
            add_to_pool_user_id=self.user_id,
        )
        candidates = database.list_sourcing_candidates_1688(product["id"])
        material_after = database.get_sourcing_material_1688(material["id"])

        self.assertEqual(product["id"], "temu-605654827796853")
        self.assertEqual(material_after["product_list_product_id"], product["id"])
        self.assertIsNone(material_after["assigned_product_id"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["temu_product_id"], product["id"])
        self.assertEqual(candidates[0]["sku_list"][0]["specs"], {"颜色": "1 set (5 bags)"})

        with database.get_connection() as conn:
            raw_data = json.loads(conn.execute("SELECT raw_data_json FROM products WHERE id = ?", (product["id"],)).fetchone()[0])
        self.assertEqual(raw_data["sku_count"], 1)
        self.assertEqual(raw_data["sku_list"][0]["sku_id"], "1 set (5 bags)")

    def test_temu_generic_dom_skus_are_replaced_by_selected_quantity_spec(self):
        material = database.create_sourcing_material_1688(
            {
                "product_url": "https://www.temu.com/wood-dice-g-601100047897009.html",
                "title": "1 Pack Wood Dice",
                "main_image_url": "https://img.example.com/main.jpg",
                "price": 23.38,
                "price_range": "$23.38",
                "shop_name": "B IVW",
                "sku_list": [
                    {"sku_id": "temu-sku-1", "specs": {"\u89c4\u683c": "SKU 1"}},
                    {"sku_id": "temu-sku-2", "specs": {"\u89c4\u683c": "SKU 2"}},
                ],
                "raw_data": {
                    "source_site": "temu",
                    "selected_options": {"quantity": "1 Pack Qty 1 70K+ sold"},
                    "gallery_image_urls": ["https://img.example.com/main.jpg"],
                    "price": {"current": "$23.38"},
                },
            }
        )

        self.assertEqual(
            material["sku_list"],
            [
                {
                    "sku_id": "1 Pack",
                    "specs": {"\u89c4\u683c": "1 Pack"},
                    "price": 23.38,
                    "image_url": "https://img.example.com/main.jpg",
                }
            ],
        )

        product = database.create_product_from_sourcing_material_1688(
            material["id"],
            add_to_pool_user_id=self.user_id,
        )
        candidates = database.list_sourcing_candidates_1688(product["id"])

        self.assertEqual(candidates[0]["sku_list"][0]["sku_id"], "1 Pack")
        self.assertEqual(candidates[0]["sku_list"][0]["specs"], {"\u89c4\u683c": "1 Pack"})


if __name__ == "__main__":
    unittest.main()
