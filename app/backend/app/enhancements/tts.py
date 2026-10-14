from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import settings
from app.llm.groq_client import GroqError, get_client

logger = logging.getLogger(__name__)

MAX_CHARS_PER_REQUEST = 1200
_MARKDOWN = re.compile(r"[*_`#>\[\]]|\(\s*\)|\[\d+\]")


def strip_for_speech(text: str) -> str:
    cleaned = re.sub(r"\[\d+\]", "", text)
    cleaned = _MARKDOWN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _split_for_tts(text: str) -> list[str]:
    if len(text) <= MAX_CHARS_PER_REQUEST:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 > MAX_CHARS_PER_REQUEST and current:
            chunks.append(current.strip())
            current = ""
        current += sentence + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


def synthesize_to_file(text: str, name: str, voice: str | None = None) -> Path | None:
    spoken = strip_for_speech(text)
    if not spoken:
        return None

    client = get_client()
    chunks = _split_for_tts(spoken)
    buffers: list[bytes] = []

    for chunk in chunks:
        try:
            buffers.append(client.synthesize_speech(chunk, voice=voice))
        except GroqError:
            logger.warning("Speech synthesis failed for chunk of %s", name, exc_info=True)
            return None

    if not buffers:
        return None

    target = settings.audio_dir / f"{name}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)

    if len(buffers) == 1:
        target.write_bytes(buffers[0])
        return target

    return _concatenate_wav(buffers, target)


def _concatenate_wav(buffers: list[bytes], target: Path) -> Path | None:
    import io
    import wave

    try:
        with wave.open(str(target), "wb") as output:
            params_set = False
            for buffer in buffers:
                with wave.open(io.BytesIO(buffer), "rb") as segment:
                    if not params_set:
                        output.setparams(segment.getparams())
                        params_set = True
                    output.writeframes(segment.readframes(segment.getnframes()))
        return target
    except Exception:
        logger.warning("Could not concatenate speech segments", exc_info=True)
        target.write_bytes(buffers[0])
        return target


def transcribe_upload(path: Path, language: str | None = None) -> str:
    try:
        payload = get_client().transcribe(path, language=language)
    except GroqError:
        logger.exception("Voice transcription failed")
        return ""
    return (payload.get("text") or "").strip()
