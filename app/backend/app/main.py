from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    assessments,
    auth as auth_routes,
    chat,
    courses,
    ingestion as ingestion_routes,
    learner,
    media,
    memory,
    notes,
    profiles,
    tasks as task_routes,
    voice,
    voice_ws,
)
from app.config import settings
from app.auth import auth_enabled, current_identity, ensure_students
from app.db.database import ensure_extensions
from app.realtime import (
    begin_shutdown,
    get_broker,
    install_shutdown_signals,
    resume_after_shutdown,
    shutting_down,
)
from app.ingestion.jobs import queued_in_database, recover_queued_jobs, worker
from app.tasks import queue_runner
import app.generation_handlers  # noqa: F401  (registers task handlers)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _warm_embedder() -> None:
    from app.retrieval.embedder import get_embedder

    try:
        get_embedder().embed_query("warmup")
        logger.info("Embedding model warm")
    except Exception:
        logger.warning("Could not warm the embedding model", exc_info=True)


_RECOVERY_SECONDS = 90


def _requeue_loop() -> None:
    """Keeps looking for jobs no process is carrying.

    Startup recovery alone is not enough: a worker thread can die on its own while the
    process lives, and a second instance may have written the row.
    """
    import time

    while not shutting_down():
        time.sleep(_RECOVERY_SECONDS)
        if shutting_down():
            return
        try:
            recover_queued_jobs()
        except Exception:
            logger.warning("Could not sweep for orphaned ingestion", exc_info=True)


def _release_orphaned_work() -> None:
    """Queues live in this process, so anything still marked running belongs to a
    process that is gone — a restart or a deploy. Left alone it shows as "working"
    in the interface for ever."""
    from sqlalchemy import select

    from app.db.database import session_scope
    from app.db.models import GenerationTask, IngestionJob, JobStatus, Source, SourceStatus

    message = "Interrupted by a restart. Start it again."
    try:
        with session_scope() as session:
            tasks = session.scalars(
                select(GenerationTask).where(GenerationTask.status == JobStatus.running)
            ).all()
            for task in tasks:
                task.status = JobStatus.failed
                task.stage = "interrupted"
                task.error = message

            jobs = session.scalars(
                select(IngestionJob).where(IngestionJob.status == JobStatus.running)
            ).all()
            for job in jobs:
                job.status = JobStatus.failed
                job.stage = "interrupted"
                job.error = message
                source = session.get(Source, job.source_id)
                if source is not None:
                    source.status = SourceStatus.failed
                    source.error = message

            if tasks or jobs:
                session.commit()
                logger.warning(
                    "Released %d generation task(s) and %d ingestion job(s) left running by a previous process",
                    len(tasks),
                    len(jobs),
                )
    except Exception:
        logger.warning("Could not reconcile interrupted work", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    try:
        ensure_extensions()
    except Exception:
        logger.warning("Could not verify pgvector extension", exc_info=True)

    resume_after_shutdown()
    install_shutdown_signals()
    logger.info("Realtime transport: %s", get_broker().name)
    _release_orphaned_work()

    if auth_enabled():
        from app.db.database import session_scope

        with session_scope() as session:
            provisioned = ensure_students(session)
        logger.info("Access keys enabled; provisioned %d new learner(s)", provisioned)
    else:
        logger.warning("ACCESS_KEYS is empty — the API is open to anyone who can reach it")
    worker.start()
    queue_runner.start()

    # The work queue cannot outlive the process, so anything the database still calls
    # queued belongs to a process that is gone. On a hosted instance that happens for
    # ordinary reasons - a deploy, an idle sleep, a memory limit - and without this an
    # upload simply never starts.
    recover_queued_jobs()
    threading.Thread(target=_requeue_loop, name="ingestion-recovery", daemon=True).start()

    if settings.warm_embedder_on_start:
        threading.Thread(target=_warm_embedder, name="embedder-warmup", daemon=True).start()

    logger.info("Study companion API ready")
    yield
    begin_shutdown()
    worker.stop()
    queue_runner.stop()


app = FastAPI(
    title="Source-Grounded Study Companion",
    description="Multimodal knowledge base, grounded tutoring, adaptive assessment and learner modelling.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected = [Depends(current_identity)]

app.include_router(auth_routes.router)
app.include_router(profiles.router, dependencies=protected)
app.include_router(courses.router, dependencies=protected)
app.include_router(ingestion_routes.router, dependencies=protected)
app.include_router(chat.router, dependencies=protected)
app.include_router(assessments.router, dependencies=protected)
app.include_router(learner.router, dependencies=protected)
app.include_router(notes.router, dependencies=protected)
app.include_router(memory.router, dependencies=protected)
app.include_router(voice.router, dependencies=protected)
app.include_router(task_routes.router, dependencies=protected)
app.include_router(voice_ws.router)
app.include_router(media.router, dependencies=protected)


@app.get("/health", tags=["system"])
def health():
    from sqlalchemy import text

    from app.db.database import engine

    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    return {
        "status": "ok" if database_ok else "degraded",
        "database": database_ok,
        "llm_configured": bool(settings.groq_api_key),
        "ingestion_queue": worker.pending,
        # Rows waiting in the database, which is the number that revealed a hosted
        # instance sitting on fifteen uploads its worker had never seen.
        "ingestion_backlog": queued_in_database(),
        "generation_queue": queue_runner.pending,
        "realtime": get_broker().name,
        "auth_required": auth_enabled(),
    }


@app.get("/api/config", tags=["system"])
def runtime_config():
    return {
        "models": {
            "generation": settings.generation_model,
            "vision": settings.vision_model,
            "verifier": settings.verifier_model,
            "judge": settings.judge_model,
            "transcription": settings.transcription_model,
            "tts": settings.tts_model,
        },
        "embedding_model": settings.embedding_model,
        "embedding_dimensions": settings.embedding_dimensions,
        "retrieval": {
            "top_k": settings.retrieval_top_k,
            "candidates": settings.retrieval_candidates,
            "grounding_threshold": settings.grounding_threshold,
            "novelty_threshold": settings.novelty_threshold,
        },
        "rate_limit": {
            "tokens_per_minute": settings.tokens_per_minute,
            "requests_per_minute": settings.requests_per_minute,
        },
        "languages": ["en", "hi", "hinglish"],
    }
