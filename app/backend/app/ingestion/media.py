from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.db.models import Modality
from app.ingestion.chunking import window_transcript
from app.ingestion.types import RawUnit, format_timestamp
from app.llm.groq_client import GroqError, get_client

logger = logging.getLogger(__name__)

AUDIO_CHUNK_SECONDS = 600
KEYFRAME_INSTRUCTION = """This is a frame captured from a lecture video.
If it shows a slide, whiteboard, diagram, or code, transcribe every visible line of text and describe any diagram in at most 90 words.
If it shows only a speaker, an empty background, or a transition, reply with exactly: NO_CONTENT"""


@lru_cache
def ffmpeg_executable() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


@lru_cache
def ffmpeg_bin_dir() -> str:
    """yt-dlp looks for a binary literally named ffmpeg, but imageio-ffmpeg ships a
    versioned filename. Expose a correctly named copy in a stable directory."""
    import shutil

    source = Path(ffmpeg_executable())
    target_dir = settings.storage_dir / "bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / ("ffmpeg.exe" if source.suffix == ".exe" else "ffmpeg")

    if not target.exists() or target.stat().st_size != source.stat().st_size:
        shutil.copy2(source, target)
        target.chmod(0o755)

    return str(target_dir)


def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def probe_duration(path: Path) -> float:
    result = _run(
        [
            ffmpeg_executable(),
            "-i",
            str(path),
            "-hide_banner",
        ]
    )
    output = result.stderr
    marker = "Duration:"
    if marker not in output:
        return 0.0
    raw = output.split(marker, 1)[1].split(",", 1)[0].strip()
    try:
        hours, minutes, seconds = raw.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return 0.0


def download_media(url: str, destination: Path) -> tuple[Path, dict]:
    import yt_dlp

    destination.mkdir(parents=True, exist_ok=True)
    options = {
        "format": "best[height<=720][ext=mp4]/best[ext=mp4]/bestvideo[height<=720]+bestaudio/best",
        "outtmpl": str(destination / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": ffmpeg_bin_dir(),
        "retries": 3,
        "socket_timeout": 60,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        path = Path(downloader.prepare_filename(info))
    if not path.exists():
        candidates = sorted(destination.glob(f"{info['id']}.*"))
        if not candidates:
            raise RuntimeError(f"Download produced no file for {url}")
        path = candidates[0]
    metadata = {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url", url),
        "uploader": info.get("uploader"),
        "video_id": info.get("id"),
    }
    return path, metadata


def extract_audio(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            ffmpeg_executable(),
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "32k",
            str(destination),
        ]
    )
    if not destination.exists():
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-600:]}")
    return destination


def split_audio(path: Path, chunk_seconds: int = AUDIO_CHUNK_SECONDS) -> list[tuple[Path, float]]:
    duration = probe_duration(path)
    if duration <= chunk_seconds:
        return [(path, 0.0)]

    workspace = Path(tempfile.mkdtemp(prefix="audio_chunks_"))
    chunks: list[tuple[Path, float]] = []
    offset = 0.0
    index = 0
    while offset < duration:
        target = workspace / f"chunk_{index:03d}{path.suffix}"
        _run(
            [
                ffmpeg_executable(),
                "-y",
                "-ss",
                str(offset),
                "-t",
                str(chunk_seconds),
                "-i",
                str(path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "32k",
                str(target),
            ]
        )
        if target.exists() and target.stat().st_size > 2048:
            chunks.append((target, offset))
        offset += chunk_seconds
        index += 1
    return chunks


def transcribe_media(audio_path: Path, language: str | None = None, progress=None) -> list[dict]:
    client = get_client()
    chunks = split_audio(audio_path)
    segments: list[dict] = []

    for index, (chunk_path, offset) in enumerate(chunks):
        if progress is not None:
            progress(index, len(chunks), f"{format_timestamp(offset)} onwards")
        try:
            payload = client.transcribe(chunk_path, language=language)
        except GroqError:
            logger.warning("Transcription failed for chunk %s", chunk_path, exc_info=True)
            continue

        for segment in payload.get("segments", []) or []:
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                {
                    "start": float(segment.get("start", 0.0)) + offset,
                    "end": float(segment.get("end", 0.0)) + offset,
                    "text": text,
                }
            )

        if not payload.get("segments") and payload.get("text"):
            segments.append(
                {"start": offset, "end": offset + AUDIO_CHUNK_SECONDS, "text": payload["text"].strip()}
            )

    if chunks and chunks[0][0] != audio_path:
        shutil.rmtree(chunks[0][0].parent, ignore_errors=True)

    segments.sort(key=lambda item: item["start"])
    return segments


def extract_keyframes(video_path: Path, source_id: uuid.UUID, interval: float | None = None) -> list[tuple[Path, float]]:
    interval = interval or settings.keyframe_interval_seconds
    duration = probe_duration(video_path)
    if duration <= 0:
        return []

    output_dir = settings.figures_dir / str(source_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    frames: list[tuple[Path, float]] = []
    timestamp = interval / 2
    index = 0
    while timestamp < duration:
        target = output_dir / f"frame_{index:04d}.jpg"
        _run(
            [
                ffmpeg_executable(),
                "-y",
                "-ss",
                str(timestamp),
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                "scale=1024:-1",
                "-q:v",
                "4",
                str(target),
            ]
        )
        if target.exists() and target.stat().st_size > 1024:
            frames.append((target, timestamp))
        timestamp += interval
        index += 1
    return frames


def describe_keyframes(frames: list[tuple[Path, float]], progress=None) -> list[RawUnit]:
    from app.ingestion.figures import _encode_image, looks_like_prompt_echo

    client = get_client()
    units: list[RawUnit] = []
    previous_description = ""

    for index, (path, timestamp) in enumerate(frames):
        if progress is not None:
            progress(index, len(frames), f"frame at {format_timestamp(timestamp)}")

        data_url = _encode_image(path)
        if data_url is None:
            continue
        try:
            completion = client.describe_image(
                data_url, KEYFRAME_INSTRUCTION, max_tokens=settings.keyframe_max_tokens, task="keyframe"
            )
        except GroqError:
            logger.warning("Keyframe description failed at %.1fs", timestamp, exc_info=True)
            continue

        description = completion.text.strip()
        if not description or description.upper().startswith("NO_CONTENT"):
            path.unlink(missing_ok=True)
            continue
        if looks_like_prompt_echo(description, KEYFRAME_INSTRUCTION):
            logger.info("Discarding prompt echo at %.0fs", timestamp)
            path.unlink(missing_ok=True)
            continue
        if _near_duplicate(description, previous_description):
            path.unlink(missing_ok=True)
            continue
        previous_description = description

        units.append(
            RawUnit(
                text=description,
                modality=Modality.figure,
                start_time_s=timestamp,
                end_time_s=timestamp,
                image_path=str(path),
                figure_caption=f"Lecture frame at {format_timestamp(timestamp)}",
                raw_text=description,
            )
        )
    return units


def _near_duplicate(left: str, right: str, threshold: float = 0.85) -> bool:
    if not right:
        return False
    left_tokens = set(left.lower().split())
    right_tokens = set(right.lower().split())
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return overlap >= threshold


def extract_media(
    path: Path,
    source_id: uuid.UUID,
    *,
    with_keyframes: bool = True,
    language: str | None = None,
    progress=None,
) -> tuple[list[RawUnit], dict]:
    audio_path = settings.audio_dir / f"{source_id}.mp3"
    extract_audio(path, audio_path)
    duration = probe_duration(path)

    def transcription_progress(index: int, total: int, item: str | None = None) -> None:
        if progress:
            progress(
                "transcribing",
                0.25 + 0.4 * (index / max(1, total)),
                done=index,
                total=total,
                item=item,
            )

    segments = transcribe_media(audio_path, language=language, progress=transcription_progress)
    units = window_transcript(segments)

    keyframe_units: list[RawUnit] = []
    if with_keyframes and _has_video_stream(path):
        frames = extract_keyframes(path, source_id)

        def keyframe_progress(index: int, total: int, item: str | None = None) -> None:
            if progress:
                progress(
                    "reading slides",
                    0.7 + 0.25 * (index / max(1, total)),
                    done=index,
                    total=total,
                    item=item,
                )

        keyframe_units = describe_keyframes(frames, progress=keyframe_progress)

    all_units = units + keyframe_units
    all_units.sort(key=lambda unit: unit.start_time_s or 0.0)
    for index, unit in enumerate(all_units):
        unit.ordinal = index

    metadata = {
        "duration_seconds": duration,
        "segment_count": len(segments),
        "transcript_units": len(units),
        "keyframe_units": len(keyframe_units),
        "full_transcript_chars": sum(len(segment["text"]) for segment in segments),
    }
    return all_units, metadata


def _has_video_stream(path: Path) -> bool:
    result = _run([ffmpeg_executable(), "-i", str(path), "-hide_banner"])
    return "Video:" in result.stderr
