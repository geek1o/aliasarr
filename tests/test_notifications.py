from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.models.db import NotificationConfig
except ImportError:
    class NotificationConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
from app.services.notifications import (
    _NOTIFICATION_DISPATCHERS,
    REQUIRED_NOTIFICATION_FIELDS,
    format_notification_message,
    notify_all,
    send_notification,
)


class TestNotificationSystem(unittest.TestCase):
    def test_providers_registered(self):
        expected_providers = {
            "telegram",
            "discord",
            "gotify",
            "ntfy",
            "pushover",
            "slack",
            "webhook",
            "email",
            "pushbullet",
            "apprise",
            "script",
        }
        for p in expected_providers:
            self.assertIn(p, _NOTIFICATION_DISPATCHERS, f"Provider {p} should be in _NOTIFICATION_DISPATCHERS")
            self.assertIn(p, REQUIRED_NOTIFICATION_FIELDS, f"Provider {p} should have REQUIRED_NOTIFICATION_FIELDS")

    def test_format_notification_message_translations(self):
        ru_msg = "🔔 Тестовое уведомление от Aliasarr — всё работает!"
        en_msg = format_notification_message(ru_msg, lang="en")
        self.assertEqual(en_msg, "🔔 Test notification from Aliasarr — everything works!")

        ru_grab = "Захвачен релиз для Lucifer S01E01, сиды: 50"
        en_grab = format_notification_message(ru_grab, lang="en")
        self.assertEqual(en_grab, "Grabbed release for Lucifer S01E01, seeds: 50")

    def test_notification_config_all_triggers(self):
        cfg = NotificationConfig(
            id=1,
            name="Test Discord",
            type="discord",
            settings={"webhook_url": "https://discord.com/api/webhooks/test"},
            enabled=True,
            on_grab=True,
            on_import=True,
            on_upgrade=True,
            on_rename=False,
            on_series_add=False,
            on_series_delete=False,
            on_episode_file_delete=False,
            on_episode_file_delete_for_upgrade=False,
            on_health_issue=True,
            on_health_restored=False,
            on_application_update=False,
            on_manual_interaction_required=True,
            on_backup=False,
        )
        self.assertTrue(cfg.on_grab)
        self.assertTrue(cfg.on_upgrade)
        self.assertFalse(cfg.on_rename)
        self.assertFalse(cfg.on_backup)

    def test_series_delete_and_backup_translations(self):
        msg_del_files = "🗑 Удалён тайтл «Breaking Bad» (вместе с файлами на диске)"
        en_del_files = format_notification_message(msg_del_files, lang="en")
        self.assertIn("Deleted title 'Breaking Bad' (along with files on disk)", en_del_files)

        msg_del_nofiles = "🗑 Удалена карточка тайтла «Breaking Bad» (файлы сохранены)"
        en_del_nofiles = format_notification_message(msg_del_nofiles, lang="en")
        self.assertIn("Deleted title card 'Breaking Bad' (files kept)", en_del_nofiles)

        msg_backup = "💾 Создан бэкап: backup_2026.zip (1.2 MB)"
        en_backup = format_notification_message(msg_backup, lang="en")
        self.assertIn("Backup created: backup_2026.zip (1.2 MB)", en_backup)

    def test_send_notification_dispatch(self):
        cfg = NotificationConfig(
            id=1,
            name="Test Pushbullet",
            type="pushbullet",
            settings={"api_key": "dummy_key"},
            enabled=True,
        )

        mock_send = AsyncMock()
        with patch.dict(_NOTIFICATION_DISPATCHERS, {"pushbullet": mock_send}):
            asyncio.run(send_notification(cfg, "Hello test", "test"))
            mock_send.assert_called_once()

    def test_telegram_send_document_when_file_path_provided(self):
        import tempfile
        from app.services.notifications import _send_telegram

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf.write(b"PK\x03\x04fake zip content")
            temp_path = tf.name

        try:
            settings = {
                "bot_token": "TEST_BOT_TOKEN_123",
                "chat_id": "12345678",
                "send_backup_file": True,
            }
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

            with patch("app.services.notifications.httpx", mock_httpx):
                asyncio.run(_send_telegram(settings, "Резервная копия создана", "backup", file_path=temp_path))

            mock_client.post.assert_called_once()
            call_args, call_kwargs = mock_client.post.call_args
            self.assertIn("sendDocument", call_args[0])
            self.assertIn("document", call_kwargs.get("files", {}))
            self.assertEqual(call_kwargs["data"]["chat_id"], "12345678")
            self.assertIn("Резервная копия создана", call_kwargs["data"]["caption"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_discord_send_multipart_when_file_path_provided(self):
        import tempfile
        from app.services.notifications import _send_discord

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
            tf.write(b"PK\x03\x04fake discord zip")
            temp_path = tf.name

        try:
            settings = {
                "webhook_url": "https://discord.com/api/webhooks/test/123",
                "send_backup_file": True,
            }
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient = MagicMock(return_value=mock_client)

            with patch("app.services.notifications.httpx", mock_httpx):
                asyncio.run(_send_discord(settings, "Резервная копия создана", "backup", file_path=temp_path))

            mock_client.post.assert_called_once()
            call_args, call_kwargs = mock_client.post.call_args
            self.assertEqual(call_args[0], "https://discord.com/api/webhooks/test/123")
            self.assertIn("files[0]", call_kwargs.get("files", {}))
            self.assertIn("payload_json", call_kwargs.get("data", {}))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_send_notification_forwards_file_path(self):
        cfg = NotificationConfig(
            id=1,
            name="Telegram Backup",
            type="telegram",
            settings={"bot_token": "token", "chat_id": "123"},
            enabled=True,
        )
        mock_dispatcher = AsyncMock()
        with patch.dict(_NOTIFICATION_DISPATCHERS, {"telegram": mock_dispatcher}):
            asyncio.run(send_notification(cfg, "Backup done", "backup", file_path="/fake/backup.zip"))
            mock_dispatcher.assert_called_once()
            call_kwargs = mock_dispatcher.call_args[1]
            self.assertEqual(call_kwargs.get("file_path"), "/fake/backup.zip")


if __name__ == "__main__":
    unittest.main()
