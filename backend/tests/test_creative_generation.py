import os
import tempfile
import unittest
from pathlib import Path

os.environ["ALIYUN_OSS_ENABLED"] = "0"
os.environ["OPENAI_API_KEY"] = ""

from app.core import database
from app.modules.creative_generation.chatgpt_listing import IMAGE_COUNT, generate_listing_package
from app.modules.creative_generation import plugin_jobs
from app.modules.creative_generation.safety import find_sensitive_terms, sanitize_marketplace_text


class CreativeGenerationTest(unittest.TestCase):
    def test_sensitive_terms_are_removed_from_title(self):
        sanitized, terms = sanitize_marketplace_text("Official Best Medical Disney Keychain 100%")

        self.assertIn("official", [term.lower() for term in terms])
        self.assertIn("disney", [term.lower() for term in terms])
        self.assertNotIn("Official", sanitized)
        self.assertNotIn("Disney", sanitized)
        self.assertNotIn("100%", sanitized)

    def test_sensitive_terms_are_seeded_into_database(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                terms = database.list_sensitive_terms(enabled=True)
            finally:
                database.DATABASE_PATH = original_path

        categories = {term["category"] for term in terms}

        self.assertIn("brand_ip", categories)
        self.assertIn("medical_claim", categories)
        self.assertTrue(any(term["term"].lower() == "disney" for term in terms))

    def test_plugin_jobs_create_complete_and_sync_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            original_upload = plugin_jobs.upload_image_bytes
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            plugin_jobs.upload_image_bytes = lambda image_bytes, content_type, key_hint: {
                "url": f"https://oss.example/{key_hint}.png",
                "storageKey": f"{key_hint}.png",
            }
            try:
                record = {
                    "id": "record-plugin-1",
                    "productId": "p1",
                    "productTitle": "Custom Keychain",
                    "mainImage": {"sourceUrl": "https://example.com/source.png"},
                    "sourceLinks": [{"title": "1688 source", "productUrl": "https://detail.1688.com/offer/1.html"}],
                    "skuEntries": [{"id": "sku-1", "name": "Black", "componentSkus": []}],
                }

                jobs = plugin_jobs.create_plugin_jobs([record])
                self.assertEqual(len(jobs), IMAGE_COUNT + 1)
                self.assertEqual(jobs[0]["status"], "queued")

                for _ in range(len(jobs)):
                    job = plugin_jobs.claim_next_plugin_job()
                    self.assertIsNotNone(job)
                    plugin_jobs.complete_plugin_job(
                        job["id"],
                        image_data_url="data:image/png;base64,iVBORw0KGgo=",
                    )

                sync = plugin_jobs.sync_records_with_plugin_jobs([record])
            finally:
                plugin_jobs.upload_image_bytes = original_upload
                database.DATABASE_PATH = original_path

        updated = sync["records"][0]
        self.assertIn("record-plugin-1", sync["completedRecordIds"])
        self.assertEqual(len(updated["productMaterialImages"]), IMAGE_COUNT)
        self.assertTrue(updated["mainImage"]["editedCloudUrl"].startswith("https://oss.example/"))
        self.assertTrue(updated["skuEntries"][0]["imageAsset"]["editedCloudUrl"].startswith("https://oss.example/"))

    def test_plan_mode_returns_eight_temu_style_images(self):
        result = generate_listing_package(
            {
                "id": "record-1",
                "productId": "p1",
                "productTitle": "官方最强医用钥匙扣",
                "sourceLinks": [{"title": "1688 source", "productUrl": "https://detail.1688.com/offer/1.html"}],
                "skuEntries": [{"id": "sku-1", "name": "黑色", "componentSkus": []}],
            },
            generate_images=False,
        )

        self.assertEqual(result["status"], "planned")
        self.assertEqual(len(result["imagePlan"]), IMAGE_COUNT)
        self.assertIn("products/p1/main/01-hero-main", result["imagePlan"][0]["key"])
        self.assertEqual(find_sensitive_terms(result["safeTitleEn"]), [])
        self.assertTrue(result["record"]["styleProfile"]["prompt"])


if __name__ == "__main__":
    unittest.main()
