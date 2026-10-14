from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.db.models import ChatMessage, ContentUnit, RevisionAsset, Source

router = APIRouter(prefix="/api/media", tags=["media"])

CHUNK_SIZE = 1024 * 512
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def _guess_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _ranged_response(path: Path, request: Request) -> Response:
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    media_type = _guess_type(path)

    if not range_header:
        return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})

    match = _RANGE.match(range_header)
    if match is None:
        raise HTTPException(status_code=416, detail="Malformed range header")

    start_raw, end_raw = match.groups()
    start = int(start_raw) if start_raw else 0
    end = int(end_raw) if end_raw else file_size - 1
    start = max(0, start)
    end = min(end, file_size - 1)

    if start > end:
        raise HTTPException(status_code=416, detail="Requested range not satisfiable")

    def iterator():
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = handle.read(min(CHUNK_SIZE, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    return StreamingResponse(
        iterator(),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        },
    )


def _resolve(path_value: str | None, label: str) -> Path:
    if not path_value:
        raise HTTPException(status_code=404, detail=f"{label} has no stored file")
    path = Path(path_value)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{label} file is missing from storage")
    return path


@router.get("/figure/{unit_id}")
def get_figure(unit_id: uuid.UUID, session: Session = DbSession):
    unit = session.get(ContentUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Content unit not found")
    path = _resolve(unit.image_path, "Figure")
    return FileResponse(path, media_type=_guess_type(path))


@router.get("/source/{source_id}")
def get_source_file(source_id: uuid.UUID, request: Request, session: Session = DbSession):
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    path = _resolve(source.storage_path, "Source")
    return _ranged_response(path, request)


@router.get("/audio/{message_id}")
def get_message_audio(message_id: uuid.UUID, request: Request, session: Session = DbSession):
    message = session.get(ChatMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    path = _resolve(message.audio_path, "Message audio")
    return _ranged_response(path, request)


@router.get("/brief/{asset_id}")
def get_brief_audio(asset_id: uuid.UUID, request: Request, session: Session = DbSession):
    asset = session.get(RevisionAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Revision asset not found")
    path = _resolve(asset.audio_path, "Brief audio")
    return _ranged_response(path, request)
