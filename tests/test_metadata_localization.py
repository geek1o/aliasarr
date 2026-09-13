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


if __name__ == "__main__":
    unittest.main()
