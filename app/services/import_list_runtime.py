"""SQLAlchemy integration for import-list adapters and durable commands."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.db import Episode, EpisodeStatus, ImportList, Show, Tag
from app.services.import_lists import (
    ImportListAddOptions,
    ImportListDefinition,
    ImportListItem,
    ImportListSyncCancelled,
    ImportListService,
    ImportListSource,
    MediaIdentity,
    build_default_adapters,
)
from app.services.postprocess import get_show_default_path, sanitize_filename
from app.services.settings_service import get_or_create_settings


logger = logging.getLogger(__name__)


def definition_from_row(row: ImportList) -> ImportListDefinition:
    return ImportListDefinition(
        id=row.id,
        name=row.name,
        source=ImportListSource(row.source),
        source_id=row.source_id,
        api_key=row.api_key or "",
        username=row.username,
        access_token=row.access_token,
        enabled=row.enabled,
        interval_minutes=row.interval_minutes,
        last_synced_at=row.last_synced_at,
        include_movies=row.include_movies,
        include_series=row.include_series,
        include_crew=row.include_crew,
        language=row.language,
        add_options=ImportListAddOptions(
            monitored=row.monitored,
            search_on_add=row.search_on_add,
            quality_profile_id=row.quality_profile_id,
            root_folder=row.root_folder,
            tags=tuple(int(tag_id) for tag_id in (row.tag_ids or [])),
        ),
    )


class DatabaseImportTarget:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def list_identities(self) -> list[MediaIdentity]:
        return [
            MediaIdentity(
                media_type=show.content_type,
                title=show.title,
                year=show.year,
                tmdb_id=show.tmdb_id,
                imdb_id=show.imdb_id,
            )
            for show in self.db.query(Show).all()
        ]

    async def add(self, item: ImportListItem, options: ImportListAddOptions) -> bool:
        filters = []
        if item.tmdb_id is not None:
            filters.append(Show.tmdb_id == item.tmdb_id)
        if item.imdb_id:
            filters.append(Show.imdb_id == item.imdb_id)
        filters.append(
            (func.lower(Show.title) == item.title.strip().lower())
            & (Show.year == item.year if item.year is not None else Show.year.is_(None))
        )
        if self.db.query(Show).filter(or_(*filters)).first():
            return False

        settings = get_or_create_settings(self.db)
        quality_profile_id = options.quality_profile_id
        if quality_profile_id is None:
            attr = "default_quality_profile_movie_id" if item.media_type == "movie" else "default_quality_profile_series_id"
            quality_profile_id = getattr(settings, attr, None)
        # Aliasarr has no Trakt metadata provider.  Keep TMDb IDs when Trakt
        # supplies them; otherwise select Aliasarr's normal content provider
        # without storing an invalid ``trakt:...`` ID for that provider.
        metadata_id = f"tmdb:{item.tmdb_id}" if item.tmdb_id else None
        metadata_source = "tmdb" if item.tmdb_id else (
            "radarr" if item.media_type == "movie" else "skyhook"
        )
        show = Show(
            title=item.title.strip(),
            year=item.year,
            overview=item.overview,
            metadata_source=metadata_source,
            metadata_id=metadata_id,
            tmdb_id=item.tmdb_id,
            imdb_id=item.imdb_id,
            content_type=item.media_type,
            monitored=options.monitored,
            quality_profile_id=quality_profile_id,
        )
        if options.root_folder:
            folder = sanitize_filename(show.title)
            if show.content_type == "movie" and show.year:
                folder = f"{folder} ({show.year})"
            show.path = str(Path(options.root_folder).expanduser() / folder)
        else:
            show.path = get_show_default_path(show, settings)
        if options.tags:
            show.tags = self.db.query(Tag).filter(Tag.id.in_(options.tags)).all()
        self.db.add(show)
        self.db.flush()
        if show.content_type == "movie":
            self.db.add(
                Episode(
                    show_id=show.id,
                    season_number=1,
                    episode_number=1,
                    title=show.title,
                    status=EpisodeStatus.WANTED if options.monitored else EpisodeStatus.IGNORED,
                    monitored=options.monitored,
                )
            )
        self.db.commit()
        self.db.refresh(show)

        if options.search_on_add:
            try:
                from app.services.metadata import refresh_show_metadata

                await refresh_show_metadata(self.db, show)
                self.db.refresh(show)
                from app.services.auto_search import search_and_grab_show

                await search_and_grab_show(self.db, show, wanted_only=True)
            except Exception:
                # The show is already committed at this point.  A transient
                # metadata/indexer error must not turn a successful import into
                # a failed item that will be retried and reported incorrectly.
                logger.exception("Post-import refresh/search failed for show id=%s", show.id)
        return True


def serialize_result(result) -> dict[str, Any]:
    preview = result.preview
    return {
        "dry_run": result.dry_run,
        "fetched_count": preview.fetched_count,
        "duplicate_count": preview.duplicate_count,
        "invalid_count": preview.invalid_count,
        "add_count": preview.add_count,
        "existing_count": preview.existing_count,
        "entries": [
            {
                "action": entry.action.value,
                "media_type": entry.item.media_type,
                "title": entry.item.title,
                "year": entry.item.year,
                "tmdb_id": entry.item.tmdb_id,
                "imdb_id": entry.item.imdb_id,
                "trakt_id": entry.item.trakt_id,
            }
            for entry in preview.entries
        ],
        "added": len(result.added),
        "became_existing": len(result.became_existing),
        "failures": [
            {"title": failure.item.title, "error": failure.error}
            for failure in result.failures
        ],
    }


async def run_import_list(
    db: Session,
    row: ImportList,
    *,
    dry_run: bool = False,
    adapters=None,
    should_cancel=None,
) -> dict[str, Any]:
    definition = definition_from_row(row)
    service = ImportListService(adapters or build_default_adapters(), DatabaseImportTarget(db))
    try:
        result = await service.sync(
            definition,
            dry_run=dry_run,
            should_cancel=should_cancel,
        )
    except ImportListSyncCancelled:
        raise
    except Exception as exc:
        if not dry_run:
            row.last_error = str(exc)
            row.last_result = None
            db.commit()
        raise
    payload = serialize_result(result)
    if not dry_run:
        row.last_synced_at = dt.datetime.utcnow()
        row.last_error = None if not result.failures else f"Ошибок элементов: {len(result.failures)}"
        row.last_result = payload
        db.commit()
    return payload


def enqueue_due_import_lists(db: Session) -> int:
    from app.services.task_manager import task_manager

    now = dt.datetime.now(dt.timezone.utc)
    queued = 0
    for row in db.query(ImportList).filter(ImportList.enabled == True).order_by(ImportList.id).all():  # noqa: E712
        if not definition_from_row(row).is_due(now):
            continue
        task_manager.enqueue(
            "import_list_sync",
            f"Синхронизация списка «{row.name}»",
            {"list_id": row.id},
            active_key=f"import_list:{row.id}",
            max_attempts=3,
            resumable=True,
        )
        queued += 1
    return queued
