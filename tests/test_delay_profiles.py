from __future__ import annotations

import datetime as dt
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.policy_routes import (
    DelayProfilePayload,
    TagPayload,
    assign_tag_to_indexer,
    assign_tag_to_show,
    create_delay_profile,
    create_tag,
)
from app.models.db import (
    Base,
    DelayProfile,
    Indexer,
    IndexerType,
    QualityProfile,
    Show,
    Tag,
    User,
)
from app.services.delay_profiles import (
    evaluate_release_delay,
    filter_delayed_candidates,
    filter_indexers_for_show,
    get_delay_profile_for_show,
)
from app.services.quality import parse_quality
from app.services.torznab import TorznabRelease


class DelayProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.user = User(username="admin", password_hash="x", is_admin=True)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _indexer(self, name: str, kind: IndexerType = IndexerType.TORZNAB) -> Indexer:
        indexer = Indexer(name=name, type=kind, base_url=f"http://{name}.test")
        self.db.add(indexer)
        self.db.commit()
        return indexer

    def test_tag_crud_assignment_and_profile_scope(self):
        show = Show(title="Tagged show")
        indexer = self._indexer("tagged")
        self.db.add(show)
        self.db.commit()

        output = create_tag(TagPayload(name=" anime "), self.db, self.user)
        self.assertEqual(output.name, "anime")

        output = assign_tag_to_show(output.id, show.id, self.db, self.user)
        output = assign_tag_to_indexer(output.id, indexer.id, self.db, self.user)
        self.assertEqual(output.show_ids, [show.id])
        self.assertEqual(output.indexer_ids, [indexer.id])

        payload = DelayProfilePayload(
            name="Anime delay",
            tag_id=output.id,
            torrent_delay_minutes=60,
            preferred_protocol="torrent",
        )
        profile = create_delay_profile(payload, self.db, self.user)
        self.assertEqual(get_delay_profile_for_show(self.db, show).id, profile.id)

        with self.assertRaises(HTTPException) as raised:
            create_delay_profile(payload, self.db, self.user)
        self.assertEqual(raised.exception.status_code, 409)

    def test_indexer_tags_restrict_automatic_search_scope(self):
        show = Show(title="One")
        other_show = Show(title="Two")
        global_indexer = self._indexer("global")
        matching_indexer = self._indexer("matching")
        other_indexer = self._indexer("other")
        matching = Tag(name="matching")
        unrelated = Tag(name="unrelated")
        matching.shows.append(show)
        matching.indexers.append(matching_indexer)
        unrelated.shows.append(other_show)
        unrelated.indexers.append(other_indexer)
        self.db.add_all([show, other_show, matching, unrelated])
        self.db.commit()

        result = filter_indexers_for_show(
            self.db,
            show,
            [global_indexer, matching_indexer, other_indexer],
        )
        self.assertEqual({item.name for item in result}, {"global", "matching"})

    def test_protocol_delay_and_preference(self):
        now = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)
        release = TorznabRelease(
            title="Show.S01E01.1080p",
            pub_date="Sun, 20 Sep 2026 11:30:00 +0000",
        )
        torrent = self._indexer("torrent")
        usenet = self._indexer("usenet", IndexerType.NEWZNAB)
        quality_profile = QualityProfile(name="HD", allowed_qualities=["720p", "1080p"])
        profile = DelayProfile(
            name="Prefer usenet",
            preferred_protocol="usenet",
            torrent_delay_minutes=60,
            usenet_delay_minutes=10,
        )

        torrent_decision = evaluate_release_delay(
            profile,
            release=release,
            indexer=torrent,
            quality=parse_quality("720p"),
            quality_profile=quality_profile,
            now=now,
        )
        usenet_decision = evaluate_release_delay(
            profile,
            release=release,
            indexer=usenet,
            quality=parse_quality("720p"),
            quality_profile=quality_profile,
            now=now,
        )
        self.assertFalse(torrent_decision.allowed)
        self.assertEqual(torrent_decision.remaining_minutes, 30)
        self.assertFalse(torrent_decision.preferred)
        self.assertTrue(usenet_decision.allowed)
        self.assertTrue(usenet_decision.preferred)

    def test_bypass_at_highest_quality_or_custom_format_threshold(self):
        now = dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc)
        release = TorznabRelease(title="Fresh", pub_date="Sun, 20 Sep 2026 11:59:00 +0000")
        indexer = self._indexer("torrent")
        quality_profile = QualityProfile(name="HD", allowed_qualities=["720p", "1080p"])
        profile = DelayProfile(
            name="Bypass",
            torrent_delay_minutes=120,
            bypass_if_highest_quality=True,
            bypass_custom_format_score=500,
        )

        highest = evaluate_release_delay(
            profile,
            release=release,
            indexer=indexer,
            quality=parse_quality("1080p"),
            quality_profile=quality_profile,
            now=now,
        )
        custom_format = evaluate_release_delay(
            profile,
            release=release,
            indexer=indexer,
            quality=parse_quality("720p"),
            quality_profile=quality_profile,
            custom_format_score=500,
            now=now,
        )
        self.assertEqual(highest.bypass_reason, "highest_quality")
        self.assertEqual(custom_format.bypass_reason, "custom_format_score")

    def test_filter_uses_tagged_profile_before_global_profile(self):
        show = Show(title="Show")
        tag = Tag(name="fast")
        show.tags.append(tag)
        indexer = self._indexer("torrent")
        profile = QualityProfile(name="HD", allowed_qualities=["720p", "1080p"])
        self.db.add_all([
            show,
            tag,
            profile,
            DelayProfile(name="Global", torrent_delay_minutes=120),
        ])
        self.db.commit()
        tagged = DelayProfile(name="Tagged", tag_id=tag.id, torrent_delay_minutes=0)
        self.db.add(tagged)
        self.db.commit()
        candidate = {
            "rel": TorznabRelease(title="Release", pub_date="Sun, 20 Sep 2026 11:59:00 +0000"),
            "indexer": indexer,
            "quality": parse_quality("720p"),
            "cf_score": 0,
        }

        eligible, delayed, selected = filter_delayed_candidates(
            self.db,
            show,
            [candidate],
            profile,
            now=dt.datetime(2026, 9, 20, 12, 0, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(selected.id, tagged.id)
        self.assertEqual(eligible, [candidate])
        self.assertEqual(delayed, [])
