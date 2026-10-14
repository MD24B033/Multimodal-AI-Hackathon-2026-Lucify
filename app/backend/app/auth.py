from __future__ import annotations

import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.config import settings
from app.db.models import Student

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccessIdentity:
    key: str
    name: str

    @property
    def masked_key(self) -> str:
        if len(self.key) <= 8:
            return "*" * len(self.key)
        return f"{self.key[:4]}{'*' * (len(self.key) - 8)}{self.key[-4:]}"


def parse_access_keys(raw: str) -> dict[str, AccessIdentity]:
    identities: dict[str, AccessIdentity] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        key, separator, name = entry.partition(":")
        key = key.strip()
        if not key:
            continue
        identities[key] = AccessIdentity(key=key, name=(name.strip() if separator else "") or key)
    return identities


_IDENTITIES: dict[str, AccessIdentity] = parse_access_keys(settings.access_key_spec)


def auth_enabled() -> bool:
    return bool(_IDENTITIES)


def identities() -> list[AccessIdentity]:
    return list(_IDENTITIES.values())


def resolve_key(key: str | None) -> AccessIdentity | None:
    if not key:
        return None
    for candidate, identity in _IDENTITIES.items():
        if hmac.compare_digest(candidate, key):
            return identity
    return None


def ensure_students(session: Session) -> int:
    created = 0
    for identity in _IDENTITIES.values():
        existing = session.scalar(
            select(Student).where(Student.name == identity.name, Student.is_simulated.is_(False))
        )
        if existing is None:
            session.add(
                Student(
                    name=identity.name,
                    onboarded_at=datetime.now(timezone.utc),
                    meta={"provisioned": True},
                )
            )
            created += 1
    if created:
        session.commit()
    return created


def student_for(session: Session, identity: AccessIdentity) -> Student:
    student = session.scalar(
        select(Student).where(Student.name == identity.name, Student.is_simulated.is_(False))
    )
    if student is None:
        student = Student(
            name=identity.name,
            onboarded_at=datetime.now(timezone.utc),
            meta={"provisioned": True},
        )
        session.add(student)
        session.commit()
    return student


def _extract_key(
    authorization: str | None,
    x_access_key: str | None,
    access_key: str | None,
) -> str | None:
    if x_access_key:
        return x_access_key.strip()
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            return token.strip()
    if access_key:
        return access_key.strip()
    return None


def current_identity(
    authorization: str | None = Header(default=None),
    x_access_key: str | None = Header(default=None, alias="X-Access-Key"),
    access_key: str | None = Query(default=None),
) -> AccessIdentity | None:
    if not auth_enabled():
        return None

    identity = resolve_key(_extract_key(authorization, x_access_key, access_key))
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid access key is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return identity


def current_student(
    identity: AccessIdentity | None = Depends(current_identity),
    session: Session = DbSession,
) -> Student | None:
    if identity is None:
        return None
    return student_for(session, identity)


def require_student(
    student: Student | None = Depends(current_student),
    session: Session = DbSession,
) -> Student:
    if student is not None:
        return student

    fallback = session.scalar(
        select(Student).where(Student.is_simulated.is_(False)).order_by(Student.created_at)
    )
    if fallback is None:
        fallback = Student(name="Local learner", onboarded_at=datetime.now(timezone.utc))
        session.add(fallback)
        session.commit()
    return fallback


def assert_owns_student(student: Student | None, student_id: uuid.UUID) -> None:
    if student is None:
        return
    if student.id != student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="That learner belongs to a different access key.",
        )
