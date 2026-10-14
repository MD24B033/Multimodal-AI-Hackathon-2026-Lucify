from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Course, Student


def db_session() -> Iterator[Session]:
    yield from get_db()


DbSession = Depends(db_session)


def get_course(course_id: uuid.UUID, session: Session = DbSession) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


def get_student(student_id: uuid.UUID, session: Session = DbSession) -> Student:
    student = session.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return student


def require(entity, name: str):
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{name} not found")
    return entity
