from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.auth import require_student
from app.config import settings
from app.db.models import Student, VoiceCredential
from app.voice.sarvam import (
    DEFAULT_SPEAKER,
    LANGUAGES,
    SPEAKERS,
    SarvamClient,
    SarvamError,
    resolve_speaker,
)

router = APIRouter(prefix="/api/voice", tags=["voice"])


class CredentialRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=300)
    language_code: str = "en-IN"
    speaker: str = DEFAULT_SPEAKER


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    language_code: str | None = None
    speaker: str | None = None


def _credential(session: Session, student: Student) -> VoiceCredential:
    credential = session.scalar(
        select(VoiceCredential).where(VoiceCredential.student_id == student.id)
    )
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="Add your Sarvam API key to use voice.",
        )
    return credential


@router.get("/status")
def voice_status(session: Session = DbSession, student: Student = Depends(require_student)):
    credential = session.scalar(
        select(VoiceCredential).where(VoiceCredential.student_id == student.id)
    )
    return {
        "configured": credential is not None,
        "hint": credential.hint if credential else None,
        "language_code": credential.language_code if credential else "en-IN",
        "speaker": resolve_speaker(credential.speaker) if credential else DEFAULT_SPEAKER,
        "languages": [{"code": code, "label": label} for code, label in LANGUAGES],
        "speakers": SPEAKERS,
    }


@router.post("/credential")
def save_credential(
    payload: CredentialRequest,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    key = payload.api_key.strip()

    try:
        with SarvamClient(key) as client:
            client.speak(
                "Voice is ready.",
                language_code=payload.language_code,
                speaker=resolve_speaker(payload.speaker),
            )
    except SarvamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    credential = session.scalar(
        select(VoiceCredential).where(VoiceCredential.student_id == student.id)
    )
    if credential is None:
        credential = VoiceCredential(student_id=student.id)
        session.add(credential)

    credential.secret = key
    credential.hint = f"…{key[-4:]}"
    credential.language_code = payload.language_code
    credential.speaker = resolve_speaker(payload.speaker)
    credential.verified_at = datetime.now(timezone.utc)
    session.commit()

    return {"configured": True, "hint": credential.hint, "verified": True}


@router.delete("/credential", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(session: Session = DbSession, student: Student = Depends(require_student)):
    credential = session.scalar(
        select(VoiceCredential).where(VoiceCredential.student_id == student.id)
    )
    if credential is not None:
        session.delete(credential)
        session.commit()


@router.post("/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language_code: str = Form(default="unknown"),
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    credential = _credential(session, student)

    suffix = (file.filename or "clip.wav").split(".")[-1]
    target = settings.audio_dir / f"voice_{uuid.uuid4()}.{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file.file.read())

    try:
        with SarvamClient(credential.secret) as client:
            text = client.transcribe(target, language_code=language_code)
    except SarvamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        target.unlink(missing_ok=True)

    if not text:
        raise HTTPException(status_code=422, detail="Could not make out any speech in that clip.")
    return {"text": text}


@router.post("/speak")
def speak(
    payload: SpeakRequest,
    session: Session = DbSession,
    student: Student = Depends(require_student),
):
    credential = _credential(session, student)

    try:
        with SarvamClient(credential.secret) as client:
            audio = client.speak(
                payload.text,
                language_code=payload.language_code or credential.language_code,
                speaker=payload.speaker or credential.speaker,
            )
    except SarvamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(content=audio, media_type="audio/wav")
