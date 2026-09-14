from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.metadata import TMDBClient, RadarrClient, refresh_all_collections_metadata


class TestCollectionTitleLanguage(unittest.TestCase):
    def test_tmdb_client_collection_details_bilingual_titles(self):
        client = TMDBClient(overview_language="ru")
        ru_resp = MagicMock()
        ru_resp.status_code = 200
        ru_resp.raise_for_status = MagicMock()
        ru_resp.json.return_value = {
            "id": 87096,
            "name": "Аватар (Коллекция)",
            "overview": "Фантастическая франшиза Джеймса Кэмерона...",
            "parts": [
                {"id": 19995, "title": "Аватар", "overview": "Бывший морпех...", "release_date": "2009-12-15"}
            ],
        }

        en_resp = MagicMock()
        en_resp.status_code = 200
        en_resp.raise_for_status = MagicMock()
        en_resp.json.return_value = {
            "id": 87096,
            "name": "Avatar Collection",
            "overview": "An epic sci-fi film series...",
            "parts": [
                {"id": 19995, "title": "Avatar", "overview": "A paraplegic Marine...", "release_date": "2009-12-15"}
            ],
        }

        trans_resp = MagicMock()
        trans_resp.status_code = 200
        trans_resp.raise_for_status = MagicMock()
        trans_resp.json.return_value = {
            "id": 87096,
            "translations": [
                {"iso_639_1": "ru", "data": {"title": "Аватар (Коллекция)"}},
                {"iso_639_1": "en", "data": {"title": "Avatar Collection"}},
                {"iso_639_1": "fr", "data": {"title": "Avatar (Collection)"}},
            ],
        }

        async def fake_get(url, **kwargs):
            if "translations" in str(url):
                return trans_resp
            params = kwargs.get("params", {})
            lang = params.get("language")
            if lang == "ru-RU":
                return ru_resp
            return en_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(87096, lang="ru"))
            self.assertEqual(res["name"], "Аватар (Коллекция)")
            self.assertIn("titles_by_lang", res)
            self.assertEqual(res["titles_by_lang"].get("ru"), "Аватар (Коллекция)")
            self.assertEqual(res["titles_by_lang"].get("en"), "Avatar Collection")
            self.assertEqual(res["titles_by_lang"].get("fr"), "Avatar (Collection)")

    def test_tmdb_client_collection_details_english_preferred(self):
        client = TMDBClient(overview_language="en")
        en_resp = MagicMock()
        en_resp.status_code = 200
        en_resp.raise_for_status = MagicMock()
        en_resp.json.return_value = {
            "id": 1001,
            "name": "Dune Collection",
            "overview": "Sci-fi epic...",
            "parts": [],
        }

        ru_resp = MagicMock()
        ru_resp.status_code = 200
        ru_resp.raise_for_status = MagicMock()
        ru_resp.json.return_value = {
            "id": 1001,
            "name": "Дюна (Коллекция)",
            "overview": "Фантастическая сага...",
            "parts": [],
        }

        trans_resp = MagicMock()
        trans_resp.status_code = 200
        trans_resp.raise_for_status = MagicMock()
        trans_resp.json.return_value = {
            "id": 1001,
            "translations": [
                {"iso_639_1": "ru", "data": {"title": "Дюна (Коллекция)"}},
                {"iso_639_1": "en", "data": {"title": "Dune Collection"}},
            ],
        }

        async def fake_get(url, **kwargs):
            if "translations" in str(url):
                return trans_resp
            params = kwargs.get("params", {})
            lang = params.get("language")
            if lang == "en-US":
                return en_resp
            return ru_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(1001, lang="en"))
            self.assertEqual(res["name"], "Dune Collection")
            self.assertIn("titles_by_lang", res)
            self.assertEqual(res["titles_by_lang"].get("en"), "Dune Collection")
            self.assertEqual(res["titles_by_lang"].get("ru"), "Дюна (Коллекция)")

    def test_tmdb_client_collection_details_cjk_fallback_does_not_map_to_ru(self):
        from app.services.metadata import TMDBClient

        client = TMDBClient(overview_language="ru")
        cjk_resp = MagicMock()
        cjk_resp.status_code = 200
        cjk_resp.raise_for_status = MagicMock()
        cjk_resp.json.return_value = {
            "id": 99999,
            "name": "罗小黑战记（系列）",
            "original_language": "zh",
            "overview": "",
            "parts": [],
        }

        en_resp = MagicMock()
        en_resp.status_code = 200
        en_resp.raise_for_status = MagicMock()
        en_resp.json.return_value = {
            "id": 99999,
            "name": "The Legend of Hei Collection",
            "overview": "Fantasy anime series...",
            "parts": [],
        }

        trans_resp = MagicMock()
        trans_resp.status_code = 200
        trans_resp.raise_for_status = MagicMock()
        trans_resp.json.return_value = {
            "id": 99999,
            "translations": [
                {"iso_639_1": "en", "data": {"title": "The Legend of Hei Collection"}},
                {"iso_639_1": "zh", "data": {"title": "罗小黑战记（系列）"}},
                {"iso_639_1": "ru", "data": {"title": ""}},
            ],
        }

        async def fake_get(url, **kwargs):
            if "translations" in str(url):
                return trans_resp
            params = kwargs.get("params", {})
            lang = params.get("language")
            if lang == "ru-RU":
                return cjk_resp
            return en_resp

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=fake_get)
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch("app.services.metadata.httpx", mock_httpx):
            res = asyncio.run(client.get_collection_details(99999, lang="ru"))
            self.assertEqual(res["name"], "The Legend of Hei Collection")
            self.assertNotIn("ru", res["titles_by_lang"])
            self.assertEqual(res["titles_by_lang"].get("en"), "The Legend of Hei Collection")
            self.assertEqual(res["titles_by_lang"].get("zh"), "罗小黑战记（系列）")

    def test_refresh_all_collections_metadata_updates_title_by_lang_setting(self):
        coll = MagicMock()
        coll.id = 55
        coll.tmdb_collection_id = 87096
        coll.title = "Avatar Collection"
        coll.titles_cache = None
        coll.overview = None
        coll.poster_url = None
        coll.backdrop_url = None

        app_settings = MagicMock()
        app_settings.metadata_overview_language = "ru"
        app_settings.metadata_collection_title_language = "ru"

        query_mock = MagicMock()
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = [coll]
        filter_mock.first.return_value = app_settings

        mock_db = MagicMock()
        mock_db.query.return_value = query_mock
        mock_db.get.return_value = coll

        fake_details = {
            "id": 87096,
            "name": "Аватар (Коллекция)",
            "overview": "Описание франшизы",
            "parts": [{"id": 19995, "title": "Аватар"}],
            "titles_by_lang": {
                "ru": "Аватар (Коллекция)",
                "en": "Avatar Collection",
            },
        }

        mock_radarr_client = MagicMock()
        mock_radarr_client.get_collection_details = AsyncMock(return_value=fake_details)

        with patch("app.services.metadata.RadarrClient", return_value=mock_radarr_client):
            res = asyncio.run(refresh_all_collections_metadata(mock_db))
            self.assertEqual(res.get("updated"), 1)
            self.assertEqual(coll.title, "Аватар (Коллекция)")
            self.assertIsNotNone(coll.titles_cache)
            tbl = json.loads(coll.titles_cache)
            self.assertEqual(tbl.get("ru"), "Аватар (Коллекция)")
            self.assertEqual(tbl.get("en"), "Avatar Collection")

    def test_refresh_all_collections_metadata_with_session_local(self):
        coll = MagicMock()
        coll.id = 55
        coll.tmdb_collection_id = 87096
        coll.title = "Avatar Collection"
        coll.titles_cache = None
        coll.overview = None
        coll.poster_url = None
        coll.backdrop_url = None
        coll.parts_cache = None
        coll.last_metadata_refresh_at = None

        app_settings = MagicMock()
        app_settings.metadata_overview_language = "ru"
        app_settings.metadata_collection_title_language = "ru"

        query_mock = MagicMock()
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock
        filter_mock.all.return_value = [coll]
        filter_mock.first.return_value = app_settings

        mock_db = MagicMock()
        mock_db.query.return_value = query_mock
        mock_db.get.return_value = coll

        fake_details = {
            "id": 87096,
            "name": "Аватар (Коллекция)",
            "overview": "Описание франшизы",
            "parts": [{"id": 19995, "title": "Аватар"}],
            "titles_by_lang": {
                "ru": "Аватар (Коллекция)",
                "en": "Avatar Collection",
            },
        }

        mock_radarr_client = MagicMock()
        mock_radarr_client.get_collection_details = AsyncMock(return_value=fake_details)

        mock_session_factory = MagicMock(return_value=mock_db)
        mock_database_module = MagicMock()
        mock_database_module.SessionLocal = mock_session_factory

        with patch.dict("sys.modules", {"app.database": mock_database_module}), \
             patch("app.services.metadata.RadarrClient", return_value=mock_radarr_client):
            res = asyncio.run(refresh_all_collections_metadata(db=None))
            self.assertEqual(res.get("updated"), 1)
            self.assertEqual(coll.title, "Аватар (Коллекция)")


if __name__ == "__main__":
    unittest.main()
