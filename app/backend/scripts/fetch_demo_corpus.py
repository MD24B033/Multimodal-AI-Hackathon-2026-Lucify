from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

DEMO_DIR = BACKEND_ROOT / "demo_corpus"


@dataclass
class CorpusItem:
    name: str
    filename: str
    url: str
    title: str
    licence: str
    attribution: str
    page_range: tuple[int, int] | None = None
    tags: list[str] = field(default_factory=list)


CORPUS = [
    CorpusItem(
        name="textbook",
        filename="nielsen_neural_networks_ch1_2.pdf",
        url="https://raw.githubusercontent.com/antonvladyka/neuralnetworksanddeeplearning.com.pdf/master/book.pdf",
        title="Neural Networks and Deep Learning (Nielsen) — Chapters 1-2",
        licence="CC BY-NC 3.0",
        attribution="Michael A. Nielsen, 'Neural Networks and Deep Learning', Determination Press, 2015. LaTeX build by Anton Vladyka.",
        page_range=(1, 64),
        tags=["textbook"],
    ),
    CorpusItem(
        name="slides_intro",
        filename="mit_6s191_L1_intro_to_deep_learning.pdf",
        url="https://introtodeeplearning.com/2022/slides/6S191_MIT_DeepLearning_L1.pdf",
        title="MIT 6.S191 Lecture 1 — Intro to Deep Learning",
        licence="MIT License",
        attribution="MIT 6.S191 Introduction to Deep Learning, introtodeeplearning.com",
        tags=["slides"],
    ),
    CorpusItem(
        name="slides_vision",
        filename="mit_6s191_L3_deep_computer_vision.pdf",
        url="https://introtodeeplearning.com/2022/slides/6S191_MIT_DeepLearning_L3.pdf",
        title="MIT 6.S191 Lecture 3 — Deep Computer Vision",
        licence="MIT License",
        attribution="MIT 6.S191 Introduction to Deep Learning, introtodeeplearning.com",
        tags=["slides"],
    ),
]

LECTURE_VIDEO = {
    "url": "https://www.youtube.com/watch?v=7sB052Pz0sQ",
    "title": "MIT 6.S191 (2022) Lecture 1 — Introduction to Deep Learning",
    "licence": "MIT License",
    "attribution": "MIT 6.S191 Introduction to Deep Learning, introtodeeplearning.com",
}


def download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 1024:
        print(f"  already present: {destination.name}")
        return destination

    print(f"  downloading {url}")
    with httpx.stream("GET", url, follow_redirects=True, timeout=180.0) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes(1 << 16):
                handle.write(chunk)
    print(f"  saved {destination.name} ({destination.stat().st_size / 1_000_000:.1f} MB)")
    return destination


def trim_pages(source: Path, destination: Path, first: int, last: int) -> Path:
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(source))
    writer = PdfWriter()
    last = min(last, len(reader.pages))
    for index in range(first - 1, last):
        writer.add_page(reader.pages[index])
    with destination.open("wb") as handle:
        writer.write(handle)
    print(f"  trimmed to pages {first}-{last} -> {destination.name}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the public demo corpus")
    parser.add_argument("--output", type=Path, default=DEMO_DIR)
    arguments = parser.parse_args()

    output_dir: Path = arguments.output
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"files": [], "video": LECTURE_VIDEO}

    for item in CORPUS:
        print(f"\n{item.title}")
        target = output_dir / item.filename

        if item.page_range is not None:
            raw = output_dir / f"_raw_{item.filename}"
            download(item.url, raw)
            if not target.exists():
                trim_pages(raw, target, *item.page_range)
        else:
            download(item.url, target)

        manifest["files"].append(
            {
                "name": item.name,
                "filename": item.filename,
                "title": item.title,
                "source_url": item.url,
                "licence": item.licence,
                "attribution": item.attribution,
                "tags": item.tags,
                "bytes": target.stat().st_size,
            }
        )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest written to {manifest_path}")


if __name__ == "__main__":
    main()
