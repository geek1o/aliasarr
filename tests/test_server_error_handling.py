from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock

try:
    from fastapi import HTTPException, Request
    from app.main import http_exception_handler, unhandled_exception_handler
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestServerErrorHandling(unittest.TestCase):
    def test_http_exception_handler_500_enrichment(self):
        if not HAS_DEPS:
            self.skipTest("FastAPI / dependencies not installed in host runner")

        mock_request = MagicMock(spec=Request)
        mock_request.method = "POST"
        mock_request.url.path = "/api/v1/shows/94/remap"

        exc = HTTPException(status_code=500, detail="Ошибка базы данных при перепривязке")

        resp = asyncio.run(http_exception_handler(mock_request, exc))
        self.assertEqual(resp.status_code, 500)

        data = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(data["status_code"], 500)
        self.assertEqual(data["method"], "POST")
        self.assertEqual(data["path"], "/api/v1/shows/94/remap")
        self.assertEqual(data["error_type"], "HTTPException")
        self.assertIn("Ошибка базы данных", data["detail"])
        self.assertIn("timestamp", data)

    def test_http_exception_handler_404_passthrough(self):
        if not HAS_DEPS:
            self.skipTest("FastAPI / dependencies not installed in host runner")

        mock_request = MagicMock(spec=Request)
        mock_request.method = "GET"
        mock_request.url.path = "/api/v1/shows/999"

        exc = HTTPException(status_code=404, detail="Show not found")

        resp = asyncio.run(http_exception_handler(mock_request, exc))
        self.assertEqual(resp.status_code, 404)

        data = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(data["detail"], "Show not found")
        # Should not pollute 404 with 500-specific diagnostic fields
        self.assertNotIn("status_code", data)

    def test_unhandled_exception_handler(self):
        if not HAS_DEPS:
            self.skipTest("FastAPI / dependencies not installed in host runner")

        mock_request = MagicMock(spec=Request)
        mock_request.method = "DELETE"
        mock_request.url.path = "/api/v1/metadata-sources/cleanup-aliases"

        exc = KeyError("missing_id")

        resp = asyncio.run(unhandled_exception_handler(mock_request, exc))
        self.assertEqual(resp.status_code, 500)

        data = json.loads(resp.body.decode("utf-8"))
        self.assertEqual(data["status_code"], 500)
        self.assertEqual(data["method"], "DELETE")
        self.assertEqual(data["path"], "/api/v1/metadata-sources/cleanup-aliases")
        self.assertEqual(data["error_type"], "KeyError")
        self.assertIn("missing_id", data["error"])
        self.assertIn("Внутренняя ошибка сервера (KeyError)", data["detail"])
        self.assertIn("timestamp", data)


if __name__ == "__main__":
    unittest.main()
