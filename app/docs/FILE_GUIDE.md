# File guide

What every file does. Line counts are a rough guide to weight, not importance.

---

# Backend

## Entry point and configuration

| File | Lines | What it does |
|---|---|---|
| `app/main.py` | 124 | FastAPI app. Registers routers, CORS, `/health`, `/api/config`. On startup: verifies pgvector, starts the ingestion worker, warms the embedding model in a background thread (kills a 29s cold start). |
| `app/config.py` | 115 | Every tunable in one place: model IDs, rate limits, retrieval thresholds, chunk sizes, token budgets, Redis URL. Pydantic settings, so any value can be overridden by environment variable. |
| `requirements.txt` | 29 | Pinned dependencies. |
| `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` | — | Migration config. `env.py` pulls the DB URL from settings; the template imports `pgvector.sqlalchemy` so generated migrations work. |
| `alembic/versions/9406d68ca648_initial_schema.py` | 518 | The whole schema in one migration, including `CREATE EXTENSION vector` and the HNSW + GIN indexes. |

## Database

| File | Lines | What it does |
|---|---|---|
| `app/db/models.py` | 544 | All 25 tables. `ContentUnit` is the core: text, modality, embedding, tsvector, **and the locator** (page/slide/timestamp/bbox) that makes citations openable. |
| `app/db/database.py` | 51 | Engine, session factory, `session_scope()` context manager, pgvector type registration on connect. |
| `app/db/base.py` | 4 | The declarative `Base`. |

## LLM layer

| File | Lines | What it does |
|---|---|---|
| `app/llm/groq_client.py` | 475 | The only thing that talks to Groq. Structured JSON output, vision, transcription, TTS. Also: retry with backoff, **duration parsing** for Groq's `1h46m33.599s` format, **daily-quota detection**, a persistent response cache, and a circuit breaker. |
| `app/llm/rate_limit.py` | 155 | Token bucket + request bucket, an **interactive priority lane** so chat pre-empts batch ingestion, and the circuit breaker that trips after repeated upstream failures. |

## Ingestion

| File | Lines | What it does |
|---|---|---|
| `app/ingestion/pipeline.py` | 278 | Orchestrates everything: parse → describe figures → embed → persist → build taxonomy → tag units. Publishes progress events. Fails loudly if extraction yields zero units. |
| `app/ingestion/documents.py` | 364 | Docling parsing with page/slide/bbox preserved. Cheaply inspects a PDF first (orientation, text density) to decide: Docling, Docling+OCR, or **render pages and read them with vision**. Collapses animated slide builds by perceptual hash. |
| `app/ingestion/media.py` | 324 | ffmpeg audio extraction and chunking, Whisper transcription with real timestamps, keyframe sampling, YouTube download. |
| `app/ingestion/figures.py` | 114 | Sends figures and full page images to the vision model and turns them into searchable prose. Drops decorative images. |
| `app/ingestion/taxonomy.py` | 349 | Extracts topics, subtopics, concepts and prerequisite edges. Then tags every unit to them **by embedding similarity — no LLM call per unit**, which is what makes this affordable. |
| `app/ingestion/chunking.py` | 139 | Heading-aware sentence packing with overlap; transcript windowing into ~45s units. |
| `app/ingestion/jobs.py` | 65 | Background worker thread pool. Uploads return immediately; this does the work. |
| `app/ingestion/types.py` | 52 | The `RawUnit` dataclass that flows through ingestion, plus timestamp formatting. |

## Retrieval and grounding

| File | Lines | What it does |
|---|---|---|
| `app/retrieval/hybrid.py` | 193 | Hybrid search: pgvector cosine + Postgres full-text, fused with Reciprocal Rank Fusion. Builds the citation objects the UI deep-links from. |
| `app/retrieval/grounding.py` | 225 | The heart of grounding. Coverage gate (refuses *before* calling the LLM), learner-aware prompting, structured answer with separated `outside_knowledge`, and validation that drops invented citation numbers. |
| `app/retrieval/embedder.py` | 55 | Local `bge-small-en-v1.5` wrapper. Lazy-loaded, thread-safe, normalised 384-dim vectors. |

## Assessment

| File | Lines | What it does |
|---|---|---|
| `app/assessment/generator.py` | 491 | Writes MCQ / short-answer / numerical questions from a chosen scope. Picks target topics from the learner model, sets difficulty from IRT ability, infers a topic for every question so none goes untagged. |
| `app/assessment/verifier.py` | 133 | Cross-model validation: Qwen independently answers each question and rejects it if it disagrees, if it isn't answerable from the source, or if more than one option is defensible. |
| `app/assessment/grading.py` | 240 | Deterministic grading for MCQ and numerical (no LLM), model grading with cited feedback for short answers. |
| `app/assessment/report.py` | 252 | Grades a submission, updates the learner model, and writes the post-assessment report: weak topics, misconceptions, mastery deltas, recommendations. |
| `app/assessment/novelty.py` | 68 | Stops repeat questions, by normalised fingerprint and by embedding similarity against the whole bank. |

## Learner model — all local maths, no LLM

| File | Lines | What it does |
|---|---|---|
| `app/learner/profile.py` | 264 | Persistence and orchestration: applies forgetting decay, records responses, propagates evidence to parent topics and prerequisites, produces dashboard snapshots. |
| `app/learner/bkt.py` | 71 | Bayesian knowledge tracing with **difficulty-conditioned slip and guess** — an easy question answered right is weak evidence. |
| `app/learner/irt.py` | 67 | 2PL ability estimation by Newton iteration; picks the next question's difficulty. |
| `app/learner/scheduler.py` | 72 | SM-2 spaced repetition, forgetting curve, review urgency. |

## Enhancements

| File | Lines | What it does |
|---|---|---|
| `app/enhancements/notes.py` | 315 | The notes maker. Four formats (summary, Cornell, cheat sheet, flashcards), depth and language control, grounded with citations, Markdown export. |
| `app/enhancements/revision.py` | 285 | Flashcard generation with SM-2 review, and spoken audio briefs for weak topics. |
| `app/enhancements/flowmap.py` | 185 | Builds the course flow map: prerequisite layering, mastery colouring, and the "what to study next" ordering. |
| `app/enhancements/schedule.py` | 188 | Exam-aware study plan weighted by weak topics and forgetting, plus the retention forecast. |
| `app/enhancements/tts.py` | 95 | Speech synthesis and voice-input transcription. Strips markdown and citation markers before speaking. |

## API routes

| File | Lines | What it does |
|---|---|---|
| `app/api/routes/courses.py` | 306 | Courses, uploads, YouTube ingest, re-ingest, units, topics, flow map, and the **SSE progress streams**. |
| `app/api/routes/learner.py` | 324 | Students, diagnostic quiz, dashboard, mastery, study plan, retention forecast, flashcards, revision packs, audio briefs. |
| `app/api/routes/chat.py` | 242 | Chat sessions, the grounded `ask` endpoint, voice transcription, raw search. Feeds conversation signals into the learner model. |
| `app/voice/sarvam.py` | 174 | Sarvam client: `bulbul:v3` speech, `saaras:v3` transcription. Strips markdown and citation markers, splits long answers and stitches the audio back together. |
| `app/api/routes/voice_ws.py` | 123 | WebSocket proxy to Sarvam's realtime transcriber. Holds the learner's key server-side and relays speech events to the browser. |
| `app/api/routes/assessments.py` | 187 | Create, fetch, answer, submit; report retrieval and the question bank. |
| `app/api/routes/notes.py` | 141 | Note formats, generation, listing, Markdown download, delete. |
| `app/api/routes/media.py` | 112 | Serves figures, source files and audio — with **HTTP range support**, which is what lets a video citation seek to its timestamp. |
| `app/api/serializers.py` | 230 | One place where DB models become JSON. Controls what's hidden before grading (answer keys) and revealed after. |
| `app/api/deps.py` | 37 | Session dependency and common 404 helpers. |

## Realtime and scripts

| File | Lines | What it does |
|---|---|---|
| `app/realtime.py` | 169 | Progress broker with two backends: Redis pub/sub, or in-process if Redis is unreachable. Also the SSE event formatter. The app never hard-fails on a missing Redis. |
| `scripts/fetch_demo_corpus.py` | 139 | Downloads the openly-licensed demo corpus and writes a manifest with licence and attribution. |
| `scripts/seed_demo.py` | 159 | Creates the demo course and learners, then ingests the corpus. Idempotent by content hash. |
| `test_db.py` | 18 | Your own quick DB connection check. |

---

# Frontend

## Pages — the four tabs

| File | Lines | What it does |
|---|---|---|
| `app/page.tsx` | 418 | **Ingestion.** Course details (title, description, exam date), file and video-URL upload, live processing queue over SSE, flow map, topic tree. |
| `app/dashboard/page.tsx` | 532 | **Dashboard.** Weak-topic chart, learning curve, retention forecast, per-topic mastery, study schedule builder, flashcard review, audio briefs. |
| `app/tutor/page.tsx` | 166 | **Tutor.** Mode switcher that hosts the three tutor experiences; owns the shared source viewer. |
| `app/assessments/page.tsx` | 479 | **Assessments.** Quiz builder with scope and format control, the quiz itself, then the graded report with cited per-answer feedback. |
| `app/layout.tsx` | 25 | Root layout; wraps everything in the workspace provider and app shell. |
| `app/globals.css` | 223 | Design tokens for light and dark, and the shared `card` / `btn` / `input` classes. |

## Components

| File | Lines | What it does |
|---|---|---|
| `components/grounded-chat.tsx` | 380 | The chat surface, reused twice: whole-course tutoring and document-scoped chat. Grounding badges, citation chips, voice input, language switching, outside-knowledge panel. |
| `components/voice-tutor.tsx` | 570 | Hands-free spoken tutoring: key gate, live transcript, turn taking driven by voice activity, barge-in on "stop", and citations on every spoken answer. |
| `components/notes-maker.tsx` | 346 | Notes UI: format picker, topic/free-text scope, depth, language, extra instructions; renders all four formats differently and lists saved notes. |
| `components/source-viewer.tsx` | 193 | **The payoff for grounding.** Citation chips, and the modal that opens a PDF at the right page, a video at the right second, or the extracted figure. |
| `components/flow-map.tsx` | 187 | Hand-rolled SVG graph of topics and prerequisites, layered by dependency and coloured by mastery. |
| `components/ui.tsx` | 201 | Shared primitives: Card, Badge, Stat, MasteryBar, ProgressBar, EmptyState, Spinner, Field. |
| `components/app-shell.tsx` | 171 | Header, four-tab nav, course and learner pickers. |
| `components/workspace-context.tsx` | 134 | Global state: which course and learner are selected, persisted to localStorage. |

## Library

| File | Lines | What it does |
|---|---|---|
| `lib/types.ts` | 303 | TypeScript mirrors of every API payload. |
| `lib/api.ts` | 60 | Thin fetch wrapper: typed helpers, error extraction, media URL builder. |
| `lib/use-ingestion-events.ts` | 54 | `EventSource` hook for live ingestion progress, keyed by source. |
| `lib/voice-session.ts` | 234 | Microphone capture through an AudioWorklet, 16 kHz PCM streamed to the voice WebSocket. Emits speech boundaries, partial and final transcripts. |
| `lib/speech-player.ts` | 132 | Plays the spoken reply and exposes a live amplitude, so the orb reacts to the voice rather than to a timer. |
| `next.config.ts`, `eslint.config.mjs`, `tsconfig.json`, `postcss.config.mjs` | — | Build and lint config. |

---

# Evaluation harness — separate program

Not part of the app. Lives in `evaluation/`, has its own virtualenv, drives the running app over
HTTP only.

| File | What it does |
|---|---|
| `run_eval.py` | CLI entry point; orchestrates both evaluations and writes the Markdown report. |
| `harness/client.py` | Typed HTTP client for the app's public API. The only way the harness can touch the system. |
| `harness/judge.py` | Groq client for the judge model, with its **own** token budget so it can be kept below the app's. |
| `harness/testset.py` | Builds the test set from the app's own units, so ground-truth source locations are known rather than guessed. |
| `harness/metrics.py` | RAGAS metrics, plus source-location accuracy and refusal metrics that RAGAS doesn't cover. |
| `harness/personalization.py` | Simulated learners with hidden true ability, run against a non-adaptive control arm. |
| `METHODOLOGY.md` | What's measured, how, and the threats to validity. |
