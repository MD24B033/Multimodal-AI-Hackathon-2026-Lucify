from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.auth import auth_enabled, resolve_key, student_for
from app.db.database import session_scope
from app.db.models import VoiceCredential

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

SARVAM_REALTIME_URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"

REALTIME_PARAMS = {
    "model": "saaras:v3-realtime",
    "language_code": "auto",
    "stream_type": "fast",
    "endpointing": "vad",
    "encoding": "linear16",
    "sample_rate": "16000",
    "mode": "transcribe",
    "return_timestamps": "false",
}


def _credential_for(access_key: str | None) -> tuple[str | None, str | None]:
    """Resolve the caller's stored Sarvam key. WebSockets cannot carry custom headers
    from the browser, so the access key arrives as a query parameter."""
    with session_scope() as session:
        if auth_enabled():
            identity = resolve_key(access_key)
            if identity is None:
                return None, "That access key was not recognised."
            student = student_for(session, identity)
            credential = session.scalar(
                select(VoiceCredential).where(VoiceCredential.student_id == student.id)
            )
        else:
            credential = session.scalar(select(VoiceCredential))

        if credential is None:
            return None, "Add your Sarvam API key before starting a spoken session."
        return credential.secret, None


@router.websocket("/api/voice/stream")
async def voice_stream(websocket: WebSocket):
    await websocket.accept()

    access_key = websocket.query_params.get("access_key")
    language = websocket.query_params.get("language_code") or "auto"

    secret, refusal = await asyncio.to_thread(_credential_for, access_key)
    if not secret:
        await websocket.send_json({"type": "error", "message": refusal})
        await websocket.close(code=4001)
        return

    import websockets

    params = {**REALTIME_PARAMS, "language_code": language}
    url = f"{SARVAM_REALTIME_URL}?{urlencode(params)}"

    try:
        upstream = await websockets.connect(
            url, additional_headers={"API-SUBSCRIPTION-KEY": secret}, max_size=None
        )
    except Exception as exc:
        logger.warning("Sarvam realtime connect failed: %s", exc)
        await websocket.send_json({"type": "error", "message": f"Sarvam refused the connection: {exc}"})
        await websocket.close(code=4002)
        return

    await websocket.send_json({"type": "connected"})

    async def browser_to_sarvam() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            kind = message.get("type")
            if kind == "audio" and isinstance(message.get("audio"), str):
                await upstream.send(
                    json.dumps({"event": "audio_input", "audio": message["audio"]})
                )
            elif kind == "finish":
                await upstream.send(json.dumps({"event": "speech_end"}))
            elif kind == "ping":
                await upstream.send(json.dumps({"event": "ping"}))

    async def sarvam_to_browser() -> None:
        async for raw in upstream:
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            await websocket.send_json({"type": "event", "data": payload})

    try:
        await asyncio.gather(browser_to_sarvam(), sarvam_to_browser())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Voice stream ended: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)[:200]})
        except Exception:
            pass
    finally:
        try:
            await upstream.close()
        except Exception:
            pass
