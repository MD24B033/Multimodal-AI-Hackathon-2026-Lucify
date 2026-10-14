from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.auth import require_student
from app.db.models import LearnerMemory, MemoryKind, Student
from app.learner.memory import remember

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    kind: MemoryKind = MemoryKind.preference
    content: str = Field(min_length=1, max_length=500)
    course_id: uuid.UUID | None = None


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=500)
    kind: MemoryKind | None = None
    pinned: bool | None = None
    archived: bool | None = None


def serialize(memory: LearnerMemory) -> dict:
    return {
        "id": str(memory.id),
        "kind": memory.kind.value,
        "content": memory.content,
        "origin": memory.origin,
        "confidence": round(memory.confidence, 2),
        "pinned": memory.pinned,
        "archived": memory.archived,
        "course_id": str(memory.course_id) if memory.course_id else None,
        "evidence": memory.evidence or {},
        "updated_at": memory.updated_at.isoformat(),
    }


def owned(session: Session, student: Student, memory_id: uuid.UUID) -> LearnerMemory:
    memory = session.get(LearnerMemory, memory_id)
    if memory is None or memory.student_id != student.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return memory


@router.get("")
def list_memories(
    course_id: uuid.UUID | None = None,
    include_archived: bool = False,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    statement = select(LearnerMemory).where(LearnerMemory.student_id == student.id)
    if not include_archived:
        statement = statement.where(LearnerMemory.archived.is_(False))
    if course_id is not None:
        statement = statement.where(
            (LearnerMemory.course_id == course_id) | (LearnerMemory.course_id.is_(None))
        )
    rows = session.scalars(
        statement.order_by(
            LearnerMemory.pinned.desc(),
            LearnerMemory.confidence.desc(),
            LearnerMemory.updated_at.desc(),
        )
    ).all()
    return [serialize(memory) for memory in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_memory(
    payload: MemoryCreate,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    memory = remember(
        session,
        student.id,
        payload.kind,
        payload.content,
        course_id=payload.course_id,
        origin="manual",
        confidence=0.9,
    )
    if memory is None:
        raise HTTPException(status_code=400, detail="Could not store that memory")
    if memory.archived:
        memory.archived = False
    session.commit()
    return serialize(memory)


@router.patch("/{memory_id}")
def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryUpdate,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    memory = owned(session, student, memory_id)
    data = payload.model_dump(exclude_unset=True)

    if data.get("content"):
        memory.content = data["content"].strip()
        memory.origin = "manual"
        memory.confidence = 0.9
    if data.get("kind") is not None:
        memory.kind = data["kind"]
    if "pinned" in data and data["pinned"] is not None:
        memory.pinned = data["pinned"]
    if "archived" in data and data["archived"] is not None:
        memory.archived = data["archived"]

    session.commit()
    return serialize(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(
    memory_id: uuid.UUID,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    memory = owned(session, student, memory_id)
    session.delete(memory)
    session.commit()


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def clear_memories(
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    session.query(LearnerMemory).filter(LearnerMemory.student_id == student.id).delete()
    session.commit()
