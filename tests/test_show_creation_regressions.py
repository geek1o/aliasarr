from __future__ import annotations

import asyncio
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.shows import add_alias, create_season_split, create_show, update_alias, update_season_split
from app.models.db import Alias, Base, SeasonSplitPart, User
from app.schemas import (
    AliasCreate,
    AliasUpdate,
    SeasonSplitCreate,
    SeasonSplitPartCreate,
    SeasonSplitUpdate,
    ShowCreate,
)


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

    def test_replace_loaded_season_split_parts(self):
        show = asyncio.run(
            create_show(
                ShowCreate(title="Split Show", quality_profile_id=10),
                db=self.db,
                current_user=self.user,
            )
        )
        created = create_season_split(
            show.id,
            SeasonSplitCreate(
                name="Two cours",
                season_number=1,
                parts=[
                    SeasonSplitPartCreate(episode_start=1, episode_end=12),
                    SeasonSplitPartCreate(episode_start=13, episode_end=24, episode_offset=12),
                ],
            ),
            db=self.db,
            current_user=self.user,
        )
        self.assertEqual(len(created.parts), 2)

        updated = update_season_split(
            show.id,
            created.id,
            SeasonSplitUpdate(
                name="Single cour",
                parts=[SeasonSplitPartCreate(episode_start=1, episode_end=12)],
            ),
            db=self.db,
            current_user=self.user,
        )

        self.assertEqual(updated.name, "Single cour")
        self.assertEqual(len(updated.parts), 1)
        self.assertEqual(
            self.db.query(SeasonSplitPart).filter_by(split_id=created.id).count(),
            1,
        )


if __name__ == "__main__":
    unittest.main()
