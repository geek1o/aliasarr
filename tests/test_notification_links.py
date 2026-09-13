from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.show_links import (
    resolve_show_external_link,
    build_series_add_notification_message,
    PROVIDER_DISPLAY_NAMES,
)
from app.services.notifications import (
    _html_to_markdown,
    _html_to_slack_mrkdwn,
    _strip_html,
    format_notification_message,
)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, AppSettings, Show, User
    from app.services.settings_service import get_or_create_settings
    from app.api.settings_routes import update_settings, SettingsUpdate, get_settings
    from fastapi import HTTPException
    HAS_DB_DEPS = True
except ImportError:
    HAS_DB_DEPS = False


class TestNotificationLinks(unittest.TestCase):
    def test_movie_link_sources(self):
        show = SimpleNamespace(
            id=1,
            title="Бойцовский клуб",
            year=1999,
            content_type="movie",
            tmdb_id=550,
            imdb_id="tt0137523",
            tvdb_id=None,
            tvmaze_id=None,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            shikimori_id=None,
            trailer_url="https://www.youtube.com/watch?v=qtRKDV93gkQ",
        )

        url, name = resolve_show_external_link(show, "tmdb")
        self.assertEqual(url, "https://www.themoviedb.org/movie/550")
        self.assertEqual(name, "TMDB")

        url, name = resolve_show_external_link(show, "imdb")
        self.assertEqual(url, "https://imdb.com/title/tt0137523/")
        self.assertEqual(name, "IMDb")

        url, name = resolve_show_external_link(show, "kinopoisk")
        self.assertIn("kinopoisk.ru", url)
        self.assertIn("%D0%91%D0%BE%D0%B9%D1%86%D0%BE%D0%B2%D1%81%D0%BA%D0%B8%D0%B9", url)
        self.assertEqual(name, "Кинопоиск")

        url, name = resolve_show_external_link(show, "trakt")
        self.assertEqual(url, "https://trakt.tv/search/tmdb/550?id_type=movie")
        self.assertEqual(name, "Trakt")

        url, name = resolve_show_external_link(show, "letterboxd")
        self.assertEqual(url, "https://letterboxd.com/tmdb/550")
        self.assertEqual(name, "Letterboxd")

        url, name = resolve_show_external_link(show, "mdblist")
        self.assertEqual(url, "https://mdblist.com/movie/tt0137523")
        self.assertEqual(name, "MDBList")

        url, name = resolve_show_external_link(show, "moviechat")
        self.assertEqual(url, "https://moviechat.org/tt0137523/")
        self.assertEqual(name, "MovieChat")

        url, name = resolve_show_external_link(show, "bluray")
        self.assertIn("blu-ray.com", url)
        self.assertIn("tt0137523", url)
        self.assertEqual(name, "Blu-ray")

        url, name = resolve_show_external_link(show, "trailer")
        self.assertEqual(url, "https://www.youtube.com/watch?v=qtRKDV93gkQ")
        self.assertEqual(name, "Трейлер")

        url, name = resolve_show_external_link(show, "none")
        self.assertIsNone(url)
        self.assertEqual(name, "")

    def test_series_link_sources(self):
        show = SimpleNamespace(
            id=2,
            title="Во все тяжкие",
            year=2008,
            content_type="series",
            tvdb_id=81189,
            tmdb_id=1396,
            imdb_id="tt0903747",
            tvmaze_id=169,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            shikimori_id=None,
            trailer_url=None,
        )

        url, name = resolve_show_external_link(show, "tvdb")
        self.assertEqual(url, "https://thetvdb.com/?tab=series&id=81189")
        self.assertEqual(name, "The TVDB")

        url, name = resolve_show_external_link(show, "tvmaze")
        self.assertEqual(url, "https://www.tvmaze.com/shows/169/_")
        self.assertEqual(name, "TV Maze")

        url, name = resolve_show_external_link(show, "tmdb")
        self.assertEqual(url, "https://www.themoviedb.org/tv/1396")
        self.assertEqual(name, "TMDB")

        url, name = resolve_show_external_link(show, "trakt")
        self.assertEqual(url, "https://trakt.tv/shows/tt0903747")
        self.assertEqual(name, "Trakt")

        url, name = resolve_show_external_link(show, "imdb")
        self.assertEqual(url, "https://imdb.com/title/tt0903747/")
        self.assertEqual(name, "IMDb")

    def test_anime_link_sources(self):
        show = SimpleNamespace(
            id=3,
            title="Ван-Пис",
            year=1999,
            content_type="anime",
            shikimori_id="21",
            anidb_id=69,
            mal_id=21,
            anilist_id=21,
            tvdb_id=74608,
            tmdb_id=37854,
            tvmaze_id=None,
            imdb_id=None,
            trailer_url=None,
        )

        url, name = resolve_show_external_link(show, "shikimori")
        self.assertEqual(url, "https://shikimori.one/animes/21")
        self.assertEqual(name, "Shikimori")

        url, name = resolve_show_external_link(show, "anidb")
        self.assertEqual(url, "https://anidb.net/anime/69")
        self.assertEqual(name, "AniDB")

        url, name = resolve_show_external_link(show, "mal")
        self.assertEqual(url, "https://myanimelist.net/anime/21")
        self.assertEqual(name, "MyAnimeList")

        url, name = resolve_show_external_link(show, "anilist")
        self.assertEqual(url, "https://anilist.co/anime/21")
        self.assertEqual(name, "AniList")

        url, name = resolve_show_external_link(show, "kitsu")
        self.assertIn("kitsu.app/anime", url)
        self.assertEqual(name, "Kitsu")

    def test_fallback_search_links_when_no_direct_id(self):
        show = SimpleNamespace(
            id=4,
            title="Unknown Show",
            year=2024,
            content_type="series",
            tvdb_id=None,
            tmdb_id=None,
            imdb_id=None,
            tvmaze_id=None,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            shikimori_id=None,
            trailer_url=None,
        )
        url, name = resolve_show_external_link(show, "tvdb")
        self.assertEqual(url, "https://thetvdb.com/search?query=Unknown%20Show")
        self.assertEqual(name, "The TVDB")

        url, name = resolve_show_external_link(show, "tmdb")
        self.assertEqual(url, "https://www.themoviedb.org/search/tv?query=Unknown%20Show")

        url, name = resolve_show_external_link(show, "imdb")
        self.assertEqual(url, "https://www.imdb.com/find/?q=Unknown%20Show&s=tt&ttype=tv")

    def test_extract_ids_from_metadata_fields(self):
        show = SimpleNamespace(
            id=5,
            title="Inception",
            year=2010,
            content_type="movie",
            metadata_source="radarr",
            metadata_id="movie:27205",
            tmdb_id=None,
            tvdb_id=None,
            imdb_id=None,
            tvmaze_id=None,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            shikimori_id=None,
            trailer_url=None,
        )
        url, name = resolve_show_external_link(show, "tmdb")
        self.assertEqual(url, "https://www.themoviedb.org/movie/27205")

        show_series = SimpleNamespace(
            id=6,
            title="Show",
            year=2020,
            content_type="series",
            metadata_source="skyhook",
            metadata_id="tvdb:12345",
            tmdb_id=None,
            tvdb_id=None,
            imdb_id=None,
            tvmaze_id=None,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            shikimori_id=None,
            trailer_url=None,
        )
        url_s, name_s = resolve_show_external_link(show_series, "tvdb")
        self.assertEqual(url_s, "https://thetvdb.com/?tab=series&id=12345")

    def test_build_series_add_notification_message_with_mock_db(self):
        mock_settings = SimpleNamespace(
            notification_link_source_movie="tmdb",
            notification_link_source_series="tvdb",
            notification_link_source_anime="shikimori",
        )
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_settings

        # 1. Movie
        movie = SimpleNamespace(
            id=10,
            title="Интерстеллар",
            year=2014,
            content_type="movie",
            tmdb_id=157336,
            imdb_id="tt0816692",
            tvdb_id=None,
            tvmaze_id=None,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            shikimori_id=None,
            trailer_url=None,
        )
        msg_m = build_series_add_notification_message(mock_db, movie)
        self.assertIn("🎬 В библиотеку добавлен тайтл: <a href=\"https://www.themoviedb.org/movie/157336\">Интерстеллар</a> (2014)", msg_m)
        self.assertIn("🔗 TMDB: https://www.themoviedb.org/movie/157336", msg_m)

        # 2. Anime
        anime = SimpleNamespace(
            id=11,
            title="Атака титанов",
            year=2013,
            content_type="anime",
            shikimori_id="16498",
            tmdb_id=None,
            imdb_id=None,
            tvdb_id=None,
            tvmaze_id=None,
            mal_id=None,
            anilist_id=None,
            anidb_id=None,
            trailer_url=None,
        )
        msg_a = build_series_add_notification_message(mock_db, anime)
        self.assertIn("https://shikimori.one/animes/16498", msg_a)
        self.assertIn("🔗 Shikimori: https://shikimori.one/animes/16498", msg_a)

        # 3. None configured
        mock_settings.notification_link_source_movie = "none"
        msg_none = build_series_add_notification_message(mock_db, movie)
        self.assertEqual(msg_none, "🎬 В библиотеку добавлен тайтл: Интерстеллар (2014)")

    def test_messenger_conversions(self):
        html_msg = (
            '🎬 В библиотеку добавлен тайтл: <a href="https://www.themoviedb.org/movie/550">Бойцовский клуб</a> (1999)\n'
            '🔗 TMDB: https://www.themoviedb.org/movie/550'
        )

        # Discord Markdown
        md = _html_to_markdown(html_msg)
        self.assertIn("[Бойцовский клуб](https://www.themoviedb.org/movie/550)", md)
        self.assertIn("🔗 TMDB: https://www.themoviedb.org/movie/550", md)

        # Slack mrkdwn
        slack = _html_to_slack_mrkdwn(html_msg)
        self.assertIn("<https://www.themoviedb.org/movie/550|Бойцовский клуб>", slack)

        # Gotify / Ntfy plain text
        plain = _strip_html(html_msg)
        self.assertIn("Бойцовский клуб (https://www.themoviedb.org/movie/550)", plain)

        # English translation
        en = format_notification_message(html_msg, lang="en")
        self.assertIn("🎬 Title added to library:", en)
        self.assertIn("https://www.themoviedb.org/movie/550", en)

    def test_settings_routes_update_and_validation(self):
        if not HAS_DB_DEPS:
            self.skipTest("Database/FastAPI dependencies not available in host runner")

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        user = User(
            id=1,
            username="admin",
            is_admin=True,
            enabled=True,
            password_hash="hash",
            is_owner=True,
        )
        db.add(user)
        db.commit()

        try:
            mock_request = MagicMock()

            # Update valid
            payload = SettingsUpdate(
                notification_link_source_movie="imdb",
                notification_link_source_series="tmdb",
                notification_link_source_anime="anidb",
            )
            res = update_settings(payload=payload, request=mock_request, db=db, current_user=user)
            self.assertEqual(res.notification_link_source_movie, "imdb")
            self.assertEqual(res.notification_link_source_series, "tmdb")
            self.assertEqual(res.notification_link_source_anime, "anidb")

            out = get_settings(db=db, current_user=user)
            self.assertEqual(out.notification_link_source_movie, "imdb")
            self.assertEqual(out.notification_link_source_series, "tmdb")
            self.assertEqual(out.notification_link_source_anime, "anidb")

            # Invalid source rejection
            with self.assertRaises(HTTPException) as cm:
                update_settings(
                    payload=SettingsUpdate(notification_link_source_movie="invalid_source"),
                    request=mock_request,
                    db=db,
                    current_user=user,
                )
            self.assertEqual(cm.exception.status_code, 400)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
