"""Queued ingestion must survive the process that queued it.

The work queue lives in memory. A hosted instance restarts for ordinary reasons — a
deploy, an idle sleep, a memory limit — and before this the database was left holding
jobs no worker had ever seen: fifteen uploads marked queued, three courses with no
units, and an upload bar that stopped and never moved again.
"""
import uuid

import pytest

from app.ingestion.jobs import IngestionWorker


@pytest.fixture
def worker():
    created = IngestionWorker(workers=1)
    # Never start real threads: this is about bookkeeping, not ingestion.
    created.start = lambda: None  # type: ignore[method-assign]
    return created


def test_a_submitted_source_is_held(worker):
    source = uuid.uuid4()
    assert worker.holds(source) is False
    worker.submit(source)
    assert worker.holds(source) is True
    assert worker.pending == 1


def test_the_same_source_is_not_queued_twice(worker):
    """A recovery sweep running beside a live upload must not double-ingest."""
    source = uuid.uuid4()
    worker.submit(source)
    worker.submit(source)
    assert worker.pending == 1


def test_different_sources_both_queue(worker):
    worker.submit(uuid.uuid4())
    worker.submit(uuid.uuid4())
    assert worker.pending == 2


def test_a_fresh_process_holds_nothing(worker):
    """The point of the bug: a restart leaves the row but not the queue."""
    source = uuid.uuid4()
    worker.submit(source)
    restarted = IngestionWorker(workers=1)
    assert restarted.holds(source) is False
    assert restarted.pending == 0


def test_finishing_releases_the_hold(worker):
    """Otherwise a source could never be re-ingested in the same process."""
    source = uuid.uuid4()
    worker.submit(source)
    # what _loop does in its finally block
    with worker._lock:
        worker._held.discard(source)
    assert worker.holds(source) is False


def test_the_restart_ceiling_is_small_enough_to_stop_a_crash_loop():
    """A file that kills the container would otherwise be retried for ever."""
    from app.ingestion.jobs import MAX_RESTARTS

    assert 1 <= MAX_RESTARTS <= 5
