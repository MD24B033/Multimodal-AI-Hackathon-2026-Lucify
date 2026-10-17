from __future__ import annotations

import logging
import queue
import threading
import uuid

from app.config import settings
from app.db.database import session_scope

logger = logging.getLogger(__name__)


class IngestionWorker:
    def __init__(self, workers: int = 1):
        self._queue: queue.Queue[uuid.UUID | None] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._worker_count = workers
        self._started = False
        self._lock = threading.Lock()
        # What this process is already carrying, so a sweep of the database does not
        # submit the same source twice.
        self._held: set[uuid.UUID] = set()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            for index in range(self._worker_count):
                thread = threading.Thread(target=self._loop, name=f"ingestion-{index}", daemon=True)
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

    def submit(self, source_id: uuid.UUID) -> None:
        self.start()
        with self._lock:
            if source_id in self._held:
                return
            self._held.add(source_id)
        self._queue.put(source_id)

    def holds(self, source_id: uuid.UUID) -> bool:
        with self._lock:
            return source_id in self._held

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    def _loop(self) -> None:
        from app.ingestion.pipeline import run_ingestion

        while True:
            source_id = self._queue.get()
            if source_id is None:
                self._queue.task_done()
                return
            try:
                with session_scope() as session:
                    run_ingestion(session, source_id)
            except Exception:
                logger.exception("Ingestion job failed for %s", source_id)
            finally:
                with self._lock:
                    self._held.discard(source_id)
                self._queue.task_done()


MAX_RESTARTS = 3


def recover_queued_jobs() -> int:
    """Re-submits jobs the database still calls queued but no process is carrying.

    Runs at startup and periodically, because the queue cannot outlive the process and
    a hosted container restarts for reasons that have nothing to do with the job: a
    deploy, an idle sleep, a memory limit. A job that keeps dying is given up on rather
    than restarted for ever, since the likeliest cause is a file this instance cannot
    hold in memory.
    """
    from sqlalchemy import select

    from app.db.models import IngestionJob, JobStatus, Source, SourceStatus

    recovered = 0
    with session_scope() as session:
        jobs = session.scalars(
            select(IngestionJob).where(IngestionJob.status == JobStatus.queued)
        ).all()
        for job in jobs:
            if worker.holds(job.source_id):
                continue

            detail = dict(job.detail or {})
            restarts = int(detail.get("restarts", 0))
            if restarts >= MAX_RESTARTS:
                job.status = JobStatus.failed
                job.stage = "failed"
                job.error = (
                    f"Gave up after {restarts} interrupted attempts. This usually means the "
                    "file is too large for the memory this instance has; try a smaller file "
                    "or split it."
                )
                source = session.get(Source, job.source_id)
                if source is not None:
                    source.status = SourceStatus.failed
                    source.error = job.error
                continue

            detail["restarts"] = restarts + 1
            job.detail = detail
            session.flush()
            worker.submit(job.source_id)
            recovered += 1

        if recovered:
            logger.info("Re-queued %d ingestion job(s) left behind by a restart", recovered)
    return recovered


def queued_in_database() -> int:
    """Rows waiting, as opposed to what this process happens to be holding."""
    from sqlalchemy import func, select

    from app.db.models import IngestionJob, JobStatus

    with session_scope() as session:
        return int(
            session.scalar(
                select(func.count(IngestionJob.id)).where(
                    IngestionJob.status == JobStatus.queued
                )
            )
            or 0
        )


worker = IngestionWorker(workers=settings.ingestion_workers)
