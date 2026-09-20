"""Import-list adapters and deterministic preview/sync orchestration.

The module deliberately does not depend on SQLAlchemy or FastAPI.  Persistence
and API layers can implement the small protocols below, while tests and command
line tools can use in-memory fakes.  No network request is made until an adapter
is explicitly asked to fetch a list.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence
from urllib.parse import quote

import httpx


class ImportListSource(str, Enum):
    TMDB_LIST = "tmdb_list"
    TMDB_PERSON = "tmdb_person"
    TRAKT_LIST = "trakt_list"


class ImportAction(str, Enum):
    ADD = "add"
    EXISTS = "exists"


class ImportListSyncCancelled(RuntimeError):
    """Raised between safe sync boundaries after a user cancellation."""


@dataclass(frozen=True)
class ImportListAddOptions:
    monitored: bool = True
    search_on_add: bool = False
    quality_profile_id: int | None = None
    root_folder: str | None = None
    tags: tuple[int, ...] = ()


@dataclass(frozen=True)
class ImportListDefinition:
    id: int | str
    name: str
    source: ImportListSource
    source_id: str
    api_key: str = field(repr=False, default="")
    username: str | None = None
    access_token: str | None = field(repr=False, default=None)
    enabled: bool = True
    interval_minutes: int = 360
    last_synced_at: datetime | None = None
    include_movies: bool = True
    include_series: bool = True
    include_crew: bool = False
    language: str | None = None
    add_options: ImportListAddOptions = field(default_factory=ImportListAddOptions)

    def __post_init__(self) -> None:
        if not str(self.source_id).strip():
            raise ValueError("source_id must not be empty")
        if self.interval_minutes < 1:
            raise ValueError("interval_minutes must be at least 1")
        if self.source is ImportListSource.TRAKT_LIST and not (self.username or "").strip():
            raise ValueError("username is required for a Trakt list")

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.last_synced_at is None:
            return True
        return _as_utc(self.last_synced_at) + timedelta(minutes=self.interval_minutes) <= _as_utc(now)


@dataclass(frozen=True)
class MediaIdentity:
    media_type: str
    title: str = ""
    year: int | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    trakt_id: int | None = None

    @property
    def keys(self) -> frozenset[tuple[str, str, str]]:
        media_type = _media_type(self.media_type)
        keys: set[tuple[str, str, str]] = set()
        if self.tmdb_id is not None:
            keys.add((media_type, "tmdb", str(self.tmdb_id)))
        if self.imdb_id:
            keys.add((media_type, "imdb", self.imdb_id.strip().casefold()))
        if self.trakt_id is not None:
            keys.add((media_type, "trakt", str(self.trakt_id)))
        normalized_title = _normalize_title(self.title)
        if normalized_title:
            keys.add((media_type, "title", f"{normalized_title}\0{self.year or 0}"))
        return frozenset(keys)


@dataclass(frozen=True)
class ImportListItem(MediaIdentity):
    source: ImportListSource = ImportListSource.TMDB_LIST
    source_item_id: str = ""
    overview: str | None = None
    poster_path: str | None = None


@dataclass(frozen=True)
class ImportPreviewEntry:
    item: ImportListItem
    action: ImportAction


@dataclass(frozen=True)
class ImportListPreview:
    list_id: int | str
    entries: tuple[ImportPreviewEntry, ...]
    fetched_count: int
    duplicate_count: int
    invalid_count: int

    @property
    def add_count(self) -> int:
        return sum(entry.action is ImportAction.ADD for entry in self.entries)

    @property
    def existing_count(self) -> int:
        return sum(entry.action is ImportAction.EXISTS for entry in self.entries)


@dataclass(frozen=True)
class ImportFailure:
    item: ImportListItem
    error: str


@dataclass(frozen=True)
class ImportListSyncResult:
    preview: ImportListPreview
    dry_run: bool
    added: tuple[ImportListItem, ...] = ()
    became_existing: tuple[ImportListItem, ...] = ()
    failures: tuple[ImportFailure, ...] = ()


class JsonHttpClient(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any: ...


class ImportListAdapter(Protocol):
    async def fetch(self, definition: ImportListDefinition) -> tuple[list[ImportListItem], int]: ...


class ImportTarget(Protocol):
    async def list_identities(self) -> Sequence[MediaIdentity]: ...

    async def add(self, item: ImportListItem, options: ImportListAddOptions) -> bool:
        """Add an item, returning False if it already exists due to a race."""


class ImportListStore(Protocol):
    async def list_enabled(self) -> Sequence[ImportListDefinition]: ...

    async def record_run(
        self,
        definition: ImportListDefinition,
        result: ImportListSyncResult,
        completed_at: datetime,
    ) -> None: ...


class HttpxJsonClient:
    """Small production HTTP implementation; adapters remain fully injectable."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()


class TMDbImportListAdapter:
    def __init__(self, http: JsonHttpClient, *, base_url: str = "https://api.themoviedb.org/3") -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def fetch(self, definition: ImportListDefinition) -> tuple[list[ImportListItem], int]:
        if definition.source not in {ImportListSource.TMDB_LIST, ImportListSource.TMDB_PERSON}:
            raise ValueError("TMDb adapter received an incompatible source")
        if not definition.api_key:
            raise ValueError("TMDb api_key is required")

        if definition.source is ImportListSource.TMDB_PERSON:
            payload = await self.http.get_json(
                f"{self.base_url}/person/{quote(definition.source_id, safe='')}/combined_credits",
                params=_tmdb_params(definition, page=None),
            )
            raw_items = list(_as_list(_as_dict(payload).get("cast")))
            if definition.include_crew:
                raw_items.extend(_as_list(_as_dict(payload).get("crew")))
        else:
            raw_items = []
            page = 1
            while page <= 100:
                payload = _as_dict(
                    await self.http.get_json(
                        f"{self.base_url}/list/{quote(definition.source_id, safe='')}",
                        params=_tmdb_params(definition, page=page),
                    )
                )
                raw_items.extend(_as_list(payload.get("items")))
                total_pages = _positive_int(payload.get("total_pages")) or 1
                if page >= total_pages:
                    break
                page += 1

        items = [item for raw in raw_items if (item := _tmdb_item(raw, definition)) is not None]
        return items, len(raw_items) - len(items)


class TraktImportListAdapter:
    def __init__(self, http: JsonHttpClient, *, base_url: str = "https://api.trakt.tv") -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def fetch(self, definition: ImportListDefinition) -> tuple[list[ImportListItem], int]:
        if definition.source is not ImportListSource.TRAKT_LIST:
            raise ValueError("Trakt adapter received an incompatible source")
        if not definition.api_key:
            raise ValueError("Trakt api_key is required")
        username = quote((definition.username or "").strip(), safe="")
        slug = quote(definition.source_id.strip(), safe="")
        url = f"{self.base_url}/users/{username}/lists/{slug}/items"
        headers = {"trakt-api-key": definition.api_key, "trakt-api-version": "2"}
        if definition.access_token:
            headers["Authorization"] = f"Bearer {definition.access_token}"

        raw_items: list[Any] = []
        page = 1
        page_size = 100
        while page <= 100:
            payload = _as_list(
                await self.http.get_json(url, params={"page": page, "limit": page_size}, headers=headers)
            )
            raw_items.extend(payload)
            if len(payload) < page_size:
                break
            page += 1

        items = [item for raw in raw_items if (item := _trakt_item(raw, definition)) is not None]
        return items, len(raw_items) - len(items)


class ImportListService:
    def __init__(self, adapters: Mapping[ImportListSource, ImportListAdapter], target: ImportTarget) -> None:
        self.adapters = dict(adapters)
        self.target = target

    async def preview(self, definition: ImportListDefinition) -> ImportListPreview:
        adapter = self.adapters.get(definition.source)
        if adapter is None:
            raise ValueError(f"no adapter registered for {definition.source.value}")
        fetched, invalid_count = await adapter.fetch(definition)
        unique_items, duplicate_count = deduplicate_items(fetched)
        existing = await self.target.list_identities()
        existing_keys = set().union(*(identity.keys for identity in existing)) if existing else set()
        entries = tuple(
            ImportPreviewEntry(
                item=item,
                action=ImportAction.EXISTS if item.keys & existing_keys else ImportAction.ADD,
            )
            for item in unique_items
        )
        return ImportListPreview(
            list_id=definition.id,
            entries=entries,
            fetched_count=len(fetched) + invalid_count,
            duplicate_count=duplicate_count,
            invalid_count=invalid_count,
        )

    async def sync(
        self,
        definition: ImportListDefinition,
        *,
        dry_run: bool = False,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ImportListSyncResult:
        if should_cancel and should_cancel():
            raise ImportListSyncCancelled("Синхронизация списка отменена")
        preview = await self.preview(definition)
        if should_cancel and should_cancel():
            raise ImportListSyncCancelled("Синхронизация списка отменена")
        if dry_run:
            return ImportListSyncResult(preview=preview, dry_run=True)

        added: list[ImportListItem] = []
        became_existing: list[ImportListItem] = []
        failures: list[ImportFailure] = []
        for entry in preview.entries:
            if should_cancel and should_cancel():
                raise ImportListSyncCancelled("Синхронизация списка отменена")
            if entry.action is not ImportAction.ADD:
                continue
            try:
                if await self.target.add(entry.item, definition.add_options):
                    added.append(entry.item)
                else:
                    became_existing.append(entry.item)
            except Exception as exc:  # isolate a bad item without aborting the whole list
                failures.append(ImportFailure(item=entry.item, error=str(exc)))
        if should_cancel and should_cancel():
            raise ImportListSyncCancelled("Синхронизация списка отменена")
        return ImportListSyncResult(
            preview=preview,
            dry_run=False,
            added=tuple(added),
            became_existing=tuple(became_existing),
            failures=tuple(failures),
        )


class ImportListScheduler:
    """Runs due lists; an external timer may call :meth:`run_due` periodically."""

    def __init__(
        self,
        service: ImportListService,
        store: ImportListStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.service = service
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def run_due(self, *, dry_run: bool = False) -> tuple[ImportListSyncResult, ...]:
        now = _as_utc(self.clock())
        definitions = sorted(await self.store.list_enabled(), key=lambda item: str(item.id))
        results: list[ImportListSyncResult] = []
        for definition in definitions:
            if not definition.is_due(now):
                continue
            result = await self.service.sync(definition, dry_run=dry_run)
            results.append(result)
            if not dry_run:
                await self.store.record_run(definition, result, _as_utc(self.clock()))
        return tuple(results)


def build_default_adapters(http: JsonHttpClient | None = None) -> dict[ImportListSource, ImportListAdapter]:
    client = http or HttpxJsonClient()
    tmdb = TMDbImportListAdapter(client)
    return {
        ImportListSource.TMDB_LIST: tmdb,
        ImportListSource.TMDB_PERSON: tmdb,
        ImportListSource.TRAKT_LIST: TraktImportListAdapter(client),
    }


def deduplicate_items(items: Iterable[ImportListItem]) -> tuple[tuple[ImportListItem, ...], int]:
    """Merge duplicates and return a stable order independent of provider order."""

    source_items = list(items)
    merged: list[ImportListItem] = []
    for item in sorted(source_items, key=_item_sort_key):
        duplicate_indexes = [index for index, other in enumerate(merged) if item.keys & other.keys]
        if not duplicate_indexes:
            merged.append(item)
        else:
            first = duplicate_indexes[0]
            combined = _merge_item(merged[first], item)
            for index in duplicate_indexes[1:]:
                combined = _merge_item(combined, merged[index])
            merged[first] = combined
            for index in reversed(duplicate_indexes[1:]):
                del merged[index]
    merged.sort(key=_item_sort_key)
    return tuple(merged), len(source_items) - len(merged)


def _merge_item(primary: ImportListItem, secondary: ImportListItem) -> ImportListItem:
    return replace(
        primary,
        title=primary.title or secondary.title,
        year=primary.year or secondary.year,
        tmdb_id=primary.tmdb_id if primary.tmdb_id is not None else secondary.tmdb_id,
        imdb_id=primary.imdb_id or secondary.imdb_id,
        trakt_id=primary.trakt_id if primary.trakt_id is not None else secondary.trakt_id,
        overview=primary.overview or secondary.overview,
        poster_path=primary.poster_path or secondary.poster_path,
    )


def _tmdb_item(raw: Any, definition: ImportListDefinition) -> ImportListItem | None:
    value = _as_dict(raw)
    media_type = _media_type(value.get("media_type") or ("movie" if value.get("title") else "series"))
    if not _media_enabled(media_type, definition):
        return None
    title = str(value.get("title") or value.get("name") or "").strip()
    tmdb_id = _positive_int(value.get("id"))
    if not title or tmdb_id is None:
        return None
    date = str(value.get("release_date") or value.get("first_air_date") or "")
    return ImportListItem(
        media_type=media_type,
        title=title,
        year=_year(date),
        tmdb_id=tmdb_id,
        source=definition.source,
        source_item_id=f"tmdb:{tmdb_id}",
        overview=_optional_string(value.get("overview")),
        poster_path=_optional_string(value.get("poster_path")),
    )


def _trakt_item(raw: Any, definition: ImportListDefinition) -> ImportListItem | None:
    value = _as_dict(raw)
    nested: dict[str, Any]
    if isinstance(value.get("movie"), dict):
        media_type, nested = "movie", value["movie"]
    elif isinstance(value.get("show"), dict):
        media_type, nested = "series", value["show"]
    else:
        return None
    if not _media_enabled(media_type, definition):
        return None
    title = str(nested.get("title") or "").strip()
    ids = _as_dict(nested.get("ids"))
    trakt_id = _positive_int(ids.get("trakt"))
    if not title or trakt_id is None:
        return None
    return ImportListItem(
        media_type=media_type,
        title=title,
        year=_positive_int(nested.get("year")),
        tmdb_id=_positive_int(ids.get("tmdb")),
        imdb_id=_optional_string(ids.get("imdb")),
        trakt_id=trakt_id,
        source=definition.source,
        source_item_id=f"trakt:{trakt_id}",
    )


def _media_enabled(media_type: str, definition: ImportListDefinition) -> bool:
    return (media_type == "movie" and definition.include_movies) or (
        media_type == "series" and definition.include_series
    )


def _tmdb_params(definition: ImportListDefinition, *, page: int | None) -> dict[str, Any]:
    params: dict[str, Any] = {"api_key": definition.api_key}
    if definition.language:
        params["language"] = definition.language
    if page is not None:
        params["page"] = page
    return params


def _item_sort_key(item: ImportListItem) -> tuple[str, str, int, int, str, int, str]:
    return (
        _media_type(item.media_type),
        _normalize_title(item.title),
        item.year or 0,
        item.tmdb_id or 0,
        (item.imdb_id or "").casefold(),
        item.trakt_id or 0,
        item.source_item_id,
    )


def _media_type(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"tv", "show", "series"}:
        return "series"
    if normalized == "movie":
        return "movie"
    return normalized


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _year(value: str) -> int | None:
    match = re.match(r"^(\d{4})", value)
    return int(match.group(1)) if match else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
