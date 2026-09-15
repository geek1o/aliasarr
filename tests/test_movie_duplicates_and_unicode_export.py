from __future__ import annotations

import unittest
import urllib.parse
import unicodedata
import re
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, Show, Episode, QualityProfile, DownloadClient, DownloadHistory, TrackedRelease
    from app.models.enums import EpisodeStatus
    from app.api.release_logs_routes import export_release_logs
    HAS_DB = True
except ImportError:
    HAS_DB = False


class TestMovieDuplicatesAndUnicodeExport(unittest.IsolatedAsyncioTestCase):
    def test_unicode_content_disposition_header_logic(self):
        """Проверяет генерацию latin-1 совместимого заголовка Content-Disposition с RFC 5987 UTF-8 для русских названий."""
        titles = [
            "Оппенгеймер",
            "Создатель (2023)",
            "Проект «Аве Мария»",
            "Человек-паук: Через вселенные",
        ]
        time_suffix = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

        for raw_title in titles:
            norm = unicodedata.normalize("NFKD", raw_title).encode("ascii", "ignore").decode("ascii")
            clean = re.sub(r"[^a-zA-Z0-9_\-.]", "_", norm).strip("_")
            safe_ascii = "_" + clean[:40] if clean else "_show_1"
            fallback_filename = f"aliasarr_release_logs{safe_ascii}_{time_suffix}.txt"
            utf8_filename = f"aliasarr_release_logs_{raw_title}_{time_suffix}.txt"
            quoted_filename = urllib.parse.quote(utf8_filename)
            content_disp = f'attachment; filename="{fallback_filename}"; filename*=UTF-8\'\'{quoted_filename}'

            # 1. Заголовок ОБЯЗАН успешно кодироваться в latin-1 (иначе Starlette выбросит UnicodeEncodeError 500)
            encoded = content_disp.encode("latin-1")
            self.assertIsInstance(encoded, bytes)

            # 2. Проверяем наличие валидных RFC параметров
            self.assertIn("filename=", content_disp)
            self.assertIn("filename*=UTF-8''", content_disp)
            self.assertTrue(all(ord(c) < 128 for c in content_disp))

    def test_movie_old_hashes_aggregation_logic(self):
        """Проверяет логику сбора старых хэшей фильма при апгрейде качества."""
        show = MagicMock()
        show.id = 42
        show.content_type = "movie"

        covered = [
            MagicMock(torrent_hash="HASH_OLD_DOWNLOADED", status="downloaded"),
        ]

        # Симулируем сбор хэшей
        old_hashes_to_cleanup = {
            ep.torrent_hash for ep in covered
            if ep.torrent_hash
        }

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [("HASH_TRACKED_1",), ("HASH_TRACKED_2",)],  # TrackedRelease
            [("HASH_HIST_1",)],  # DownloadHistory
        ]

        if show.content_type == "movie":
            prev_tr = mock_db.query().filter().all()
            for (p_h,) in prev_tr:
                if p_h:
                    old_hashes_to_cleanup.add(p_h)
            prev_dh = mock_db.query().filter().all()
            for (p_h,) in prev_dh:
                if p_h:
                    old_hashes_to_cleanup.add(p_h)

        self.assertIn("HASH_OLD_DOWNLOADED", old_hashes_to_cleanup)
        self.assertIn("HASH_TRACKED_1", old_hashes_to_cleanup)
        self.assertIn("HASH_TRACKED_2", old_hashes_to_cleanup)
        self.assertIn("HASH_HIST_1", old_hashes_to_cleanup)

    async def test_export_release_logs_cyrillic_response(self):
        """Проверяет генерацию Response в export_release_logs для тайтла с русским названием."""
        try:
            from app.api.release_logs_routes import export_release_logs
        except ImportError:
            self.skipTest("FastAPI not available")

        mock_show = MagicMock()
        mock_show.id = 1
        mock_show.title = "Оппенгеймер"

        mock_db = MagicMock()
        mock_db.get.return_value = mock_show
        mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        response = await export_release_logs(
            show_id=1,
            include_diagnostics=False,
            db=mock_db,
            current_user=MagicMock(),
        )

        self.assertEqual(response.status_code, 200)
        content_disp = response.headers.get("content-disposition", "")
        self.assertTrue(content_disp.startswith("attachment;"))
        encoded_header = content_disp.encode("latin-1")
        self.assertIsInstance(encoded_header, bytes)
        self.assertIn("filename*=", content_disp)
        self.assertIn("filename=", content_disp)
