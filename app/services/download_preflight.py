"""Preflight validation for downloads before they are sent to a client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.file_preflight import (
    ConflictPolicy,
    FileIntent,
    OperationMode,
    preflight_file_operation,
)
from app.services.path_security import configured_download_roots, map_local_path


def content_download_folder(settings: Any, content_type: str) -> str:
    if content_type == "movie":
        return str(getattr(settings, "download_folder_movies", "") or "")
    if content_type == "anime":
        return str(getattr(settings, "download_folder_anime", "") or "")
    return str(getattr(settings, "download_folder_series", "") or "")


def prepare_download_target(
    settings: Any,
    content_type: str,
    download_client: Any,
    *,
    size_bytes: int | None = None,
    probe_write: bool = True,
) -> str:
    """Validate the local target and return the path visible to the client."""
    local_folder = content_download_folder(settings, content_type)
    if not local_folder:
        return ""
    local_root = Path(local_folder).expanduser().resolve(strict=False)
    probe_target = local_root / ".aliasarr-download-preflight"
    report = preflight_file_operation(
        [
            FileIntent(
                source=None,
                destination=probe_target,
                mode=OperationMode.DOWNLOAD,
                size_bytes=max(0, int(size_bytes or 0)),
                conflict_policy=ConflictPolicy.REPLACE,
            )
        ],
        destination_roots=configured_download_roots(settings),
        probe_write=probe_write,
    )
    report.raise_for_errors()
    mappings = getattr(download_client, "remote_path_mappings", None) or []
    return map_local_path(str(local_root), mappings)
