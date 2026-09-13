from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.metadata import (
    select_overview,
    get_metadata_client,
    TMDBClient,
    SkyHookClient,
    RadarrClient,
    TheTVDBClient,
    refresh_show_metadata,
)


class TestSelectOverview(unittest.TestCase):
    def test_russian_preferred_selects_russian_when_available(self):
        overviews = {"ru": "Русское описание", "en": "English overview", "de": "Deutsche Übersicht"}
        res = select_overview(overviews, original_overview="Original overview", preferred_lang="ru")
        self.assertEqual(res, "Русское описание")

    def test_russian_preferred_fallback_to_original_or_english(self):
        overviews = {"en": "English overview", "de": "Deutsche Übersicht"}
        res = select_overview(overviews, original_overview="Original overview", preferred_lang="ru")
        self.assertEqual(res, "Original overview")

        res_no_orig = select_overview(overviews, original_overview="", preferred_lang="ru")
        self.assertEqual(res_no_orig, "English overview")

    def test_english_preferred_selects_english_when_available(self):
        overviews = {"ru": "Русское описание", "en": "English overview", "fr": "Description française"}
        res = select_overview(overviews, original_overview="French original", preferred_lang="en")
        self.assertEqual(res, "English overview")

    def test_english_preferred_fallback_to_original_or_russian(self):
        overviews = {"ru": "Русское описание"}
        res = select_overview(overviews, original_overview="French original", preferred_lang="en")
        self.assertEqual(res, "French original")

        res_no_orig = select_overview(overviews, original_overview=None, preferred_lang="en")
        self.assertEqual(res_no_orig, "Русское описание")

    def test_original_preferred_selects_original(self):
        overviews = {"ru": "Русское описание", "en": "English overview"}
        res = select_overview(overviews, original_overview="Japanese Original", preferred_lang="original")
        self.assertEqual(res, "Japanese Original")

    def test_original_preferred_fallback_when_original_missing(self):
        overviews = {"ru": "Русское описание", "en": "English overview"}
        res = select_overview(overviews, original_overview="", preferred_lang="original")
        self.assertEqual(res, "English overview")

    def test_custom_language_preferred(self):
        overviews = {
            "ru": "Русское описание",
            "en": "English overview",
            "de": "Deutsche Übersicht",
            "it": "Descrizione italiana",
        }
        res = select_overview(overviews, original_overview="Base overview", preferred_lang="de")
        self.assertEqual(res, "Deutsche Übersicht")

        # Fallback for missing custom language
        res_missing = select_overview(overviews, original_overview="Base overview", preferred_lang="es")
        self.assertEqual(res_missing, "English overview")

    def test_empty_or_none_inputs_handled_safely(self):
        self.assertIsNone(select_overview({}, None, preferred_lang="ru"))
        self.assertIsNone(select_overview(None, "", preferred_lang="en"))
        self.assertEqual(select_overview({"ru": "  Текст  "}, None, preferred_lang="ru"), "Текст")


class TestMetadataClientsOverviewLanguage(unittest.TestCase):
    def test_client_init_stores_overview_language(self):
        tmdb = TMDBClient(overview_language="en")
        self.assertEqual(tmdb.overview_language, "en")

        skyhook = SkyHookClient(overview_language="de")
        self.assertEqual(skyhook.overview_language, "de")

        radarr = RadarrClient(overview_language="original")
        self.assertEqual(radarr.overview_language, "original")

        tvdb = TheTVDBClient(overview_language="fr")
        self.assertEqual(tvdb.overview_language, "fr")

    def test_get_metadata_client_passes_overview_language(self):
        source = MagicMock()
        source.type = "radarr"
        source.api_key = ""
        source.base_url = ""
        source.field_mapping = {}

        client = get_metadata_client(source, overview_language="en")
        self.assertEqual(client.overview_language, "en")

        source.type = "skyhook"
        client2 = get_metadata_client(source, overview_language="original")
        self.assertEqual(client2.overview_language, "original")


class TestRefreshShowMetadataWithOverviewLanguage(unittest.TestCase):
    def test_refresh_show_metadata_applies_preferred_overview_language(self):
        mock_db = MagicMock()
        mock_settings = MagicMock()
        mock_settings.metadata_overview_language = "en"
        mock_settings.metadata_refresh_aliases = True
        mock_db.query().filter().first.return_value = mock_settings

        mock_show = MagicMock()
        mock_show.id = 1
        mock_show.title = "Test Show"
        mock_show.metadata_id = "12345"
        mock_show.metadata_source = "skyhook"
        mock_show.content_type = "series"
        mock_show.overview = "Старое русское описание"
        mock_show.poster_url = ""
        mock_show.rating = 0.0
        mock_show.genre = ""
        mock_show.network = ""
        mock_show.year = 2024
        mock_show.premiere_date = None
        mock_show.episodes = []
        mock_show.aliases = []

        fake_details = MagicMock()
        fake_details.external_id = "tvdb:12345"
        fake_details.title = "Test Show"
        fake_details.overview = "New English overview"
        fake_details.poster_url = "http://poster.jpg"
        fake_details.rating = 8.5
        fake_details.genre = "Drama"
        fake_details.network = "HBO"
        fake_details.year = 2024
        fake_details.premiere_date = "2024-01-01"
        fake_details.in_cinemas_date = None
        fake_details.digital_release_date = None
        fake_details.physical_release_date = None
        fake_details.episodes = []
        fake_details.aliases = ["Test Show Alias"]

        with patch("app.services.metadata.get_metadata_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_details = AsyncMock(return_value=fake_details)
            mock_get_client.return_value = mock_client

            res = asyncio.run(refresh_show_metadata(mock_db, mock_show))
            self.assertTrue(res.get("updated"))
            self.assertEqual(mock_show.overview, "New English overview")


if __name__ == "__main__":
    unittest.main()
