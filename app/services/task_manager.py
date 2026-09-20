"""Persistent background activity tracking and durable command primitives."""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect as pyinspect
import logging
import os
import socket
import threading
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable, Optional

from sqlalchemy.exc import IntegrityError

from app.models.db import BackgroundTask

logger = logging.getLogger("aliasarr.tasks")

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class Task:
    """Detached task snapshot whose mutations are persisted by its manager."""

    def __init__(
        self,
        task_id: str,
        name: str,
        title: str,
        message: str = "",
        progress: Optional[float] = None,
        show_id: Optional[int] = None,
        total_items: Optional[int] = None,
        current_item: Optional[int] = None,
        *,
        manager: Optional["TaskManager"] = None,
        status: str = "running",
        started_at: Optional[dt.datetime] = None,
        ended_at: Optional[dt.datetime] = None,
        error: Optional[str] = None,
        mode: str = "inline",
        payload: Optional[dict] = None,
        result: Optional[dict] = None,
        attempts: int = 0,
        max_attempts: int = 1,
    ) -> None:
        self.id = task_id
        self.name = name
        self.title = title
        self.message = message or ""
        self.progress = progress
        self.show_id = show_id
        self.total_items = total_items
        self.current_item = current_item
        self.status = status
        self.started_at = started_at or dt.datetime.utcnow()
        self.ended_at = ended_at
        self.error = error
        self.mode = mode
        self.payload = payload
        self.result = result
        self.attempts = attempts
        self.max_attempts = max_attempts
        self._manager = manager

    @classmethod
    def from_row(
        cls, row: BackgroundTask, manager: Optional["TaskManager"] = None
    ) -> "Task":
        return cls(
            task_id=row.id,
            name=row.name,
            title=row.title,
            message=row.message,
            progress=row.progress,
            show_id=row.show_id,
            total_items=row.total_items,
            current_item=row.current_item,
            manager=manager,
            status=row.status,
            started_at=row.started_at or row.created_at,
            ended_at=row.ended_at,
            error=row.error,
            mode=row.mode,
            payload=row.payload,
            result=row.result,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
        )

    def _copy_from(self, other: "Task") -> None:
        for attr in (
            "name",
            "title",
            "message",
            "progress",
            "show_id",
            "total_items",
            "current_item",
            "status",
            "started_at",
            "ended_at",
            "error",
            "mode",
            "payload",
            "result",
            "attempts",
            "max_attempts",
        ):
            setattr(self, attr, getattr(other, attr))

    def update(
        self,
        message: Optional[str] = None,
        progress: Optional[float] = None,
        current_item: Optional[int] = None,
        total_items: Optional[int] = None,
        show_id: Optional[int] = None,
    ) -> None:
        if self._manager is not None:
            updated = self._manager.update_task(
                self.id,
                message=message,
                progress=progress,
                current_item=current_item,
                total_items=total_items,
                show_id=show_id,
            )
            if updated:
                self._copy_from(updated)
            return
        if message is not None:
            self.message = message
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        if current_item is not None:
            self.current_item = current_item
        if total_items is not None:
            self.total_items = total_items
        if show_id is not None:
            self.show_id = show_id

    def complete(
        self, message: Optional[str] = None, result: Optional[dict] = None
    ) -> None:
        if self._manager is not None:
            updated = self._manager.finish_task(self.id, message=message, result=result)
            if updated:
                self._copy_from(updated)
            return
        self.status = "completed"
        self.ended_at = dt.datetime.utcnow()
        if message is not None:
            self.message = message
        self.progress = 1.0
        self.result = result

    def fail(self, error: Optional[str] = None, message: Optional[str] = None) -> None:
        if self._manager is not None:
            updated = self._manager.fail_task(self.id, error=error, message=message)
            if updated:
                self._copy_from(updated)
            return
        self.status = "failed"
        self.ended_at = dt.datetime.utcnow()
        if error is not None:
            self.error = str(error)
        if message is not None:
            self.message = message
        elif error is not None:
            self.message = f"Ошибка: {error}"

    def to_dict(self) -> dict[str, Any]:
        now = self.ended_at or dt.datetime.utcnow()
        duration = (now - self.started_at).total_seconds()
        pct = round(self.progress * 100, 1) if self.progress is not None else None
        return {
            "id": self.id,
            "name": self.name,
            "title": self.title,
            "message": self.message,
            "progress": self.progress,
            "percentage": pct,
            "show_id": self.show_id,
            "total_items": self.total_items,
            "current_item": self.current_item,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": round(max(0.1, duration), 1),
            "error": self.error,
        }


class TaskManager:
    def __init__(
        self,
        history_limit: int = 30,
        *,
        session_factory: Optional[Callable] = None,
        worker_poll_interval: float = 0.5,
    ) -> None:
        if session_factory is None:
            from app.database import SessionLocal

            session_factory = SessionLocal
        self._session_factory = session_factory
        self._history_limit = max(1, history_limit)
        self._lock = threading.RLock()
        self._storage_ready = False
        self._worker_poll_interval = max(0.05, worker_poll_interval)
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    def _ensure_storage(self) -> None:
        if self._storage_ready:
            return
        with self._lock:
            if self._storage_ready:
                return
            bind = (
                self._session_factory.kw.get("bind")
                if hasattr(self._session_factory, "kw")
                else None
            )
            if bind is None:
                session = self._session_factory()
                try:
                    bind = session.get_bind()
                finally:
                    session.close()
            BackgroundTask.__table__.create(bind=bind, checkfirst=True)
            self._storage_ready = True

    @staticmethod
    def _now() -> dt.datetime:
        return dt.datetime.utcnow()

    def _to_task(self, row: BackgroundTask) -> Task:
        return Task.from_row(row, manager=self)

    def get_task(self, task_id: str) -> Optional[Task]:
        self._ensure_storage()
        with self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            return self._to_task(row) if row else None

    def is_active(self, task_id: str) -> bool:
        self._ensure_storage()
        with self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            return bool(row and row.status in ACTIVE_STATUSES)

    def start_task(
        self,
        name: str,
        title: str,
        message: str = "",
        progress: Optional[float] = None,
        show_id: Optional[int] = None,
        total_items: Optional[int] = None,
        current_item: Optional[int] = None,
    ) -> Task:
        self._ensure_storage()
        now = self._now()
        row = BackgroundTask(
            id=str(uuid.uuid4()),
            name=name,
            title=title,
            message=message,
            progress=max(0.0, min(1.0, float(progress)))
            if progress is not None
            else None,
            show_id=show_id,
            total_items=total_items,
            current_item=current_item,
            status="running",
            mode="inline",
            resumable=False,
            attempts=1,
            max_attempts=1,
            started_at=now,
            heartbeat_at=now,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        with self._lock, self._session_factory() as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            task = self._to_task(row)
        logger.info("Запущена задача [%s] %s: %s", task.id, task.title, task.message)
        return task

    def update_task(
        self,
        task_id: str,
        message: Optional[str] = None,
        progress: Optional[float] = None,
        current_item: Optional[int] = None,
        total_items: Optional[int] = None,
        show_id: Optional[int] = None,
        **kwargs: Any,
    ) -> Optional[Task]:
        self._ensure_storage()
        with self._lock, self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            if not row or row.status not in ACTIVE_STATUSES:
                return self._to_task(row) if row else None
            if message is not None:
                row.message = message
            if progress is not None:
                row.progress = max(0.0, min(1.0, float(progress)))
            if current_item is not None:
                row.current_item = current_item
            if total_items is not None:
                row.total_items = total_items
            if show_id is not None:
                row.show_id = show_id
            row.heartbeat_at = self._now()
            row.updated_at = self._now()
            db.commit()
            db.refresh(row)
            return self._to_task(row)

    def finish_task(
        self, task_id: str, message: Optional[str] = None, **kwargs: Any
    ) -> Optional[Task]:
        if kwargs.get("status") == "failed":
            return self.fail_task(task_id, error=kwargs.get("error"), message=message)
        self._ensure_storage()
        with self._lock, self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            if not row:
                return None
            if row.status in ACTIVE_STATUSES:
                row.status = "completed"
                row.ended_at = self._now()
                row.updated_at = self._now()
                row.progress = 1.0
                row.active_key = None
                row.worker_id = None
                if message is not None:
                    row.message = message
                if "result" in kwargs:
                    row.result = kwargs["result"]
                db.commit()
                db.refresh(row)
                logger.info(
                    "Завершена задача [%s] %s: %s", row.id, row.title, row.message
                )
            return self._to_task(row)

    def fail_task(
        self,
        task_id: str,
        error: Optional[str] = None,
        message: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Task]:
        self._ensure_storage()
        with self._lock, self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            if not row:
                return None
            if row.status in ACTIVE_STATUSES:
                err = error or kwargs.get("error")
                row.status = "failed"
                row.ended_at = self._now()
                row.updated_at = self._now()
                row.error = str(err) if err is not None else None
                row.message = (
                    message
                    or kwargs.get("message")
                    or (f"Ошибка: {err}" if err is not None else row.message)
                )
                row.active_key = None
                row.worker_id = None
                db.commit()
                db.refresh(row)
                logger.warning(
                    "Ошибка в задаче [%s] %s: %s", row.id, row.title, row.message
                )
            return self._to_task(row)

    @asynccontextmanager
    async def track(
        self,
        name: str,
        title: str,
        message: str = "",
        progress: Optional[float] = None,
        show_id: Optional[int] = None,
        total_items: Optional[int] = None,
        current_item: Optional[int] = None,
    ):
        task = self.start_task(
            name, title, message, progress, show_id, total_items, current_item
        )
        try:
            yield task
            if self.is_active(task.id):
                self.finish_task(task.id)
        except Exception as exc:
            if self.is_active(task.id):
                self.fail_task(task.id, error=str(exc))
            raise

    @contextmanager
    def track_sync(
        self,
        name: str,
        title: str,
        message: str = "",
        progress: Optional[float] = None,
        show_id: Optional[int] = None,
        total_items: Optional[int] = None,
        current_item: Optional[int] = None,
    ):
        task = self.start_task(
            name, title, message, progress, show_id, total_items, current_item
        )
        try:
            yield task
            if self.is_active(task.id):
                self.finish_task(task.id)
        except Exception as exc:
            if self.is_active(task.id):
                self.fail_task(task.id, error=str(exc))
            raise

    def get_status(self) -> dict[str, Any]:
        self._ensure_storage()
        with self._session_factory() as db:
            running_rows = (
                db.query(BackgroundTask)
                .filter(BackgroundTask.status == "running")
                .order_by(
                    BackgroundTask.started_at.desc(), BackgroundTask.created_at.desc()
                )
                .all()
            )
            queued_rows = (
                db.query(BackgroundTask)
                .filter(BackgroundTask.status == "queued")
                .order_by(BackgroundTask.created_at.asc())
                .all()
            )
            recent_rows = (
                db.query(BackgroundTask)
                .filter(BackgroundTask.status.in_(TERMINAL_STATUSES))
                .order_by(
                    BackgroundTask.ended_at.desc(), BackgroundTask.updated_at.desc()
                )
                .limit(min(15, self._history_limit))
                .all()
            )
            running = [self._to_task(row).to_dict() for row in running_rows]
            queued = [self._to_task(row).to_dict() for row in queued_rows]
            return {
                "running": running,
                "recent": [self._to_task(row).to_dict() for row in recent_rows],
                "running_count": len(running),
                "queued": queued,
                "queued_count": len(queued),
            }

    def clear_history(self) -> None:
        self._ensure_storage()
        with self._lock, self._session_factory() as db:
            db.query(BackgroundTask).filter(
                BackgroundTask.status.in_(TERMINAL_STATUSES)
            ).delete(synchronize_session=False)
            db.commit()

    def enqueue(
        self,
        name: str,
        title: str,
        payload: Optional[dict] = None,
        *,
        message: str = "",
        show_id: Optional[int] = None,
        idempotency_key: Optional[str] = None,
        active_key: Optional[str] = None,
        max_attempts: int = 3,
        available_at: Optional[dt.datetime] = None,
        resumable: bool = True,
    ) -> Task:
        self._ensure_storage()
        now = self._now()
        with self._lock, self._session_factory() as db:
            if idempotency_key:
                existing = (
                    db.query(BackgroundTask)
                    .filter(BackgroundTask.idempotency_key == idempotency_key)
                    .first()
                )
                if existing:
                    return self._to_task(existing)
            if active_key:
                existing = (
                    db.query(BackgroundTask)
                    .filter(BackgroundTask.active_key == active_key)
                    .first()
                )
                if existing:
                    return self._to_task(existing)
            row = BackgroundTask(
                id=str(uuid.uuid4()),
                name=name,
                title=title,
                message=message,
                status="queued",
                mode="command",
                payload=payload or {},
                show_id=show_id,
                resumable=resumable,
                attempts=0,
                max_attempts=max(1, int(max_attempts)),
                idempotency_key=idempotency_key,
                concurrency_key=active_key,
                active_key=active_key,
                available_at=available_at or now,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            try:
                db.commit()
                db.refresh(row)
                return self._to_task(row)
            except IntegrityError:
                db.rollback()
                query = db.query(BackgroundTask)
                existing = None
                if idempotency_key:
                    existing = query.filter(
                        BackgroundTask.idempotency_key == idempotency_key
                    ).first()
                if existing is None and active_key:
                    existing = query.filter(
                        BackgroundTask.active_key == active_key
                    ).first()
                if existing:
                    return self._to_task(existing)
                raise

    def claim_next(self) -> Optional[Task]:
        self._ensure_storage()
        now = self._now()
        with self._session_factory() as db:
            candidate = (
                db.query(BackgroundTask.id)
                .filter(
                    BackgroundTask.status == "queued",
                    BackgroundTask.available_at <= now,
                )
                .order_by(
                    BackgroundTask.available_at.asc(), BackgroundTask.created_at.asc()
                )
                .first()
            )
            if not candidate:
                return None
            updated = (
                db.query(BackgroundTask)
                .filter(
                    BackgroundTask.id == candidate[0], BackgroundTask.status == "queued"
                )
                .update(
                    {
                        BackgroundTask.status: "running",
                        BackgroundTask.worker_id: self._worker_id,
                        BackgroundTask.claimed_at: now,
                        BackgroundTask.heartbeat_at: now,
                        BackgroundTask.started_at: now,
                        BackgroundTask.updated_at: now,
                        BackgroundTask.attempts: BackgroundTask.attempts + 1,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            if updated != 1:
                return None
            row = db.get(BackgroundTask, candidate[0])
            return self._to_task(row) if row else None

    def heartbeat_task(self, task_id: str) -> bool:
        self._ensure_storage()
        with self._session_factory() as db:
            updated = (
                db.query(BackgroundTask)
                .filter(
                    BackgroundTask.id == task_id,
                    BackgroundTask.status == "running",
                    BackgroundTask.worker_id == self._worker_id,
                )
                .update(
                    {
                        BackgroundTask.heartbeat_at: self._now(),
                        BackgroundTask.updated_at: self._now(),
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            return updated == 1

    def _retry_claimed(
        self, task_id: str, error: str, delay_seconds: float = 0
    ) -> Optional[Task]:
        with self._lock, self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            if not row or row.status != "running":
                return self._to_task(row) if row else None
            if row.resumable and row.attempts < row.max_attempts:
                row.status = "queued"
                row.available_at = self._now() + dt.timedelta(
                    seconds=max(0, delay_seconds)
                )
                row.worker_id = None
                row.claimed_at = None
                row.heartbeat_at = None
                row.error = error
                row.updated_at = self._now()
                db.commit()
                db.refresh(row)
                return self._to_task(row)
        return self.fail_task(task_id, error=error)

    def cancel_task(
        self, task_id: str, message: str = "Отменено пользователем"
    ) -> Optional[Task]:
        self._ensure_storage()
        with self._lock, self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            if not row:
                return None
            if row.status in ACTIVE_STATUSES:
                row.status = "cancelled"
                row.message = message
                row.ended_at = self._now()
                row.updated_at = self._now()
                row.active_key = None
                row.worker_id = None
                db.commit()
                db.refresh(row)
            return self._to_task(row)

    def retry_task(self, task_id: str) -> Optional[Task]:
        self._ensure_storage()
        with self._lock, self._session_factory() as db:
            row = db.get(BackgroundTask, task_id)
            if not row or row.mode != "command" or row.status not in TERMINAL_STATUSES:
                return self._to_task(row) if row else None
            if row.concurrency_key:
                conflict = (
                    db.query(BackgroundTask)
                    .filter(
                        BackgroundTask.active_key == row.concurrency_key,
                        BackgroundTask.id != row.id,
                    )
                    .first()
                )
                if conflict:
                    return self._to_task(conflict)
            row.status = "queued"
            row.active_key = row.concurrency_key
            row.attempts = 0
            row.error = None
            row.ended_at = None
            row.available_at = self._now()
            row.updated_at = self._now()
            db.commit()
            db.refresh(row)
            return self._to_task(row)

    def recover_startup(self) -> dict[str, int]:
        self._ensure_storage()
        now = self._now()
        recovered = 0
        failed = 0
        with self._lock, self._session_factory() as db:
            rows = (
                db.query(BackgroundTask)
                .filter(BackgroundTask.status == "running")
                .all()
            )
            for row in rows:
                if (
                    row.mode == "command"
                    and row.resumable
                    and row.attempts < row.max_attempts
                ):
                    row.status = "queued"
                    row.available_at = now
                    row.worker_id = None
                    row.claimed_at = None
                    row.heartbeat_at = None
                    row.error = (
                        "Выполнение прервано перезапуском Aliasarr; "
                        "задача поставлена в очередь повторно"
                    )
                    recovered += 1
                else:
                    row.status = "failed"
                    row.error = "Выполнение прервано перезапуском Aliasarr"
                    row.message = "Прервано перезапуском Aliasarr"
                    row.ended_at = now
                    row.active_key = None
                    row.worker_id = None
                    failed += 1
                row.updated_at = now
            db.commit()
        return {"requeued": recovered, "failed": failed}

    async def run_once(self) -> Optional[Task]:
        task = self.claim_next()
        if task is None:
            return None
        from app.services.task_handlers import get_task_handler

        handler = get_task_handler(task.name)
        if handler is None:
            self.fail_task(
                task.id, error=f"Не зарегистрирован обработчик задачи: {task.name}"
            )
            return self.get_task(task.id)
        try:
            result = handler(task, task.payload or {})
            if pyinspect.isawaitable(result):
                result = await result
            if self.is_active(task.id):
                self.finish_task(
                    task.id, result=result if isinstance(result, dict) else None
                )
        except asyncio.CancelledError:
            self._retry_claimed(
                task.id, "Выполнение остановлено при завершении Aliasarr"
            )
            raise
        except Exception as exc:
            delay = min(300.0, float(2 ** max(0, task.attempts - 1)))
            self._retry_claimed(task.id, str(exc), delay_seconds=delay)
        return self.get_task(task.id)

    async def _worker_loop(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            task = await self.run_once()
            if task is None:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._worker_poll_interval
                    )
                except asyncio.TimeoutError:
                    pass

    async def start_worker(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._stop_event = asyncio.Event()
        self._worker_task = asyncio.create_task(
            self._worker_loop(), name="aliasarr-task-worker"
        )

    async def shutdown(self, timeout: float = 10.0) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        worker = self._worker_task
        if worker is None:
            return
        try:
            await asyncio.wait_for(worker, timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        finally:
            self._worker_task = None


task_manager = TaskManager()
