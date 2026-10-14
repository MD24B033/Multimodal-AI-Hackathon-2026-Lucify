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
| Answer relevancy | 91.0% | Source hit rate | 75.0% |
| Faithfulness | 65.3% | Mean reciprocal rank | 75.0% |
| Context precision | 68.8% | Correct refusal rate | 100.0% |
| Context recall | 62.5% | False refusal rate | 0.0% |

Every off-material question was refused, and no answerable question was refused wrongly. The
adaptive learner model gains 11.6% more true mastery than an otherwise identical non-adaptive
control arm. Sample sizes are small because the whole system runs inside a free Groq tier of 8,000
tokens per minute — the threats to validity are stated in
[app/docs/EVALUATION.md](app/docs/EVALUATION.md).

## Running it

Start with [app/README.md](app/README.md): PostgreSQL 18 with pgvector, a Groq key, and optionally
Upstash Redis for live progress and a shared token budget across processes. Retrieval, embeddings
and every learner-model calculation run locally, so language models are only called where they are
genuinely needed.
