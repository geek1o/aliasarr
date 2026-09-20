from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import Base, ImportList, Show, Tag
from app.services.import_list_runtime import definition_from_row, run_import_list
from app.services.import_lists import ImportListItem, ImportListSource


class FakeAdapter:
    def __init__(self, items):
        self.items = items

    async def fetch(self, _definition):
        return list(self.items), 0


class ImportListRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/db.sqlite")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp.cleanup()

    def make_row(self, **values):
        defaults = {
            "name": "Watchlist",
            "source": "tmdb_list",
            "source_id": "42",
            "api_key": "secret",
            "root_folder": f"{self.temp.name}/library",
        }
        defaults.update(values)
        row = ImportList(**defaults)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def test_definition_does_not_expose_or_drop_options(self):
        row = self.make_row(tag_ids=[3, 4], quality_profile_id=7, search_on_add=True)
        definition = definition_from_row(row)
        self.assertEqual(definition.source, ImportListSource.TMDB_LIST)
        self.assertEqual(definition.add_options.tags, (3, 4))
        self.assertEqual(definition.add_options.quality_profile_id, 7)
        self.assertTrue(definition.add_options.search_on_add)

    def test_preview_is_read_only_and_sync_adds_tagged_show(self):
        tag = Tag(name="kids")
        self.db.add(tag)
        self.db.commit()
        row = self.make_row(tag_ids=[tag.id])
        item = ImportListItem(
            media_type="movie",
            title="Arrival",
            year=2016,
            tmdb_id=329865,
            source=ImportListSource.TMDB_LIST,
            source_item_id="tmdb:329865",
        )
        adapters = {ImportListSource.TMDB_LIST: FakeAdapter([item])}

        preview = asyncio.run(run_import_list(self.db, row, dry_run=True, adapters=adapters))
        self.assertEqual(preview["add_count"], 1)
        self.assertEqual(self.db.query(Show).count(), 0)
        self.assertIsNone(row.last_synced_at)

        result = asyncio.run(run_import_list(self.db, row, adapters=adapters))
        self.assertEqual(result["added"], 1)
        show = self.db.query(Show).one()
        self.assertEqual(show.tmdb_id, 329865)
        self.assertEqual([value.name for value in show.tags], ["kids"])
        self.assertIn("Arrival (2016)", show.path)
        self.db.refresh(row)
        self.assertIsNotNone(row.last_synced_at)

    def test_existing_external_id_is_not_duplicated(self):
        self.db.add(Show(title="Localized", content_type="movie", tmdb_id=329865))
        self.db.commit()
        row = self.make_row()
        item = ImportListItem(
            media_type="movie",
            title="Arrival",
            year=2016,
            tmdb_id=329865,
            source=ImportListSource.TMDB_LIST,
            source_item_id="tmdb:329865",
        )

        result = asyncio.run(
            run_import_list(
                self.db,
                row,
                adapters={ImportListSource.TMDB_LIST: FakeAdapter([item])},
            )
        )

        self.assertEqual(result["existing_count"], 1)
        self.assertEqual(result["added"], 0)
        self.assertEqual(self.db.query(Show).count(), 1)

    def test_post_import_search_failure_does_not_mark_committed_show_failed(self):
        row = self.make_row(search_on_add=True)
        item = ImportListItem(
            media_type="movie",
            title="Arrival",
            year=2016,
            tmdb_id=329865,
            source=ImportListSource.TMDB_LIST,
            source_item_id="tmdb:329865",
        )

        with patch(
            "app.services.metadata.refresh_show_metadata",
            new=AsyncMock(side_effect=RuntimeError("metadata unavailable")),
        ):
            result = asyncio.run(
                run_import_list(
                    self.db,
                    row,
                    adapters={ImportListSource.TMDB_LIST: FakeAdapter([item])},
                )
            )

        self.assertEqual(result["added"], 1)
        self.assertEqual(result["failures"], [])
        self.assertEqual(self.db.query(Show).count(), 1)

    def test_trakt_only_item_does_not_store_unsupported_metadata_provider_id(self):
        row = self.make_row(source="trakt_list", source_id="watchlist", username="alice")
        item = ImportListItem(
            media_type="series",
            title="A Trakt-only Show",
            year=2025,
            trakt_id=12345,
            source=ImportListSource.TRAKT_LIST,
            source_item_id="trakt:12345",
        )

        result = asyncio.run(
            run_import_list(
                self.db,
                row,
                adapters={ImportListSource.TRAKT_LIST: FakeAdapter([item])},
            )
        )

        show = self.db.query(Show).one()
        self.assertEqual(result["added"], 1)
        self.assertEqual(show.metadata_source, "skyhook")
        self.assertIsNone(show.metadata_id)


if __name__ == "__main__":
    unittest.main()
