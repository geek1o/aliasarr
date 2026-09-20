from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


class UnsafeMediaPathError(ValueError):
    """Raised when a destructive operation targets a path outside the media roots."""


@dataclass(frozen=True)
class PathMapping:
    """A download-client path prefix and the matching local path prefix."""

    remote_root: str
    local_root: str


def configured_library_roots(settings) -> tuple[Path, ...]:
    """Return resolved, unique library roots configured for every content category."""
    raw_roots = (
        getattr(settings, "root_folder", None),
        getattr(settings, "root_folder_movies", None),
        getattr(settings, "root_folder_series", None),
        getattr(settings, "root_folder_anime", None),
    )
    roots: list[Path] = []
    for raw_root in raw_roots:
        if not raw_root or not str(raw_root).strip():
            continue
        root = Path(str(raw_root)).expanduser().resolve(strict=False)
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def configured_download_roots(settings) -> tuple[Path, ...]:
    """Return resolved, unique download roots configured for every category."""
    raw_roots = (
        getattr(settings, "download_folder", None),
        getattr(settings, "download_folder_movies", None),
        getattr(settings, "download_folder_series", None),
        getattr(settings, "download_folder_anime", None),
    )
    roots: list[Path] = []
    for raw_root in raw_roots:
        if not raw_root or not str(raw_root).strip():
            continue
        root = Path(str(raw_root)).expanduser().resolve(strict=False)
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def require_descendant(
    path: str | os.PathLike[str],
    roots: Iterable[str | os.PathLike[str]],
    *,
    allow_root: bool = False,
) -> Path:
    """Resolve *path* and require containment in one of *roots*.

    Existing symlinks are resolved on both sides.  This makes the helper safe for
    both paths that already exist and destinations whose last components have not
    been created yet.
    """
    if not path or not str(path).strip():
        raise UnsafeMediaPathError("Пустой путь нельзя использовать для файловой операции")

    candidate = Path(path).expanduser().resolve(strict=False)
    resolved_roots = tuple(
        Path(root).expanduser().resolve(strict=False)
        for root in roots
        if root and str(root).strip()
    )
    if not resolved_roots:
        raise UnsafeMediaPathError("Не настроены разрешённые корневые папки")

    for root in resolved_roots:
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if allow_root or relative != Path("."):
            return candidate

    roots_text = ", ".join(str(root) for root in resolved_roots)
    raise UnsafeMediaPathError(
        f"Путь {candidate} находится вне разрешённых корней: {roots_text}"
    )


def safe_join_under(base: str | os.PathLike[str], relative_path: str) -> Path:
    """Join an untrusted client-reported relative path below *base*.

    Torrent APIs use POSIX separators even when Aliasarr itself runs elsewhere.
    Backslashes are therefore treated as separators as well. Absolute paths,
    drive-qualified paths and parent traversal are rejected before resolution.
    """
    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw:
        raise UnsafeMediaPathError("Пустое имя файла загрузчика")
    if raw.startswith("/") or (len(raw) >= 2 and raw[1] == ":"):
        raise UnsafeMediaPathError(f"Загрузчик вернул абсолютный путь: {relative_path}")

    rel = PurePosixPath(raw)
    if rel.is_absolute() or any(part == ".." for part in rel.parts):
        raise UnsafeMediaPathError(f"Путь загрузчика выходит из папки загрузки: {relative_path}")
    clean_parts = [part for part in rel.parts if part not in ("", ".")]
    if not clean_parts:
        raise UnsafeMediaPathError("Пустое имя файла загрузчика")

    base_path = Path(base).expanduser().resolve(strict=False)
    candidate = base_path.joinpath(*clean_parts).resolve(strict=False)
    return require_descendant(candidate, (base_path,))


def _coerce_mapping(value: PathMapping | Mapping[str, Any]) -> PathMapping:
    if isinstance(value, PathMapping):
        return value
    remote = value.get("remote_root", value.get("remote", ""))
    local = value.get("local_root", value.get("local", ""))
    return PathMapping(str(remote or ""), str(local or ""))


def map_client_path(
    client_path: str,
    mappings: Sequence[PathMapping | Mapping[str, Any]],
    *,
    require_mapping: bool = False,
) -> Path:
    """Translate a path reported by a remote download client to a local path.

    The most specific (longest) remote prefix wins. Prefixes are matched on path
    component boundaries, so ``/data`` never matches ``/database``.
    """
    raw = str(client_path or "").strip().replace("\\", "/")
    if not raw:
        raise UnsafeMediaPathError("Загрузчик вернул пустой путь")

    normalized = os.path.normpath(raw)
    candidates: list[tuple[int, str, str]] = []
    for item in mappings:
        mapping = _coerce_mapping(item)
        remote = os.path.normpath(mapping.remote_root.replace("\\", "/"))
        local = mapping.local_root.strip()
        if not remote or remote == "." or not local:
            continue
        try:
            common = os.path.commonpath((normalized, remote))
        except ValueError:
            continue
        if common == remote:
            candidates.append((len(remote), remote, local))

    if not candidates:
        if require_mapping:
            raise UnsafeMediaPathError(f"Для пути загрузчика не настроено сопоставление: {client_path}")
        return Path(client_path).expanduser().resolve(strict=False)

    _, remote, local = max(candidates, key=lambda item: item[0])
    suffix = os.path.relpath(normalized, remote)
    local_root = Path(local).expanduser().resolve(strict=False)
    if suffix == ".":
        return local_root
    return safe_join_under(local_root, suffix)


def map_local_path(
    local_path: str,
    mappings: Sequence[PathMapping | Mapping[str, Any]],
) -> str:
    """Translate a local Aliasarr path to the matching download-client path."""
    candidate = Path(local_path).expanduser().resolve(strict=False)
    choices: list[tuple[int, Path, str]] = []
    for item in mappings:
        mapping = _coerce_mapping(item)
        if not mapping.local_root.strip() or not mapping.remote_root.strip():
            continue
        local_root = Path(mapping.local_root).expanduser().resolve(strict=False)
        try:
            candidate.relative_to(local_root)
        except ValueError:
            continue
        choices.append((len(local_root.parts), local_root, mapping.remote_root))
    if not choices:
        return str(local_path)
    _, local_root, remote_root = max(choices, key=lambda value: value[0])
    relative = candidate.relative_to(local_root)
    remote = remote_root.rstrip("/\\")
    if not relative.parts:
        return remote
    return f"{remote}/{'/'.join(relative.parts)}"


def require_library_descendant(path: str, settings) -> Path:
    """Resolve *path* and require it to be below, but not equal to, a library root.

    Resolving both sides prevents a symlink located below a media root from escaping
    containment before a delete or recursive chmod operation.
    """
    roots = configured_library_roots(settings)
    if not roots:
        raise UnsafeMediaPathError("Не настроена корневая папка медиатеки")
    try:
        return require_descendant(path, roots)
    except UnsafeMediaPathError as exc:
        candidate = Path(str(path)).expanduser().resolve(strict=False)
        roots_text = ", ".join(str(root) for root in roots)
        raise UnsafeMediaPathError(
            f"Путь {candidate} находится вне разрешённых корней медиатеки: {roots_text}"
        ) from exc


def require_library_descendants(paths: Iterable[str], settings) -> None:
    """Validate every non-empty path before beginning a destructive operation."""
    for path in paths:
        if path:
            require_library_descendant(path, settings)
