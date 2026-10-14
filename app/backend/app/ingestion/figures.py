from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from app.config import settings
from app.db.models import Modality
from app.ingestion.types import RawUnit
from app.llm.groq_client import GroqError, get_client

logger = logging.getLogger(__name__)

MAX_EDGE = 1100
MIN_EDGE = 48

FIGURE_INSTRUCTION = """You are building a searchable knowledge base from course material.
Describe this figure so a student can find and understand it from text search alone.

Report, in plain prose and at most 120 words:
- what kind of visual it is (diagram, plot, flowchart, photograph, screenshot, equation)
- every label, axis, legend entry, and piece of text visible in it
- the relationships or trend it conveys
- the concept it teaches

State only what is visible. Do not speculate about content outside the image.
If the image carries no instructional content (a logo, divider, or decoration), reply with exactly: DECORATIVE"""


SLIDE_PAGE_INSTRUCTION = """This is one slide from a lecture deck. It has no machine-readable text, so you are the only way its content enters the knowledge base.

Produce, as plain prose:
1. Every word of text on the slide, transcribed exactly, including titles, bullets, labels, axis names, legends and equations. Write equations in readable notation.
2. A description of any diagram, plot, architecture figure or illustration: what it shows, how its parts relate, and what trend or structure it conveys.
3. One sentence naming the concept the slide teaches.

Do not add facts that are not on the slide. If the slide is only a title card, section divider or logo, reply with exactly: NO_CONTENT"""

PAGE_INSTRUCTION = """This is one page of a course document that has no machine-readable text, so you are the only way its content enters the knowledge base.

Transcribe every word on the page exactly, then describe any figure, diagram, table or plot it contains and what it conveys. Write equations in readable notation.

Do not add anything that is not on the page. If the page is blank or only a cover or divider, reply with exactly: NO_CONTENT"""


def looks_like_prompt_echo(description: str, instruction: str) -> bool:
    """Vision models sometimes repeat the instruction instead of answering. Reject
    anything that substantially overlaps the prompt we sent."""
    body = description.strip().lower()
    if not body:
        return True

    opening = instruction.strip().lower()[:80]
    if opening and body.startswith(opening[:40]):
        return True

    instruction_lines = {
        line.strip().lower()
        for line in instruction.splitlines()
        if len(line.strip()) > 30
    }
    if not instruction_lines:
        return False

    matched = sum(1 for line in instruction_lines if line in body)
    return matched >= 2


def describe_page_image(path: Path, page_no: int, is_slides: bool) -> str | None:
    data_url = _encode_image(path)
    if data_url is None:
        return None

    instruction = SLIDE_PAGE_INSTRUCTION if is_slides else PAGE_INSTRUCTION
    try:
        completion = get_client().describe_image(
            data_url, instruction, max_tokens=settings.page_image_max_tokens, task="page_image"
        )
    except GroqError:
        logger.warning("Page description failed for %s page %s", path.name, page_no, exc_info=True)
        return None

    description = completion.text.strip()
    if not description or description.upper().startswith("NO_CONTENT"):
        return None
    if looks_like_prompt_echo(description, instruction):
        logger.info("Discarding prompt echo for %s page %s", path.name, page_no)
        return None
    return description


def _encode_image(path: Path) -> str | None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if min(image.size) < MIN_EDGE:
                return None
            if max(image.size) > MAX_EDGE:
                scale = MAX_EDGE / max(image.size)
                image = image.resize((int(image.width * scale), int(image.height * scale)))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=82)
    except Exception:
        logger.debug("Could not encode figure %s", path, exc_info=True)
        return None

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def describe_figures(units: list[RawUnit], progress=None) -> list[RawUnit]:
    client = get_client()
    figures = [unit for unit in units if unit.modality is Modality.figure and unit.image_path]
    kept: list[RawUnit] = []

    for index, unit in enumerate(figures):
        if progress is not None:
            where = unit.page_no or unit.slide_no
            place = f" on {'slide' if unit.slide_no else 'page'} {where}" if where else ""
            progress(index, len(figures), f"figure {index + 1}{place}")

        data_url = _encode_image(Path(unit.image_path))
        if data_url is None:
            continue

        try:
            completion = client.describe_image(data_url, FIGURE_INSTRUCTION, task="figure")
        except GroqError:
            logger.warning("Vision description failed for %s", unit.image_path, exc_info=True)
            continue

        description = completion.text.strip()
        if not description or description.upper().startswith("DECORATIVE"):
            continue
        if looks_like_prompt_echo(description, FIGURE_INSTRUCTION):
            continue

        caption = (unit.figure_caption or "").strip()
        unit.raw_text = description
        unit.text = f"{caption}\n{description}".strip() if caption else description
        kept.append(unit)

    removed = {id(unit) for unit in figures} - {id(unit) for unit in kept}
    return [unit for unit in units if id(unit) not in removed]
