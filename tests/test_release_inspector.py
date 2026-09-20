from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Alias, AppSettings, Base, Episode, EpisodeStatus, Show
from app.schemas import ReleaseInspectorRequest, SearchResultOut
from app.services import release_inspector


class TestReleaseInspector(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(AppSettings(api_key="test-key", min_seeds=0))
        self.show = Show(title="Example Show", year=2024, content_type="series")
        self.show.aliases.append(
            Alias(text="Example Show", language="en", source="manual")
        )
        self.show.episodes.extend(
            [
                Episode(
                    season_number=1,
                    episode_number=1,
                    status=EpisodeStatus.WANTED,
                    monitored=True,
                ),
                Episode(
                    season_number=1,
                    episode_number=2,
                    status=EpisodeStatus.DOWNLOADED,
                    monitored=True,
                ),
            ]
        )
        self.db.add(self.show)
        self.db.commit()
        self.db.refresh(self.show)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def inspect(self, title: str, **kwargs):
        return release_inspector.inspect_release(
            self.db,
            title=title,
            show=self.show,
            **kwargs,
        )

    def test_uses_one_parser_pass_and_precomputed_match(self):
        real_parse = release_inspector.parse_episode
        with (
            patch.object(
                release_inspector, "parse_episode", wraps=real_parse
            ) as parse_mock,
            patch(
                "app.services.matcher.match_release",
                side_effect=AssertionError(
                    "DecisionEngine must reuse the inspector match"
                ),
            ),
        ):
            result = self.inspect("Example.Show.S01E01.1080p.WEB-DL")

        self.assertEqual(parse_mock.call_count, 1)
        self.assertTrue(result["match"]["matched"])
        self.assertEqual(result["analysis"]["episodes"], [1])

    def test_returns_full_match_coverage_and_decision(self):
        result = self.inspect("Example.Show.S01E01.1080p.WEB-DL-GROUP", seeders=4)

        self.assertEqual(result["show"]["id"], self.show.id)
        self.assertEqual(result["coverage"]["summary"], "S01E01")
        self.assertEqual(result["coverage"]["wanted_overlap"], 1)
        self.assertIn("quality_details", result["decision"])
        self.assertIn("custom_formats", result["decision"])

    def test_zero_seeders_is_not_replaced_by_a_default(self):
        settings = self.db.query(AppSettings).first()
        settings.min_seeds = 1
        self.db.commit()

        result = self.inspect("Example.Show.S01E01.1080p.WEB-DL", seeders=0)

        self.assertFalse(result["decision"]["approved"])
        self.assertTrue(
            any("(0)" in reason for reason in result["decision"]["rejections"])
        )

    def test_parse_only_non_video_is_read_only(self):
        before = self.db.query(Show).count()
        result = release_inspector.inspect_release(
            self.db,
            title="Example Show Original Soundtrack [FLAC]",
            categories=[],
        )

        self.assertEqual(result["analysis"]["status"], "non_video")
        self.assertIsNone(result["match"])
        self.assertFalse(result["decision"]["approved"])
        self.assertEqual(self.db.query(Show).count(), before)

    def test_request_validation_and_search_categories_contract(self):
        with self.assertRaises(ValidationError):
            ReleaseInspectorRequest(title="   ")
        with self.assertRaises(ValidationError):
            ReleaseInspectorRequest(title="ok", seeders=-1)

        search_result = SearchResultOut(
            title="Example.Show.S01E01",
            indexer="test",
            guid="guid",
            categories=[5000],
        )
        self.assertEqual(search_result.categories, [5000])


class TestReleaseInspectorFrontend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.js = (root / "web" / "js" / "app.js").read_text(encoding="utf-8")

    def test_shared_modal_and_live_api_are_wired(self):
        self.assertIn('id="release-inspector-modal"', self.html)
        self.assertIn("function openReleaseInspectorFromSearch(", self.js)
        self.assertIn("function openDatasetDiagnoseModal(", self.js)
        self.assertIn('api("/api/v1/release-inspector"', self.js)

    def test_server_strings_are_escaped_before_rendering(self):
        escaped_reasons = "reasons.map(reason => `<li>${escapeHtml(reason)}</li>`)"
        self.assertIn(escaped_reasons, self.js)
        self.assertIn("escapeHtml(match.alias_text", self.js)
        self.assertIn("escapeHtml(analysis.matched_pattern", self.js)


if __name__ == "__main__":
    unittest.main()
