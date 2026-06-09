import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.api import routes_sync


class SyncRoutesTest(unittest.TestCase):
    def test_sync_token_allows_development_when_unconfigured(self):
        with patch.object(routes_sync, "WORKBENCH_SYNC_TOKEN", ""):
            routes_sync.ensure_sync_authorized(None, None)

    def test_sync_token_accepts_header_token(self):
        with patch.object(routes_sync, "WORKBENCH_SYNC_TOKEN", "secret-token"):
            routes_sync.ensure_sync_authorized("secret-token", None)

    def test_sync_token_accepts_bearer_token(self):
        with patch.object(routes_sync, "WORKBENCH_SYNC_TOKEN", "secret-token"):
            routes_sync.ensure_sync_authorized(None, "Bearer secret-token")

    def test_sync_token_rejects_invalid_token(self):
        with patch.object(routes_sync, "WORKBENCH_SYNC_TOKEN", "secret-token"):
            with self.assertRaises(HTTPException) as ctx:
                routes_sync.ensure_sync_authorized("wrong-token", None)

        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
