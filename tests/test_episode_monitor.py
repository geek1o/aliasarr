"""
Unit tests for automatic unmonitoring of episodes upon download/import:
- Postprocessing sets status=DOWNLOADED and monitored=False
- Manual toggle via set_episode_status supports re-monitoring
- Upgrading re-enables monitored=True
- run_wanted_search skips downloaded episodes when monitored=False
- Startup migration unmonitors legacy downloaded episodes without upgrade requests
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

try:
    from sqlalchemy import create_engine, or_, and_
    from sqlalchemy.orm import sessionmaker

    from app.models.db import (
        Base,
        Episode,
        EpisodeStatus,
        Show,
        QualityProfile,
        AppSettings,
    )
    from app.api.operations import set_episode_status, toggle_episode_upgrade
    from app.services.postprocess import process_download_directory, process_movie_download
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "Requires sqlalchemy and project dependencies")
class TestEpisodeMonitor(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

        self.temp_dir = tempfile.mkdtemp()
        self.download_dir = os.path.join(self.temp_dir, "downloads")
        self.library_dir = os.path.join(self.temp_dir, "library")
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.library_dir, exist_ok=True)

        self.profile = QualityProfile(
            name="HD-1080p",
            cutoff_quality="WEBDL-1080p",
            allowed_qualities=["SDTV", "WEBDL-720p", "WEBDL-1080p", "Bluray-1080p"],
            upgrade_allowed=False,
        )
        self.db.add(self.profile)
        self.db.commit()
        self.db.refresh(self.profile)

        self.mock_user = MagicMock()
        self.mock_user.id = 1
        self.mock_user.username = "admin"

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_postprocess_series_unmonitors_episode(self):
        show = Show(
            title="Test Series",
            content_type="series",
            quality_profile_id=self.profile.id,
            root_folder=self.library_dir,
            monitored=True,
        )
        self.db.add(show)
        self.db.commit()
        self.db.refresh(show)

        ep = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            title="Pilot",
            status=EpisodeStatus.DOWNLOADING,
            monitored=True,
        )
        self.db.add(ep)
        self.db.commit()
        self.db.refresh(ep)

        # Create dummy video file in download directory
        video_name = "Test.Series.S01E01.1080p.WEB-DL.mkv"
        video_path = os.path.join(self.download_dir, video_name)
        with open(video_path, "wb") as f:
            f.write(b"0" * 1024)

        result = process_download_directory(
            db=self.db,
            download_path=self.download_dir,
            show=show,
            season_num=1,
            actual_ep_num=1,
            use_hardlinks=False,
            keep_source=False,
        )

        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0].get("status"), "imported")

        self.db.refresh(ep)
        self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)
        self.assertFalse(ep.monitored, "Episode should be automatically unmonitored after import")

    def test_postprocess_movie_unmonitors_movie(self):
        show = Show(
            title="Test Movie",
            content_type="movie",
            year=2024,
            quality_profile_id=self.profile.id,
            root_folder=self.library_dir,
            monitored=True,
        )
        self.db.add(show)
        self.db.commit()
        self.db.refresh(show)

        ep = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            title="Test Movie",
            status=EpisodeStatus.DOWNLOADING,
            monitored=True,
        )
        self.db.add(ep)
        self.db.commit()
        self.db.refresh(ep)

        movie_name = "Test.Movie.2024.1080p.WEB-DL.mkv"
        movie_path = os.path.join(self.download_dir, movie_name)
        with open(movie_path, "wb") as f:
            f.write(b"0" * 1024)

        result = process_movie_download(
            db=self.db,
            download_path=self.download_dir,
            show=show,
            use_hardlinks=False,
            keep_source=False,
            root_folder=self.library_dir,
        )

        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0].get("status"), "imported")

        self.db.refresh(ep)
        self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)
        self.assertFalse(ep.monitored, "Movie episode should be automatically unmonitored after import")

    def test_manual_toggle_episode_monitor(self):
        show = Show(
            title="Show for Toggle",
            content_type="series",
            quality_profile_id=self.profile.id,
            monitored=True,
        )
        self.db.add(show)
        self.db.commit()

        # Downloaded episode with monitored=False
        ep = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=5,
            title="Episode 5",
            status=EpisodeStatus.DOWNLOADED,
            monitored=False,
        )
        self.db.add(ep)
        self.db.commit()
        self.db.refresh(ep)

        # 1. User manually turns on monitoring
        res1 = set_episode_status(
            episode_id=ep.id,
            monitored=True,
            db=self.db,
            current_user=self.mock_user,
        )
        self.db.refresh(ep)
        self.assertTrue(res1["monitored"])
        self.assertTrue(ep.monitored)
        self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)

        # 2. User manually turns off monitoring
        res2 = set_episode_status(
            episode_id=ep.id,
            monitored=False,
            db=self.db,
            current_user=self.mock_user,
        )
        self.db.refresh(ep)
        self.assertFalse(res2["monitored"])
        self.assertFalse(ep.monitored)
        self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)

        # 3. Passing status="downloaded" without monitored flag keeps/sets monitored=False
        res3 = set_episode_status(
            episode_id=ep.id,
            status="downloaded",
            db=self.db,
            current_user=self.mock_user,
        )
        self.db.refresh(ep)
        self.assertFalse(res3["monitored"])
        self.assertFalse(ep.monitored)

    def test_upgrade_re_enables_monitor(self):
        show = Show(
            title="Show for Upgrade",
            content_type="series",
            quality_profile_id=self.profile.id,
            monitored=True,
        )
        self.db.add(show)
        self.db.commit()

        ep = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=2,
            title="Episode 2",
            status=EpisodeStatus.DOWNLOADED,
            monitored=False,
            upgrade_requested=False,
        )
        self.db.add(ep)
        self.db.commit()
        self.db.refresh(ep)

        # Enable upgrade
        res = toggle_episode_upgrade(
            episode_id=ep.id,
            requested=True,
            db=self.db,
            current_user=self.mock_user,
        )
        self.db.refresh(ep)
        self.assertTrue(res["upgrade_requested"])
        self.assertTrue(res["monitored"])
        self.assertTrue(ep.upgrade_requested)
        self.assertTrue(ep.monitored)

    def test_run_wanted_search_query_skips_downloaded_unmonitored(self):
        show1 = Show(title="Completed Show", content_type="series", monitored=True)
        show2 = Show(title="Wanted Show", content_type="series", monitored=True)
        self.db.add_all([show1, show2])
        self.db.commit()

        # Show 1 has downloaded unmonitored episode
        ep1 = Episode(
            show_id=show1.id,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.DOWNLOADED,
            monitored=False,
            upgrade_requested=False,
        )
        # Show 2 has wanted monitored episode
        ep2 = Episode(
            show_id=show2.id,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.WANTED,
            monitored=True,
        )
        self.db.add_all([ep1, ep2])
        self.db.commit()

        # The query from run_wanted_search
        wanted_shows_ids = [
            r[0] for r in self.db.query(Episode.show_id).join(Show, Show.id == Episode.show_id).filter(
                Show.monitored == True,  # noqa: E712
                Episode.monitored == True,  # noqa: E712
                or_(
                    Episode.status == EpisodeStatus.WANTED,
                    and_(Episode.status == EpisodeStatus.DOWNLOADED, Episode.upgrade_requested == True),
                    Show.upgrade_requested == True,
                )
            ).distinct().all()
        ]

        self.assertNotIn(show1.id, wanted_shows_ids, "Completed show with monitored=False must NOT be searched")
        self.assertIn(show2.id, wanted_shows_ids, "Wanted show with monitored=True MUST be searched")

        # If upgrade_requested is enabled on show1's episode and monitored=True
        ep1.upgrade_requested = True
        ep1.monitored = True
        self.db.commit()

        wanted_shows_ids_after = [
            r[0] for r in self.db.query(Episode.show_id).join(Show, Show.id == Episode.show_id).filter(
                Show.monitored == True,  # noqa: E712
                Episode.monitored == True,  # noqa: E712
                or_(
                    Episode.status == EpisodeStatus.WANTED,
                    and_(Episode.status == EpisodeStatus.DOWNLOADED, Episode.upgrade_requested == True),
                    Show.upgrade_requested == True,
                )
            ).distinct().all()
        ]
        self.assertIn(show1.id, wanted_shows_ids_after, "Episode with upgrade_requested=True should now be searched")

    def test_startup_migration_unmonitors_legacy_downloaded(self):
        show = Show(title="Legacy Show", content_type="series", monitored=True)
        self.db.add(show)
        self.db.commit()

        # Episode 1: downloaded, monitored=True, no upgrade
        ep1 = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.DOWNLOADED,
            monitored=True,
            upgrade_requested=False,
        )
        # Episode 2: downloaded, monitored=True, upgrade requested
        ep2 = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=2,
            status=EpisodeStatus.DOWNLOADED,
            monitored=True,
            upgrade_requested=True,
        )
        # Episode 3: wanted, monitored=True
        ep3 = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=3,
            status=EpisodeStatus.WANTED,
            monitored=True,
        )
        settings = AppSettings(
            api_key="test-key",
            unmonitor_downloaded_migrated=False,
        )
        self.db.add_all([ep1, ep2, ep3, settings])
        self.db.commit()

        # Simulate startup migration
        if not getattr(settings, "unmonitor_downloaded_migrated", False):
            self.db.query(Episode).filter(
                Episode.status == EpisodeStatus.DOWNLOADED,
                Episode.upgrade_requested == False,
            ).update({Episode.monitored: False}, synchronize_session=False)
            settings.unmonitor_downloaded_migrated = True
            self.db.commit()

        self.db.refresh(ep1)
        self.db.refresh(ep2)
        self.db.refresh(ep3)
        self.db.refresh(settings)

        self.assertFalse(ep1.monitored, "Downloaded ep without upgrade should have monitored=False")
        self.assertTrue(ep2.monitored, "Downloaded ep with upgrade_requested=True should stay monitored=True")
        self.assertTrue(ep3.monitored, "Wanted ep should stay monitored=True")
        self.assertTrue(settings.unmonitor_downloaded_migrated)


if __name__ == "__main__":
    unittest.main()
