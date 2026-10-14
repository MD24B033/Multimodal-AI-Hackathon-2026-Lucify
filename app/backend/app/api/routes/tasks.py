from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.auth import require_student
from app.db.models import Course, GenerationTask, JobStatus, Student
from app.realtime import sse_stream
from app.tasks import active_tasks, course_busy, queue_runner, serialize, task_channel

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class TaskRequest(BaseModel):
    course_id: uuid.UUID
    kind: str = Field(min_length=1, max_length=40)
    label: str = ""
    params: dict = Field(default_factory=dict)


@router.get("")
def list_tasks(
    course_id: uuid.UUID | None = None,
    include_done: bool = True,
    limit: int = 20,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    statement = select(GenerationTask).where(GenerationTask.student_id == student.id)
    if course_id is not None:
        statement = statement.where(GenerationTask.course_id == course_id)
    if not include_done:
        statement = statement.where(
            GenerationTask.status.in_([JobStatus.queued, JobStatus.running])
        )
    rows = session.scalars(
        statement.order_by(GenerationTask.created_at.desc()).limit(min(limit, 60))
    ).all()
    return [serialize(task) for task in rows]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def enqueue(
    payload: TaskRequest,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    if session.get(Course, payload.course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")

    try:
        task = queue_runner.submit(
            session,
            student_id=student.id,
            course_id=payload.course_id,
            kind=payload.kind,
            label=payload.label or payload.kind,
            params=payload.params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return serialize(task)


@router.get("/busy")
def busy(
    course_id: uuid.UUID,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    return {
        "busy": course_busy(session, course_id),
        "active": [serialize(task) for task in active_tasks(session, student.id)],
        "queued": queue_runner.pending,
    }


@router.get("/{task_id}")
def get_task(
    task_id: uuid.UUID,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    task = session.get(GenerationTask, task_id)
    if task is None or task.student_id != student.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return serialize(task)


@router.post("/{task_id}/acknowledge")
def acknowledge(
    task_id: uuid.UUID,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    task = session.get(GenerationTask, task_id)
    if task is None or task.student_id != student.id:
        raise HTTPException(status_code=404, detail="Task not found")
    task.acknowledged = True
    session.commit()
    return serialize(task)


@router.get("/stream/events")
async def stream(request: Request, student: Student = Depends(require_student)):
    return StreamingResponse(
        sse_stream(task_channel(student.id), request, include_latest=False),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
