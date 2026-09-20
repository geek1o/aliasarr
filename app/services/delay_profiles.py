"""Область действия индексаторов и задержка автоматического захвата релизов."""

from __future__ import annotations

import datetime as dt
import email.utils
import math
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.db import DelayProfile, IndexerType, Show
from app.services.quality import parse_quality


@dataclass(frozen=True)
class ReleaseDelayDecision:
    allowed: bool
    protocol: str
    preferred: bool
    delay_minutes: int
    age_minutes: Optional[float]
    remaining_minutes: int = 0
    bypass_reason: Optional[str] = None


def protocol_for_indexer(indexer: Any) -> str:
    """Newznab считается Usenet, остальные поддерживаемые индексаторы — torrent."""
    indexer_type = getattr(indexer, "type", None)
    value = getattr(indexer_type, "value", indexer_type)
    return "usenet" if value == IndexerType.NEWZNAB.value else "torrent"


def get_delay_profile_for_show(db: Session, show: Show) -> Optional[DelayProfile]:
    """Возвращает профиль конкретной метки тайтла, иначе глобальный профиль."""
    tag_ids = [tag.id for tag in (getattr(show, "tags", None) or []) if getattr(tag, "id", None)]
    if tag_ids:
        tagged = (
            db.query(DelayProfile)
            .filter(DelayProfile.enabled == True, DelayProfile.tag_id.in_(tag_ids))  # noqa: E712
            .order_by(DelayProfile.id.asc())
            .first()
        )
        if isinstance(tagged, DelayProfile):
            return tagged
    global_profile = (
        db.query(DelayProfile)
        .filter(DelayProfile.enabled == True, DelayProfile.tag_id.is_(None))  # noqa: E712
        .order_by(DelayProfile.id.asc())
        .first()
    )
    # Ряд unit-тестов автопоиска использует минимальный MagicMock Session и не
    # объявляет DelayProfile в query side effect. Не трактуем такой mock как профиль.
    return global_profile if isinstance(global_profile, DelayProfile) else None


def filter_indexers_for_show(db: Session, show: Show, indexers: list[Any]) -> list[Any]:
    """Нетегированные индексаторы глобальны; тегированные требуют общей метки с тайтлом."""
    show_tag_ids = {
        tag.id for tag in (getattr(show, "tags", None) or []) if getattr(tag, "id", None)
    }
    result = []
    for indexer in indexers:
        tag_ids = {
            tag.id
            for tag in (getattr(indexer, "tags", None) or [])
            if getattr(tag, "id", None)
        }
        if not tag_ids or show_tag_ids.intersection(tag_ids):
            result.append(indexer)
    return result


def _parse_published_at(raw: Any) -> Optional[dt.datetime]:
    if isinstance(raw, dt.datetime):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        value = raw.strip()
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            parsed = None
        if parsed is None:
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _highest_allowed_rank(quality_profile: Any) -> Optional[int]:
    allowed = getattr(quality_profile, "allowed_qualities", None) or []
    ranks = [parse_quality(name).rank for name in allowed if name]
    return max(ranks) if ranks else None


def evaluate_release_delay(
    profile: DelayProfile,
    *,
    release: Any,
    indexer: Any,
    quality: Any,
    quality_profile: Any,
    custom_format_score: int = 0,
    now: Optional[dt.datetime] = None,
) -> ReleaseDelayDecision:
    """Проверяет, выдержал ли релиз задержку. Используется только автопоиском."""
    protocol = protocol_for_indexer(indexer)
    preferred_protocol = (profile.preferred_protocol or "torrent").lower()
    preferred = preferred_protocol in ("either", "any", protocol)
    delay_minutes = max(
        0,
        profile.usenet_delay_minutes if protocol == "usenet" else profile.torrent_delay_minutes,
    )

    highest_rank = _highest_allowed_rank(quality_profile)
    quality_rank = getattr(quality, "rank", None)
    if profile.bypass_if_highest_quality and highest_rank is not None and quality_rank is not None:
        if quality_rank >= highest_rank:
            return ReleaseDelayDecision(
                True, protocol, preferred, delay_minutes, None, bypass_reason="highest_quality",
            )

    threshold = profile.bypass_custom_format_score
    if threshold is not None and custom_format_score >= threshold:
        return ReleaseDelayDecision(
            True, protocol, preferred, delay_minutes, None, bypass_reason="custom_format_score",
        )

    if delay_minutes == 0:
        return ReleaseDelayDecision(True, protocol, preferred, 0, None)

    published_at = _parse_published_at(getattr(release, "pub_date", None))
    if published_at is None:
        # Некоторые RSS/Torznab-адаптеры не отдают pubDate. Не блокируем такой
        # релиз навсегда: задержка без опорного времени не может быть вычислена.
        return ReleaseDelayDecision(
            True, protocol, preferred, delay_minutes, None, bypass_reason="unknown_publish_date",
        )

    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    else:
        current = current.astimezone(dt.timezone.utc)
    age_minutes = max(0.0, (current - published_at).total_seconds() / 60.0)
    if age_minutes >= delay_minutes:
        return ReleaseDelayDecision(True, protocol, preferred, delay_minutes, age_minutes)

    return ReleaseDelayDecision(
        False,
        protocol,
        preferred,
        delay_minutes,
        age_minutes,
        remaining_minutes=max(1, math.ceil(delay_minutes - age_minutes)),
    )


def filter_delayed_candidates(
    db: Session,
    show: Show,
    candidates: list[dict[str, Any]],
    quality_profile: Any,
    *,
    now: Optional[dt.datetime] = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Optional[DelayProfile]]:
    """Возвращает доступные и отложенные кандидаты, дополняя их решением политики."""
    profile = get_delay_profile_for_show(db, show)
    if profile is None:
        return candidates, [], None

    eligible: list[dict[str, Any]] = []
    delayed: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = evaluate_release_delay(
            profile,
            release=candidate["rel"],
            indexer=candidate["indexer"],
            quality=candidate.get("quality"),
            quality_profile=quality_profile,
            custom_format_score=candidate.get("cf_score") or 0,
            now=now,
        )
        candidate["delay_decision"] = decision
        candidate["preferred_protocol"] = decision.preferred
        (eligible if decision.allowed else delayed).append(candidate)
    return eligible, delayed, profile
