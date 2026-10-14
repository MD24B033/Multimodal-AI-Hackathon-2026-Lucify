from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.db.models import Modality, SourceKind
from app.ingestion.chunking import merge_text_blocks
from app.ingestion.types import RawUnit

logger = logging.getLogger(__name__)

HEADING_LABELS = {"section_header", "title", "page_header"}
SKIP_LABELS = {"page_footer", "footnote"}
SLIDE_FORMATS = {SourceKind.pptx}


@dataclass(frozen=True)
class PdfProfile:
    is_slides: bool
    needs_ocr: bool
    page_count: int
    chars_per_page: float = 0.0

    @property
    def has_no_text_layer(self) -> bool:
        return self.chars_per_page < 15.0


def inspect_pdf(path: Path) -> PdfProfile:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
    except Exception:
        logger.debug("Could not pre-inspect %s", path, exc_info=True)
        return PdfProfile(is_slides=False, needs_ocr=settings.enable_ocr, page_count=0)

    pages = reader.pages
    page_count = len(pages)
    if page_count == 0:
        return PdfProfile(is_slides=False, needs_ocr=settings.enable_ocr, page_count=0)

    sample = pages[: min(page_count, 12)]
    landscape = 0
    characters = 0

    for page in sample:
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        if height and width / height >= 1.25:
            landscape += 1
        try:
            characters += len(page.extract_text() or "")
        except Exception:
            continue

    density = characters / len(sample)
    return PdfProfile(
        is_slides=landscape / len(sample) >= 0.8,
        needs_ocr=settings.enable_ocr or density < settings.ocr_fallback_chars_per_page,
        page_count=page_count,
        chars_per_page=density,
    )


def render_pdf_pages(path: Path, source_id: uuid.UUID, scale: float = 2.0) -> list[tuple[Path, int]]:
    import pypdfium2

    output_dir = settings.figures_dir / str(source_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    rendered: list[tuple[Path, int]] = []
    document = pypdfium2.PdfDocument(str(path))
    try:
        for index in range(len(document)):
            page = document[index]
            image = page.render(scale=scale).to_pil()
            target = output_dir / f"page_{index + 1:04d}.jpg"
            image.convert("RGB").save(target, quality=85)
            rendered.append((target, index + 1))
    finally:
        document.close()
    return rendered


def _page_fingerprint(path: Path) -> list[int]:
    from PIL import Image

    with Image.open(path) as image:
        thumbnail = image.convert("L").resize((48, 32))
        return list(thumbnail.getdata())


def _fingerprint_distance(left: list[int], right: list[int]) -> float:
    if not left or len(left) != len(right):
        return 1.0
    total = sum(abs(a - b) for a, b in zip(left, right))
    return total / (len(left) * 255.0)


def collapse_progressive_builds(
    pages: list[tuple[Path, int]],
    threshold: float = 0.012,
) -> list[tuple[Path, int]]:
    if len(pages) < 2:
        return pages

    fingerprints = [_page_fingerprint(path) for path, _ in pages]
    kept: list[tuple[Path, int]] = []

    index = 0
    while index < len(pages):
        run_end = index
        while (
            run_end + 1 < len(pages)
            and _fingerprint_distance(fingerprints[run_end], fingerprints[run_end + 1]) < threshold
        ):
            run_end += 1

        for dropped_path, _ in pages[index:run_end]:
            dropped_path.unlink(missing_ok=True)
        kept.append(pages[run_end])
        index = run_end + 1

    return kept


def extract_page_images(
    path: Path,
    source_id: uuid.UUID,
    *,
    is_slides: bool,
    progress=None,
) -> tuple[list[RawUnit], dict]:
    from app.ingestion.figures import describe_page_image

    rendered = render_pdf_pages(path, source_id)
    total_rendered = len(rendered)
    pages = collapse_progressive_builds(rendered) if is_slides else rendered
    units: list[RawUnit] = []

    consecutive_failures = 0

    for index, (image_path, page_no) in enumerate(pages):
        if progress is not None:
            progress(index, len(pages), f"{'slide' if is_slides else 'page'} {page_no}")

        description = describe_page_image(image_path, page_no, is_slides)
        if not description:
            consecutive_failures += 1
            if consecutive_failures >= settings.max_consecutive_page_failures:
                raise RuntimeError(
                    f"Gave up after {consecutive_failures} consecutive pages could not be read "
                    f"(stopped at page {page_no} of {len(pages)}). The model provider is most "
                    f"likely unreachable. Re-ingest this source once connectivity is restored; "
                    f"pages already described are cached and will not be paid for twice."
                )
            image_path.unlink(missing_ok=True)
            continue

        consecutive_failures = 0

        units.append(
            RawUnit(
                text=description,
                raw_text=description,
                modality=Modality.figure,
                ordinal=index,
                page_no=None if is_slides else page_no,
                slide_no=page_no if is_slides else None,
                image_path=str(image_path),
                figure_caption=f"{'Slide' if is_slides else 'Page'} {page_no}",
            )
        )

    metadata = {
        "page_count": total_rendered,
        "pages_read": len(pages),
        "builds_collapsed": total_rendered - len(pages),
        "figure_count": len(units),
        "table_count": 0,
        "extraction": "vision",
    }
    return units, metadata


@lru_cache
def _converter(with_ocr: bool, with_tables: bool):
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_page_images = False
    pipeline_options.images_scale = settings.figure_image_scale
    pipeline_options.do_table_structure = with_tables
    pipeline_options.do_ocr = with_ocr
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=settings.docling_threads,
        device=AcceleratorDevice.AUTO,
    )

    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )


def _provenance(item) -> tuple[int | None, list[float] | None]:
    provenance = getattr(item, "prov", None)
    if not provenance:
        return None, None
    first = provenance[0]
    page_no = getattr(first, "page_no", None)
    bbox = getattr(first, "bbox", None)
    if bbox is not None:
        bbox = [float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)]
    return page_no, bbox


def _update_heading_stack(stack: list[tuple[int, str]], level: int, text: str) -> list[str]:
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, text))
    return [entry[1] for entry in stack]


def extract_document(
    path: Path,
    kind: SourceKind,
    source_id: uuid.UUID,
    progress=None,
) -> tuple[list[RawUnit], dict]:
    from docling_core.types.doc.document import PictureItem, TableItem

    profile = inspect_pdf(path) if kind is SourceKind.pdf else PdfProfile(False, settings.enable_ocr, 0)
    is_slides = kind in SLIDE_FORMATS or profile.is_slides

    if kind is SourceKind.pdf and profile.has_no_text_layer:
        logger.info("%s has no text layer, reading its pages with the vision model", path.name)
        return extract_page_images(path, source_id, is_slides=is_slides, progress=progress)

    document = _converter(profile.needs_ocr, not is_slides).convert(str(path)).document

    heading_stack: list[tuple[int, str]] = []
    text_blocks: list[RawUnit] = []
    standalone: list[RawUnit] = []

    figures_dir = settings.figures_dir / str(source_id)

    for item, level in document.iterate_items():
        label = str(getattr(item, "label", "") or "")
        page_no, bbox = _provenance(item)
        slide_no = page_no if is_slides else None
        page_for_doc = None if is_slides else page_no

        if isinstance(item, PictureItem):
            caption = item.caption_text(document) or ""
            image = None
            try:
                image = item.get_image(document)
            except Exception:
                logger.debug("Figure image extraction failed", exc_info=True)
            image_path = None
            if image is not None:
                figures_dir.mkdir(parents=True, exist_ok=True)
                image_path = figures_dir / f"fig_{len(standalone):04d}_p{page_no or 0}.png"
                image.save(image_path)
                image_path = str(image_path)
            standalone.append(
                RawUnit(
                    text=caption.strip() or "Figure",
                    modality=Modality.figure,
                    heading_path=[entry[1] for entry in heading_stack],
                    page_no=page_for_doc,
                    slide_no=slide_no,
                    bbox=bbox,
                    image_path=image_path,
                    figure_caption=caption.strip() or None,
                )
            )
            continue

        if isinstance(item, TableItem):
            try:
                markdown = item.export_to_markdown(document)
            except Exception:
                markdown = ""
            caption = item.caption_text(document) or ""
            body = "\n".join(part for part in (caption, markdown) if part.strip())
            if body.strip():
                standalone.append(
                    RawUnit(
                        text=body.strip(),
                        modality=Modality.table,
                        heading_path=[entry[1] for entry in heading_stack],
                        page_no=page_for_doc,
                        slide_no=slide_no,
                        bbox=bbox,
                        figure_caption=caption.strip() or None,
                    )
                )
            continue

        text = (getattr(item, "text", "") or "").strip()
        if not text or label in SKIP_LABELS:
            continue

        if label in HEADING_LABELS:
            heading_path = _update_heading_stack(heading_stack, level, text)
            text_blocks.append(
                RawUnit(
                    text=text,
                    modality=Modality.text,
                    heading_path=heading_path,
                    page_no=page_for_doc,
                    slide_no=slide_no,
                    bbox=bbox,
                )
            )
            continue

        if label == "formula":
            standalone.append(
                RawUnit(
                    text=text,
                    modality=Modality.equation,
                    heading_path=[entry[1] for entry in heading_stack],
                    page_no=page_for_doc,
                    slide_no=slide_no,
                    bbox=bbox,
                )
            )
            continue

        text_blocks.append(
            RawUnit(
                text=text,
                modality=Modality.text,
                heading_path=[entry[1] for entry in heading_stack],
                page_no=page_for_doc,
                slide_no=slide_no,
                bbox=bbox,
            )
        )

    units = merge_text_blocks(text_blocks) + standalone
    units.sort(key=lambda unit: (unit.slide_no or unit.page_no or 0, unit.modality.value))
    for index, unit in enumerate(units):
        unit.ordinal = index

    metadata = {
        "page_count": len(document.pages),
        "figure_count": sum(1 for unit in units if unit.modality is Modality.figure),
        "table_count": sum(1 for unit in units if unit.modality is Modality.table),
        "docling_name": getattr(document, "name", None),
    }
    return units, metadata
