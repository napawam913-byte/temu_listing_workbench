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
    image_file_to_data_url,
    image_file_to_upload,
    request_json,
)


class VisualGenerationClientImageTest(unittest.TestCase):
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
