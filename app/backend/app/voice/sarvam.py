from __future__ import annotations

import base64
import logging
import re
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sarvam.ai"
TTS_CHAR_LIMIT = 480
STT_SECONDS_LIMIT = 30

LANGUAGES = [
    ("en-IN", "English"),
    ("hi-IN", "हिंदी"),
    ("bn-IN", "বাংলা"),
    ("gu-IN", "ગુજરાતી"),
    ("kn-IN", "ಕನ್ನಡ"),
    ("ml-IN", "മലയാളം"),
    ("mr-IN", "मराठी"),
    ("od-IN", "ଓଡ଼ିଆ"),
    ("pa-IN", "ਪੰਜਾਬੀ"),
    ("ta-IN", "தமிழ்"),
    ("te-IN", "తెలుగు"),
]

DEFAULT_SPEAKER = "priya"

SPEAKERS = [
    "priya", "shubh", "aditya", "ritu", "neha", "rahul", "pooja", "rohan",
    "simran", "kavya", "amit", "dev", "ishita", "shreya", "ratan", "varun",
    "manan", "sumit", "roopa", "kabir", "aayan", "ashutosh", "advait", "anand",
    "tanya", "tarun", "sunny", "mani", "gokul", "vijay", "shruti", "suhani",
    "mohit", "kavitha", "rehan", "soham", "rupali",
]


def resolve_speaker(name: str | None) -> str:
    """Speakers are model-specific and the v2 names were retired. Anything stored or
    requested that bulbul:v3 does not know falls back rather than failing the call."""
    candidate = (name or "").strip().lower()
    return candidate if candidate in SPEAKERS else DEFAULT_SPEAKER

_MARKUP = re.compile(r"\[\d+\]|[*_`#>\[\]]")


class SarvamError(RuntimeError):
    pass


def strip_for_speech(text: str) -> str:
    cleaned = _MARKUP.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _split(text: str, limit: int = TTS_CHAR_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(current) + len(sentence) + 1 > limit and current:
            chunks.append(current.strip())
            current = ""
        current += sentence + " "
    if current.strip():
        chunks.append(current.strip())
    return chunks


class SarvamClient:
    """Thin wrapper over Sarvam's speech endpoints. The key only ever buys a voice and
    an ear; every decision about what to say stays in this application."""

    def __init__(self, api_key: str, timeout: float = 90.0):
        if not api_key:
            raise SarvamError("A Sarvam API key is required")
        self.api_key = api_key
        self._client = httpx.Client(
            timeout=timeout, headers={"API-SUBSCRIPTION-KEY": api_key}
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SarvamClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def verify(self) -> bool:
        self.speak("Ready.", language_code="en-IN")
        return True

    def speak(
        self,
        text: str,
        *,
        language_code: str = "en-IN",
        speaker: str = DEFAULT_SPEAKER,
        model: str = "bulbul:v3",
        pace: float = 1.0,
        sample_rate: int = 16000,
    ) -> bytes:
        spoken = strip_for_speech(text)
        if not spoken:
            raise SarvamError("Nothing to speak")

        pieces = _split(spoken)
        common = {
            "target_language_code": language_code,
            "model": model,
            "speaker": resolve_speaker(speaker),
            "pace": pace,
            "speech_sample_rate": sample_rate,
            "enable_preprocessing": True,
        }

        if len(pieces) > 1:
            try:
                return _join_wav(self._synthesise({**common, "inputs": pieces}))
            except SarvamError:
                logger.info("Batched synthesis refused, falling back to one call per sentence group")

        chunks: list[bytes] = []
        for piece in pieces:
            chunks.extend(self._synthesise({**common, "inputs": [piece]}))
        return _join_wav(chunks)

    def _synthesise(self, payload: dict[str, Any]) -> list[bytes]:
        response = self._client.post(f"{BASE_URL}/text-to-speech", json=payload)
        if response.status_code != 200:
            raise SarvamError(
                f"Sarvam text-to-speech failed ({response.status_code}): {response.text[:200]}"
            )

        audios = response.json().get("audios") or []
        if not audios:
            raise SarvamError("Sarvam returned no audio")
        return [base64.b64decode(item) for item in audios]

    def transcribe(
        self,
        audio_path: Path,
        *,
        language_code: str = "unknown",
        model: str = "saaras:v3",
    ) -> str:
        with audio_path.open("rb") as handle:
            files = {"file": (audio_path.name, handle, "audio/wav")}
            data = {"model": model, "language_code": language_code}
            response = self._client.post(
                f"{BASE_URL}/speech-to-text", files=files, data=data
            )

        if response.status_code != 200:
            raise SarvamError(f"Sarvam speech-to-text failed ({response.status_code}): {response.text[:200]}")

        body = response.json()
        return (body.get("transcript") or body.get("text") or "").strip()


def _join_wav(chunks: list[bytes]) -> bytes:
    if len(chunks) == 1:
        return chunks[0]

    import io
    import wave

    buffer = io.BytesIO()
    try:
        with wave.open(buffer, "wb") as output:
            params_set = False
            for chunk in chunks:
                with wave.open(io.BytesIO(chunk), "rb") as segment:
                    if not params_set:
                        output.setparams(segment.getparams())
                        params_set = True
                    output.writeframes(segment.readframes(segment.getnframes()))
        return buffer.getvalue()
    except Exception:
        logger.warning("Could not concatenate Sarvam audio, returning first chunk", exc_info=True)
        return chunks[0]
