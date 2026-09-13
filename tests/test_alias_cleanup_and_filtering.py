from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.metadata import (
    detect_alias_language,
    is_alias_allowed,
    get_allowed_metadata_languages,
    refresh_show_metadata,
)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import (
        Base,
        Show,
        Alias,
        AppSettings,
        MetadataSource,
        MetadataSourceType,
        User,
        AliasLanguage,
    )
    from app.schemas import ShowOut
    from app.api.metadata_routes import cleanup_unallowed_aliases
    HAS_DB = True
except ImportError:
    HAS_DB = False


class TestAliasLanguageDetectionAndFiltering(unittest.TestCase):
    def test_detect_alias_language(self):
        self.assertEqual(detect_alias_language("Клиника"), "ru")
        self.assertEqual(detect_alias_language("Наруто: Ураганные хроники"), "ru")
        self.assertEqual(detect_alias_language("ナルト 疾風伝"), "ja")
        self.assertEqual(detect_alias_language("나루토 질풍전"), "ko")
        self.assertEqual(detect_alias_language("火影忍者：疾风传"), "zh")
        self.assertEqual(detect_alias_language("Großstadt"), "de")
        self.assertEqual(detect_alias_language("El Niño"), "es")
        self.assertEqual(detect_alias_language("Miłość"), "pl")
        self.assertEqual(detect_alias_language("Szörnyű"), "hu")
        self.assertEqual(detect_alias_language("Antonín Dvořák"), "cs")
        self.assertEqual(detect_alias_language("Dağ"), "tr")
        self.assertEqual(detect_alias_language("București"), "ro")
        self.assertEqual(detect_alias_language("Scrubs"), "en")
        self.assertEqual(detect_alias_language("The Office (US)"), "en")

    def test_is_alias_allowed_with_allowed_langs(self):
        allowed = {"ru", "rus", "en", "eng"}

        # Allowed Latin & Cyrillic
        self.assertTrue(is_alias_allowed("Scrubs", "en", allowed))
        self.assertTrue(is_alias_allowed("Клиника", "ru", allowed))
        self.assertTrue(is_alias_allowed("Клиника", None, allowed))

        # Foreign characters rejected when language is not allowed
        self.assertFalse(is_alias_allowed("Großstadt", None, allowed))
        self.assertFalse(is_alias_allowed("El Niño", None, allowed))
        self.assertFalse(is_alias_allowed("Miłość", None, allowed))
        self.assertFalse(is_alias_allowed("Szörnyű", None, allowed))
        self.assertFalse(is_alias_allowed("Antonín Dvořák", None, allowed))
        self.assertFalse(is_alias_allowed("Dağ", None, allowed))

        # Asian scripts rejected even if incorrectly tagged as "en"
        self.assertFalse(is_alias_allowed("ナルト 疾風伝", "en", allowed))
        self.assertFalse(is_alias_allowed("나루토 질풍전", "en", allowed))
        self.assertFalse(is_alias_allowed("火影忍者", "en", allowed))

        # When German is added to allowed, German diacritics are allowed
        allowed_with_de = {"ru", "en", "de"}
        self.assertTrue(is_alias_allowed("Großstadt", None, allowed_with_de))
        self.assertTrue(is_alias_allowed("Scrubs – Die Anfänger", "de", allowed_with_de))

        # When Italian is added, Italian words are allowed
        allowed_with_it = {"ru", "en", "it"}
        self.assertTrue(is_alias_allowed("La vita è bella", "it", allowed_with_it))
        self.assertTrue(is_alias_allowed("Il padrino", "it", allowed_with_it))

        # CJK separation: allowing Japanese does NOT allow Korean or Chinese
        allowed_with_ja = {"ru", "en", "ja", "jpn"}
        self.assertTrue(is_alias_allowed("ナルト 疾風伝", "ja", allowed_with_ja))
        self.assertTrue(is_alias_allowed("ナルト 疾風伝", None, allowed_with_ja))
        self.assertTrue(is_alias_allowed("俺たちのアナコンダ", None, allowed_with_ja))
        # Korean and Chinese must be rejected!
        self.assertFalse(is_alias_allowed("아나콘다", "ko", allowed_with_ja))
        self.assertFalse(is_alias_allowed("아나콘다", None, allowed_with_ja))
        self.assertFalse(is_alias_allowed("新狂蟒之灾", "zh", allowed_with_ja))
        self.assertFalse(is_alias_allowed("新狂蟒之灾", None, allowed_with_ja))

        # Allowing Korean does NOT allow Japanese or Chinese
        allowed_with_ko = {"ru", "en", "ko", "kor"}
        self.assertTrue(is_alias_allowed("아나콘다", "ko", allowed_with_ko))
        self.assertTrue(is_alias_allowed("아나콘다", None, allowed_with_ko))
        self.assertFalse(is_alias_allowed("ナルト 疾風伝", "ja", allowed_with_ko))
        self.assertFalse(is_alias_allowed("新狂蟒之灾", "zh", allowed_with_ko))

        # Allowing Chinese does NOT allow Japanese or Korean
        allowed_with_zh = {"ru", "en", "zh", "chi"}
        self.assertTrue(is_alias_allowed("新狂蟒之灾", "zh", allowed_with_zh))
        self.assertTrue(is_alias_allowed("新狂蟒之灾", None, allowed_with_zh))
        self.assertFalse(is_alias_allowed("ナルト 疾風伝", "ja", allowed_with_zh))
        self.assertFalse(is_alias_allowed("아나콘다", "ko", allowed_with_zh))


@unittest.skipUnless(HAS_DB, "Requires sqlalchemy, fastapi, and pydantic")
class TestAliasCleanupAndSettings(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.user = User(
            id=1,
            username="admin",
            is_admin=True,
            is_owner=True,
            enabled=True,
            password_hash="hash",
        )
        self.db.add(self.user)

        self.settings = AppSettings(
            id=1,
            api_key="test-key",
            metadata_refresh_aliases=True,
        )
        self.db.add(self.settings)

        self.source = MetadataSource(
            id=1,
            name="SkyHook",
            type=MetadataSourceType.SKYHOOK,
            enabled=True,
            field_mapping={"alias_languages": ["ru", "en"]},
        )
        self.db.add(self.source)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_cleanup_unallowed_aliases_endpoint(self):
        show = Show(
            id=1,
            title="Scrubs",
            content_type="series",
            metadata_source="skyhook",
            metadata_id="tvdb:76156",
        )
        self.db.add(show)
        self.db.flush()

        # Add various aliases
        a_title = Alias(show_id=show.id, text="Scrubs", language="en", source="skyhook", priority=1)
        a_ru = Alias(show_id=show.id, text="Клиника", language="ru", source="skyhook", priority=2)
        a_de = Alias(show_id=show.id, text="Scrubs – Die Anfänger", language="de", source="skyhook", priority=3)
        a_pl = Alias(show_id=show.id, text="Hoży doktorzy", language="pl", source="skyhook", priority=4)
        a_manual = Alias(show_id=show.id, text="Moja Klinika", language="pl", source="manual", priority=5)

        self.db.add_all([a_title, a_ru, a_de, a_pl, a_manual])
        self.db.commit()

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        import asyncio
        res = asyncio.run(cleanup_unallowed_aliases(
            request=mock_request,
            db=self.db,
            current_user=self.user,
        ))

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["deleted_count"], 2)
        self.assertEqual(res["shows_affected"], 1)

        remaining_aliases = self.db.query(Alias).filter(Alias.show_id == show.id).all()
        remaining_texts = {a.text for a in remaining_aliases}

        # Check that title, ru, and manual were preserved
        self.assertIn("Scrubs", remaining_texts)
        self.assertIn("Клиника", remaining_texts)
        self.assertIn("Moja Klinika", remaining_texts)

        # Check that foreign unallowed auto-aliases were removed
        self.assertNotIn("Scrubs – Die Anfänger", remaining_texts)
        self.assertNotIn("Hoży doktorzy", remaining_texts)

    def test_refresh_show_metadata_respects_refresh_aliases_setting(self):
        show = Show(
            id=2,
            title="Scrubs",
            content_type="series",
            metadata_source="skyhook",
            metadata_id="tvdb:76156",
        )
        self.db.add(show)
        self.db.flush()

        a_title = Alias(show_id=show.id, text="Scrubs", language="en", source="skyhook", priority=1)
        self.db.add(a_title)
        self.db.commit()

        fake_details = MagicMock()
        fake_details.external_id = "tvdb:76156"
        fake_details.title = "Scrubs"
        fake_details.aliases = ["Клиника", "Hoży doktorzy", "Großstadt"]
        fake_details.overview = "Description"
        fake_details.poster_url = None
        fake_details.rating = 8.5
        fake_details.genre = "Comedy"
        fake_details.network = "ABC"
        fake_details.year = 2001
        fake_details.premiere_date = "2001-10-02"
        fake_details.episodes = []

        # 1. When metadata_refresh_aliases is False, aliases are frozen
        self.settings.metadata_refresh_aliases = False
        self.db.commit()

        with patch("app.services.metadata.get_metadata_client") as mock_get_client:
            client_mock = AsyncMock()
            client_mock.get_details.return_value = fake_details
            mock_get_client.return_value = client_mock

            import asyncio
            asyncio.run(refresh_show_metadata(self.db, show))

        aliases_frozen = self.db.query(Alias).filter(Alias.show_id == show.id).all()
        self.assertEqual(len(aliases_frozen), 1)
        self.assertEqual(aliases_frozen[0].text, "Scrubs")

        # 2. When metadata_refresh_aliases is True, allowed aliases are added and unallowed filtered
        self.settings.metadata_refresh_aliases = True
        self.db.commit()

        with patch("app.services.metadata.get_metadata_client") as mock_get_client:
            client_mock = AsyncMock()
            client_mock.get_details.return_value = fake_details
            mock_get_client.return_value = client_mock

            import asyncio
            asyncio.run(refresh_show_metadata(self.db, show))

        aliases_updated = self.db.query(Alias).filter(Alias.show_id == show.id).all()
        alias_texts = {a.text for a in aliases_updated}
        self.assertIn("Scrubs", alias_texts)
        self.assertIn("Клиника", alias_texts)
        # Filtered out:
        self.assertNotIn("Hoży doktorzy", alias_texts)
        self.assertNotIn("Großstadt", alias_texts)

    def test_show_with_multilingual_aliases_serialization(self):
        """Проверяет, что карточка с алиасами на различных языках (zh, ja, ko, de и т.д.)
        успешно считывается из БД и сериализуется в ShowOut без ошибки LookupError."""
        show = Show(title="Naruto Shippuden")
        self.db.add(show)
        self.db.commit()
        self.db.refresh(show)

        aliases_to_add = [
            ("Наруто: Ураганные хроники", "ru"),
            ("Naruto: Shippuden", "en"),
            ("火影忍者：疾风传", "zh"),
            ("ナルト 疾風伝", "ja"),
            ("나루토 질풍전", "ko"),
            ("Naruto Shippuden (DE)", "de"),
            ("Custom Lang Alias", "custom_iso"),
        ]

        for text, lang in aliases_to_add:
            self.db.add(Alias(
                show_id=show.id,
                text=text,
                language=lang,
                source="skyhook",
                priority=1,
            ))
        self.db.commit()

        # Query show with aliases from DB
        fetched_show = self.db.query(Show).filter(Show.id == show.id).first()
        self.assertIsNotNone(fetched_show)
        self.assertEqual(len(fetched_show.aliases), 7)

        # Validate with Pydantic ShowOut (where the 500 error previously occurred)
        show_out = ShowOut.model_validate(fetched_show)
        self.assertEqual(show_out.title, "Naruto Shippuden")
        self.assertEqual(len(show_out.aliases), 7)
        languages = {a.language for a in show_out.aliases}
        self.assertIn("zh", languages)
        self.assertIn("ja", languages)
        self.assertIn("ko", languages)
        self.assertIn("de", languages)
        self.assertIn("custom_iso", languages)

    def test_get_allowed_metadata_languages_separation_by_content_type(self):
        """Проверяет, что фильмы берут настройки из Radarr/Films, а сериалы и аниме — из Sonarr."""
        # Удаляем предыдущие источники
        self.db.query(MetadataSource).delete()
        # Добавляем Sonarr с японским языком для аниме
        sonarr = MetadataSource(
            name="Sonarr SkyHook",
            type="skyhook",
            enabled=True,
            field_mapping={"alias_languages": ["ru", "ja"]},
        )
        # Добавляем Radarr (Films) только с русским языком
        radarr = MetadataSource(
            name="Films",
            type="radarr",
            enabled=True,
            field_mapping={"alias_languages": ["ru"]},
        )
        self.db.add_all([sonarr, radarr])
        self.db.commit()

        movie_show = Show(title="Anaconda", content_type="movie", metadata_source="tmdb")
        anime_show = Show(title="Naruto", content_type="anime", metadata_source="skyhook")
        series_show = Show(title="Scrubs", content_type="series", metadata_source="skyhook")

        movie_langs = get_allowed_metadata_languages(self.db, movie_show)
        anime_langs = get_allowed_metadata_languages(self.db, anime_show)
        series_langs = get_allowed_metadata_languages(self.db, series_show)

        # Фильмы должны содержать только русский и английский
        self.assertIn("ru", movie_langs)
        self.assertIn("en", movie_langs)
        self.assertNotIn("ja", movie_langs)
        self.assertNotIn("zh", movie_langs)
        self.assertNotIn("ko", movie_langs)

        # Аниме и сериалы должны содержать японский из Sonarr
        self.assertIn("ja", anime_langs)
        self.assertIn("ja", series_langs)

    def test_cleanup_unallowed_aliases_movie_vs_anime(self):
        """Проверяет, что при очистке алиасов в фильмах удаляются лишние CJK,
        но в аниме сохраняются разрешенные японские алиасы."""
        self.db.query(MetadataSource).delete()
        sonarr = MetadataSource(
            name="Sonarr SkyHook",
            type="skyhook",
            enabled=True,
            field_mapping={"alias_languages": ["ru", "ja"]},
        )
        radarr = MetadataSource(
            name="Films",
            type="radarr",
            enabled=True,
            field_mapping={"alias_languages": ["ru"]},
        )
        self.db.add_all([sonarr, radarr])
        self.db.commit()

        # Создаем фильм "Anaconda" с мультиязычными авто-алиасами
        movie = Show(title="Anaconda", content_type="movie", metadata_source="skyhook")  # даже если ошибочный skyhook
        self.db.add(movie)
        self.db.commit()
        self.db.refresh(movie)

        movie_aliases = [
            ("Anaconda", "en"),
            ("Анаконда", "ru"),
            ("아나콘다", "ko"),
            ("新狂蟒之灾", "zh"),
            ("俺たちのアナコンダ", "ja"),
        ]
        for t, l in movie_aliases:
            self.db.add(Alias(show_id=movie.id, text=t, language=l, source="skyhook", priority=1))

        # Создаем аниме "Naruto"
        anime = Show(title="Naruto", content_type="anime", metadata_source="skyhook")
        self.db.add(anime)
        self.db.commit()
        self.db.refresh(anime)

        anime_aliases = [
            ("Naruto", "en"),
            ("Наруто", "ru"),
            ("ナルト", "ja"),
            ("火影忍者", "zh"),
        ]
        for t, l in anime_aliases:
            self.db.add(Alias(show_id=anime.id, text=t, language=l, source="skyhook", priority=1))

        self.db.commit()

        # Запускаем процедуру очистки
        from unittest.mock import MagicMock
        req = MagicMock()
        import asyncio
        asyncio.run(cleanup_unallowed_aliases(req, db=self.db, current_user=self.user))

        # Проверяем фильм: корейский, китайский и японский должны быть удалены!
        remaining_movie = {a.text for a in self.db.query(Alias).filter(Alias.show_id == movie.id).all()}
        self.assertIn("Anaconda", remaining_movie)
        self.assertIn("Анаконда", remaining_movie)
        self.assertNotIn("아나콘다", remaining_movie)
        self.assertNotIn("新狂蟒之灾", remaining_movie)
        self.assertNotIn("俺たちのアナコンダ", remaining_movie)

        # Проверяем аниме: японский "ナルト" должен остаться, а китайский "火影忍者" удален!
        remaining_anime = {a.text for a in self.db.query(Alias).filter(Alias.show_id == anime.id).all()}
        self.assertIn("Naruto", remaining_anime)
        self.assertIn("Наруто", remaining_anime)
        self.assertIn("ナルト", remaining_anime)
        self.assertNotIn("火影忍者", remaining_anime)


if __name__ == "__main__":
    unittest.main()
