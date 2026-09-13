from __future__ import annotations

import asyncio
import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.params import Depends
from starlette.requests import Request

from app.api.blocklist_routes import get_blocked_shows_summary, list_blocklist_entries
from app.api.dataset_routes import get_dataset_data, get_harvest_status
from app.api.operations import get_health_check
from app.auth import ApiKeyMiddleware


def _request(path: str, host: bytes = b"testserver") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [(b"host", host)],
            "client": ("203.0.113.10", 50000),
            "server": ("testserver", 80),
        }
    )


class TestAuthPathSecurity(unittest.TestCase):
    def _dispatch(self, request: Request):
        middleware = ApiKeyMiddleware(app=MagicMock())
        db = MagicMock()
        settings = MagicMock(login_enabled=True, api_key="secret")
        call_next = AsyncMock(return_value=MagicMock(status_code=200))

        async def run():
            with (
                patch("app.auth.SessionLocal", return_value=db),
                patch("app.auth.get_or_create_settings", return_value=settings),
                patch("app.auth._get_valid_session_user", return_value=(False, None)),
            ):
                response = await middleware.dispatch(request, call_next)
            return response, call_next

        return asyncio.run(run())

    def test_host_header_cannot_inject_public_prefix_into_protected_path(self):
        request = _request(
            "/api/v1/dataset/data",
            host=b"testserver/api/v1/health",
        )
        self.assertTrue(request.url.path.startswith("/api/v1/health"))

        response, call_next = self._dispatch(request)

        self.assertEqual(response.status_code, 401)
        call_next.assert_not_awaited()

    def test_extended_health_check_is_not_public(self):
        response, call_next = self._dispatch(_request("/api/v1/health-check"))

        self.assertEqual(response.status_code, 401)
        call_next.assert_not_awaited()

    def test_basic_health_probe_remains_public(self):
        response, call_next = self._dispatch(_request("/api/v1/health"))

        self.assertEqual(response.status_code, 200)
        call_next.assert_awaited_once()

    def test_sensitive_read_routes_have_endpoint_dependencies(self):
        for endpoint in (
            get_health_check,
            list_blocklist_entries,
            get_blocked_shows_summary,
            get_harvest_status,
            get_dataset_data,
        ):
            default = inspect.signature(endpoint).parameters["current_user"].default
            self.assertIsInstance(default, Depends)


if __name__ == "__main__":
    unittest.main()
