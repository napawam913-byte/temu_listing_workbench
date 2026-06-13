import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core import database


class AdminApiUsageTest(unittest.TestCase):
    def test_admin_api_usage_summary_requires_admin_and_aggregates_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                database.create_user("member", "secret123")
                database.record_api_usage(
                    provider="openai-compatible",
                    api_type="chat",
                    stage="title",
                    model="gpt-5.5",
                    call_count=3,
                )
                database.record_api_usage(
                    provider="openai-compatible",
                    api_type="image",
                    stage="visual-image",
                    model="gpt-image-2",
                    call_count=1,
                    status="failed",
                )

                from app.main import create_app

                admin_client = TestClient(create_app())
                self.assertEqual(admin_client.get("/api/admin/api-usage").status_code, 401)

                admin_login = admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(admin_login.status_code, 200)
                response = admin_client.get("/api/admin/api-usage")
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual(body["totalCalls"], 4)
                self.assertEqual(body["exactCalls"], 4)
                self.assertEqual(body["inferredCalls"], 0)
                rows_by_model = {item["model"]: item for item in body["items"]}
                self.assertEqual(rows_by_model["gpt-5.5"]["callCount"], 3)
                self.assertEqual(rows_by_model["gpt-5.5"]["successCount"], 3)
                self.assertEqual(rows_by_model["gpt-image-2"]["failedCount"], 1)

                member_client = TestClient(create_app())
                member_login = member_client.post("/api/auth/login", json={"username": "member", "password": "secret123"})
                self.assertEqual(member_login.status_code, 200)
                self.assertEqual(member_client.get("/api/admin/api-usage").status_code, 403)
            finally:
                database.DATABASE_PATH = original_path

    def test_admin_api_channel_can_be_applied_to_stage_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()

                from app.main import create_app

                admin_client = TestClient(create_app())
                admin_login = admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(admin_login.status_code, 200)

                response = admin_client.get("/api/admin/api-channels")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["channels"])
                self.assertTrue(response.json()["routes"])

                update_response = admin_client.put(
                    "/api/admin/api-channels",
                    json={
                        "items": [
                            {
                                "id": "custom_a",
                                "name": "备用渠道 A",
                                "enabled": True,
                                "apiKey": "sk-custom-a",
                                "baseUrl": "https://backup.example.com/v1",
                                "textModel": "backup-chat",
                                "imageModel": "backup-image",
                            }
                        ]
                    },
                )
                self.assertEqual(update_response.status_code, 200)

                apply_response = admin_client.post(
                    "/api/admin/api-channels/apply",
                    json={"stage": "title_split", "channelId": "custom_a", "model": "backup-chat-fast"},
                )
                self.assertEqual(apply_response.status_code, 200)

                self.assertEqual(database.get_app_setting_value("OPENAI_TITLE_SPLIT_API_KEY"), "sk-custom-a")
                self.assertEqual(
                    database.get_app_setting_value("OPENAI_TITLE_SPLIT_BASE_URL"),
                    "https://backup.example.com/v1",
                )
                self.assertEqual(database.get_app_setting_value("OPENAI_TITLE_SPLIT_MODEL"), "backup-chat-fast")

                routes_by_stage = {item["stage"]: item for item in apply_response.json()["routes"]}
                self.assertEqual(routes_by_stage["title_split"]["channelId"], "custom_a")
                self.assertEqual(routes_by_stage["title_split"]["model"], "backup-chat-fast")

                apply_all_response = admin_client.post(
                    "/api/admin/api-channels/apply-all",
                    json={"channelId": "custom_a", "textModel": "relay-text", "imageModel": "relay-image"},
                )
                self.assertEqual(apply_all_response.status_code, 200)
                self.assertEqual(database.get_app_setting_value("OPENAI_TITLE_MODEL"), "relay-text")
                self.assertEqual(database.get_app_setting_value("OPENAI_RECOMMENDATION_MODEL"), "relay-text")
                self.assertEqual(database.get_app_setting_value("OPENAI_IMAGE_MODEL"), "relay-image")
                self.assertEqual(database.get_app_setting_value("OPENAI_IMAGE_BASE_URL"), "https://backup.example.com/v1")
            finally:
                database.DATABASE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
