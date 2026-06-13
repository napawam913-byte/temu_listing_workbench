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


if __name__ == "__main__":
    unittest.main()
