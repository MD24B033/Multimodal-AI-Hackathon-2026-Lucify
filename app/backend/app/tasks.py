from __future__ import annotations

import logging
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import session_scope
from app.db.models import GenerationTask, JobStatus
from app.realtime import publish_progress

logger = logging.getLogger(__name__)

TaskHandler = Callable[[Session, GenerationTask], dict[str, Any]]
_HANDLERS: dict[str, TaskHandler] = {}


def handler(kind: str):
    def register(function: TaskHandler) -> TaskHandler:
        _HANDLERS[kind] = function
        return function

    return register


def task_channel(student_id: uuid.UUID) -> str:
    return f"tasks:{student_id}"


def serialize(task: GenerationTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "kind": task.kind,
        "label": task.label,
        "status": task.status.value,
        "stage": task.stage,
        "progress": round(task.progress, 3),
        "course_id": str(task.course_id),
        "result": task.result or {},
        "error": task.error,
        "acknowledged": task.acknowledged,
        "created_at": task.created_at.isoformat(),
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def _broadcast(task: GenerationTask, terminal: bool = False) -> None:
    publish_progress(task_channel(task.student_id), {**serialize(task), "terminal": terminal})


class TaskQueue:
    """Generation runs here rather than inside a request, so navigating away or closing a
    tab never cancels work that is already under way."""

    def __init__(self, workers: int = 1):
        self._queue: queue.Queue[uuid.UUID | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._worker_count = workers
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            for index in range(self._worker_count):
                thread = threading.Thread(target=self._loop, name=f"generation-{index}", daemon=True)
                thread.start()
                self._threads.append(thread)
            self._started = True

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            for _ in self._threads:
                self._queue.put(None)
            self._started = False

    def submit(
        self,
        session: Session,
        *,
        student_id: uuid.UUID,
        course_id: uuid.UUID,
        kind: str,
        label: str,
        params: dict[str, Any],
    ) -> GenerationTask:
        if kind not in _HANDLERS:
            raise ValueError(f"No handler registered for {kind!r}")

        task = GenerationTask(
            student_id=student_id,
            course_id=course_id,
            kind=kind,
            label=label,
            params=params,
            stage="queued",
        )
        session.add(task)
        session.commit()

        self.start()
        self._queue.put(task.id)
        _broadcast(task)
        return task

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def _loop(self) -> None:
        while True:
            task_id = self._queue.get()
            if task_id is None:
                self._queue.task_done()
                return
            try:
                self._run(task_id)
            except Exception:
                logger.exception("Generation task %s crashed", task_id)
            finally:
                self._queue.task_done()

    def _run(self, task_id: uuid.UUID) -> None:
        with session_scope() as session:
            task = session.get(GenerationTask, task_id)
            if task is None:
                return

            task.status = JobStatus.running
            task.stage = "working"
            task.progress = 0.1
            task.started_at = datetime.now(timezone.utc)
            session.commit()
            _broadcast(task)

            try:
                result = _HANDLERS[task.kind](session, task)
                task.result = result or {}
                task.status = JobStatus.succeeded
                task.stage = "complete"
                task.progress = 1.0
            except Exception as exc:
                logger.exception("Generation task %s failed", task_id)
                session.rollback()
                task = session.get(GenerationTask, task_id)
                if task is None:
                    return
                task.status = JobStatus.failed
                task.stage = "failed"
                task.error = str(exc)[:1500]
            finally:
                if task is not None:
                    task.finished_at = datetime.now(timezone.utc)
                    session.commit()
                    _broadcast(task, terminal=True)


queue_runner = TaskQueue()


def active_tasks(session: Session, student_id: uuid.UUID) -> list[GenerationTask]:
    return list(
        session.scalars(
            select(GenerationTask)
            .where(
                GenerationTask.student_id == student_id,
                GenerationTask.status.in_([JobStatus.queued, JobStatus.running]),
            )
            .order_by(GenerationTask.created_at)
        ).all()
    )


def course_busy(session: Session, course_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(GenerationTask.id).where(
                GenerationTask.course_id == course_id,
                GenerationTask.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
        is not None
    )
