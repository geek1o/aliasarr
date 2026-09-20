"""Import-safe registry for durable background-task handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

_HANDLERS: dict[str, Callable] = {}


def register_task_handler(name: str, handler: Optional[Callable] = None):
    """Register directly or use as ``@register_task_handler('name')``."""

    def decorator(func: Callable) -> Callable:
        _HANDLERS[name] = func
        return func

    if handler is not None:
        return decorator(handler)
    return decorator


def get_task_handler(name: str) -> Optional[Callable]:
    return _HANDLERS.get(name)


def unregister_task_handler(name: str) -> None:
    _HANDLERS.pop(name, None)


def clear_task_handlers() -> None:
    """Remove handlers, primarily to isolate tests."""
    _HANDLERS.clear()


def register_builtin_task_handlers() -> None:
    """Register restart-safe commands without importing them at module load."""

    async def refresh_metadata(task, payload: dict):
        from app.services.metadata import refresh_all_shows_metadata

        return await refresh_all_shows_metadata(
            None,
            force=bool(payload.get("force", True)),
            username=str(payload.get("username") or "system"),
            task_handle=task,
        )

    register_task_handler("metadata_refresh", refresh_metadata)
