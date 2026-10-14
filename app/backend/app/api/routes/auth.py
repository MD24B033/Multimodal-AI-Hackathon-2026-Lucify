from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.api.serializers import serialize_student
from app.auth import (
    AccessIdentity,
    auth_enabled,
    current_identity,
    resolve_key,
    student_for,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SessionRequest(BaseModel):
    key: str = Field(min_length=1, max_length=200)


@router.get("/status")
def auth_status():
    return {"auth_required": auth_enabled()}


@router.post("/session")
def create_session(payload: SessionRequest, session: Session = DbSession):
    if not auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This instance is running without access keys.",
        )

    identity = resolve_key(payload.key.strip())
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That access key is not recognised.",
        )

    student = student_for(session, identity)
    return {"name": identity.name, "student": serialize_student(student)}


@router.get("/me")
def whoami(
    identity: AccessIdentity | None = Depends(current_identity),
    session: Session = DbSession,
):
    if identity is None:
        return {"auth_required": False, "name": None, "student": None}
    student = student_for(session, identity)
    return {"auth_required": True, "name": identity.name, "student": serialize_student(student)}
