from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest.mock import patch

try:
    from fastapi import Response
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request

    from app.api.auth_routes import LoginRequest, auth_status, login
    from app.auth import get_client_ip
    from app.models.db import Base, Session as SessionModel, User
    from app.services.settings_service import get_or_create_settings, hash_password
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


def make_request(peer_ip: str, forwarded_for: str | None = None) -> Request:
    headers = [(b"host", b"aliasarr.test")]
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/status",
            "raw_path": b"/api/v1/auth/status",
            "query_string": b"",
            "headers": headers,
            "client": (peer_ip, 12345),
            "server": ("aliasarr.test", 80),
            "scheme": "http",
        }
    )


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestTrustedProxyHandling(unittest.TestCase):
    def test_untrusted_client_cannot_spoof_forwarded_ip(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALIASARR_TRUSTED_PROXIES", None)
            request = make_request("8.8.8.8", "127.0.0.1")
            self.assertEqual(get_client_ip(request), "8.8.8.8")

    def test_configured_proxy_can_forward_client_ip(self):
        with patch.dict(os.environ, {"ALIASARR_TRUSTED_PROXIES": "10.0.0.5/32"}):
            request = make_request("10.0.0.5", "198.51.100.20")
            self.assertEqual(get_client_ip(request), "198.51.100.20")


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestLocalAuthBehavior(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.settings = get_or_create_settings(self.db)
        self.settings.login_enabled = True
        self.settings.auth_disabled_for_local_addresses = True
        self.owner = User(
            username="admin",
            password_hash=hash_password("correct-password"),
            is_admin=True,
            is_owner=True,
            session_timeout_minutes=60,
        )
        self.db.add_all([self.settings, self.owner])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_local_bypass_authenticates_without_creating_permanent_session(self):
        result = auth_status(make_request("192.168.1.20"), db=self.db)
        self.assertTrue(result["authenticated"])
        self.assertFalse(result["login_required"])
        self.assertEqual(result["user"]["username"], "admin")

    def test_spoofed_forwarded_header_does_not_activate_local_bypass(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ALIASARR_TRUSTED_PROXIES", None)
            result = auth_status(
                make_request("8.8.8.8", "127.0.0.1"),
                db=self.db,
            )
        self.assertFalse(result["authenticated"])
        self.assertTrue(result["login_required"])

    def test_explicit_local_login_uses_normal_session_timeout(self):
        request = make_request("192.168.1.20")
        response = Response()
        result = login(
            LoginRequest(username="admin", password="correct-password"),
            response=response,
            request=request,
            db=self.db,
        )
        session = self.db.query(SessionModel).filter_by(token=result["token"]).one()
        remaining = session.expires_at - dt.datetime.utcnow()
        self.assertLess(remaining, dt.timedelta(minutes=61))
        self.assertGreater(remaining, dt.timedelta(minutes=59))


if __name__ == "__main__":
    unittest.main()
