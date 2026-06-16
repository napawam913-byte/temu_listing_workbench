import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.core import database
from app.core.config import WORKBENCH_SESSION_COOKIE_NAME


class AuthAndUserIsolationTest(unittest.TestCase):
    def test_product_api_requires_login_and_accepts_session_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                from app.main import create_app

                client = TestClient(create_app())

                unauthenticated = client.get("/api/products")
                self.assertEqual(unauthenticated.status_code, 401)

                login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(login.status_code, 200)
                self.assertNotIn("token", login.json())
                self.assertIn(WORKBENCH_SESSION_COOKIE_NAME, login.cookies)

                authenticated = client.get("/api/products")
                self.assertEqual(authenticated.status_code, 200)
                self.assertEqual(authenticated.json()["total"], 0)

                logout = client.post("/api/auth/logout")
                self.assertEqual(logout.status_code, 200)
                self.assertEqual(client.get("/api/products").status_code, 401)
            finally:
                database.DATABASE_PATH = original_path

    def test_auth_session_and_user_scoped_product_pool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                user_a = database.create_user("alice", "secret123")
                user_b = database.create_user("bob", "secret123")

                authed = database.authenticate_user("alice", "secret123")
                self.assertEqual(authed["id"], user_a["id"])

                session = database.create_user_session(user_a["id"])
                self.assertEqual(database.get_user_by_session_token(session["token"])["username"], "alice")

                batch_id = "batch-1"
                database.insert_upload_batch(
                    batch_id=batch_id,
                    source_filename="test.xlsx",
                    saved_path=Path(tmpdir) / "test.xlsx",
                    file_type="xlsx",
                    total_rows=1,
                    imported_count=1,
                    failed_count=0,
                )
                database.replace_products(
                    batch_id,
                    [
                        {
                            "id": "product-1",
                            "source_row_index": 1,
                            "source_type": "yunqi",
                            "source_product_id": "source-1",
                            "title_cn": "商品",
                            "title_en": None,
                            "title": "商品",
                            "main_image_url": None,
                            "gallery_image_urls": [],
                            "video_url": None,
                            "source_url": None,
                            "category_path": "配饰",
                            "category_level1": "配饰",
                            "category_level2": None,
                            "tags": [],
                            "price_usd": 1,
                            "gmv_usd": 0,
                            "weekly_sales": 0,
                            "monthly_sales": 0,
                            "review_count": 0,
                            "listing_time": "2026-06-06",
                            "status": "active",
                            "raw_data": {},
                        }
                    ],
                    add_to_pool_user_id=None,
                )

                database.add_products_to_pool(["product-1"], user_id=user_a["id"])
                self.assertEqual(database.list_products(page=1, page_size=10, user_id=user_a["id"])["total"], 1)
                self.assertEqual(database.list_products(page=1, page_size=10, user_id=user_b["id"])["total"], 0)
                self.assertTrue(database.soft_delete_product("product-1", user_id=user_a["id"]))
                self.assertEqual(database.list_products(page=1, page_size=10, user_id=user_a["id"])["total"], 0)
                self.assertEqual(database.list_products(page=1, page_size=10, scope="all", user_id=user_b["id"])["total"], 1)
            finally:
                database.DATABASE_PATH = original_path

    def test_expired_sessions_are_ignored_by_auth_and_user_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            original_ttl = database.WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            database.WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS = 1
            try:
                database.init_db()
                user = database.create_user("carol", "secret123")
                old_session = database.create_user_session(user["id"])
                old_time = "2000-01-01 00:00:00"
                with database.get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE user_sessions
                        SET created_at = ?, updated_at = ?, last_seen_at = ?
                        WHERE token = ?
                        """,
                        (old_time, old_time, old_time, old_session["token"]),
                    )

                self.assertIsNone(database.get_user_by_session_token(old_session["token"]))
                with database.get_connection() as conn:
                    status = conn.execute(
                        "SELECT status FROM user_sessions WHERE token = ?",
                        (old_session["token"],),
                    ).fetchone()["status"]
                self.assertEqual(status, "expired")

                fresh_session = database.create_user_session(user["id"])
                self.assertEqual(database.get_user_by_session_token(fresh_session["token"])["username"], "carol")

                users_by_name = {row["username"]: row for row in database.list_users()}
                self.assertEqual(users_by_name["carol"]["activeSessionCount"], 1)
            finally:
                database.WORKBENCH_SESSION_COOKIE_MAX_AGE_SECONDS = original_ttl
                database.DATABASE_PATH = original_path

    def test_link_records_are_user_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                user_a = database.create_user("alice", "secret123")
                user_b = database.create_user("bob", "secret123")
                record = {
                    "id": "same-record-id",
                    "productId": "product-1",
                    "productTitle": "A Product",
                    "sourceLinks": [],
                    "skuEntries": [],
                    "componentSkuCount": 0,
                }

                database.upsert_link_list_record(record, user_id=user_a["id"])
                database.upsert_link_list_record({**record, "productTitle": "B Product"}, user_id=user_b["id"])

                records_a = database.list_link_list_records(user_id=user_a["id"])
                records_b = database.list_link_list_records(user_id=user_b["id"])
                self.assertEqual(records_a[0]["productTitle"], "A Product")
                self.assertEqual(records_b[0]["productTitle"], "B Product")
            finally:
                database.DATABASE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
