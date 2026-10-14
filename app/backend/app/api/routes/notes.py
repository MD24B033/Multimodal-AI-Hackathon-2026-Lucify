from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.db.models import Course, RevisionAsset, Student
from app.enhancements.notes import (
    NOTE_FORMATS,
    NotesGenerationFailed,
    export_markdown,
    generate_notes,
    list_notes,
)

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NotesRequest(BaseModel):
    course_id: uuid.UUID
    student_id: uuid.UUID
    note_format: str = Field(default="summary")
    topic_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None
    free_text: str | None = None
    source_ids: list[uuid.UUID] | None = None
    depth: str = "standard"
    language: str = "en"
    extra_instructions: str | None = None


@router.get("/formats")
def formats():
    return {
        "formats": [
            {
                "value": "summary",
                "label": "Structured summary",
                "description": "Headings, bullets, key definitions and a worked example.",
            },
            {
                "value": "cornell",
                "label": "Cornell notes",
                "description": "Cue column, detailed notes, and a summary strip for active recall.",
            },
            {
                "value": "cheatsheet",
                "label": "Cheat sheet",
                "description": "Dense one-pager of formulas, definitions and key facts.",
            },
            {
                "value": "flashcards",
                "label": "Flashcards",
                "description": "Question and answer pairs you can drill and schedule.",
            },
        ],
        "depths": ["brief", "standard", "deep"],
        "languages": ["en", "hi", "hinglish"],
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_notes(payload: NotesRequest, session: Session = DbSession):
    if payload.note_format not in NOTE_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown format: {payload.note_format}")
    if session.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    if session.get(Student, payload.student_id) is None:
        raise HTTPException(status_code=404, detail="Student not found")

    try:
        note = generate_notes(
            session,
            payload.course_id,
            payload.student_id,
            note_format=payload.note_format,
            topic_id=payload.topic_id,
            concept_id=payload.concept_id,
            free_text=payload.free_text,
            source_ids=payload.source_ids,
            depth=payload.depth,
            language=payload.language,
            extra_instructions=payload.extra_instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotesGenerationFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if note is None:
        raise HTTPException(
            status_code=422,
            detail="The course material does not cover that well enough to write notes from.",
        )
    return note


@router.get("")
def list_saved_notes(
    course_id: uuid.UUID,
    student_id: uuid.UUID,
    session: Session = DbSession,
):
    return list_notes(session, course_id, student_id)


@router.get("/{note_id}")
def get_note(note_id: uuid.UUID, session: Session = DbSession):
    asset = session.get(RevisionAsset, note_id)
    if asset is None or not asset.kind.startswith("notes_"):
        raise HTTPException(status_code=404, detail="Note not found")
    return {
        "id": str(asset.id),
        "title": asset.title,
        "format": asset.kind.removeprefix("notes_"),
        "created_at": asset.created_at.isoformat(),
        "payload": asset.payload,
    }


@router.get("/{note_id}/markdown", response_class=PlainTextResponse)
def download_markdown(note_id: uuid.UUID, session: Session = DbSession):
    asset = session.get(RevisionAsset, note_id)
    if asset is None or not asset.kind.startswith("notes_"):
        raise HTTPException(status_code=404, detail="Note not found")
    return PlainTextResponse(
        export_markdown(asset.payload or {}),
        headers={
            "Content-Disposition": f'attachment; filename="{asset.title[:60] or "notes"}.md"'
        },
    )


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: uuid.UUID, session: Session = DbSession):
    asset = session.get(RevisionAsset, note_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Note not found")
    session.delete(asset)
    session.commit()
