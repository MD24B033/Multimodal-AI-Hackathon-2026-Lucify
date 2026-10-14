from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.db.models import Modality


@dataclass
class RawUnit:
    text: str
    modality: Modality
    ordinal: int = 0
    raw_text: str | None = None
    heading_path: list[str] = field(default_factory=list)
    page_no: int | None = None
    slide_no: int | None = None
    start_time_s: float | None = None
    end_time_s: float | None = None
    bbox: list[float] | None = None
    image_path: str | None = None
    figure_caption: str | None = None

    @property
    def token_count(self) -> int:
        return max(1, int(len(self.text.split()) * 1.33))

    def fingerprint(self, source_key: str) -> str:
        material = f"{source_key}|{self.modality.value}|{self.page_no}|{self.slide_no}|{self.start_time_s}|{self.text}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def locator_label(self) -> str:
        if self.slide_no is not None:
            return f"Slide {self.slide_no}"
        if self.start_time_s is not None:
            return f"{_format_timestamp(self.start_time_s)}"
        if self.page_no is not None:
            return f"Page {self.page_no}"
        return "Document"


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def format_timestamp(seconds: float) -> str:
    return _format_timestamp(seconds)
