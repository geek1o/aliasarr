from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.file_preflight import (
    ConflictPolicy,
    FileIntent,
    FilePreflightError,
    OperationMode,
    preflight_file_operation,
)
from app.services.path_security import (
    PathMapping,
    UnsafeMediaPathError,
    configured_download_roots,
    map_client_path,
    require_descendant,
    safe_join_under,
)


class TestPathResolution(unittest.TestCase):
    def test_safe_join_rejects_absolute_and_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            for unsafe in ("/etc/passwd", "../outside.mkv", "folder/../../outside.mkv", r"C:\\Windows\\file.mkv"):
                with self.subTest(unsafe=unsafe), self.assertRaises(UnsafeMediaPathError):
                    safe_join_under(tmp, unsafe)

    def test_safe_join_resolves_below_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = safe_join_under(tmp, r"Show\Season 01/episode.mkv")
            self.assertEqual(result, Path(tmp, "Show", "Season 01", "episode.mkv").resolve())

    def test_require_descendant_rejects_root_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsafeMediaPathError):
                require_descendant(tmp, (tmp,))
            self.assertEqual(require_descendant(tmp, (tmp,), allow_root=True), Path(tmp).resolve())

    def test_remote_mapping_uses_longest_component_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            mappings = [
                PathMapping("/data", str(Path(tmp, "generic"))),
                {"remote_root": "/data/tv", "local_root": str(Path(tmp, "series"))},
            ]
            mapped = map_client_path("/data/tv/Show/E01.mkv", mappings, require_mapping=True)
            self.assertEqual(mapped, Path(tmp, "series", "Show", "E01.mkv").resolve())

    def test_remote_mapping_does_not_match_partial_component(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(UnsafeMediaPathError):
            map_client_path(
                "/database/file.mkv",
                [PathMapping("/data", tmp)],
                require_mapping=True,
            )

    def test_configured_download_roots_are_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = SimpleNamespace(
                download_folder=tmp,
                download_folder_movies=tmp,
                download_folder_series=str(Path(tmp, "series")),
                download_folder_anime="",
            )
            self.assertEqual(configured_download_roots(settings), (Path(tmp).resolve(), Path(tmp, "series").resolve()))


class TestFilePreflight(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.downloads = self.base / "downloads"
        self.library = self.base / "library"
        self.downloads.mkdir()
        self.library.mkdir()
        self.source = self.downloads / "episode.mkv"
        self.source.write_bytes(b"video")

    def tearDown(self):
        self.temp.cleanup()

    def _intent(self, **kwargs):
        values = {
            "source": self.source,
            "destination": self.library / "Show" / "episode.mkv",
            "mode": OperationMode.COPY,
        }
        values.update(kwargs)
        return FileIntent(**values)

    def test_valid_copy_reports_required_space(self):
        report = preflight_file_operation(
            [self._intent()],
            source_roots=(self.downloads,),
            destination_roots=(self.library,),
        )
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(sum(report.required_bytes_by_device.values()), self.source.stat().st_size)

    def test_source_and_destination_must_be_inside_allowed_roots(self):
        outside_source = self.base / "outside.mkv"
        outside_source.write_bytes(b"x")
        outside_dest = self.base / "elsewhere" / "out.mkv"
        report = preflight_file_operation(
            [FileIntent(outside_source, outside_dest, OperationMode.COPY)],
            source_roots=(self.downloads,),
            destination_roots=(self.library,),
        )
        self.assertFalse(report.ok)
        self.assertIn("source_outside_roots", {i.code for i in report.errors})
        self.assertIn("destination_outside_roots", {i.code for i in report.errors})

    def test_delete_can_target_descendant_but_never_configured_root(self):
        child_report = preflight_file_operation(
            [FileIntent(self.source, None, OperationMode.DELETE)],
            source_roots=(self.downloads,),
        )
        root_report = preflight_file_operation(
            [FileIntent(self.downloads, None, OperationMode.DELETE)],
            source_roots=(self.downloads,),
        )
        self.assertTrue(child_report.ok, child_report.issues)
        self.assertIn("source_outside_roots", {i.code for i in root_report.errors})

    def test_symlink_destination_cannot_escape_root(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.library / "escape").symlink_to(outside, target_is_directory=True)
        report = preflight_file_operation(
            [self._intent(destination=self.library / "escape" / "episode.mkv")],
            source_roots=(self.downloads,),
            destination_roots=(self.library,),
        )
        self.assertIn("destination_outside_roots", {i.code for i in report.errors})

    def test_duplicate_destination_is_an_error(self):
        second = self.downloads / "episode2.mkv"
        second.write_bytes(b"two")
        destination = self.library / "Show" / "same.mkv"
        report = preflight_file_operation(
            [
                self._intent(destination=destination),
                self._intent(source=second, destination=destination),
            ],
            source_roots=(self.downloads,),
            destination_roots=(self.library,),
        )
        self.assertIn("duplicate_destination", {i.code for i in report.errors})

    def test_existing_destination_obeys_conflict_policy(self):
        destination = self.library / "existing.mkv"
        destination.write_bytes(b"old")
        blocked = preflight_file_operation(
            [self._intent(destination=destination)],
            destination_roots=(self.library,),
        )
        allowed = preflight_file_operation(
            [self._intent(destination=destination, conflict_policy=ConflictPolicy.REPLACE)],
            destination_roots=(self.library,),
        )
        self.assertIn("destination_exists", {i.code for i in blocked.errors})
        self.assertTrue(allowed.ok, allowed.issues)

    def test_hardlink_same_device_requires_no_data_space(self):
        report = preflight_file_operation(
            [self._intent(mode=OperationMode.HARDLINK)],
            source_roots=(self.downloads,),
            destination_roots=(self.library,),
        )
        self.assertTrue(report.ok, report.issues)
        self.assertEqual(report.required_bytes_by_device, {})
        self.assertEqual(report.decisions[0].effective_mode, OperationMode.HARDLINK)

    def test_insufficient_space_is_reported_and_raiseable(self):
        usage = SimpleNamespace(total=100, used=95, free=5)
        with patch("app.services.file_preflight.shutil.disk_usage", return_value=usage):
            report = preflight_file_operation(
                [self._intent(size_bytes=10)],
                destination_roots=(self.library,),
            )
        self.assertIn("insufficient_space", {i.code for i in report.errors})
        with self.assertRaises(FilePreflightError):
            report.raise_for_errors()

    def test_write_probe_failure_is_reported(self):
        with patch("app.services.file_preflight._probe_writable", side_effect=PermissionError("denied")):
            report = preflight_file_operation(
                [self._intent()],
                destination_roots=(self.library,),
                probe_write=True,
            )
        self.assertIn("destination_probe_failed", {i.code for i in report.errors})


if __name__ == "__main__":
    unittest.main()
