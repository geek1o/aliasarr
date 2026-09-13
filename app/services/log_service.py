"""
Захват и сохранение логов приложения в базе данных для системного журнала и событий.

Подключается как специализированный logging.Handler к логгеру "aliasarr" и его подсистемам.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any, Tuple

import datetime as dt
import logging
import queue
import threading
import time

try:
    from app.database import SessionLocal
except ImportError:
    SessionLocal = None

_LEVEL_MAP = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}

_LOG_QUEUE: queue.Queue[Tuple[dt.datetime, str, str, str]] = queue.Queue(maxsize=10000)
_WORKER_STOP_EVENT = threading.Event()
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()


def _flush_batch(batch: List[Tuple[dt.datetime, str, str, str]]) -> None:
    if not batch or SessionLocal is None:
        return
    try:
        from app.models.db import LogEntry

        db = SessionLocal()
        try:
            entries = [
                LogEntry(
                    created_at=created_at,
                    level=level,
                    component=component,
                    message=message,
                )
                for created_at, level, component, message in batch
            ]
            db.add_all(entries)
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
    except Exception:
        pass


def _log_worker_loop() -> None:
    batch: List[Tuple[dt.datetime, str, str, str]] = []
    last_flush_time = time.time()

    while not _WORKER_STOP_EVENT.is_set():
        try:
            item = _LOG_QUEUE.get(timeout=0.5)
            batch.append(item)
            _LOG_QUEUE.task_done()
        except queue.Empty:
            pass

        now = time.time()
        if batch and (len(batch) >= 50 or (now - last_flush_time) >= 1.0):
            _flush_batch(batch)
            batch = []
            last_flush_time = now

    while not _LOG_QUEUE.empty():
        try:
            batch.append(_LOG_QUEUE.get_nowait())
            _LOG_QUEUE.task_done()
        except queue.Empty:
            break
    if batch:
        _flush_batch(batch)


def _ensure_worker_started() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_STOP_EVENT.clear()
            _WORKER_THREAD = threading.Thread(
                target=_log_worker_loop,
                name="aliasarr-log-flusher",
                daemon=True,
            )
            _WORKER_THREAD.start()


class DBLogHandler(logging.Handler):
    """
    Пишет логи в таблицу log_entries асинхронно через неблокирующую очередь.
    Никогда не блокирует вызывающий поток и не открывает транзакций синхронно в emit().
    """

    def __init__(self, level=logging.NOTSET):
        super().__init__(level)
        _ensure_worker_started()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = _LEVEL_MAP.get(record.levelno, "info")
            message = self.format(record) if self.formatter else record.getMessage()

            if "API-ключ (из " in message or "X-Api-Key:" in message:
                message = "Системный API-ключ инициализирован (секрет скрыт)"

            item = (
                dt.datetime.utcnow(),
                level,
                record.name,
                message[:4000],
            )

            try:
                _LOG_QUEUE.put_nowait(item)
            except queue.Full:
                try:
                    _LOG_QUEUE.get_nowait()
                    _LOG_QUEUE.task_done()
                except queue.Empty:
                    pass
                try:
                    _LOG_QUEUE.put_nowait(item)
                except queue.Full:
                    pass
        except Exception:
            pass

    def flush(self) -> None:
        flush_db_logs()

    def close(self) -> None:
        self.flush()
        super().close()


def flush_db_logs() -> None:
    """Сбрасывает все накопленные в очереди записи логов в базу данных немедленно."""
    items: List[Tuple[dt.datetime, str, str, str]] = []
    while not _LOG_QUEUE.empty():
        try:
            items.append(_LOG_QUEUE.get_nowait())
            _LOG_QUEUE.task_done()
        except queue.Empty:
            break
    if items:
        _flush_batch(items)


def stop_db_log_worker() -> None:
    """Останавливает фоновый поток логирования и сбрасывает остаток очереди."""
    global _WORKER_THREAD
    _WORKER_STOP_EVENT.set()
    flush_db_logs()
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            _WORKER_THREAD.join(timeout=2.0)
            _WORKER_THREAD = None


def install_db_log_handler() -> None:
    handler = DBLogHandler(level=logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in ("aliasarr",):
        lg = logging.getLogger(name)
        if not any(isinstance(h, DBLogHandler) for h in lg.handlers):
            lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)


def sanitize_legacy_log_entries(db) -> None:
    """Очищает устаревшие записи логов, в которых мог содержаться сырой API-ключ."""
    from app.models.db import LogEntry
    try:
        entries = db.query(LogEntry).filter(
            (LogEntry.message.like("%API-ключ (из %")) |
            (LogEntry.message.like("%X-Api-Key:%"))
        ).all()
        for e in entries:
            e.message = "Системный API-ключ инициализирован (секрет скрыт)"
        db.commit()
    except Exception:
        db.rollback()


def purge_old_logs(db, retention_days: int = 14) -> int:
    from app.models.db import LogEntry

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=retention_days)
    deleted = db.query(LogEntry).filter(LogEntry.created_at < cutoff).delete()
    db.commit()
    return deleted
