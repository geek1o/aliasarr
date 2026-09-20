from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.download_preflight import prepare_download_target
from app.services.file_preflight import FilePreflightError


class DownloadPreflightTests(unittest.TestCase):
    def settings(self, folder: str):
        return SimpleNamespace(
            download_folder_movies="",
            download_folder_series=folder,
            download_folder_anime="",
        )

    def test_validates_local_folder_and_returns_remote_client_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir, "downloads")
            local.mkdir()
            client = SimpleNamespace(
                remote_path_mappings=[{"remote_root": "/client/downloads", "local_root": str(local)}]
            )
            target = prepare_download_target(self.settings(str(local)), "series", client, size_bytes=5)
            self.assertEqual(target, "/client/downloads")

    def test_insufficient_space_fails_preflight(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "app.services.file_preflight.shutil.disk_usage",
                return_value=SimpleNamespace(total=100, used=95, free=5),
            ):
                with self.assertRaises(FilePreflightError):
                    prepare_download_target(
                        self.settings(temp_dir),
                        "series",
                        SimpleNamespace(remote_path_mappings=[]),
                        size_bytes=10,
                    )

    def test_empty_download_folder_keeps_client_default(self):
        target = prepare_download_target(
            self.settings(""),
            "series",
            SimpleNamespace(remote_path_mappings=[]),
        )
        self.assertEqual(target, "")


if __name__ == "__main__":
    unittest.main()
