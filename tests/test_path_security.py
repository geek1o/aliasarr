from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.shows import delete_show
from app.models.db import Base, Show, User
from app.services import backup_service, settings_service
from app.services.path_security import UnsafeMediaPathError, require_library_descendant


class TestPathSecurity(unittest.TestCase):
    def test_accepts_descendant_but_rejects_root_and_sibling(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "library")
            root.mkdir()
            settings = SimpleNamespace(
                root_folder=str(root),
                root_folder_movies="",
                root_folder_series="",
                root_folder_anime="",
            )

            accepted = require_library_descendant(str(root / "Show"), settings)
            self.assertEqual(accepted, (root / "Show").resolve())
            with self.assertRaises(UnsafeMediaPathError):
                require_library_descendant(str(root), settings)
            with self.assertRaises(UnsafeMediaPathError):
                require_library_descendant(str(Path(temp_dir, "outside")), settings)

    def test_resolved_symlink_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir, "library")
            outside = Path(temp_dir, "outside")
            root.mkdir()
            outside.mkdir()
            symlink = root / "escaped"
            symlink.symlink_to(outside, target_is_directory=True)
            settings = SimpleNamespace(
                root_folder=str(root),
                root_folder_movies="",
                root_folder_series="",
                root_folder_anime="",
            )

            with self.assertRaises(UnsafeMediaPathError):
                require_library_descendant(str(symlink), settings)

    def test_delete_show_rejects_path_outside_library_before_removing_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            library = Path(temp_dir, "library")
            outside = Path(temp_dir, "outside")
            library.mkdir()
            outside.mkdir()
            marker = outside / "must-survive.txt"
            marker.write_text("safe", encoding="utf-8")

            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(engine)
            db = sessionmaker(bind=engine)()
            try:
                from app.services.settings_service import get_or_create_settings

                settings = get_or_create_settings(db)
                settings.root_folder = str(library)
                user = User(username="admin", password_hash="hash", is_admin=True, is_owner=True)
                show = Show(title="Unsafe", path=str(outside))
                db.add_all([settings, user, show])
                db.commit()

                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(delete_show(show.id, delete_files=True, db=db, current_user=user))
                self.assertEqual(raised.exception.status_code, 400)
                self.assertTrue(marker.exists())
                self.assertIsNotNone(db.get(Show, show.id))
            finally:
                db.close()
                engine.dispose()


class TestSecretFileModes(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX file modes are not available on Windows")
    def test_backup_directory_repairs_existing_archive_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir, "existing.zip")
            archive.write_bytes(b"zip")
            archive.chmod(0o666)
            with patch.object(backup_service, "BACKUP_DIR", temp_dir):
                backup_service._ensure_backup_dir()

            self.assertEqual(Path(temp_dir).stat().st_mode & 0o777, 0o700)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_api_key_file_is_created_with_owner_only_mode(self):
        writer = MagicMock()
        writer.__enter__.return_value = writer
        writer.__exit__.return_value = False
        with (
            patch.object(settings_service.os, "makedirs"),
            patch.object(settings_service.os, "open", return_value=42) as open_mock,
            patch.object(settings_service.os, "fchmod") as chmod_mock,
            patch.object(settings_service.os, "fdopen", return_value=writer),
        ):
            settings_service.write_api_key_file("secret")

        self.assertEqual(open_mock.call_args.args[-1], 0o600)
        chmod_mock.assert_called_once_with(42, 0o600)
        writer.write.assert_called_once_with("secret\n")


if __name__ == "__main__":
    unittest.main()
