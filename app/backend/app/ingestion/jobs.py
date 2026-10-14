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
        self._queue.put(source_id)

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
                self._queue.task_done()


worker = IngestionWorker(workers=settings.ingestion_workers)
