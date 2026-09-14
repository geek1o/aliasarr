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


class TestLanguageCodeNormalization(unittest.TestCase):
    def test_ukrainian_not_mapped_to_english(self):
        from app.services.metadata import normalize_metadata_lang_code
        self.assertEqual(normalize_metadata_lang_code("uk"), "uk")
        self.assertEqual(normalize_metadata_lang_code("ukr"), "uk")
        self.assertEqual(normalize_metadata_lang_code("ukrainian"), "uk")
        self.assertEqual(normalize_metadata_lang_code("UA"), "uk")
        self.assertNotEqual(normalize_metadata_lang_code("uk"), "en")

    def test_arabic_not_mapped_to_spanish(self):
        from app.services.metadata import normalize_metadata_lang_code
        self.assertEqual(normalize_metadata_lang_code("ar"), "ar")
        self.assertEqual(normalize_metadata_lang_code("ara"), "ar")
        self.assertEqual(normalize_metadata_lang_code("arabic"), "ar")
        # Country AR is Argentina -> Spanish
        self.assertEqual(normalize_metadata_lang_code("AR"), "es")

    def test_country_codes_mapped_correctly(self):
        from app.services.metadata import normalize_metadata_lang_code
        self.assertEqual(normalize_metadata_lang_code("GB"), "en")
        self.assertEqual(normalize_metadata_lang_code("US"), "en")
        self.assertEqual(normalize_metadata_lang_code("RU"), "ru")
        self.assertEqual(normalize_metadata_lang_code("JP"), "ja")

    def test_overview_fallback_with_ukrainian_and_english(self):
        from app.services.metadata import select_overview
        overviews = {
            "en": "Doug and Griff are inseparable childhood friends...",
            "ru": "Даг и Грифф — неразлучные друзья с детства...",
            "uk": "Даг і Гріфф — нерозлучні друзі з дитинства...",
        }
        # When Japanese is preferred but missing, fall back to English (not Ukrainian)
        res_ja = select_overview(overviews, original_overview="Doug and Griff...", preferred_lang="ja")
        self.assertEqual(res_ja, "Doug and Griff are inseparable childhood friends...")

        # When Russian is preferred, select Russian
        res_ru = select_overview(overviews, original_overview="Doug and Griff...", preferred_lang="ru")
        self.assertEqual(res_ru, "Даг и Грифф — неразлучные друзья с детства...")

        # When Ukrainian is preferred, select Ukrainian
        res_uk = select_overview(overviews, original_overview="Doug and Griff...", preferred_lang="uk")
        self.assertEqual(res_uk, "Даг і Гріфф — нерозлучні друзі з дитинства...")


class TestTVDetailsAndSkyHookEnrichment(unittest.TestCase):
    def test_tmdb_get_tv_details_variables_and_overview(self):
        from app.services.metadata import TMDBClient

        tmdb_data = {
            "name": "The Expanse",
            "original_name": "The Expanse",
            "overview": "A thriller set two hundred years in the future...",
            "translations": {
                "translations": [
                    {
                        "iso_639_1": "ru",
                        "iso_3166_1": "RU",
                        "data": {
                            "name": "Пространство",
                            "overview": "В начале XXIII века детектив..."
                        }
                    },
                    {
                        "iso_639_1": "en",
                        "iso_3166_1": "US",
                        "data": {
                            "name": "The Expanse",
                            "overview": "A thriller set two hundred years in the future..."
                        }
                    }
                ]
            },
            "alternative_titles": {
                "results": [
                    {"title": "Экспансия", "iso_3166_1": "RU"}
                ]
            },
            "seasons": []
        }

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = tmdb_data
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            client = TMDBClient(overview_language="ru")
            details = asyncio.run(client._get_tv_details("63639", fetch_episodes=False))
            self.assertEqual(details.overview, "В начале XXIII века детектив...")
            self.assertIn("Пространство", details.aliases)
            self.assertIn("Экспансия", details.aliases)

    def test_skyhook_client_enriches_tv_series_with_tmdb_russian_overview(self):
        from app.services.metadata import SkyHookClient

        skyhook_data = {
            "title": "The Expanse",
            "overview": "Two hundred years in the future (SkyHook English)",
            "tmdbId": 63639,
            "tvdbId": 280619,
            "episodes": [],
            "images": []
        }
        tmdb_data = {
            "name": "The Expanse",
            "overview": "Default TMDB English",
            "translations": {
                "translations": [
                    {
                        "iso_639_1": "ru",
                        "iso_3166_1": "RU",
                        "data": {
                            "name": "Пространство",
                            "overview": "В начале XXIII века детектив..."
                        }
                    }
                ]
            },
            "alternative_titles": {
                "results": [
                    {"title": "Экспансия", "iso_3166_1": "RU"}
                ]
            },
            "seasons": []
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            m = MagicMock()
            m.status_code = 200
            if "skyhook" in url:
                if "/shows/en/" in url:
                    m.json.return_value = skyhook_data
                else:
                    m.status_code = 400
            elif "api.themoviedb.org" in url:
                m.json.return_value = tmdb_data
            return m

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            client = SkyHookClient(overview_language="ru")
            details = asyncio.run(client.get_details("tvdb:280619"))
            self.assertEqual(details.overview, "В начале XXIII века детектив...")
            self.assertIn("Пространство", details.aliases)
            self.assertIn("Экспансия", details.aliases)


class TestCollectionDetailsOverviewLanguage(unittest.TestCase):
    def setUp(self):
        from app.services.metadata import _COLLECTION_DETAILS_CACHE
        _COLLECTION_DETAILS_CACHE.clear()

    def test_collection_details_requests_russian_language(self):
        from app.services.metadata import TMDBClient

        client = TMDBClient(overview_language="ru")
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "id": 1001,
            "name": "Гарри Поттер (Коллекция)",
            "overview": "История юного волшебника Гарри Поттера...",
            "parts": [
                {
                    "id": 101,
                    "title": "Гарри Поттер и философский камень",
                    "overview": "Одиннадцатилетний мальчик-сирота...",
                    "release_date": "2001-11-16",
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(1001))
            self.assertEqual(res["name"], "Гарри Поттер (Коллекция)")
            self.assertEqual(res["overview"], "История юного волшебника Гарри Поттера...")
            self.assertEqual(res["parts"][0]["title"], "Гарри Поттер и философский камень")
            self.assertEqual(res["parts"][0]["overview"], "Одиннадцатилетний мальчик-сирота...")

            # Verify that TMDb was queried with language=ru-RU
            self.assertTrue(mock_client.get.called)
            first_call = mock_client.get.call_args_list[0]
            self.assertEqual(first_call[1].get("params", {}).get("language"), "ru-RU")

    def test_collection_details_requests_english_language(self):
        from app.services.metadata import TMDBClient

        client = TMDBClient(overview_language="en")
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "id": 1001,
            "name": "Harry Potter Collection",
            "overview": "The story of a young wizard...",
            "parts": [
                {
                    "id": 101,
                    "title": "Harry Potter and the Philosopher's Stone",
                    "overview": "An eleven-year-old orphan...",
                    "release_date": "2001-11-16",
                }
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(1001))
            self.assertEqual(res["name"], "Harry Potter Collection")
            self.assertTrue(mock_client.get.called)
            first_call = mock_client.get.call_args_list[0]
            self.assertEqual(first_call[1].get("params", {}).get("language"), "en-US")

    def test_collection_details_fallback_to_english_when_russian_missing(self):
        from app.services.metadata import TMDBClient

        client = TMDBClient(overview_language="ru")

        ru_resp = MagicMock()
        ru_resp.status_code = 200
        ru_resp.raise_for_status = MagicMock()
        ru_resp.json.return_value = {
            "id": 2002,
            "name": "Редкая сага",
            "overview": "",  # Пустой синопсис в русском TMDb
            "parts": [
                {
                    "id": 201,
                    "title": "Часть 1",
                    "overview": "",
                    "release_date": "2020-01-01",
                }
            ],
        }

        en_resp = MagicMock()
        en_resp.status_code = 200
        en_resp.raise_for_status = MagicMock()
        en_resp.json.return_value = {
            "id": 2002,
            "name": "Rare Saga",
            "overview": "English saga overview fallback",
            "parts": [
                {
                    "id": 201,
                    "title": "Part 1",
                    "overview": "English part 1 overview",
                    "release_date": "2020-01-01",
                }
            ],
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            lang = kwargs.get("params", {}).get("language")
            if lang == "ru-RU":
                return ru_resp
            elif lang == "en-US":
                return en_resp
            return ru_resp

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(2002))
            self.assertEqual(res["name"], "Редкая сага")
            # Should have fallen back to English overview
            self.assertEqual(res["overview"], "English saga overview fallback")
            self.assertEqual(res["parts"][0]["overview"], "English part 1 overview")

    def test_collection_cache_partitioned_by_language_and_bypass(self):
        from app.services.metadata import TMDBClient, _COLLECTION_DETAILS_CACHE

        _COLLECTION_DETAILS_CACHE.clear()
        client_ru = TMDBClient(overview_language="ru")
        client_en = TMDBClient(overview_language="en")

        resp_ru = MagicMock()
        resp_ru.status_code = 200
        resp_ru.raise_for_status = MagicMock()
        resp_ru.json.return_value = {
            "id": 3003,
            "name": "Русская сага",
            "overview": "Русское описание",
            "parts": [],
        }

        resp_en = MagicMock()
        resp_en.status_code = 200
        resp_en.raise_for_status = MagicMock()
        resp_en.json.return_value = {
            "id": 3003,
            "name": "English Saga",
            "overview": "English overview",
            "parts": [],
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            lang = kwargs.get("params", {}).get("language")
            return resp_ru if lang == "ru-RU" else resp_en

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res_ru = asyncio.run(client_ru.get_collection_details(3003))
            self.assertEqual(res_ru["overview"], "Русское описание")
            self.assertIn("3003_ru-RU", _COLLECTION_DETAILS_CACHE)

            res_en = asyncio.run(client_en.get_collection_details(3003))
            self.assertEqual(res_en["overview"], "English overview")
            self.assertIn("3003_en-US", _COLLECTION_DETAILS_CACHE)

    def test_radarr_client_forwards_overview_language_to_collection_details(self):
        from app.services.metadata import RadarrClient

        client = RadarrClient(overview_language="ru")
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {
            "id": 4004,
            "name": "Сага Радарр",
            "overview": "Описание",
            "parts": [],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=fake_resp)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(4004))
            self.assertEqual(res["name"], "Сага Радарр")
            self.assertTrue(mock_client.get.called)
            first_call = mock_client.get.call_args_list[0]
            self.assertEqual(first_call[1].get("params", {}).get("language"), "ru-RU")


if __name__ == "__main__":
    unittest.main()
