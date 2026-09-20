from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from app.services.path_security import UnsafeMediaPathError
from app.services.recycle_bin import (
    MANIFEST_NAME,
    list_recycled_media,
    purge_expired_recycled_media,
    purge_recycled_media,
    recycle_media_path,
    restore_recycled_media,
)


class RecycleBinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.library = self.base / "library"
        self.library.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_recycle_list_and_restore_file(self):
        media = self.library / "Show" / "episode.mkv"
        media.parent.mkdir()
        media.write_bytes(b"video")

        entry = recycle_media_path(media, library_roots=[self.library], operation="episode_delete")

        self.assertFalse(media.exists())
        self.assertTrue(Path(entry.recycled_path).exists())
        self.assertEqual(list_recycled_media([self.library]), [entry])
        restored = restore_recycled_media(entry.id, library_roots=[self.library])
        self.assertEqual(restored, media.resolve())
        self.assertEqual(media.read_bytes(), b"video")
        self.assertEqual(list_recycled_media([self.library]), [])

    def test_recycle_directory_and_purge(self):
        show = self.library / "Show"
        show.mkdir()
        (show / "episode.mkv").write_bytes(b"video")
        entry = recycle_media_path(show, library_roots=[self.library], operation="show_delete")

        purge_recycled_media(entry.id, library_roots=[self.library])

        self.assertFalse(Path(entry.recycled_path).exists())
        self.assertEqual(list_recycled_media([self.library]), [])

    def test_path_outside_roots_is_rejected(self):
        outside = self.base / "outside.mkv"
        outside.write_bytes(b"video")
        with self.assertRaises(UnsafeMediaPathError):
            recycle_media_path(outside, library_roots=[self.library])

    def test_invalid_manifest_is_ignored(self):
        bucket = self.library / ".aliasarr-recycle" / "bad"
        bucket.mkdir(parents=True)
        (bucket / MANIFEST_NAME).write_text("{broken", encoding="utf-8")
        self.assertEqual(list_recycled_media([self.library]), [])

    def test_expired_entries_are_purged(self):
        media = self.library / "episode.mkv"
        media.write_bytes(b"video")
        entry = recycle_media_path(media, library_roots=[self.library])
        manifest = Path(entry.recycled_path).parent / MANIFEST_NAME
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["created_at"] = "2024-01-01T00:00:00+00:00"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        removed = purge_expired_recycled_media(
            library_roots=[self.library],
            retention_days=30,
            now=dt.datetime(2024, 3, 1, tzinfo=dt.UTC),
        )
        self.assertEqual(removed, [entry.id])
        self.assertFalse(Path(entry.recycled_path).exists())


if __name__ == "__main__":
    unittest.main()
