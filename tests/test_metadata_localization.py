from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.metadata import (
    MetadataResult,
    MetadataShowDetails,
    SkyHookClient,
    TMDBClient,
    RadarrClient,
)


class TestMetadataLocalizationModels(unittest.TestCase):
    def test_metadata_result_fields(self):
        r = MetadataResult(
            external_id="tvdb:123",
            title="Моя геройская академия",
            original_title="僕のヒーローアカデミア",
            titles_by_lang={"ru": "Моя геройская академия", "en": "My Hero Academia", "original": "僕のヒーローアカデミア"},
            year=2016,
            overview="В мире, где 80% населения рождается с причудами...",
        )
        self.assertEqual(r.title, "Моя геройская академия")
        self.assertEqual(r.original_title, "僕のヒーローアカデミア")
        self.assertEqual(r.titles_by_lang["en"], "My Hero Academia")

    def test_metadata_show_details_fields(self):
        d = MetadataShowDetails(
            external_id="tvdb:123",
            title="My Hero Academia",
            original_title="僕のヒーローアカдемия",
            titles_by_lang={"ru": "Моя геройская академия", "en": "My Hero Academia", "original": "僕のヒーローアカдемия"},
            year=2016,
            overview="В мире, где 80% населения рождается с причудами...",
        )
        self.assertEqual(d.title, "My Hero Academia")
        self.assertEqual(d.original_title, "僕のヒーローアカдемия")
        self.assertEqual(d.titles_by_lang["ru"], "Моя геройская академия")

    def test_metadata_api_routes_schemas_when_available(self):
        try:
            from app.api.metadata_routes import (
                MetadataSearchResultOut,
                MetadataDetailsOut,
                ImportShowRequest,
            )
            out = MetadataSearchResultOut(
                external_id="tvdb:123",
                title="Моя геройская академия",
                original_title="僕のヒーローアカдемия",
                titles_by_lang={"ru": "Моя геройская академия", "en": "My Hero Academia"},
                year=2016,
                overview="Описание",
            )
            dumped = out.model_dump()
            self.assertEqual(dumped["title"], "Моя геройская академия")
            self.assertEqual(dumped["original_title"], "僕のヒーローアカдемия")
            self.assertEqual(dumped["titles_by_lang"]["ru"], "Моя геройская академия")
            self.assertEqual(dumped["titles_by_lang"]["en"], "My Hero Academia")

            det = MetadataDetailsOut(
                external_id="tvdb:123",
                title="My Hero Academia",
                original_title="僕のヒーローアカдемия",
                titles_by_lang={"ru": "Моя геройская академия", "en": "My Hero Academia"},
                year=2016,
                overview="Описание",
                aliases=["Boku no Hero Academia"],
            )
            det_dumped = det.model_dump()
            self.assertEqual(det_dumped["original_title"], "僕のヒーローアカдемия")
            self.assertIn("ru", det_dumped["titles_by_lang"])

            req = ImportShowRequest(
                external_id="tvdb:123",
                content_type="series",
                title="Моя геройская академия",
            )
            self.assertEqual(req.title, "Моя геройская академия")
        except ImportError:
            pass


class TestSkyHookLocalizationEnrichment(unittest.TestCase):
    def test_skyhook_search_enriches_with_tmdb_russian_title_and_overview(self):
        skyhook_results = [
            {
                "title": "My Hero Academia",
                "year": 2016,
                "overview": "English synopsis from Skyhook",
                "tvdbId": 305074,
                "tmdbId": 65930,
            }
        ]

        tmdb_search_results = {
            "results": [
                {
                    "id": 65930,
                    "name": "Моя геройская академия",
                    "original_name": "僕のヒーローアカдемия",
                    "overview": "В мире, где 80% населения рождается с причудами...",
                    "first_air_date": "2016-04-03",
                }
            ]
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            m = MagicMock()
            m.status_code = 200
            if "skyhook" in url:
                m.json.return_value = skyhook_results
            elif "api.themoviedb.org" in url:
                m.json.return_value = tmdb_search_results
            return m

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            client = SkyHookClient(overview_language="ru")
            results = asyncio.run(client.search("My Hero Academia"))

            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res.title, "Моя геройская академия")
            self.assertEqual(res.original_title, "僕のヒーローアカдемия")
            self.assertEqual(res.titles_by_lang["ru"], "Моя геройская академия")
            self.assertEqual(res.titles_by_lang["en"], "My Hero Academia")
            self.assertEqual(res.titles_by_lang["original"], "僕のヒーローアカдемия")
            self.assertIn("80% населения", res.overview)

    def test_skyhook_search_transliterated_query_enriches_via_tmdb_id(self):
        # Transliterated title in Skyhook
        skyhook_results = [
            {
                "title": "Moya Prekrasnaya Nyanya",
                "year": 2004,
                "overview": "English overview",
                "tvdbId": 81504,
                "tmdbId": 33123,
            }
        ]

        tmdb_by_id_response = {
            "id": 33123,
            "name": "Moya Prekrasnaya Nyanya",
            "original_name": "Моя прекрасная няня",
            "original_language": "ru",
            "overview": "Виктория Прутковская до пятнадцати лет жила в Мариуполе...",
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            m = MagicMock()
            m.status_code = 200
            if "skyhook" in url:
                m.json.return_value = skyhook_results
            elif "api.themoviedb.org/3/search/tv" in url:
                # Transliterated text search in TMDb returns 0 results
                m.json.return_value = {"results": []}
            elif "api.themoviedb.org/3/tv/33123" in url:
                # Direct ID lookup returns Russian info
                m.json.return_value = tmdb_by_id_response
            else:
                m.json.return_value = {}
            return m

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            client = SkyHookClient(overview_language="ru")
            results = asyncio.run(client.search("Moya Prekrasnaya Nyanya"))

            self.assertEqual(len(results), 1)
            res = results[0]
            self.assertEqual(res.title, "Моя прекрасная няня")
            self.assertEqual(res.original_title, "Моя прекрасная няня")
            self.assertEqual(res.titles_by_lang["ru"], "Моя прекрасная няня")
            self.assertEqual(res.titles_by_lang["en"], "Moya Prekrasnaya Nyanya")
            self.assertIn("Виктория Прутковская", res.overview)

    def test_tmdb_tv_details_fallback_to_original_name_when_ru_translation_empty(self):
        translations_data = {
            "translations": [
                {
                    "iso_639_1": "ru",
                    "data": {
                        "name": "",
                        "overview": "Виктория Прутковская...",
                    },
                },
                {
                    "iso_639_1": "en",
                    "data": {
                        "name": "My Fair Nanny",
                        "overview": "Russian sitcom based on The Nanny...",
                    },
                },
            ]
        }
        show_data = {
            "id": 33123,
            "name": "Moya Prekrasnaya Nyanya",
            "original_name": "Моя прекрасная няня",
            "original_language": "ru",
            "first_air_date": "2004-09-27",
            "overview": "",
            "number_of_seasons": 0,
            "seasons": [],
            "external_ids": {"tvdb_id": 81504},
            "translations": translations_data,
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            m = MagicMock()
            m.status_code = 200
            m.json.return_value = show_data
            return m

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            client = TMDBClient(api_key="fake_key", overview_language="ru")
            details = asyncio.run(client.get_details("tmdb:33123"))

            self.assertEqual(details.original_title, "Моя прекрасная няня")
            self.assertEqual(details.titles_by_lang["ru"], "Моя прекрасная няня")
            self.assertEqual(details.titles_by_lang["en"], "My Fair Nanny")
            self.assertIn("Виктория Прутковская", details.overview)

    def test_skyhook_details_enrichment_for_transliterated_show(self):
        skyhook_show_data = {
            "tvdbId": 81504,
            "title": "Moya Prekrasnaya Nyanya",
            "overview": "English synopsis",
            "tmdbId": 33123,
            "seasons": [],
            "episodes": [],
        }

        tmdb_show_data = {
            "id": 33123,
            "name": "Moya Prekrasnaya Nyanya",
            "original_name": "Моя прекрасная няня",
            "original_language": "ru",
            "first_air_date": "2004-09-27",
            "overview": "",
            "number_of_seasons": 0,
            "seasons": [],
            "external_ids": {"tvdb_id": 81504},
            "translations": {
                "translations": [
                    {
                        "iso_639_1": "ru",
                        "data": {
                            "name": "",
                            "overview": "Виктория Прутковская до пятнадцати лет жила в Мариуполе...",
                        },
                    }
                ]
            },
        }

        mock_client = AsyncMock()
        async def mock_get(url, **kwargs):
            m = MagicMock()
            m.status_code = 200
            if "skyhook" in url:
                m.json.return_value = skyhook_show_data
            else:
                m.json.return_value = tmdb_show_data
            return m

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            client = SkyHookClient(overview_language="ru")
            details = asyncio.run(client.get_details("tvdb:81504"))

            self.assertEqual(details.original_title, "Моя прекрасная няня")
            self.assertEqual(details.titles_by_lang["ru"], "Моя прекрасная няня")
            self.assertEqual(details.titles_by_lang["en"], "Moya Prekrasnaya Nyanya")
            self.assertIn("Виктория Прутковская", details.overview)
            self.assertIn("Моя прекрасная няня", details.aliases)


if __name__ == "__main__":
    unittest.main()
