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
        UserRole,
    )
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
            role=UserRole.ADMIN,
            is_active=True,
            password_hash="hash",
        )
        self.db.add(self.user)

        self.settings = AppSettings(
            id=1,
            metadata_refresh_aliases=True,
            alias_languages=["ru", "en"],
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
        fake_details.aliases = ["Клиника", "Hoży doktorzy", "Scrubs – Die Anfänger"]
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
        self.assertNotIn("Scrubs – Die Anfänger", alias_texts)


if __name__ == "__main__":
    unittest.main()
