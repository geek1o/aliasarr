"""Read-only inspection of one release title using the production release pipeline."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.db import AppSettings, Episode, EpisodeStatus, QualityProfile, Show
from app.services.decision_engine import DecisionEngine
from app.services.matcher import (
    build_alias_candidates,
    is_non_video_release,
    match_release,
    resolve_part_offset,
)
from app.services.parser import (
    ParsedRelease,
    ReleaseKind,
    detect_season_label,
    parse_episode,
)


def serialize_parsed_release(
    parsed: ParsedRelease,
    *,
    title: str,
    categories: Optional[list[int]] = None,
) -> dict[str, Any]:
    """Return the parser result without reimplementing any parsing rules."""
    season_label = detect_season_label(title)
    is_video = not is_non_video_release(title, categories=categories)
    status = "parsed"
    if not is_video:
        status = "non_video"
    elif parsed.kind == ReleaseKind.UNKNOWN and season_label.get("type") == "none":
        status = "unknown"

    return {
        "kind": parsed.kind.value,
        "is_video": is_video,
        "season": parsed.season,
        "seasons": list(parsed.seasons or []),
        "episodes": list(parsed.episodes or []),
        "part": parsed.part,
        "total_in_part": parsed.total_in_part,
        "is_range": parsed.is_range,
        "has_specials": parsed.has_specials,
        "special_episodes": list(parsed.special_episodes or []),
        "matched_pattern": parsed.matched_pattern,
        "season_label": season_label,
        "status": status,
        "status_text": {
            "parsed": "Распознано",
            "unknown": "Не распознано",
            "non_video": "Не-видео (отфильтровано)",
        }[status],
    }


def _target_episodes(
    show: Show, season: Optional[int], episode: Optional[int]
) -> list[Episode]:
    episodes = list(show.episodes or [])
    if season is not None:
        episodes = [ep for ep in episodes if ep.season_number == season]
    if episode is not None:
        episodes = [ep for ep in episodes if ep.episode_number == episode]
    return episodes


def _episode_key(ep: Episode) -> str:
    return f"S{int(ep.season_number or 0):02d}E{int(ep.episode_number or 0):02d}"


def _build_coverage(
    show: Show, match: Any, target_episodes: list[Episode]
) -> dict[str, Any]:
    parsed = match.parsed
    all_episodes = list(show.episodes or [])
    candidate_pool = target_episodes or all_episodes
    alias = getattr(match, "alias_candidate", None)
    effective_season = (
        alias.season_number
        if alias is not None and alias.season_number is not None
        else (parsed.season if parsed.season is not None else 1)
    )
    alias_offset = (alias.episode_offset or 0) if alias is not None else 0
    part_offset = 0
    if not alias_offset and parsed.part and parsed.part >= 2:
        season_eps = [ep for ep in all_episodes if ep.season_number == effective_season]
        wanted_eps = [
            ep
            for ep in candidate_pool
            if ep.season_number == effective_season
            and ep.status in (EpisodeStatus.WANTED, EpisodeStatus.MISSING)
        ]
        part_offset = resolve_part_offset(
            parsed.part,
            parsed.total_in_part,
            parsed.episodes,
            season_eps,
            wanted_eps,
        )
    effective_offset = alias_offset or part_offset

    covered: list[Episode] = []
    if show.content_type == "movie":
        covered = candidate_pool if match.matched else []
    elif parsed.has_specials:
        regular = {number + effective_offset for number in (parsed.episodes or [])}
        specials = set(parsed.special_episodes or [])
        covered = [
            ep
            for ep in candidate_pool
            if (
                ep.season_number == effective_season
                and (not regular or ep.episode_number in regular)
            )
            or (
                ep.season_number == 0
                and (not specials or ep.episode_number in specials)
            )
        ]
    elif parsed.kind == ReleaseKind.SEASON_PACK:
        covered = [ep for ep in candidate_pool if ep.season_number == effective_season]
    elif parsed.seasons:
        seasons = set(parsed.seasons)
        covered = [ep for ep in candidate_pool if ep.season_number in seasons]
    elif parsed.episodes:
        effective_numbers = {number + effective_offset for number in parsed.episodes}
        covered = [
            ep
            for ep in candidate_pool
            if (
                (
                    ep.season_number == effective_season
                    and ep.episode_number in effective_numbers
                )
                or (
                    ep.absolute_number is not None
                    and ep.absolute_number in effective_numbers
                )
            )
        ]

    unique_covered = {ep.id: ep for ep in covered}
    covered = sorted(
        unique_covered.values(),
        key=lambda ep: (ep.season_number or 0, ep.episode_number or 0),
    )
    wanted_count = sum(
        ep.status in (EpisodeStatus.WANTED, EpisodeStatus.MISSING) for ep in covered
    )
    downloaded_count = sum(ep.status == EpisodeStatus.DOWNLOADED for ep in covered)

    if show.content_type == "movie" and covered:
        summary = "Фильм"
    elif not covered:
        summary = (
            "Серии не совпали" if show.content_type != "movie" else "Фильм не совпал"
        )
    elif len(covered) == 1:
        summary = _episode_key(covered[0])
    else:
        summary = (
            f"{_episode_key(covered[0])}–{_episode_key(covered[-1])} "
            f"({len(covered)} сер.)"
        )

    return {
        "summary": summary,
        "count": len(covered),
        "wanted_overlap": wanted_count,
        "downloaded_overlap": downloaded_count,
        "part_offset": part_offset,
        "effective_offset": effective_offset,
        "episodes": [
            {
                "id": ep.id,
                "season": ep.season_number,
                "episode": ep.episode_number,
                "absolute": ep.absolute_number,
                "key": _episode_key(ep),
                "status": ep.status.value
                if hasattr(ep.status, "value")
                else str(ep.status),
                "monitored": bool(ep.monitored),
            }
            for ep in covered[:500]
        ],
        "truncated": len(covered) > 500,
    }


def inspect_release(
    db: Session,
    *,
    title: str,
    show: Optional[Show] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    size_bytes: int = 0,
    seeders: int = 0,
    categories: Optional[list[int]] = None,
    torrent_hash: Optional[str] = None,
    guid: Optional[str] = None,
    download_url: Optional[str] = None,
) -> dict[str, Any]:
    """Inspect a release through the production pipeline without side effects."""
    categories = list(categories or [])
    parsed = parse_episode(title)
    analysis = serialize_parsed_release(parsed, title=title, categories=categories)
    target_episodes = _target_episodes(show, season, episode) if show else []

    match = None
    quality_profile = None
    if show:
        aliases = build_alias_candidates(show, db=db)
        match = match_release(
            title,
            show.id,
            aliases,
            content_type=show.content_type,
            categories=categories,
            show_year=getattr(show, "year", None),
            parsed=parsed,
        )
        if show.quality_profile_id:
            quality_profile = db.get(QualityProfile, show.quality_profile_id)

    decision = DecisionEngine.evaluate_release(
        db=db,
        title=title,
        show=show,
        episodes=target_episodes or None,
        size_bytes=size_bytes,
        seeders=seeders,
        settings=db.query(AppSettings).first(),
        quality_profile=quality_profile,
        categories=categories,
        torrent_hash=torrent_hash,
        guid=guid,
        download_url=download_url,
        precomputed_match=match,
    )

    match_data = None
    coverage = None
    if show and match is not None:
        alias = getattr(match, "alias_candidate", None)
        coverage = _build_coverage(show, match, target_episodes)
        match_data = {
            "matched": match.matched,
            "show_id": show.id,
            "show_title": show.title,
            "alias_id": match.alias_id,
            "alias_text": match.alias_text,
            "score": round(match.score, 1),
            "effective_season": match.effective_season,
            "effective_episodes": match.effective_episodes,
            "alias_scope": None
            if alias is None
            else {
                "season": alias.season_number,
                "episode_start": alias.episode_start,
                "episode_end": alias.episode_end,
                "episode_offset": alias.episode_offset or 0,
                "part_type": alias.part_type,
                "target_number": alias.target_number,
            },
        }

    return {
        "title": title,
        "show": None
        if show is None
        else {
            "id": show.id,
            "title": show.title,
            "content_type": show.content_type,
            "year": show.year,
        },
        "analysis": analysis,
        "match": match_data,
        "coverage": coverage,
        "decision": decision.to_dict(),
    }
