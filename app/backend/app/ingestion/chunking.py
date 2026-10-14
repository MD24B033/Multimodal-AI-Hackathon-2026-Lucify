from __future__ import annotations

import re

from app.config import settings
from app.db.models import Modality
from app.ingestion.types import RawUnit

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])|\n{2,}")


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.33))


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part and part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def pack_sentences(
    sentences: list[str],
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = estimate_tokens(sentence)
        if sentence_tokens > target_tokens * 1.6:
            if current:
                chunks.append(" ".join(current))
                current, current_tokens = [], 0
            words = sentence.split()
            stride = max(1, int(target_tokens / 1.33))
            for start in range(0, len(words), stride):
                chunks.append(" ".join(words[start : start + stride]))
            continue

        if current_tokens + sentence_tokens > target_tokens and current:
            chunks.append(" ".join(current))
            carried: list[str] = []
            carried_tokens = 0
            for previous in reversed(current):
                previous_tokens = estimate_tokens(previous)
                if carried_tokens + previous_tokens > overlap_tokens:
                    break
                carried.insert(0, previous)
                carried_tokens += previous_tokens
            current = carried
            current_tokens = carried_tokens

        current.append(sentence)
        current_tokens += sentence_tokens

    if current:
        chunks.append(" ".join(current))
    return [chunk for chunk in chunks if chunk.strip()]


def merge_text_blocks(blocks: list[RawUnit]) -> list[RawUnit]:
    if not blocks:
        return []

    target = settings.chunk_target_tokens
    overlap = settings.chunk_overlap_tokens
    merged: list[RawUnit] = []
    buffer: list[RawUnit] = []

    def flush() -> None:
        if not buffer:
            return
        combined = " ".join(block.text.strip() for block in buffer if block.text.strip())
        if not combined.strip():
            buffer.clear()
            return
        pieces = pack_sentences(split_sentences(combined), target, overlap)
        anchor = buffer[0]
        pages = [block.page_no for block in buffer if block.page_no is not None]
        for piece in pieces:
            merged.append(
                RawUnit(
                    text=piece,
                    modality=Modality.text,
                    heading_path=list(anchor.heading_path),
                    page_no=anchor.page_no if anchor.page_no is not None else (pages[0] if pages else None),
                    slide_no=anchor.slide_no,
                    bbox=anchor.bbox,
                )
            )
        buffer.clear()

    for block in blocks:
        same_section = bool(buffer) and buffer[-1].heading_path == block.heading_path
        same_location = bool(buffer) and buffer[-1].slide_no == block.slide_no
        if buffer and (not same_section or not same_location):
            flush()
        buffer.append(block)
        if sum(item.token_count for item in buffer) >= target * 2:
            flush()

    flush()
    return merged


def window_transcript(
    segments: list[dict],
    window_seconds: float | None = None,
) -> list[RawUnit]:
    window = window_seconds or settings.transcript_window_seconds
    units: list[RawUnit] = []
    buffer: list[dict] = []

    def flush() -> None:
        if not buffer:
            return
        text = " ".join(segment["text"].strip() for segment in buffer).strip()
        if text:
            units.append(
                RawUnit(
                    text=text,
                    modality=Modality.transcript,
                    start_time_s=float(buffer[0]["start"]),
                    end_time_s=float(buffer[-1]["end"]),
                )
            )
        buffer.clear()

    for segment in segments:
        if not segment.get("text", "").strip():
            continue
        if buffer and float(segment["end"]) - float(buffer[0]["start"]) > window:
            flush()
        buffer.append(segment)

    flush()
    return units
