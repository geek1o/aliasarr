import unittest
from unittest.mock import MagicMock

try:
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, AppSettings, User
    from app.services.settings_service import get_or_create_settings
    from app.api.settings_routes import update_settings, SettingsUpdate
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestSettingsScrollbar(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            id=1,
            username="admin",
            is_admin=True,
            is_owner=True,
            enabled=True,
            password_hash="hash",
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        if hasattr(self, "db"):
            self.db.close()

    def test_app_settings_default_scrollbar_mode(self):
        settings = get_or_create_settings(self.db)
        self.assertEqual(settings.scrollbar_mode, "autohide")

    def test_update_settings_scrollbar_mode_valid(self):
        get_or_create_settings(self.db)
        mock_request = MagicMock()

        for mode in ("autohide", "styled", "hidden", "native"):
            payload = SettingsUpdate(scrollbar_mode=mode)
            res = update_settings(payload=payload, request=mock_request, db=self.db, current_user=self.user)
            self.assertEqual(res.scrollbar_mode, mode)
            settings = get_or_create_settings(self.db)
            self.assertEqual(settings.scrollbar_mode, mode)

    def test_update_settings_scrollbar_mode_invalid(self):
        get_or_create_settings(self.db)
        mock_request = MagicMock()

        payload = SettingsUpdate(scrollbar_mode="unknown_mode")
        with self.assertRaises(HTTPException) as ctx:
            update_settings(payload=payload, request=mock_request, db=self.db, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_design_preferences_are_persisted_server_side(self):
        get_or_create_settings(self.db)
        result = update_settings(
            payload=SettingsUpdate(design_system="servarr", glass_mode="on"),
            request=MagicMock(),
            db=self.db,
            current_user=self.user,
        )

        self.assertEqual(result.design_system, "servarr")
        self.assertEqual(result.glass_mode, "on")
        settings = get_or_create_settings(self.db)
        self.assertEqual(settings.design_system, "servarr")
        self.assertEqual(settings.glass_mode, "on")

    def test_invalid_design_preferences_are_rejected(self):
        get_or_create_settings(self.db)
        for payload in (
            SettingsUpdate(design_system="unknown"),
            SettingsUpdate(glass_mode="blur-everything"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                update_settings(payload=payload, request=MagicMock(), db=self.db, current_user=self.user)
            self.assertEqual(ctx.exception.status_code, 400)
