from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.api import shows
    from app.api.metadata_routes import normalize_metadata_lang_code
    from app.services import matcher, metadata, postprocess
    from app.services.download_client import RTorrentClient
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "FastAPI / dependencies not installed in host runner")
class TestRuntimeNameRegressions(unittest.TestCase):
    def test_metadata_language_normalizer_is_available_to_routes(self):
        self.assertEqual(normalize_metadata_lang_code("ru-RU"), "ru")

    def test_parser_and_typing_names_are_resolvable(self):
        self.assertTrue(hasattr(shows, "ParsedRelease"))
        self.assertIn("Any", matcher._is_int.__annotations__["v"])
        self.assertIn("Session", metadata.trigger_show_metadata_refresh_if_needed.__annotations__["db"])

    def test_manual_import_tracks_destinations_locally(self):
        local_names = shows.execute_global_manual_import.__code__.co_varnames
        self.assertIn("used_dest_paths", local_names)
        self.assertIn("just_written_files", local_names)

    def test_postprocess_uses_module_level_database_and_quality_names(self):
        for function in (postprocess.process_download, postprocess.process_movie_download):
            local_names = function.__code__.co_varnames
            self.assertNotIn("DownloadHistory", local_names)
            self.assertNotIn("TrackedRelease", local_names)
            self.assertNotIn("parse_quality", local_names)

    def test_rtorrent_http_upload_wraps_payload_as_xmlrpc_binary(self):
        response = MagicMock(content=b"torrent-data")
        response.raise_for_status.return_value = None
        http_client = AsyncMock()
        http_client.get.return_value = response
        http_client.__aenter__.return_value = http_client
        http_client.__aexit__.return_value = None

        client = RTorrentClient("localhost", 5000)
        client._call = AsyncMock()
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = http_client

        with patch("app.services.download_client.httpx", mock_httpx):
            asyncio.run(client.add_torrent("https://example.test/file.torrent"))

        payload = client._call.await_args.args[2]
        self.assertEqual(payload.data, b"torrent-data")

    def test_radarr_tmdb_fallback_builds_poster_url(self):
        async def fake_get(url, **kwargs):
            response = MagicMock()
            if "/search/movie" in url:
                response.status_code = 200
                response.json.return_value = {
                    "results": [
                        {
                            "id": 42,
                            "title": "Тестовый фильм",
                            "original_title": "Test Movie",
                            "poster_path": "/poster.jpg",
                            "release_date": "2024-01-01",
                        }
                    ]
                }
            else:
                response.status_code = 503
            return response

        http_client = AsyncMock()
        http_client.get = fake_get
        http_client.__aenter__.return_value = http_client
        http_client.__aexit__.return_value = None
        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = http_client

        with patch("app.services.metadata.httpx", mock_httpx):
            results = asyncio.run(metadata.RadarrClient().search("Test Movie"))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].poster_url, "https://image.tmdb.org/t/p/w500/poster.jpg")


if __name__ == "__main__":
    unittest.main()
