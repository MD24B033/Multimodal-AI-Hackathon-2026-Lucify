from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select

from app.config import settings
from app.db.database import session_scope
from app.db.models import Course, Source, SourceKind, SourceStatus, Student
from app.ingestion.pipeline import detect_kind, file_digest, run_ingestion

DEMO_DIR = BACKEND_ROOT / "demo_corpus"
COURSE_TITLE = "Deep Learning Foundations"
COURSE_DESCRIPTION = (
    "Neural networks and deep learning, built from a textbook, two lecture slide decks "
    "and a recorded lecture."
)


def ensure_course(session, title: str) -> Course:
    course = session.scalar(select(Course).where(Course.title == title))
    if course is None:
        course = Course(
            title=title,
            description=COURSE_DESCRIPTION,
            exam_date=date.today() + timedelta(days=21),
        )
        session.add(course)
        session.commit()
        print(f"Created course {title}")
    else:
        print(f"Using existing course {title}")
    return course


def ensure_students(session, names: list[str]) -> list[Student]:
    students = []
    for name in names:
        student = session.scalar(select(Student).where(Student.name == name))
        if student is None:
            student = Student(name=name)
            session.add(student)
            session.commit()
            print(f"Created learner {name}")
        students.append(student)
    return students


def register_file(session, course: Course, path: Path, title: str) -> Source | None:
    digest = file_digest(path)
    existing = session.scalar(
        select(Source).where(Source.course_id == course.id, Source.content_hash == digest)
    )
    if existing is not None:
        if existing.status is SourceStatus.ready:
            print(f"  already ingested: {title}")
            return None
        return existing

    source_id = uuid.uuid4()
    destination = settings.uploads_dir / str(source_id) / path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, destination)

    source = Source(
        id=source_id,
        course_id=course.id,
        kind=detect_kind(path.name),
        title=title,
        original_filename=path.name,
        storage_path=str(destination),
        content_hash=digest,
    )
    session.add(source)
    session.commit()
    return source


def register_video(session, course: Course, url: str, title: str) -> Source | None:
    existing = session.scalar(
        select(Source).where(Source.course_id == course.id, Source.external_url == url)
    )
    if existing is not None:
        if existing.status is SourceStatus.ready:
            print(f"  already ingested: {title}")
            return None
        return existing

    source = Source(
        course_id=course.id,
        kind=SourceKind.youtube,
        title=title,
        external_url=url,
    )
    session.add(source)
    session.commit()
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo course and ingest its material")
    parser.add_argument("--with-video", action="store_true", help="also ingest the lecture video")
    parser.add_argument("--only", nargs="*", help="limit to these manifest names")
    arguments = parser.parse_args()

    manifest_path = DEMO_DIR / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Run scripts/fetch_demo_corpus.py first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    with session_scope() as session:
        course = ensure_course(session, COURSE_TITLE)
        ensure_students(session, ["Nipun", "Priya"])

        pending: list[Source] = []
        for entry in manifest["files"]:
            if arguments.only and entry["name"] not in arguments.only:
                continue
            path = DEMO_DIR / entry["filename"]
            if not path.exists():
                print(f"  missing file, skipping: {entry['filename']}")
                continue
            print(f"\n{entry['title']}")
            source = register_file(session, course, path, entry["title"])
            if source is not None:
                pending.append(source)

        if arguments.with_video:
            video = manifest["video"]
            print(f"\n{video['title']}")
            source = register_video(session, course, video["url"], video["title"])
            if source is not None:
                pending.append(source)

        for source in pending:
            print(f"\nIngesting {source.title}")
            started = time.perf_counter()
            try:
                result = run_ingestion(session, source.id)
                elapsed = time.perf_counter() - started
                print(f"  done in {elapsed / 60:.1f} min: {result}")
            except Exception as exc:
                print(f"  FAILED: {exc}")

        print(f"\nCourse id: {course.id}")


if __name__ == "__main__":
    main()
