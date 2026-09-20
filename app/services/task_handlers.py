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

    async def sync_import_list(task, payload: dict):
        from app.database import SessionLocal
        from app.models.db import ImportList
        from app.services.import_list_runtime import run_import_list
        from app.services.task_manager import task_manager

        list_id = int(payload["list_id"])
        with SessionLocal() as db:
            row = db.get(ImportList, list_id)
            if row is None:
                raise RuntimeError(f"Список импорта {list_id} не найден")
            task.update(message=f"Получение элементов списка «{row.name}»", progress=0.1)
            result = await run_import_list(
                db,
                row,
                dry_run=False,
                should_cancel=lambda: not task_manager.is_active(task.id),
            )
            task.update(
                message=f"Добавлено: {result['added']}, уже в библиотеке: {result['existing_count']}",
                progress=1.0,
            )
            return result

    register_task_handler("import_list_sync", sync_import_list)
