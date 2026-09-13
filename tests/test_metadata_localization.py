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

    def test_skyhook_search_respects_title_language(self):
        skyhook_results = [
            {
                "title": "My Hero Academia",
                "year": 2016,
                "overview": "English overview",
                "tvdbId": 305074,
                "tmdbId": 65930,
            }
        ]
        tmdb_results = {
            "results": [
                {
                    "id": 65930,
                    "name": "Моя геройская академия",
                    "original_name": "僕のヒーローアカデミア",
                    "first_air_date": "2016-04-03",
                    "overview": "В мире, где 80% населения...",
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
                m.json.return_value = tmdb_results
            return m

        mock_client.get = mock_get
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            # When title_language is 'ru'
            client_ru = SkyHookClient(overview_language="ru", title_language="ru")
            res_ru = asyncio.run(client_ru.search("My Hero Academia"))
            self.assertEqual(res_ru[0].title, "Моя геройская академия")
            self.assertEqual(res_ru[0].titles_by_lang["en"], "My Hero Academia")
            self.assertEqual(res_ru[0].titles_by_lang["ru"], "Моя геройская академия")

            # When title_language is 'en'
            client_en = SkyHookClient(overview_language="ru", title_language="en")
            res_en = asyncio.run(client_en.search("My Hero Academia"))
            self.assertEqual(res_en[0].title, "My Hero Academia")
            self.assertEqual(res_en[0].titles_by_lang["en"], "My Hero Academia")
            self.assertEqual(res_en[0].titles_by_lang["ru"], "Моя геройская академия")


try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, Show, Alias, AppSettings, User, Role
    from app.api.shows import bulk_switch_title_language, BulkSwitchTitleLanguageRequest, update_show
    from app.schemas import ShowUpdate
    HAS_DB = True
except ImportError:
    HAS_DB = False


@unittest.skipUnless(HAS_DB, "Database dependencies not available in current environment")
class TestTitleLanguageAndBulkSwitch(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.settings = AppSettings(id=1, metadata_overview_language="ru", metadata_title_language="ru")
        self.db.add(self.settings)

        self.user = User(id=1, username="admin", role=Role.ADMIN, password_hash="hash")
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def test_app_settings_metadata_title_language(self):
        s = self.db.query(AppSettings).filter(AppSettings.id == 1).first()
        self.assertEqual(s.metadata_title_language, "ru")

        s.metadata_title_language = "en"
        self.db.commit()

        s_updated = self.db.query(AppSettings).filter(AppSettings.id == 1).first()
        self.assertEqual(s_updated.metadata_title_language, "en")

    def test_bulk_switch_to_russian_from_aliases(self):
        from app.models.db import Show, Alias
        from app.api.shows import bulk_switch_title_language, BulkSwitchTitleLanguageRequest

        show1 = Show(id=1, title="My Hero Academia", year=2016, content_type="series")
        self.db.add(show1)
        self.db.flush()
        alias1 = Alias(show_id=1, text="Моя геройская академия", language="ru")
        self.db.add(alias1)

        show2 = Show(id=2, title="Атака титанов", year=2013, content_type="series")
        self.db.add(show2)
        self.db.flush()
        alias2 = Alias(show_id=2, text="Attack on Titan", language="en")
        self.db.add(alias2)

        self.db.commit()

        req = BulkSwitchTitleLanguageRequest(show_ids=[1, 2], target_language="ru")
        resp = asyncio.run(bulk_switch_title_language(req, db=self.db, current_user=self.user))

        self.assertEqual(resp.total, 2)
        self.assertEqual(resp.updated, 1)
        self.assertEqual(resp.skipped, 1)

        s1 = self.db.get(Show, 1)
        self.assertEqual(s1.title, "Моя геройская академия")
        alias_texts = {a.text for a in s1.aliases}
        self.assertIn("My Hero Academia", alias_texts)
        self.assertNotIn("Моя геройская академия", alias_texts)

        s2 = self.db.get(Show, 2)
        self.assertEqual(s2.title, "Атака титанов")

    def test_bulk_switch_to_english_from_aliases(self):
        from app.models.db import Show, Alias
        from app.api.shows import bulk_switch_title_language, BulkSwitchTitleLanguageRequest

        show1 = Show(id=1, title="Моя прекрасная няня", year=2004, content_type="series")
        self.db.add(show1)
        self.db.flush()
        alias1 = Alias(show_id=1, text="Moya Prekrasnaya Nyanya", language="en")
        self.db.add(alias1)

        show2 = Show(id=2, title="Breaking Bad", year=2008, content_type="series")
        self.db.add(show2)
        self.db.flush()
        alias2 = Alias(show_id=2, text="Во все тяжкие", language="ru")
        self.db.add(alias2)

        self.db.commit()

        req = BulkSwitchTitleLanguageRequest(show_ids=[1, 2], target_language="en")
        resp = asyncio.run(bulk_switch_title_language(req, db=self.db, current_user=self.user))

        self.assertEqual(resp.total, 2)
        self.assertEqual(resp.updated, 1)
        self.assertEqual(resp.skipped, 1)

        s1 = self.db.get(Show, 1)
        self.assertEqual(s1.title, "Moya Prekrasnaya Nyanya")
        alias_texts = {a.text for a in s1.aliases}
        self.assertIn("Моя прекрасная няня", alias_texts)

        s2 = self.db.get(Show, 2)
        self.assertEqual(s2.title, "Breaking Bad")

    def test_update_show_preserves_old_title_in_aliases(self):
        from app.models.db import Show
        from app.api.shows import update_show
        from app.schemas import ShowUpdate

        show = Show(id=1, title="Breaking Bad", year=2008, content_type="series")
        self.db.add(show)
        self.db.commit()

        payload = ShowUpdate(title="Во все тяжкие")
        res = asyncio.run(update_show(show_id=1, payload=payload, db=self.db, current_user=self.user))

        self.assertEqual(res.title, "Во все тяжкие")
        s = self.db.get(Show, 1)
        self.assertEqual(s.title, "Во все тяжкие")
        alias_texts = {a.text for a in s.aliases}
        self.assertIn("Breaking Bad", alias_texts)

    @patch("app.api.metadata_routes.get_metadata_client")
    def test_get_source_details_normalizes_language(self, mock_get_client):
        from app.api.metadata_routes import get_source_details

        mock_client = AsyncMock()
        mock_details = MagicMock()
        mock_details.external_id = "tvdb:12345"
        mock_details.title = "Default Title"
        mock_details.original_title = "Original Title"
        mock_details.titles_by_lang = {"ru": "Русское название", "en": "English Title"}
        mock_details.year = 2024
        mock_details.overview = "Описание"
        mock_details.poster_url = "http://example.com/poster.jpg"
        mock_details.tmdb_id = 123
        mock_details.tvdb_id = 456
        mock_details.genres = []
        mock_details.network = "HBO"
        mock_details.status = "continuing"
        mock_details.runtime = 45
        mock_details.total_seasons = 1
        mock_details.seasons = []
        mock_client.get_details.return_value = mock_details
        mock_get_client.return_value = mock_client

        res = asyncio.run(
            get_source_details(
                external_id="tvdb:12345",
                source_id=None,
                content_type="series",
                db=self.db,
                current_user=self.user,
            )
        )
        self.assertEqual(res.title, "Русское название")


if __name__ == "__main__":
    unittest.main()

