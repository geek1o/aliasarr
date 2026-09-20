from __future__ import annotations

import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db import BackgroundTask
from app.services.task_handlers import clear_task_handlers, register_task_handler
from app.services.task_manager import TaskManager


class PersistentTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = f"{self.temp_dir.name}/tasks.db"
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        BackgroundTask.__table__.create(self.engine, checkfirst=True)
        self.manager = TaskManager(
            session_factory=self.sessions, worker_poll_interval=0.01
        )
        clear_task_handlers()

    def tearDown(self):
        clear_task_handlers()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_inline_task_contract_persists_across_manager_instances(self):
        task = self.manager.start_task(
            "manual_import", "Ручной импорт", "Подготовка", progress=0.0, show_id=7
        )
        task.update(message="Половина", progress=0.5, current_item=1, total_items=2)

        status = TaskManager(session_factory=self.sessions).get_status()
        self.assertEqual(status["running_count"], 1)
        self.assertEqual(status["running"][0]["id"], task.id)
        self.assertEqual(status["running"][0]["progress"], 0.5)
        self.assertEqual(status["running"][0]["percentage"], 50.0)

        task.complete("Готово")
        persisted = TaskManager(session_factory=self.sessions).get_task(task.id)
        self.assertEqual(persisted.status, "completed")
        self.assertEqual(persisted.message, "Готово")
        self.assertEqual(persisted.progress, 1.0)

    def test_direct_fail_inside_context_is_not_overwritten(self):
        with self.manager.track_sync("import_files", "Импорт") as task:
            task.fail("disk full")

        persisted = self.manager.get_task(task.id)
        self.assertEqual(persisted.status, "failed")
        self.assertEqual(persisted.error, "disk full")

    def test_finish_failed_compatibility_does_not_deadlock(self):
        task = self.manager.start_task("legacy", "Legacy")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self.manager.finish_task,
                task.id,
                "Не удалось",
                status="failed",
                error="boom",
            )
            result = future.result(timeout=2)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "boom")

    def test_enqueue_is_idempotent_and_active_key_deduplicates(self):
        first = self.manager.enqueue(
            "metadata_refresh",
            "Метаданные",
            {"force": True},
            idempotency_key="request-1",
            active_key="metadata_refresh",
        )
        same_request = self.manager.enqueue(
            "metadata_refresh", "Другое имя", {}, idempotency_key="request-1"
        )
        same_active = self.manager.enqueue(
            "metadata_refresh", "Ещё одно", {}, active_key="metadata_refresh"
        )
        self.assertEqual(first.id, same_request.id)
        self.assertEqual(first.id, same_active.id)
        self.assertEqual(self.manager.get_status()["queued_count"], 1)

    def test_claim_is_atomic_between_managers(self):
        queued = self.manager.enqueue("once", "Один раз")
        other = TaskManager(session_factory=self.sessions)
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(
                executor.map(
                    lambda manager: manager.claim_next(), (self.manager, other)
                )
            )
        claimed = [task for task in claims if task is not None]
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].id, queued.id)
        self.assertEqual(claimed[0].attempts, 1)

    def test_startup_recovery_requeues_resumable_and_fails_inline(self):
        inline = self.manager.start_task("inline", "Inline")
        command = self.manager.enqueue("resume", "Resume", max_attempts=3)
        claimed = self.manager.claim_next()
        self.assertEqual(claimed.id, command.id)

        recovered = TaskManager(session_factory=self.sessions).recover_startup()
        self.assertEqual(recovered, {"requeued": 1, "failed": 1})
        self.assertEqual(self.manager.get_task(command.id).status, "queued")
        self.assertEqual(self.manager.get_task(inline.id).status, "failed")

    def test_worker_executes_registered_handler_and_persists_result(self):
        calls = []

        @register_task_handler("echo")
        async def echo(task, payload):
            calls.append(task.id)
            task.update(message="Выполняется", progress=0.5)
            return {"value": payload["value"]}

        queued = self.manager.enqueue("echo", "Echo", {"value": 42})
        result = asyncio.run(self.manager.run_once())
        self.assertEqual(calls, [queued.id])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result, {"value": 42})

    def test_failed_handler_retries_then_reaches_terminal_status(self):
        @register_task_handler("fail")
        async def fail(_task, _payload):
            raise RuntimeError("temporary")

        queued = self.manager.enqueue("fail", "Fail", max_attempts=1)
        result = asyncio.run(self.manager.run_once())
        self.assertEqual(result.id, queued.id)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "temporary")

    def test_clear_history_preserves_active_tasks(self):
        running = self.manager.start_task("running", "Running")
        queued = self.manager.enqueue("queued", "Queued")
        completed = self.manager.start_task("done", "Done")
        completed.complete()

        self.manager.clear_history()
        self.assertIsNotNone(self.manager.get_task(running.id))
        self.assertIsNotNone(self.manager.get_task(queued.id))
        self.assertIsNone(self.manager.get_task(completed.id))


if __name__ == "__main__":
    unittest.main()
