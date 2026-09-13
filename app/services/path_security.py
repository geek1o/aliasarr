from __future__ import annotations

from pathlib import Path
from typing import Iterable


class UnsafeMediaPathError(ValueError):
    """Raised when a destructive operation targets a path outside the media roots."""


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


def require_library_descendant(path: str, settings) -> Path:
    """Resolve *path* and require it to be below, but not equal to, a library root.

    Resolving both sides prevents a symlink located below a media root from escaping
    containment before a delete or recursive chmod operation.
    """
    if not path or not str(path).strip():
        raise UnsafeMediaPathError("Пустой путь нельзя использовать для файловой операции")

    candidate = Path(str(path)).expanduser().resolve(strict=False)
    roots = configured_library_roots(settings)
    if not roots:
        raise UnsafeMediaPathError("Не настроена корневая папка медиатеки")

    for root in roots:
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if relative != Path("."):
            return candidate

    roots_text = ", ".join(str(root) for root in roots)
    raise UnsafeMediaPathError(
        f"Путь {candidate} находится вне разрешённых корней медиатеки: {roots_text}"
    )


def require_library_descendants(paths: Iterable[str], settings) -> None:
    """Validate every non-empty path before beginning a destructive operation."""
    for path in paths:
        if path:
            require_library_descendant(path, settings)
