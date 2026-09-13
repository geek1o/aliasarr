import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.metadata import (
    SkyHookClient,
    MetadataResult,
    MetadataShowDetails,
    MetadataEpisode,
    TMDBClient,
    RadarrClient,
)


class TestSkyhookResilience(unittest.TestCase):

    def test_skyhook_primary_success(self):
        """Проверка успешного поиска через основной Sonarr SkyHook."""
        async def run():
            client = SkyHookClient()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = [
                {
                    "tvdbId": 305074,
                    "title": "Моя геройская академия",
                    "year": 2016,
                    "overview": "В мире, где 80% населения обладает способностями...",
                    "images": [{"coverType": "Poster", "url": "https://artworks.thetvdb.com/posters/305074.jpg"}],
                    "genres": ["Animation", "Action"],
                    "originalCountry": "Japan",
                    "rating": {"value": 8.4},
                }
            ]

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client

            with patch("app.services.metadata.httpx", mock_httpx):
                results = await client.search("Моя геройская академия")

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].external_id, "tvdb:305074")
                self.assertEqual(results[0].title, "Моя геройская академия")
                self.assertEqual(results[0].content_type, "anime")
                self.assertEqual(results[0].year, 2016)

        asyncio.run(run())

    def test_skyhook_backup_fallback_on_primary_failure(self):
        """Проверка переключения на резервный Servarr шлюз при падении основного SkyHook."""
        async def run():
            client = SkyHookClient()

            primary_url = f"{client.base_url}/search/en/"
            backup_url = f"{client.BACKUP_URL}/search/en/"

            async def mock_get_side_effect(url, **kwargs):
                if url == primary_url:
                    raise Exception("Connection timed out after 25s")
                elif url == backup_url:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = [
                        {
                            "tvdbId": 305074,
                            "title": "My Hero Academia (Servarr Backup)",
                            "year": 2016,
                            "genres": ["Animation"],
                            "originalCountry": "JP",
                        }
                    ]
                    return resp
                raise ValueError(f"Unexpected URL: {url}")

            mock_client = AsyncMock()
            mock_client.get.side_effect = mock_get_side_effect
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client

            with patch("app.services.metadata.httpx", mock_httpx):
                results = await client.search("My Hero Academia")

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].external_id, "tvdb:305074")
                self.assertEqual(results[0].title, "My Hero Academia (Servarr Backup)")
                self.assertEqual(results[0].content_type, "anime")

        asyncio.run(run())

    def test_skyhook_tmdb_fallback_when_both_skyhooks_down(self):
        """Проверка автоматического аварийного переключения на TMDb TV, когда оба шлюза SkyHook недоступны."""
        async def run():
            client = SkyHookClient()

            primary_url = f"{client.base_url}/search/en/"
            backup_url = f"{client.BACKUP_URL}/search/en/"
            tmdb_url = f"{client.TMDB_URL}/search/tv"

            async def mock_get_side_effect(url, **kwargs):
                if url in (primary_url, backup_url):
                    raise Exception("Network unreachable")
                elif url == tmdb_url:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {
                        "results": [
                            {
                                "id": 65930,
                                "name": "Моя геройская академия",
                                "original_name": "Boku no Hero Academia",
                                "first_air_date": "2016-04-03",
                                "overview": "Описание из TMDb...",
                                "poster_path": "/path/to/poster.jpg",
                                "vote_average": 8.7,
                                "origin_country": ["JP"],
                            }
                        ]
                    }
                    return resp
                raise ValueError(f"Unexpected URL: {url}")

            mock_client = AsyncMock()
            mock_client.get.side_effect = mock_get_side_effect
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client

            with patch("app.services.metadata.httpx", mock_httpx):
                results = await client.search("Моя геройская академия")

                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].external_id, "tv:65930")
                self.assertEqual(results[0].title, "Моя геройская академия")
                self.assertEqual(results[0].year, 2016)
                self.assertEqual(results[0].content_type, "anime")
                self.assertIn("/path/to/poster.jpg", results[0].poster_url)

        asyncio.run(run())

    def test_skyhook_get_details_tv_prefix(self):
        """Проверка получения деталей по external_id вида 'tv:65930' через TMDB fallback."""
        async def run():
            client = SkyHookClient()

            mock_details = MetadataShowDetails(
                external_id="tv:65930",
                title="Моя геройская академия",
                aliases=["Boku no Hero Academia", "My Hero Academia"],
                overview="Школьник Идзуку Мидория родился без суперспособностей...",
                poster_url="https://image.tmdb.org/t/p/w500/poster.jpg",
                episodes=[
                    MetadataEpisode(season_number=1, episode_number=1, title="Идзуку Мидория: Происхождение"),
                ],
                rating=8.7,
                country="JP",
                content_type="anime",
                tmdb_id=65930,
                tvdb_id=305074,
            )

            with patch("app.services.metadata.TMDBClient._get_tv_details", new_callable=AsyncMock) as mock_tv:
                mock_tv.return_value = mock_details
                details = await client.get_details("tv:65930")

                self.assertEqual(details.external_id, "tv:65930")
                self.assertEqual(details.title, "Моя геройская академия")
                self.assertEqual(details.tvdb_id, 305074)
                self.assertEqual(len(details.episodes), 1)

        asyncio.run(run())

    def test_search_all_metadata_sources_emergency_tv_fallback(self):
        """Проверка, что поиск 'Все источники' гарантированно возвращает и фильмы, и сериалы, даже если SkyHook упал."""
        try:
            import fastapi
        except ImportError:
            self.skipTest("FastAPI not installed in host environment")

        async def run():
            from app.api.metadata_routes import search_all_metadata_sources

            movie_results = [
                MetadataResult(
                    external_id="movie:1001",
                    title="Моя геройская академия: Миссия мировых героев",
                    year=2021,
                    content_type="movie",
                ),
                MetadataResult(
                    external_id="movie:1002",
                    title="Моя геройская академия: Восхождение героев",
                    year=2019,
                    content_type="movie",
                ),
            ]

            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.all.return_value = []
            mock_db.query.return_value.filter.return_value.first.return_value = None

            with patch.object(RadarrClient, "search", new_callable=AsyncMock, return_value=movie_results), \
                 patch.object(SkyHookClient, "search", new_callable=AsyncMock, return_value=[]), \
                 patch.object(TMDBClient, "search", new_callable=AsyncMock) as mock_tmdb_search, \
                 patch("app.api.metadata_routes._find_existing_show", return_value=None):

                mock_tmdb_search.return_value = [
                    MetadataResult(
                        external_id="tv:65930",
                        title="Моя геройская академия",
                        year=2016,
                        content_type="anime",
                    )
                ]

                res = await search_all_metadata_sources(query="Моя геройская академия", db=mock_db, current_user=MagicMock())

                content_types = {r.content_type for r in res}
                self.assertIn("movie", content_types)
                self.assertIn("anime", content_types)
                self.assertEqual(len(res), 3)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
