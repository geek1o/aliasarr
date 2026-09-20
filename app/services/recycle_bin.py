"""Recoverable media deletion backed by per-library recycle directories."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from app.services.file_preflight import QuarantineRecord, quarantine_path, restore_quarantined
from app.services.path_security import UnsafeMediaPathError, require_descendant


MANIFEST_NAME = ".aliasarr-recycle.json"


@dataclass(frozen=True)
class RecycleEntry:
    id: str
    original_path: str
    recycled_path: str
    operation: str
    size_bytes: int
    created_at: str
    library_root: str


def _resolved_roots(roots: Iterable[str | os.PathLike[str]]) -> tuple[Path, ...]:
    unique: list[Path] = []
    for raw in roots:
        if not raw or not str(raw).strip():
            continue
        root = Path(raw).expanduser().resolve(strict=False)
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def _owning_root(path: Path, roots: tuple[Path, ...]) -> Path:
    candidates: list[Path] = []
    for root in roots:
        try:
            require_descendant(path, (root,))
        except UnsafeMediaPathError:
            continue
        candidates.append(root)
    if not candidates:
        raise UnsafeMediaPathError(f"Путь {path} находится вне корней медиатеки")
    return max(candidates, key=lambda item: len(item.parts))


def _entry_id(library_root: Path, bucket: Path) -> str:
    value = f"{library_root}\0{bucket.name}".encode("utf-8", errors="surrogatepass")
    return hashlib.sha256(value).hexdigest()[:24]


def _write_manifest(entry: RecycleEntry, bucket: Path) -> None:
    target = bucket / MANIFEST_NAME
    temporary = bucket / f"{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def recycle_media_path(
    path: str | os.PathLike[str],
    *,
    library_roots: Iterable[str | os.PathLike[str]],
    operation: str = "delete",
) -> RecycleEntry:
    """Move a media path into the owning library's hidden recycle directory."""
    source = Path(path).expanduser().resolve(strict=False)
    roots = _resolved_roots(library_roots)
    owner = _owning_root(source, roots)
    recycle_root = owner / ".aliasarr-recycle"
    record = quarantine_path(source, recycle_root, operation=operation)
    bucket = record.quarantined_path.parent
    entry = RecycleEntry(
        id=_entry_id(owner, bucket),
        original_path=str(record.original_path),
        recycled_path=str(record.quarantined_path),
        operation=record.operation,
        size_bytes=record.size_bytes,
        created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        library_root=str(owner),
    )
    try:
        _write_manifest(entry, bucket)
    except Exception:
        restore_quarantined(record)
        try:
            bucket.rmdir()
        except OSError:
            pass
        raise
    return entry


def _read_entry(manifest: Path, owner: Path) -> RecycleEntry | None:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        entry = RecycleEntry(**payload)
        recycled = require_descendant(entry.recycled_path, (owner / ".aliasarr-recycle",))
        if Path(entry.library_root).resolve(strict=False) != owner:
            return None
        if not recycled.exists():
            return None
        return entry
    except (OSError, TypeError, ValueError, json.JSONDecodeError, UnsafeMediaPathError):
        return None


def list_recycled_media(
    library_roots: Iterable[str | os.PathLike[str]],
) -> list[RecycleEntry]:
    entries: list[RecycleEntry] = []
    for owner in _resolved_roots(library_roots):
        recycle_root = owner / ".aliasarr-recycle"
        if not recycle_root.is_dir():
            continue
        for manifest in recycle_root.glob(f"*/{MANIFEST_NAME}"):
            entry = _read_entry(manifest, owner)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda entry: entry.created_at, reverse=True)


def find_recycled_media(
    entry_id: str,
    library_roots: Iterable[str | os.PathLike[str]],
) -> RecycleEntry:
    for entry in list_recycled_media(library_roots):
        if entry.id == entry_id:
            return entry
    raise FileNotFoundError("Элемент корзины не найден")


def restore_recycled_media(
    entry_id: str,
    *,
    library_roots: Iterable[str | os.PathLike[str]],
    overwrite: bool = False,
) -> Path:
    entry = find_recycled_media(entry_id, library_roots)
    owner = Path(entry.library_root).resolve(strict=False)
    original = require_descendant(entry.original_path, (owner,))
    recycled = require_descendant(entry.recycled_path, (owner / ".aliasarr-recycle",))
    record = QuarantineRecord(original, recycled, entry.operation, entry.size_bytes)
    restored = restore_quarantined(record, overwrite=overwrite)
    shutil.rmtree(recycled.parent, ignore_errors=True)
    return restored


def purge_recycled_media(
    entry_id: str,
    *,
    library_roots: Iterable[str | os.PathLike[str]],
) -> None:
    entry = find_recycled_media(entry_id, library_roots)
    owner = Path(entry.library_root).resolve(strict=False)
    recycled = require_descendant(entry.recycled_path, (owner / ".aliasarr-recycle",))
    if recycled.is_dir() and not recycled.is_symlink():
        shutil.rmtree(recycled)
    else:
        recycled.unlink(missing_ok=True)
    shutil.rmtree(recycled.parent, ignore_errors=True)


def purge_expired_recycled_media(
    *,
    library_roots: Iterable[str | os.PathLike[str]],
    retention_days: int,
    now: dt.datetime | None = None,
) -> list[str]:
    if retention_days < 0:
        raise ValueError("retention_days не может быть отрицательным")
    current = now or dt.datetime.now(dt.timezone.utc)
    removed: list[str] = []
    for entry in list_recycled_media(library_roots):
        created = dt.datetime.fromisoformat(entry.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        if created <= current - dt.timedelta(days=retention_days):
            purge_recycled_media(entry.id, library_roots=library_roots)
            removed.append(entry.id)
    return removed
