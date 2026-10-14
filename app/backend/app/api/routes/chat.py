from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.serializers import serialize_message
from app.config import settings
from app.db.models import ChatMessage, ChatSession, Course, GroundingStatus, Student
from app.enhancements.tts import synthesize_to_file, transcribe_upload
from app.learner import memory as learner_memory
from app.learner import profile
from app.retrieval.context import build_context, maybe_summarise, remember_units, reset_context
from app.retrieval.grounding import answer_question
from app.retrieval.hybrid import search

router = APIRouter(prefix="/api/chat", tags=["chat"])

CONFUSION_MARKERS = (
    "i don't understand",
    "i do not understand",
    "confused",
    "still lost",
    "explain again",
    "simpler",
    "i don't get",
    "makes no sense",
    "samajh nahi",
)


class SessionCreate(BaseModel):
    course_id: uuid.UUID
    student_id: uuid.UUID
    title: str | None = None
    mode: str = "text"
    scoped_source_id: uuid.UUID | None = None


class AskRequest(BaseModel):
    message: str = Field(min_length=1)
    language: str = "en"
    topic_ids: list[uuid.UUID] | None = None
    source_ids: list[uuid.UUID] | None = None
    speak: bool = False


class SearchRequest(BaseModel):
    course_id: uuid.UUID
    query: str
    top_k: int = 8


def _looks_confused(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in CONFUSION_MARKERS)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, session: Session = DbSession):
    if session.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    if session.get(Student, payload.student_id) is None:
        raise HTTPException(status_code=404, detail="Student not found")

    chat = ChatSession(
        course_id=payload.course_id,
        student_id=payload.student_id,
        title=payload.title or "New session",
        mode=payload.mode,
        scoped_source_id=payload.scoped_source_id,
    )
    session.add(chat)
    session.commit()
    return {
        "id": str(chat.id),
        "course_id": str(chat.course_id),
        "student_id": str(chat.student_id),
        "title": chat.title,
        "created_at": chat.created_at.isoformat(),
        "messages": [],
    }


@router.get("/sessions")
def list_sessions(
    course_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    mode: str | None = None,
    session: Session = DbSession,
):
    statement = select(ChatSession).order_by(ChatSession.updated_at.desc())
    if course_id:
        statement = statement.where(ChatSession.course_id == course_id)
    if student_id:
        statement = statement.where(ChatSession.student_id == student_id)
    if mode:
        statement = statement.where(ChatSession.mode == mode)
    sessions = session.scalars(statement.limit(50)).all()
    counts = dict(
        session.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_([item.id for item in sessions]))
            .group_by(ChatMessage.session_id)
        ).all()
    )
    return [
        {
            "id": str(item.id),
            "course_id": str(item.course_id),
            "student_id": str(item.student_id),
            "title": item.title,
            "mode": item.mode,
            "scoped_source_id": str(item.scoped_source_id) if item.scoped_source_id else None,
            "message_count": counts.get(item.id, 0),
            "summary": item.summary,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        for item in sessions
    ]


@router.get("/sessions/{session_id}")
def get_session(session_id: uuid.UUID, session: Session = DbSession):
    chat = session.get(ChatSession, session_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    messages = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at)
    ).all()
    return {
        "id": str(chat.id),
        "course_id": str(chat.course_id),
        "student_id": str(chat.student_id),
        "title": chat.title,
        "messages": [serialize_message(message) for message in messages],
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: uuid.UUID, session: Session = DbSession):
    chat = session.get(ChatSession, session_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    session.delete(chat)
    session.commit()


@router.post("/sessions/{session_id}/ask")
def ask(session_id: uuid.UUID, payload: AskRequest, session: Session = DbSession):
    chat = session.get(ChatSession, session_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    started = time.perf_counter()
    scoped = payload.source_ids or (
        [chat.scoped_source_id] if chat.scoped_source_id else None
    )

    retrieval = search(
        session,
        chat.course_id,
        payload.message,
        topic_ids=payload.topic_ids,
        source_ids=scoped,
    )
    context = build_context(session, chat, retrieval)

    user_message = ChatMessage(
        session_id=session_id,
        role="user",
        content=payload.message,
        language=payload.language,
    )
    session.add(user_message)
    session.flush()

    result = answer_question(
        session,
        chat.course_id,
        payload.message,
        student_id=chat.student_id,
        history=context.history,
        topic_ids=payload.topic_ids,
        source_ids=scoped,
        language=payload.language,
        context_block=context.block,
        session_summary=context.summary,
    )

    assistant_message = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=result.answer,
        citations=result.citations,
        grounding_status=result.status,
        coverage=result.coverage,
        outside_knowledge=result.outside_knowledge,
        retrieved_unit_ids=[str(item.unit.id) for item in (result.retrieval.units if result.retrieval else [])],
        topic_ids=[str(topic_id) for topic_id in result.topic_ids],
        language=payload.language,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    session.add(assistant_message)
    session.flush()

    confused = _looks_confused(payload.message)
    if result.topic_ids and result.status is not GroundingStatus.refused:
        profile.record_chat_signal(
            session,
            chat.student_id,
            result.topic_ids,
            confusion=confused,
        )

    learner_memory.observe_message(
        session, chat.student_id, payload.message, course_id=chat.course_id
    )
    if confused:
        learner_memory.observe_confusion(
            session, chat.student_id, payload.message, result.topic_ids, chat.course_id
        )

    if payload.speak and result.answer:
        audio_path = synthesize_to_file(result.answer, f"message_{assistant_message.id}")
        if audio_path is not None:
            assistant_message.audio_path = str(audio_path)

    if chat.title == "New session":
        chat.title = payload.message[:80]

    remember_units(session, chat, context.all_units)
    maybe_summarise(session, chat)
    session.commit()

    return {
        "user_message": serialize_message(user_message),
        "message": serialize_message(assistant_message),
        "followups": result.followups,
        "unsupported_claims": result.unsupported_claims,
        "context": {
            "fresh_excerpts": len(context.fresh),
            "recalled_excerpts": len(context.recalled),
            "tokens_saved": context.tokens_saved,
        },
    }


@router.post("/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
):
    suffix = (file.filename or "audio.webm").split(".")[-1]
    target = settings.audio_dir / f"upload_{uuid.uuid4()}.{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file.file.read())

    try:
        text = transcribe_upload(target, language=language)
    finally:
        target.unlink(missing_ok=True)

    if not text:
        raise HTTPException(status_code=502, detail="Could not transcribe audio")
    return {"text": text}


@router.post("/search")
def search_material(payload: SearchRequest, session: Session = DbSession):
    result = search(session, payload.course_id, payload.query, top_k=payload.top_k)
    return {
        "query": payload.query,
        "best_score": round(result.best_score, 4),
        "results": result.citations(),
    }
