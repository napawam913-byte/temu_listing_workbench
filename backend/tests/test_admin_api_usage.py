import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core import database


class AdminApiUsageTest(unittest.TestCase):
    def test_chufan_image_model_alias_uses_documented_generation_model(self):
        from app.modules.visual_generation.service import (
            is_chufan_ai_image_target,
            normalize_image_model_for_channel,
        )

        chufan_settings = {"channel_id": "chufan_ai", "base_url": "https://api.aicoming.top/v1"}
        external_settings = {"channel_id": "external", "base_url": "https://external.example.com/v1"}

        self.assertEqual(normalize_image_model_for_channel(chufan_settings, "gpt-image-2"), "gpt-image-2-1k")
        self.assertTrue(is_chufan_ai_image_target(chufan_settings, "gpt-image-2-1k"))
        self.assertFalse(is_chufan_ai_image_target(external_settings, "gpt-image-2"))

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
                channels_by_id = {item["id"]: item for item in response.json()["channels"]}
                self.assertEqual(set(channels_by_id), {"chufan_ai"})
                self.assertEqual(channels_by_id["chufan_ai"]["name"], "初凡AI")
                self.assertEqual(channels_by_id["chufan_ai"]["baseUrl"], "https://api.aicoming.top/v1")
                self.assertEqual(channels_by_id["chufan_ai"]["textModel"], "gpt-5.5")
                self.assertEqual(channels_by_id["chufan_ai"]["imageModel"], "gpt-image-2-1k")

                update_response = admin_client.put(
                    "/api/admin/api-channels",
                    json={
                        "items": [
                            {
                                "id": "chufan_ai",
                                "name": "初凡AI",
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
                    json={"stage": "title_split", "channelId": "chufan_ai", "model": "backup-chat-fast"},
                )
                self.assertEqual(apply_response.status_code, 200)

                self.assertEqual(database.get_app_setting_value("OPENAI_TITLE_SPLIT_API_KEY"), "sk-custom-a")
                self.assertEqual(
                    database.get_app_setting_value("OPENAI_TITLE_SPLIT_BASE_URL"),
                    "https://backup.example.com/v1",
                )
                self.assertEqual(database.get_app_setting_value("OPENAI_TITLE_SPLIT_MODEL"), "")

                routes_by_stage = {item["stage"]: item for item in apply_response.json()["routes"]}
                self.assertEqual(routes_by_stage["title_split"]["channelId"], "chufan_ai")
                self.assertNotEqual(routes_by_stage["title_split"]["model"], "backup-chat-fast")

                apply_all_response = admin_client.post(
                    "/api/admin/api-channels/apply-all",
                    json={"channelId": "chufan_ai", "textModel": "relay-text", "imageModel": "relay-image"},
                )
                self.assertEqual(apply_all_response.status_code, 200)
                self.assertEqual(database.get_app_setting_value("OPENAI_TITLE_MODEL"), "")
                self.assertEqual(database.get_app_setting_value("OPENAI_RECOMMENDATION_MODEL"), "")
                self.assertEqual(database.get_app_setting_value("OPENAI_IMAGE_MODEL"), "")
                self.assertEqual(database.get_app_setting_value("OPENAI_IMAGE_BASE_URL"), "https://backup.example.com/v1")
            finally:
                database.DATABASE_PATH = original_path

    def test_admin_prompt_configs_are_admin_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                database.create_user("prompt-member", "secret123")

                from app.main import create_app

                anonymous_client = TestClient(create_app())
                self.assertEqual(anonymous_client.get("/api/admin/prompt-configs").status_code, 401)

                member_client = TestClient(create_app())
                member_login = member_client.post(
                    "/api/auth/login",
                    json={"username": "prompt-member", "password": "secret123"},
                )
                self.assertEqual(member_login.status_code, 200)
                self.assertEqual(member_client.get("/api/admin/prompt-configs").status_code, 403)

                admin_client = TestClient(create_app())
                admin_login = admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(admin_login.status_code, 200)
                response = admin_client.get("/api/admin/prompt-configs")
                self.assertEqual(response.status_code, 200)
                items = response.json()["items"]
                ids = {item["id"] for item in items}
                self.assertEqual(
                    ids,
                    {
                        "title",
                        "title_split",
                        "recommendation",
                        "product_attribute",
                        "visual_analysis",
                        "visual_prompt",
                        "visual_image",
                    },
                )
                visual_prompt = next(item for item in items if item["id"] == "visual_prompt")
                self.assertEqual(visual_prompt["modelKey"], "OPENAI_VISUAL_PROMPT_MODEL")
                self.assertIn("Return JSON only", visual_prompt["content"])
            finally:
                database.DATABASE_PATH = original_path

    def test_runtime_api_channel_uses_stage_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                member = database.create_user("member-model", "secret123")
                database.upsert_user_api_credential(
                    user_id=member["id"],
                    channel_id="chufan_ai",
                    api_key="sk-member-channel",
                    base_url="https://member-channel.example.com/v1",
                    text_model="member-text-should-not-win",
                    image_model="member-image-should-not-win",
                    enabled=True,
                )
                database.upsert_app_setting(key="OPENAI_TITLE_MODEL", value="stage-title-model", category="ai")
                database.upsert_app_setting(key="OPENAI_RECOMMENDATION_MODEL", value="stage-rec-model", category="ai")
                database.upsert_app_setting(key="OPENAI_VISUAL_ANALYSIS_MODEL", value="stage-vision-model", category="ai")
                database.upsert_app_setting(key="OPENAI_IMAGE_MODEL", value="stage-image-model", category="ai")

                from app.modules.creative_generation.chatgpt_listing import get_openai_settings
                from app.modules.creative_generation.listing_title_optimizer import get_title_optimizer_settings
                from app.modules.visual_generation.clients import get_ai_stage_settings

                title_settings = get_title_optimizer_settings(user_id=member["id"])
                self.assertEqual(title_settings.api_key, "sk-member-channel")
                self.assertEqual(title_settings.base_url, "https://member-channel.example.com/v1")
                self.assertEqual(title_settings.text_model, "stage-title-model")
                self.assertEqual(title_settings.channel_id, "chufan_ai")

                recommendation_settings = get_openai_settings("recommendation", user_id=member["id"])
                self.assertEqual(recommendation_settings.api_key, "sk-member-channel")
                self.assertEqual(recommendation_settings.text_model, "stage-rec-model")
                self.assertEqual(recommendation_settings.channel_id, "chufan_ai")

                visual_settings = get_ai_stage_settings("visual_analysis", user_id=member["id"])
                self.assertEqual(visual_settings["api_key"], "sk-member-channel")
                self.assertEqual(visual_settings["model"], "stage-vision-model")
                self.assertEqual(visual_settings["channel_id"], "chufan_ai")

                image_settings = get_ai_stage_settings("image", user_id=member["id"])
                self.assertEqual(image_settings["api_key"], "sk-member-channel")
                self.assertEqual(image_settings["model"], "stage-image-model")
                self.assertEqual(image_settings["channel_id"], "chufan_ai")

                database.upsert_app_setting(key="AI_CHANNEL_CHUFAN_AI_ENABLED", value="1", category="ai_channel")
                database.upsert_app_setting(key="AI_CHANNEL_CHUFAN_AI_API_KEY", value="sk-admin-channel", category="ai_channel")
                database.upsert_app_setting(
                    key="AI_CHANNEL_CHUFAN_AI_BASE_URL",
                    value="https://admin-channel.example.com/v1",
                    category="ai_channel",
                )
                admin_channel_settings = get_openai_settings("recommendation")
                self.assertEqual(admin_channel_settings.api_key, "sk-admin-channel")
                self.assertEqual(admin_channel_settings.base_url, "https://admin-channel.example.com/v1")
                self.assertEqual(admin_channel_settings.text_model, "stage-rec-model")
                self.assertEqual(admin_channel_settings.channel_id, "chufan_ai")
            finally:
                database.DATABASE_PATH = original_path

    def test_admin_can_assign_member_api_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                member = database.create_user("member2", "secret123")

                from app.main import create_app

                member_client = TestClient(create_app())
                member_login = member_client.post("/api/auth/login", json={"username": "member2", "password": "secret123"})
                self.assertEqual(member_login.status_code, 200)
                self.assertEqual(member_client.get(f"/api/admin/users/{member['id']}/api-credentials").status_code, 403)

                admin_client = TestClient(create_app())
                admin_login = admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(admin_login.status_code, 200)

                initial_response = admin_client.get(f"/api/admin/users/{member['id']}/api-credentials")
                self.assertEqual(initial_response.status_code, 200)
                initial_items = {item["channelId"]: item for item in initial_response.json()["items"]}
                self.assertEqual(set(initial_items), {"chufan_ai"})
                self.assertFalse(initial_items["chufan_ai"]["apiKeyConfigured"])

                update_response = admin_client.put(
                    f"/api/admin/users/{member['id']}/api-credentials",
                    json={
                        "items": [
                            {
                                "channelId": "chufan_ai",
                                "enabled": True,
                                "apiKey": "sk-member-chufan",
                                "baseUrl": "https://api.aicoming.top/v1",
                                "textModel": "gpt-5.5",
                                "imageModel": "gpt-image-2-1k",
                            }
                        ]
                    },
                )
                self.assertEqual(update_response.status_code, 200)
                updated_items = {item["channelId"]: item for item in update_response.json()["items"]}
                self.assertTrue(updated_items["chufan_ai"]["enabled"])
                self.assertTrue(updated_items["chufan_ai"]["apiKeyConfigured"])

                runtime_credential = database.get_enabled_user_api_credential(member["id"])
                self.assertIsNotNone(runtime_credential)
                self.assertEqual(runtime_credential["channelId"], "chufan_ai")
                self.assertEqual(runtime_credential["apiKey"], "sk-member-chufan")
                self.assertEqual(runtime_credential["baseUrl"], "https://api.aicoming.top/v1")
                self.assertEqual(runtime_credential["textModel"], "gpt-5.5")

                with database.get_connection() as conn:
                    row = conn.execute(
                        """
                        SELECT *
                        FROM user_api_settings
                        WHERE user_id = ? AND channel_id = ?
                        """,
                        (member["id"], "chufan_ai"),
                    ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["api_key"], "sk-member-chufan")
            finally:
                database.DATABASE_PATH = original_path

    def test_member_channel_without_key_is_not_displayed_as_runtime_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                member = database.create_user("member-no-key", "secret123")
                database.upsert_app_setting(key="AI_CHANNEL_CHUFAN_AI_ENABLED", value="1", category="ai_channel")
                database.upsert_app_setting(key="AI_CHANNEL_CHUFAN_AI_API_KEY", value="sk-admin-chufan", category="ai_channel")
                database.upsert_app_setting(
                    key="AI_CHANNEL_CHUFAN_AI_BASE_URL",
                    value="https://api.aicoming.top/v1",
                    category="ai_channel",
                )
                database.upsert_app_setting(key="OPENAI_IMAGE_API_KEY", value="sk-old-stage", category="ai")
                database.upsert_app_setting(
                    key="OPENAI_IMAGE_BASE_URL",
                    value="https://legacy-stage.example.com/v1",
                    category="ai",
                )
                database.upsert_user_api_credential(
                    user_id=member["id"],
                    channel_id="chufan_ai",
                    enabled=True,
                    base_url="https://station-88.aicoming.top/v1",
                    text_model="deepseek-v4-pro",
                    image_model="gpt-image-2",
                )

                self.assertIsNone(database.get_enabled_user_api_credential(member["id"]))

                from app.api.routes_admin import serialize_user_api_credentials

                items = {item["channelId"]: item for item in serialize_user_api_credentials(member["id"])}
                self.assertFalse(items["chufan_ai"]["enabled"])
                self.assertFalse(items["chufan_ai"]["apiKeyConfigured"])
                self.assertEqual(items["chufan_ai"]["baseUrl"], "https://api.aicoming.top/v1")
                self.assertEqual(items["chufan_ai"]["textModel"], "gpt-5.5")
                self.assertEqual(items["chufan_ai"]["imageModel"], "gpt-image-2-1k")

                from app.api.routes_admin import serialize_api_channel_bundle

                routes = {item["stage"]: item for item in serialize_api_channel_bundle()["routes"]}
                self.assertEqual(routes["image"]["channelId"], "chufan_ai")
                self.assertEqual(routes["image"]["baseUrl"], "https://api.aicoming.top/v1")
            finally:
                database.DATABASE_PATH = original_path

    def test_member_cannot_save_own_user_api_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                member = database.create_user("member-self", "secret123")

                from app.main import create_app

                client = TestClient(create_app())
                login = client.post("/api/auth/login", json={"username": "member-self", "password": "secret123"})
                self.assertEqual(login.status_code, 200)

                initial_response = client.get("/api/user/api-settings")
                self.assertEqual(initial_response.status_code, 404)

                update_response = client.put(
                    "/api/user/api-settings",
                    json={
                        "items": [
                            {
                                "channelId": "chufan_ai",
                                "enabled": True,
                                "apiKey": "sk-self-chufan",
                                "baseUrl": "https://api.aicoming.top/v1",
                                "textModel": "gpt-5.5",
                                "imageModel": "gpt-image-2-1k",
                            }
                        ]
                    },
                )
                self.assertEqual(update_response.status_code, 404)
                self.assertIsNone(database.get_enabled_user_api_credential(member["id"]))

                with database.get_connection() as conn:
                    row = conn.execute(
                        "SELECT channel_id, enabled FROM user_api_settings WHERE user_id = ?",
                        (member["id"],),
                    ).fetchone()
                self.assertIsNone(row)
            finally:
                database.DATABASE_PATH = original_path

    def test_api_usage_summary_groups_by_team_user_and_channel(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                lead = database.create_managed_user(
                    username="lead-admin",
                    password="secret123",
                    display_name="Lead Admin",
                    role="admin",
                )
                member = database.create_managed_user(
                    username="team-member",
                    password="secret123",
                    display_name="Team Member",
                    manager_user_id=lead["id"],
                )
                database.record_api_usage(
                    provider="openai-compatible",
                    api_type="chat",
                    stage="title",
                    model="gpt-5.5",
                    user_id=member["id"],
                    channel_id="chufan_ai",
                    call_count=2,
                )
                database.record_api_usage(
                    provider="openai-compatible",
                    api_type="image",
                    stage="image",
                    model="gpt-image-2",
                    user_id=lead["id"],
                    channel_id="legacy_channel",
                    status="failed",
                    call_count=1,
                )

                from app.main import create_app

                client = TestClient(create_app())
                login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(login.status_code, 200)
                limit_response = client.put(
                    f"/api/admin/users/{member['id']}/usage-limit",
                    json={"monthlyApiCallLimit": 3},
                )
                self.assertEqual(limit_response.status_code, 200)
                self.assertEqual(limit_response.json()["limit"]["monthlyApiCallLimit"], 3)
                self.assertEqual(limit_response.json()["limit"]["monthlyCallCount"], 2)

                response = client.get("/api/admin/api-usage")
                self.assertEqual(response.status_code, 200)
                body = response.json()

                team_rows = {item["adminUserId"]: item for item in body["byTeam"]}
                self.assertIn(lead["id"], team_rows)
                self.assertEqual(team_rows[lead["id"]]["callCount"], 3)
                self.assertEqual(team_rows[lead["id"]]["userCount"], 2)

                user_rows = {item["userId"]: item for item in body["byUser"]}
                self.assertEqual(user_rows[member["id"]]["callCount"], 2)
                self.assertEqual(user_rows[member["id"]]["managerId"], lead["id"])
                self.assertEqual(user_rows[member["id"]]["monthlyCallCount"], 2)
                self.assertEqual(user_rows[member["id"]]["monthlyApiCallLimit"], 3)
                self.assertEqual(user_rows[member["id"]]["monthlyRemainingCalls"], 1)
                self.assertEqual(user_rows[member["id"]]["usageStatus"], "ok")
                database.assert_user_api_usage_allowed(member["id"])
                with self.assertRaises(ValueError):
                    database.assert_user_api_usage_allowed(member["id"], requested_calls=2)

                channel_rows = {item["channelId"]: item for item in body["byChannel"]}
                self.assertEqual(channel_rows["chufan_ai"]["callCount"], 2)
                self.assertEqual(channel_rows["legacy_channel"]["failedCount"], 1)
            finally:
                database.DATABASE_PATH = original_path

    def test_visual_generation_concurrency_limits_user_and_team(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                member_a = database.create_managed_user(
                    username="visual-a",
                    password="secret123",
                    manager_user_id=database.DEFAULT_USER_ID,
                )
                member_b = database.create_managed_user(
                    username="visual-b",
                    password="secret123",
                    manager_user_id=database.DEFAULT_USER_ID,
                )
                database.upsert_app_setting(key="VISUAL_USER_CONCURRENCY_LIMIT", value="1", category="visual")
                database.upsert_app_setting(key="VISUAL_TEAM_CONCURRENCY_LIMIT", value="10", category="visual")

                from app.modules.visual_generation.service import (
                    TASK_STATUS_QUEUED,
                    TASK_STATUS_RUNNING,
                    VisualTaskError,
                    assert_visual_concurrency_available,
                    create_visual_task,
                    ensure_visual_generation_schema,
                    get_visual_task_status_summary,
                )

                task = create_visual_task(user_id=member_a["id"], record={"id": "record-a", "productTitle": "A"})
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    conn.execute(
                        "UPDATE visual_generation_tasks SET status = ? WHERE id = ?",
                        (TASK_STATUS_QUEUED, task["id"]),
                    )

                assert_visual_concurrency_available(member_a["id"])
                summary = get_visual_task_status_summary(user_id=member_a["id"])
                self.assertEqual(summary["queuedCount"], 1)
                self.assertEqual(summary["runningCount"], 0)

                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    conn.execute(
                        "UPDATE visual_generation_tasks SET status = ? WHERE id = ?",
                        (TASK_STATUS_RUNNING, task["id"]),
                    )

                with self.assertRaises(VisualTaskError):
                    assert_visual_concurrency_available(member_a["id"])
                assert_visual_concurrency_available(member_a["id"], exclude_task_id=task["id"])

                database.upsert_app_setting(key="VISUAL_USER_CONCURRENCY_LIMIT", value="10", category="visual")
                database.upsert_app_setting(key="VISUAL_TEAM_CONCURRENCY_LIMIT", value="1", category="visual")
                with self.assertRaises(VisualTaskError):
                    assert_visual_concurrency_available(member_b["id"])
            finally:
                database.DATABASE_PATH = original_path

    def test_visual_run_queues_when_member_concurrency_is_full(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_path = database.DATABASE_PATH
            database.DATABASE_PATH = Path(tmpdir) / "app.db"
            try:
                database.init_db()
                database.upsert_app_setting(key="VISUAL_USER_CONCURRENCY_LIMIT", value="1", category="visual")
                database.upsert_app_setting(key="VISUAL_TEAM_CONCURRENCY_LIMIT", value="10", category="visual")

                from app.main import create_app
                from app.modules.visual_generation.service import (
                    TASK_STATUS_RUNNING,
                    create_visual_task,
                    ensure_visual_generation_schema,
                    get_visual_task,
                )

                client = TestClient(create_app())
                login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
                self.assertEqual(login.status_code, 200)

                running = create_visual_task(
                    user_id=database.DEFAULT_USER_ID,
                    record={"id": "running-record", "productTitle": "Running"},
                    source_image_ref="https://example.test/running.png",
                )
                queued = create_visual_task(
                    user_id=database.DEFAULT_USER_ID,
                    record={"id": "queued-record", "productTitle": "Queued"},
                    source_image_ref="https://example.test/queued.png",
                )
                with database.get_connection() as conn:
                    ensure_visual_generation_schema(conn)
                    conn.execute(
                        "UPDATE visual_generation_tasks SET status = ? WHERE id = ?",
                        (TASK_STATUS_RUNNING, running["id"]),
                    )

                with patch("app.api.routes_visual_generation.run_visual_job") as run_job:
                    response = client.post(
                        f"/api/visual/tasks/{queued['id']}/run",
                        json={"sourceImageRef": "https://example.test/queued.png"},
                    )

                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertTrue(body["queued"])
                self.assertTrue(body["waitingForConcurrency"])
                self.assertIn("等待队列", body["message"])
                self.assertEqual(body["item"]["status"], "queued")
                run_job.assert_called_once()
                self.assertEqual(
                    get_visual_task(task_id=queued["id"], user_id=database.DEFAULT_USER_ID)["status"],
                    "queued",
                )
            finally:
                database.DATABASE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
