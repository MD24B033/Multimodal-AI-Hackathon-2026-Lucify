from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.auth import require_student
from app.db.models import Course, Profile, Student

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

ACCENTS = ("iris", "cyan", "mint", "amber", "rose")


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    accent: str = "iris"


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    accent: str | None = None


def serialize(profile: Profile, course_count: int = 0) -> dict:
    return {
        "id": str(profile.id),
        "name": profile.name,
        "description": profile.description,
        "accent": profile.accent,
        "is_default": profile.is_default,
        "course_count": course_count,
        "created_at": profile.created_at.isoformat(),
    }


def ensure_default_profile(session: Session, student: Student) -> Profile:
    profile = session.scalar(
        select(Profile).where(Profile.student_id == student.id).order_by(Profile.created_at)
    )
    if profile is not None:
        return profile

    profile = Profile(
        student_id=student.id,
        name="My studies",
        description="Default workspace",
        accent="iris",
        is_default=True,
    )
    session.add(profile)
    session.commit()

    orphans = session.scalars(select(Course).where(Course.profile_id.is_(None))).all()
    if orphans:
        for course in orphans:
            course.profile_id = profile.id
        session.commit()
    return profile


def owned_profile(session: Session, student: Student, profile_id: uuid.UUID) -> Profile:
    profile = session.get(Profile, profile_id)
    if profile is None or profile.student_id != student.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return profile


@router.get("")
def list_profiles(
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    ensure_default_profile(session, student)

    counts = dict(
        session.execute(
            select(Course.profile_id, func.count(Course.id)).group_by(Course.profile_id)
        ).all()
    )
    profiles = session.scalars(
        select(Profile).where(Profile.student_id == student.id).order_by(Profile.created_at)
    ).all()
    return [serialize(profile, counts.get(profile.id, 0)) for profile in profiles]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_profile(
    payload: ProfileCreate,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    name = payload.name.strip()
    existing = session.scalar(
        select(Profile).where(Profile.student_id == student.id, Profile.name == name)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"You already have a profile called {name!r}")

    profile = Profile(
        student_id=student.id,
        name=name,
        description=(payload.description or "").strip() or None,
        accent=payload.accent if payload.accent in ACCENTS else "iris",
    )
    session.add(profile)
    session.commit()
    return serialize(profile)


@router.patch("/{profile_id}")
def update_profile(
    profile_id: uuid.UUID,
    payload: ProfileUpdate,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    profile = owned_profile(session, student, profile_id)
    data = payload.model_dump(exclude_unset=True)

    if "name" in data and data["name"]:
        profile.name = data["name"].strip()
    if "description" in data:
        profile.description = (data["description"] or "").strip() or None
    if "accent" in data and data["accent"] in ACCENTS:
        profile.accent = data["accent"]

    session.commit()
    count = session.scalar(select(func.count(Course.id)).where(Course.profile_id == profile.id))
    return serialize(profile, count or 0)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    profile_id: uuid.UUID,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    profile = owned_profile(session, student, profile_id)

    remaining = session.scalar(
        select(func.count(Profile.id)).where(Profile.student_id == student.id)
    )
    if (remaining or 0) <= 1:
        raise HTTPException(status_code=409, detail="You need at least one profile")

    course_count = session.scalar(
        select(func.count(Course.id)).where(Course.profile_id == profile.id)
    )
    if course_count:
        raise HTTPException(
            status_code=409,
            detail=f"This profile still holds {course_count} course(s). Delete or move them first.",
        )

    session.delete(profile)
    session.commit()
