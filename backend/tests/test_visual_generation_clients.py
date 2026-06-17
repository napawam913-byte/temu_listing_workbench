import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from PIL import Image

from app.modules.visual_generation.clients import (
    VisualGenerationError,
    get_ai_stage_settings,
    image_file_to_data_url,
    image_file_to_upload,
    request_generated_image,
    request_json,
)


class VisualGenerationClientImageTest(unittest.TestCase):
    def test_member_without_api_key_does_not_inherit_admin_channel_key(self):
        with patch("app.modules.visual_generation.clients.get_enabled_user_api_credential", return_value=None):
            with patch("app.modules.visual_generation.clients.get_user_role", return_value="user"):
                with patch("app.modules.visual_generation.clients.get_runtime_setting", return_value=""):
                    with patch("app.modules.visual_generation.clients.get_enabled_admin_api_channel_credential") as admin_channel:
                        with self.assertRaises(VisualGenerationError):
                            get_ai_stage_settings("visual_analysis", user_id="member-1")

        admin_channel.assert_not_called()

    def test_admin_without_personal_key_can_use_admin_channel_key(self):
        with patch("app.modules.visual_generation.clients.get_enabled_user_api_credential", return_value=None):
            with patch("app.modules.visual_generation.clients.get_user_role", return_value="admin"):
                with patch("app.modules.visual_generation.clients.get_runtime_setting", return_value=""):
                    with patch(
                        "app.modules.visual_generation.clients.get_enabled_admin_api_channel_credential",
                        return_value={
                            "channelId": "chufan_ai",
                            "apiKey": "admin-key",
                            "baseUrl": "https://api.example.test/v1",
                            "textModel": "channel-chat",
                            "imageModel": "channel-image",
                        },
                    ):
                        settings = get_ai_stage_settings("visual_analysis", user_id="admin-1")

        self.assertEqual(settings["api_key"], "admin-key")
        self.assertEqual(settings["base_url"], "https://api.example.test/v1")

    def test_image_file_to_data_url_normalizes_to_supported_jpeg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "reference.png"
            Image.new("RGBA", (16, 16), (255, 0, 0, 128)).save(image_path)

            data_url = image_file_to_data_url(image_path)

            self.assertTrue(data_url.startswith("data:image/jpeg;base64,"))
            payload = data_url.split(",", 1)[1]
            self.assertTrue(base64.b64decode(payload).startswith(b"\xff\xd8"))

    def test_image_file_to_upload_rejects_invalid_image_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "not-an-image.jpg"
            image_path.write_text("<html>not an image</html>", encoding="utf-8")

            with self.assertRaises(VisualGenerationError):
                image_file_to_upload(image_path)

    def test_request_json_retries_transient_upstream_error(self):
        error_body = json.dumps(
            {"error": {"code": "upstream_error", "message": "Upstream service temporarily unavailable"}}
        ).encode("utf-8")
        responses = [
            HTTPError("https://example.test/v1/chat/completions", 502, "Bad Gateway", {}, io.BytesIO(error_body)),
            FakeResponse(b'{"ok": true}'),
        ]

        def fake_urlopen(*_args, **_kwargs):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("app.modules.visual_generation.clients.urllib.request.urlopen", side_effect=fake_urlopen) as urlopen:
            with patch("app.modules.visual_generation.clients.time.sleep") as sleep:
                result = request_json(
                    "https://example.test/v1/chat/completions",
                    "sk-test",
                    {"model": "gpt-5.5", "messages": [{"role": "user", "content": "hi"}]},
                )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_generated_image_uses_extended_image_timeout(self):
        captured: dict[str, int] = {}

        def fake_request_json(*_args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return {"data": [{"b64_json": base64.b64encode(b"image-bytes").decode("ascii")}]}

        with patch(
            "app.modules.visual_generation.clients.image_generation_timeout_seconds",
            return_value=900,
        ):
            with patch("app.modules.visual_generation.clients.request_json", side_effect=fake_request_json):
                image_bytes = request_generated_image(
                    api_url="https://api.aicoming.top/v1/images/generations",
                    api_key="sk-test",
                    model="gpt-image-2-1k",
                    size="",
                    prompt="test prompt",
                )

        self.assertEqual(image_bytes, b"image-bytes")
        self.assertEqual(captured["timeout"], 900)

    def test_image_edits_uploads_multiple_reference_images(self):
        captured: dict[str, object] = {}

        def fake_request_multipart(*_args, **kwargs):
            captured["fields"] = kwargs.get("fields")
            captured["files"] = kwargs.get("files")
            return {"data": [{"b64_json": base64.b64encode(b"edited-image-bytes").decode("ascii")}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            first_path = Path(tmpdir) / "first.png"
            second_path = Path(tmpdir) / "second.png"
            Image.new("RGB", (16, 16), (255, 0, 0)).save(first_path)
            Image.new("RGB", (16, 16), (0, 0, 255)).save(second_path)

            with patch("app.modules.visual_generation.clients.request_multipart", side_effect=fake_request_multipart):
                image_bytes = request_generated_image(
                    api_url="https://api.aicoming.top/v1/images/edits",
                    api_key="sk-test",
                    model="gpt-image-2-1k",
                    size="",
                    prompt="combine the product references",
                    reference_image_paths=[first_path, second_path],
                )

        self.assertEqual(image_bytes, b"edited-image-bytes")
        self.assertEqual(captured["fields"], [("model", "gpt-image-2-1k"), ("prompt", "combine the product references")])
        files = captured["files"]
        self.assertIsInstance(files, list)
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0][0], "image[]")
        self.assertEqual(files[1][0], "image[]")


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


if __name__ == "__main__":
    unittest.main()
