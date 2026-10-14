# Grounding method

The requirement is that answers are tied to the uploaded material, that citations open the exact
page, slide or timestamp, and that anything the material does not cover is declined or flagged
rather than answered from the model's own knowledge.

This is enforced in four places, not one. A prompt alone is not a grounding mechanism.

## 1. The locator is part of the data model

Every `ContentUnit` is written with its origin attached: `page_no`, `slide_no`, `start_time_s` and
`end_time_s`, plus the `bbox` on the page. There is no code path that creates a unit without one.
A citation is therefore not a string the model produced — it is a row in the database, and the
frontend turns it into a deep link:

| Source kind | Locator | What opens |
|---|---|---|
| Textbook PDF | `page_no` | the PDF at `#page=N` |
| Slide deck | `slide_no` | the deck at that slide |
| Lecture video | `start_time_s` | the player seeked to that second, over HTTP range requests |
| Figure or diagram | `bbox` + stored crop | the extracted image itself |

Slides are distinguished from pages by page aspect ratio, so a PDF export of a deck cites
"Slide 12", not "Page 12".

## 2. A coverage gate before generation

Retrieval runs first. If the best semantic similarity across all retrieved units is below
`grounding_threshold` (0.38 cosine), the system **refuses without calling the generation model at
all**:

```python
if not retrieval.units or retrieval.best_score < settings.grounding_threshold:
    return GroundedAnswer(answer=REFUSAL_TEMPLATE, status=GroundingStatus.refused, ...)
```

This matters because it makes refusal a property of retrieval, not of the model's willingness to
say "I don't know." A model that is feeling helpful cannot talk its way past it.

## 3. Structured generation that separates grounded from ungrounded content

The generation call returns a strict JSON object, not prose:

```json
{
  "status": "grounded | partial | unsupported",
  "answer": "...with [1] [3] markers...",
  "used_citations": [1, 3],
  "outside_knowledge": "",
  "unsupported_claims": [],
  "followups": ["..."]
}
```

Two fields carry the requirement that outside knowledge be separated from source-backed content:

- `answer` may only contain claims supported by the numbered excerpts.
- `outside_knowledge` is where general knowledge goes. The UI renders it in a visually distinct
  panel labelled "Outside your course material", so a student can never mistake it for something
  the course said.

`status` drives the badge on every answer: **grounded**, **partially covered**, or **not covered**.

## 4. Citation validation after generation

Models invent citation numbers. Every marker the model returns is intersected with the markers that
were actually supplied:

```python
used &= {citation["marker"] for citation in all_citations}
citations = [c for c in all_citations if c["marker"] in used]
```

A hallucinated `[7]` when only six excerpts were given is dropped rather than rendered. And when the
status is `unsupported`, no citations are attached at all — an answer that says "the material does
not cover this" must not be decorated with sources that imply it does.

## Retrieval that feeds the gate

Grounding is only as good as retrieval, so retrieval is hybrid:

- **Dense**: pgvector cosine over `BAAI/bge-small-en-v1.5` embeddings, HNSW index, top 40.
- **Lexical**: PostgreSQL `websearch_to_tsquery` over a GIN-indexed generated `tsvector`, top 40.
- **Fusion**: Reciprocal Rank Fusion, `Σ 1/(60 + rank)`.

Dense search alone misses exact symbols, variable names and rare terminology; lexical search alone
misses paraphrase. RRF is used instead of weighted score blending because cosine distance and
`ts_rank_cd` are not on comparable scales — only their ranks are.

The coverage gate reads the **dense** similarity rather than the fused RRF score, because RRF scores
are rank-derived and say nothing about whether the top result is actually relevant.

## Multimodal grounding

A diagram cannot be retrieved by text search unless it has text. Figures are therefore passed to the
vision model and stored as prose descriptions that include every visible label, axis and legend
entry, with the original crop kept alongside for display.

Two ingestion paths exist:

- **PDFs with a text layer** (most textbooks) are parsed by Docling; embedded figures are extracted
  as images and described individually.
- **PDFs with no text layer** (the MIT 6.S191 decks are entirely images) are rendered page by page
  and read by the vision model, which transcribes the text *and* explains the diagram in one pass.
  This is both faster and more useful than CPU OCR, which would recover the words but not the
  meaning of an architecture figure.

For lecture video, the transcript is windowed into ~45-second units carrying real start and end
times, and keyframes are sampled and described so that slides shown on screen but never spoken aloud
are still retrievable.

## Grounding in assessment, not just chat

The same discipline applies to generated questions. Each question stores `source_unit_ids` and a
citation list, and the generator is instructed to cite only excerpt numbers it was shown. Feedback
on a wrong answer is generated against those same excerpts and cites them, so a student is told what
the material actually says and can open it.

## Honest limitations

- The coverage threshold is a single global constant tuned by hand. A per-course calibrated
  threshold would be better and is not implemented.
- `status` is self-reported by the generation model. The citation-marker validation catches invented
  sources, and the RAGAS faithfulness metric measures whether claims are entailed by the context,
  but there is no per-sentence entailment check inside the live chat path — that would roughly
  double the token cost per answer, which the 8k/minute cap does not allow.
- Figure descriptions are model output. A mis-read axis label becomes a wrong citation, and the
  system has no way to detect that.
