from __future__ import annotations

import hashlib
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ContentUnit,
    IngestionJob,
    JobStatus,
    Modality,
    Source,
    SourceKind,
    SourceStatus,
)
from app.ingestion.types import RawUnit
from app.realtime import (
    course_channel,
    ingestion_feed_channel,
    publish_progress,
    source_channel,
)
from app.retrieval.embedder import get_embedder

logger = logging.getLogger(__name__)

DOCUMENT_KINDS = {SourceKind.pdf, SourceKind.pptx, SourceKind.docx, SourceKind.html}
MEDIA_KINDS = {SourceKind.video, SourceKind.audio, SourceKind.youtube}


def detect_kind(filename: str) -> SourceKind:
    suffix = Path(filename).suffix.lower().lstrip(".")
    mapping = {
        "pdf": SourceKind.pdf,
        "pptx": SourceKind.pptx,
        "ppt": SourceKind.pptx,
        "docx": SourceKind.docx,
        "doc": SourceKind.docx,
        "html": SourceKind.html,
        "htm": SourceKind.html,
        "mp4": SourceKind.video,
        "mkv": SourceKind.video,
        "mov": SourceKind.video,
        "webm": SourceKind.video,
        "avi": SourceKind.video,
        "mp3": SourceKind.audio,
        "wav": SourceKind.audio,
        "m4a": SourceKind.audio,
        "aac": SourceKind.audio,
        "ogg": SourceKind.audio,
    }
    if suffix not in mapping:
        raise ValueError(f"Unsupported file type: .{suffix}")
    return mapping[suffix]


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class JobReporter:
    def __init__(self, session: Session, job: IngestionJob, source: Source):
        self.session = session
        self.job = job
        self.source = source
        self.started = time.monotonic()

    def update(
        self,
        stage: str,
        progress: float,
        terminal: bool = False,
        *,
        done: int | None = None,
        total: int | None = None,
        **detail,
    ) -> None:
        self.job.stage = stage
        self.job.progress = max(0.0, min(1.0, progress))

        merged = dict(self.job.detail or {})
        if done is not None:
            merged["done"] = done
        if total is not None:
            merged["total"] = total
        if done is None and total is None and not detail:
            merged.pop("done", None)
            merged.pop("total", None)
        # Whatever is being read right now belongs to this stage alone: a later stage
        # that names nothing must not keep showing the last page it happened to see.
        merged.pop("item", None)
        merged.update({key: value for key, value in detail.items() if value is not None})
        self.job.detail = merged

        self.session.commit()
        self._broadcast(stage, terminal)

    def _eta_seconds(self, elapsed: float, terminal: bool) -> int | None:
        """Projected from the share of the bar already covered. The stage weights are
        chosen to track real time rather than step count, so this stays honest once
        enough of the work has happened to extrapolate from."""
        progress = self.job.progress
        if terminal or progress < 0.05 or progress >= 0.999:
            return None
        return max(1, round(elapsed * (1 - progress) / progress))

    def _broadcast(self, stage: str, terminal: bool) -> None:
        elapsed = time.monotonic() - self.started
        payload = {
            "source_id": str(self.source.id),
            "course_id": str(self.source.course_id),
            "title": self.source.title,
            "kind": self.source.kind.value,
            "status": self.job.status.value,
            "stage": stage,
            "progress": round(self.job.progress, 4),
            "detail": self.job.detail or {},
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": self._eta_seconds(elapsed, terminal),
            "error": self.job.error,
            "terminal": terminal,
        }
        publish_progress(source_channel(self.source.id), payload)
        publish_progress(course_channel(self.source.course_id), payload)
        publish_progress(ingestion_feed_channel(), payload)


def persist_units(
    session: Session,
    source: Source,
    units: list[RawUnit],
) -> int:
    if not units:
        return 0

    embedder = get_embedder()
    source_key = str(source.id)
    seen_hashes: set[str] = set()
    prepared: list[tuple[RawUnit, str]] = []

    for unit in units:
        text = unit.text.strip()
        if len(text) < 12:
            continue
        digest = unit.fingerprint(source_key)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        prepared.append((unit, digest))

    if not prepared:
        return 0

    vectors = embedder.embed_documents([unit.text for unit, _ in prepared])

    for (unit, digest), vector in zip(prepared, vectors):
        session.add(
            ContentUnit(
                course_id=source.course_id,
                source_id=source.id,
                ordinal=unit.ordinal,
                modality=unit.modality,
                text=unit.text.strip(),
                raw_text=unit.raw_text,
                heading_path=unit.heading_path,
                page_no=unit.page_no,
                slide_no=unit.slide_no,
                start_time_s=unit.start_time_s,
                end_time_s=unit.end_time_s,
                bbox=unit.bbox,
                image_path=unit.image_path,
                figure_caption=unit.figure_caption,
                token_count=unit.token_count,
                content_hash=digest,
                embedding=vector,
            )
        )

    session.commit()
    return len(prepared)


def run_ingestion(session: Session, source_id: uuid.UUID) -> dict:
    from app.ingestion.documents import extract_document
    from app.ingestion.figures import describe_figures
    from app.ingestion.media import download_media, extract_media
    from app.ingestion.taxonomy import build_taxonomy, tag_units

    source = session.get(Source, source_id)
    if source is None:
        raise ValueError(f"Source {source_id} not found")

    job = session.scalar(select(IngestionJob).where(IngestionJob.source_id == source_id))
    if job is None:
        job = IngestionJob(source_id=source_id)
        session.add(job)
        session.commit()

    reporter = JobReporter(session, job, source)
    job.status = JobStatus.running
    job.error = None
    job.detail = {}
    source.status = SourceStatus.processing
    source.error = None
    reporter.update("starting", 0.02)

    try:
        session.query(ContentUnit).filter(ContentUnit.source_id == source_id).delete()
        session.commit()

        if source.kind is SourceKind.youtube:
            reporter.update("downloading", 0.05)
            media_dir = Path(source.storage_path) if source.storage_path else None
            if media_dir is None or not Path(media_dir).exists():
                from app.config import settings

                target_dir = settings.uploads_dir / str(source.id)
                path, metadata = download_media(source.external_url, target_dir)
                source.storage_path = str(path)
                source.title = source.title or metadata.get("title") or source.title
                source.meta = {**(source.meta or {}), **metadata}
                session.commit()

        path = Path(source.storage_path) if source.storage_path else None
        if path is None or not path.exists():
            raise FileNotFoundError(f"Stored file missing for source {source_id}")

        if source.kind in DOCUMENT_KINDS:
            reporter.update("parsing document", 0.1)

            def page_progress(index: int, total: int, item: str | None = None) -> None:
                reporter.update(
                    "reading pages",
                    0.12 + 0.6 * (index / max(1, total)),
                    done=index,
                    total=total,
                    pages=total,
                    item=item,
                )

            units, metadata = extract_document(path, source.kind, source.id, progress=page_progress)
            source.page_count = metadata.get("page_count")

            figure_count = sum(1 for unit in units if unit.modality is Modality.figure)
            if figure_count:
                reporter.update("reading figures", 0.4, done=0, total=figure_count, figures=figure_count)

                def figure_progress(index: int, total: int, item: str | None = None) -> None:
                    reporter.update(
                        "reading figures",
                        0.4 + 0.3 * (index / max(1, total)),
                        done=index,
                        total=total,
                        item=item,
                    )

                units = describe_figures(units, progress=figure_progress)
        else:
            def media_progress(stage: str, progress: float, **detail) -> None:
                reporter.update(stage, progress, **detail)

            reporter.update("extracting audio", 0.1)
            units, metadata = extract_media(path, source.id, progress=media_progress)
            source.duration_seconds = metadata.get("duration_seconds")

        source.meta = {**(source.meta or {}), **metadata}
        reporter.update("embedding", 0.8)
        stored = persist_units(session, source, units)

        if stored == 0:
            raise RuntimeError(
                "Extraction produced no usable content. This usually means the model provider was "
                "unreachable during ingestion, or the file holds no readable text. Check "
                "connectivity and re-ingest."
            )

        reporter.update("building topic map", 0.88)
        taxonomy_stats = build_taxonomy(session, source.course_id)

        reporter.update("tagging topics", 0.95)
        tag_stats = tag_units(session, source.course_id)

        source.status = SourceStatus.ready
        job.status = JobStatus.succeeded
        reporter.update(
            "complete",
            1.0,
            terminal=True,
            units=stored,
            taxonomy=taxonomy_stats,
            tagging=tag_stats,
            **metadata,
        )
        session.commit()
        return {"units": stored, "taxonomy": taxonomy_stats, "tagging": tag_stats}

    except Exception as exc:
        logger.exception("Ingestion failed for source %s", source_id)
        session.rollback()
        source = session.get(Source, source_id)
        job = session.scalar(select(IngestionJob).where(IngestionJob.source_id == source_id))
        if source is not None:
            source.status = SourceStatus.failed
            source.error = str(exc)[:2000]
        if job is not None:
            job.status = JobStatus.failed
            job.error = str(exc)[:2000]
            job.stage = "failed"
        session.commit()

        if source is not None:
            failure = {
                "source_id": str(source.id),
                "course_id": str(source.course_id),
                "title": source.title,
                "status": JobStatus.failed.value,
                "stage": "failed",
                "progress": 1.0,
                "detail": {},
                "error": str(exc)[:500],
                "terminal": True,
            }
            publish_progress(source_channel(source.id), failure)
            publish_progress(course_channel(source.course_id), failure)
        raise
