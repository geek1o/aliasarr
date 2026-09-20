from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from app.services.import_lists import (
    ImportAction,
    ImportListAddOptions,
    ImportListDefinition,
    ImportListScheduler,
    ImportListService,
    ImportListSource,
    ImportListSyncCancelled,
    ImportListSyncResult,
    ImportListItem,
    MediaIdentity,
    TMDbImportListAdapter,
    TraktImportListAdapter,
    deduplicate_items,
)


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get_json(self, url, *, params=None, headers=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        return self.responses.pop(0)


class FakeAdapter:
    def __init__(self, items, invalid_count=0):
        self.items = list(items)
        self.invalid_count = invalid_count
        self.calls = []

    async def fetch(self, definition):
        self.calls.append(definition.id)
        return list(self.items), self.invalid_count


class FakeTarget:
    def __init__(self, existing=(), *, race_titles=(), fail_titles=()):
        self.existing = list(existing)
        self.race_titles = set(race_titles)
        self.fail_titles = set(fail_titles)
        self.added = []

    async def list_identities(self):
        return list(self.existing)

    async def add(self, item, options):
        self.added.append((item, options))
        if item.title in self.fail_titles:
            raise RuntimeError(f"cannot add {item.title}")
        return item.title not in self.race_titles


class FakeStore:
    def __init__(self, definitions):
        self.definitions = list(definitions)
        self.recorded = []

    async def list_enabled(self):
        return list(self.definitions)

    async def record_run(self, definition, result, completed_at):
        self.recorded.append((definition.id, result, completed_at))


def definition(source=ImportListSource.TMDB_LIST, **kwargs):
    values = {
        "id": kwargs.pop("id", 1),
        "name": "My list",
        "source": source,
        "source_id": kwargs.pop("source_id", "42"),
        "api_key": "secret",
    }
    if source is ImportListSource.TRAKT_LIST:
        values["username"] = kwargs.pop("username", "user")
    values.update(kwargs)
    return ImportListDefinition(**values)


class TestImportListAdapters(unittest.TestCase):
    def test_tmdb_list_paginates_and_normalizes_movies_and_series(self):
        http = FakeHttp(
            [
                {
                    "page": 1,
                    "total_pages": 2,
                    "items": [
                        {"id": 11, "media_type": "movie", "title": "Arrival", "release_date": "2016-09-01"},
                        {"id": None, "media_type": "movie", "title": "Broken"},
                    ],
                },
                {
                    "page": 2,
                    "total_pages": 2,
                    "items": [
                        {"id": 22, "media_type": "tv", "name": "Dark", "first_air_date": "2017-12-01"}
                    ],
                },
            ]
        )

        items, invalid = asyncio.run(TMDbImportListAdapter(http).fetch(definition(language="ru-RU")))

        self.assertEqual([(item.title, item.media_type, item.year) for item in items], [
            ("Arrival", "movie", 2016),
            ("Dark", "series", 2017),
        ])
        self.assertEqual(invalid, 1)
        self.assertEqual([call[1]["page"] for call in http.calls], [1, 2])
        self.assertTrue(all(call[1]["api_key"] == "secret" for call in http.calls))
        self.assertTrue(all(call[1]["language"] == "ru-RU" for call in http.calls))

    def test_tmdb_person_uses_cast_and_optionally_crew(self):
        payload = {
            "cast": [{"id": 1, "media_type": "movie", "title": "Cast title"}],
            "crew": [{"id": 2, "media_type": "tv", "name": "Crew title"}],
        }
        http = FakeHttp([payload])
        items, invalid = asyncio.run(
            TMDbImportListAdapter(http).fetch(
                definition(ImportListSource.TMDB_PERSON, source_id="12/34", include_crew=True)
            )
        )

        self.assertEqual([item.title for item in items], ["Cast title", "Crew title"])
        self.assertEqual(invalid, 0)
        self.assertIn("/person/12%2F34/combined_credits", http.calls[0][0])
        self.assertNotIn("page", http.calls[0][1])

    def test_trakt_list_maps_ids_filters_media_and_sends_auth(self):
        http = FakeHttp(
            [[
                {
                    "movie": {
                        "title": "Heat",
                        "year": 1995,
                        "ids": {"trakt": 1, "tmdb": 949, "imdb": "tt0113277"},
                    }
                },
                {"show": {"title": "Ignored", "year": 2020, "ids": {"trakt": 2, "tmdb": 3}}},
                {"episode": {"title": "Unsupported"}},
            ]]
        )
        config = definition(
            ImportListSource.TRAKT_LIST,
            source_id="top movies",
            username="john/doe",
            access_token="token",
            include_series=False,
        )

        items, invalid = asyncio.run(TraktImportListAdapter(http).fetch(config))

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].tmdb_id, 949)
        self.assertEqual(items[0].imdb_id, "tt0113277")
        self.assertEqual(invalid, 2)
        url, params, headers = http.calls[0]
        self.assertIn("/users/john%2Fdoe/lists/top%20movies/items", url)
        self.assertEqual(params, {"page": 1, "limit": 100})
        self.assertEqual(headers["trakt-api-key"], "secret")
        self.assertEqual(headers["Authorization"], "Bearer token")

    def test_invalid_configuration_fails_before_http(self):
        with self.assertRaisesRegex(ValueError, "username"):
            definition(ImportListSource.TRAKT_LIST, username="")
        with self.assertRaisesRegex(ValueError, "interval_minutes"):
            definition(interval_minutes=0)


class TestImportListService(unittest.TestCase):
    def setUp(self):
        self.arrival = ImportListItem(
            media_type="movie",
            title="Arrival",
            year=2016,
            tmdb_id=329865,
            source=ImportListSource.TMDB_LIST,
            source_item_id="tmdb:329865",
        )
        self.dark = ImportListItem(
            media_type="series",
            title="Dark",
            year=2017,
            tmdb_id=70523,
            source=ImportListSource.TMDB_LIST,
            source_item_id="tmdb:70523",
        )

    def test_deduplication_is_deterministic_and_merges_identifiers(self):
        trakt_arrival = ImportListItem(
            media_type="movie",
            title="  ARRIVAL ",
            year=2016,
            imdb_id="tt2543164",
            trakt_id=114225,
            source=ImportListSource.TRAKT_LIST,
            source_item_id="trakt:114225",
        )
        first, first_duplicates = deduplicate_items([self.dark, trakt_arrival, self.arrival])
        second, second_duplicates = deduplicate_items(reversed([self.dark, trakt_arrival, self.arrival]))

        self.assertEqual(first, second)
        self.assertEqual(first_duplicates, 1)
        self.assertEqual(second_duplicates, 1)
        merged_arrival = next(item for item in first if item.media_type == "movie")
        self.assertEqual(merged_arrival.tmdb_id, 329865)
        self.assertEqual(merged_arrival.imdb_id, "tt2543164")

    def test_deduplication_collapses_transitive_identifier_matches(self):
        by_tmdb = ImportListItem(
            media_type="movie",
            title="Localized title",
            year=2016,
            tmdb_id=329865,
            source_item_id="a",
        )
        by_imdb = ImportListItem(
            media_type="movie",
            title="Original title",
            year=2016,
            imdb_id="tt2543164",
            source_item_id="b",
        )
        bridge = ImportListItem(
            media_type="movie",
            title="Third title",
            year=2016,
            tmdb_id=329865,
            imdb_id="tt2543164",
            source_item_id="c",
        )

        merged, duplicate_count = deduplicate_items([by_tmdb, by_imdb, bridge])

        self.assertEqual(len(merged), 1)
        self.assertEqual(duplicate_count, 2)
        self.assertEqual(merged[0].tmdb_id, 329865)
        self.assertEqual(merged[0].imdb_id, "tt2543164")

    def test_preview_classifies_existing_and_never_writes(self):
        adapter = FakeAdapter([self.dark, self.arrival, self.arrival], invalid_count=2)
        target = FakeTarget([MediaIdentity(media_type="movie", tmdb_id=329865)])
        service = ImportListService({ImportListSource.TMDB_LIST: adapter}, target)

        preview = asyncio.run(service.preview(definition()))

        self.assertEqual(preview.fetched_count, 5)
        self.assertEqual(preview.duplicate_count, 1)
        self.assertEqual(preview.invalid_count, 2)
        self.assertEqual(preview.add_count, 1)
        self.assertEqual(preview.existing_count, 1)
        actions = {entry.item.title: entry.action for entry in preview.entries}
        self.assertEqual(actions, {"Arrival": ImportAction.EXISTS, "Dark": ImportAction.ADD})
        self.assertEqual(target.added, [])

    def test_dry_run_and_live_sync_handle_race_and_item_failure(self):
        failure = ImportListItem(
            media_type="movie",
            title="Failure",
            year=2020,
            tmdb_id=777,
            source=ImportListSource.TMDB_LIST,
            source_item_id="tmdb:777",
        )
        options = ImportListAddOptions(quality_profile_id=4, tags=(3, 5))
        config = definition(add_options=options)
        adapter = FakeAdapter([self.arrival, self.dark, failure])
        target = FakeTarget(race_titles={"Dark"}, fail_titles={"Failure"})
        service = ImportListService({ImportListSource.TMDB_LIST: adapter}, target)

        dry_result = asyncio.run(service.sync(config, dry_run=True))
        self.assertTrue(dry_result.dry_run)
        self.assertEqual(target.added, [])

        result = asyncio.run(service.sync(config))
        self.assertEqual([item.title for item in result.added], ["Arrival"])
        self.assertEqual([item.title for item in result.became_existing], ["Dark"])
        self.assertEqual([failure.item.title for failure in result.failures], ["Failure"])
        self.assertTrue(all(saved_options == options for _, saved_options in target.added))

    def test_live_sync_stops_between_items_after_cancellation(self):
        adapter = FakeAdapter([self.arrival, self.dark])
        target = FakeTarget()
        service = ImportListService({ImportListSource.TMDB_LIST: adapter}, target)

        with self.assertRaises(ImportListSyncCancelled):
            asyncio.run(
                service.sync(
                    definition(),
                    should_cancel=lambda: len(target.added) >= 1,
                )
            )

        self.assertEqual([item.title for item, _options in target.added], ["Arrival"])


class TestImportListScheduler(unittest.TestCase):
    def test_only_due_lists_run_in_stable_order_and_are_recorded(self):
        now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        due_b = definition(id="b", last_synced_at=now - timedelta(minutes=361))
        due_a = definition(id="a", last_synced_at=None)
        not_due = definition(id="c", last_synced_at=now - timedelta(minutes=10))
        disabled = definition(id="d", enabled=False)
        adapter = FakeAdapter([])
        service = ImportListService({ImportListSource.TMDB_LIST: adapter}, FakeTarget())
        store = FakeStore([due_b, disabled, not_due, due_a])
        scheduler = ImportListScheduler(service, store, clock=lambda: now)

        results = asyncio.run(scheduler.run_due())

        self.assertEqual(len(results), 2)
        self.assertEqual(adapter.calls, ["a", "b"])
        self.assertEqual([row[0] for row in store.recorded], ["a", "b"])
        self.assertTrue(all(row[2] == now for row in store.recorded))

    def test_scheduler_dry_run_does_not_advance_persistent_state(self):
        now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        adapter = FakeAdapter([])
        service = ImportListService({ImportListSource.TMDB_LIST: adapter}, FakeTarget())
        store = FakeStore([definition()])

        results = asyncio.run(ImportListScheduler(service, store, clock=lambda: now).run_due(dry_run=True))

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ImportListSyncResult)
        self.assertTrue(results[0].dry_run)
        self.assertEqual(store.recorded, [])


if __name__ == "__main__":
    unittest.main()
