# Lucify

A source-grounded study companion. It ingests your own course material — PDFs, slide decks, lecture
video and audio — and then tutors, assesses and plans from that material alone, citing the page,
slide or timestamp behind every claim and refusing when the evidence is not there.

Multimodal AI Hackathon 2026, Track D.

| | |
|---|---|
| **Live app** | https://lucify-tau.vercel.app (access key required — there is no signup) |
| **API health** | https://multimodal-ai-hackathon-2026-lucify-production.up.railway.app/health |
| **Demo video** | [app/docs/demo/lucify_demo.mp4](app/docs/demo/lucify_demo.mp4) — 8:31, narrated |
| **Evaluation results** | [evaluation/results/RESULTS.md](evaluation/results/RESULTS.md) |

## Submission contents

| Deliverable | Where |
|---|---|
| Working prototype | [`app/`](app) — FastAPI backend, Next.js frontend, setup in [app/README.md](app/README.md) |
| Architecture | [app/docs/ARCHITECTURE.md](app/docs/ARCHITECTURE.md) |
| Grounding method | [app/docs/GROUNDING.md](app/docs/GROUNDING.md) |
| Learner model | [app/docs/LEARNER_MODEL.md](app/docs/LEARNER_MODEL.md) |
| Evaluation methodology | [app/docs/EVALUATION.md](app/docs/EVALUATION.md) and [evaluation/METHODOLOGY.md](evaluation/METHODOLOGY.md) |
| Evaluation harness and results | [`evaluation/`](evaluation) |
| Demonstration video | [app/docs/demo/](app/docs/demo) with a full voice-over transcript |

## Headline results

Measured on the Deep Learning Foundations course (327 content units, 37 topics, 3 sources) by a
harness that runs as its own process and drives the app over its public HTTP API, so it cannot
shortcut retrieval.

| | | | |
|---|---|---|---|
| Faithfulness | 96.4% | Source hit rate | 85.7% |
| Answer relevancy | 89.6% | Mean reciprocal rank | 78.6% |
| Context precision | 90.4% | Locator hit rate | 100% |
| Context recall | 100% | Correct / false refusal | 100% / 0% |

Measured 2026-10-15 on 11 of 12 cases: one hit a transient provider error and is declared
rather than scored, so the answerable denominator is 7. **These are not like for like with the
earlier run** kept at [rag_baseline_2026-10-14.json](evaluation/results/rag_baseline_2026-10-14.json):
the judge now sees the passages the generator was actually given rather than only the one or two it
cited, which is a fairer test and moves faithfulness and context recall most of all. The sample is
small either way.

Every off-material question was refused and no answerable question was refused wrongly. The adaptive
learner model gains 11.6% more true mastery than an otherwise identical non-adaptive control arm.
Sample sizes are small throughout because the whole system runs inside a free Groq tier of 8,000
tokens per minute — the threats to validity are in
[app/docs/EVALUATION.md](app/docs/EVALUATION.md), and the audit that produced these corrections is
in [evaluation/ENGINEERING_REPORT.md](evaluation/ENGINEERING_REPORT.md).

## Running it

Start with [app/README.md](app/README.md): PostgreSQL 18 with pgvector, a Groq key, and optionally
Upstash Redis for live progress and a shared token budget across processes. Retrieval, embeddings
and every learner-model calculation run locally, so language models are only called where they are
genuinely needed.
