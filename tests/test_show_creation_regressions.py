from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.shows import add_alias, create_show, update_alias
from app.models.db import Alias, Base, User
from app.schemas import AliasCreate, AliasUpdate, ShowCreate


class TestShowCreationRegressions(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(
            username="audit-admin",
            password_hash="hash",
            is_admin=True,
            is_owner=True,
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_create_show_without_explicit_quality_profile(self):
        show = asyncio.run(
            create_show(
                ShowCreate(title="Regression Show", content_type="series"),
                db=self.db,
                current_user=self.user,
            )
        )

        self.assertEqual(show.title, "Regression Show")
        self.assertIsNone(show.quality_profile_id)

    def test_create_and_update_scoped_alias_fields(self):
        show = asyncio.run(
            create_show(
                ShowCreate(
                    title="Scoped Alias Show",
                    quality_profile_id=10,
                    aliases=[
                        AliasCreate(
                            text="Scoped Alias",
                            season_number=1,
                            episode_start=14,
                            episode_end=26,
                            episode_offset=13,
                        )
                    ],
                ),
                db=self.db,
                current_user=self.user,
            )
        )

        alias = self.db.query(Alias).filter_by(show_id=show.id, text="Scoped Alias").one()
        self.assertEqual(alias.season_number, 1)
        self.assertEqual(alias.episode_start, 14)
        self.assertEqual(alias.episode_end, 26)
        self.assertEqual(alias.episode_offset, 13)

        created = add_alias(
            show.id,
            AliasCreate(text="Second Alias", season_number=2, episode_offset=24),
            db=self.db,
            current_user=self.user,
        )
        updated = update_alias(
            show.id,
            created.id,
            AliasUpdate(episode_start=25, episode_end=36, episode_offset=24),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(updated.season_number, 2)
        self.assertEqual(updated.episode_start, 25)
        self.assertEqual(updated.episode_end, 36)
        self.assertEqual(updated.episode_offset, 24)


if __name__ == "__main__":
    unittest.main()
