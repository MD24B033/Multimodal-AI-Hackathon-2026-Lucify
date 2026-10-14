# Architecture

## What the system is

Lucify is a source-grounded study companion. It ingests lecture videos, textbooks and slide decks
into a single knowledge base where every unit of content keeps a link back to its exact origin —
page, slide, bounding box or timestamp — and then uses that knowledge base to run cited tutoring,
adaptive assessment and a per-topic learner model.

Two properties separate it from a document chatbot:

- **Nothing is said that cannot be pointed at.** Retrieval happens before generation, the answer
  must cite the excerpts it was given, invented citations are stripped, and a question the material
  does not cover is refused rather than answered from the model's own knowledge.
- **Studying leaves a trace.** Every answered question updates mastery for the topic it belongs to,
  and that estimate drives what gets asked next, what gets revised and when.

## The constraints that shaped everything

| Constraint | Consequence |
|---|---|
| Groq is the only model provider, free tier: **8,000 tokens/minute** and **200,000 tokens/day** | Embeddings run locally; no per-unit LLM calls; aggressive caching; a shared token budget |
| The daily cap is invisible in response headers | It has to be parsed out of the 429 body and surfaced as its own error |
| Upstash free tier bills per command | Live progress is polled from a cursor, one poller per channel, stopping when nobody watches |
| Single modest machine, no GPU | OCR is off by default; Docling runs CPU-threaded; one ingestion worker |
| Deployed for a handful of named people | Pre-shared access keys rather than signup, to bound the hosting bill |

Most of what follows that looks unusual is a consequence of one of these rows.

## Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI, mostly sync | Ingestion is CPU-bound and the DB driver is sync; one concurrency model avoids async/sync bugs. Event streams are the deliberate exception |
| Database | PostgreSQL 18 + pgvector | Vectors, full-text search and relational learner state in one store, one transaction |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | Typed models, reproducible schema |
| Document parsing | Docling | Layout-aware PDF/PPTX/DOCX parsing that preserves page numbers and bounding boxes |
| Media | ffmpeg (bundled via `imageio-ffmpeg`) + Groq Whisper | No system install; word-level timestamps |
| Embeddings | `BAAI/bge-small-en-v1.5`, local | 384-dim, free, offline, no rate limit — the single biggest reason the system works under the cap |
| Generation | `openai/gpt-oss-120b` | Long context, strict structured outputs |
| Vision | `qwen/qwen3.8-27b` | Reads diagrams, figures and image-only slides |
| Verification | `qwen/qwen3.8-27b` | A genuinely different model family from the generator |
| Speech (optional) | Sarvam `bulbul:v3` + `saaras:v3-realtime` | Learner-supplied key, used only as a voice and an ear |
| Realtime | Upstash Redis streams over REST | Progress that survives a restart and crosses processes |
| Frontend | Next.js 16, React 19, Tailwind v4, `motion` | Static shell talking to the API; no server-side secrets |

## System map

```
┌─ browser ────────────────────────────────────────────────┐
│  Next.js app  ──HTTP──►  FastAPI                         │
│       │                                                  │
│       ├──EventSource──►  /events      (live progress)    │
│       └──WebSocket────►  /api/voice/stream  (speech)     │
└──────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  PostgreSQL            Upstash Redis           Groq API
  + pgvector            streams: progress       generation,
  units, mastery,       shared token budget     vision, ASR
  sessions, tasks                                    │
                                              Sarvam (optional)
                                              TTS + realtime STT

  In-process: ingestion worker  ·  generation queue  ·  local embedder
```

The ingestion worker and the generation queue are thread pools inside the API process. They are
separate from the request that started them on purpose: closing a tab must never cancel work.

## Ingestion

Uploads return `202` immediately with a `Source` row; the pipeline runs in the background and
reports progress as it goes.

```
Upload ─► Source row ─► ingestion worker
                           │
                           ├─ documents.py ── Docling ──► text / tables / figures  (page, slide, bbox)
                           │                      ├─ figures ──► vision model ─► searchable description
                           │                      └─ text-less pages ─► pypdfium2 render ─► vision model
                           │
                           └─ media.py ─── yt-dlp / ffmpeg ─► audio ─► Whisper ─► segments (timestamps)
                                              └──── keyframes ──────► vision model ─► on-screen slide text
                           │
                           ▼
                     ContentUnit rows  (text + locator + modality + embedding + tsvector)
                           │
                           ├─ taxonomy.py ─► Topics / Subtopics / Concepts / Prerequisite edges
                           └─ tag_units()  ─► UnitTopic, UnitConcept links (embedding similarity)
```

Stages are reported as they happen — `downloading`, `parsing document`, `reading pages`,
`reading figures`, `embedding`, `building topic map`, `tagging topics` — each with a fractional
progress value, so the interface shows real work rather than a spinner.

Three things worth calling out:

**OCR is off by default, then applied selectively.** Docling parses without OCR, and text density
is measured per page afterwards; only a document with a sparse text layer is re-parsed with it. On
CPU, OCR costs minutes on a deck that does not need it.

**A slide deck exported to PDF is detected by aspect ratio**, so citations read "Slide 12" rather
than "Page 12" without the learner having to say so.

**Image-only slides go through vision, not OCR.** A deck with no text layer at all is rendered page
by page and read by the vision model, which recovers the meaning of a diagram rather than a bag of
characters. This is the most expensive part of ingestion by a wide margin — vision accounts for the
majority of all tokens the system spends.

Ingestion is idempotent: re-ingesting a source deletes its old units first, duplicate uploads are
rejected by content hash, and a source that produced zero units fails loudly instead of being
marked ready.

## The knowledge base

`ContentUnit` is the atom of the system. Every unit carries:

- `text` — what gets embedded and retrieved. For a figure this is the vision model's description
  plus its caption, which is what makes diagrams findable by text search.
- `modality` — `text`, `figure`, `table`, `transcript` or `equation`.
- **A locator** — `page_no`, `slide_no`, `start_time_s`/`end_time_s`, and `bbox`. This is never
  optional. It is what makes a citation openable.
- `embedding vector(384)` with an HNSW cosine index.
- `search_vector tsvector`, a generated column with a GIN index.
- `heading_path` — the section hierarchy the unit sits under, used for chunk coherence.

Chunking is heading-aware for documents (~320 tokens with 60 overlap) and window-based for
transcripts (45-second windows), because a lecture has no headings to respect.

## Retrieval

Hybrid, because dense and lexical retrieval fail differently. Dense search misses exact symbols and
rare terms; lexical search misses paraphrase.

1. Vector search: `embedding <=> query` over pgvector, top 40.
2. Lexical search: `websearch_to_tsquery` against the GIN index, top 40.
3. Fuse with Reciprocal Rank Fusion, `score = Σ 1/(k + rank)` with `k = 60`, keeping the top 8.

RRF is used rather than score normalisation because cosine distance and `ts_rank_cd` are not on
comparable scales, and RRF only needs the ranks.

Filters for topic, source and modality are applied before fusion, so a quiz scoped to one topic
retrieves only from that topic's units, and a document-scoped chat sees only that document.

## Grounding, citation and refusal

`retrieval/grounding.py` is the gate between retrieval and the learner:

1. **Coverage check.** If nothing retrieved clears `grounding_threshold` (0.38), the question is
   refused before any model call. A refusal costs zero tokens and says what the material does
   cover instead.
2. **Cited generation.** The model receives numbered excerpts and must attach markers to its
   claims, returned as structured JSON rather than free text.
3. **Citation validation.** Markers pointing at excerpts that were not supplied are dropped, and an
   answer left with no surviving citation is downgraded to a refusal.

The refusal path is measured, not assumed: the evaluation harness scores both correct refusals and
false refusals, because a system that refuses everything would otherwise look perfectly faithful.

## Conversation context

A naive chat implementation re-sends every retrieved excerpt on every turn, which is exactly what
an 8,000-token-per-minute cap cannot afford. `retrieval/context.py` keeps a ledger per session:

- Units already quoted in this session are tracked on `ChatSession.seen_unit_ids`.
- On each turn, retrieval is split into **fresh** and **recalled**. Fresh excerpts are sent in full;
  recalled ones are rendered as a one-line reference — still citable, nearly free.
- Older turns are folded into a running ~90-word memo every six messages, so history stays bounded.

The win is on follow-up questions about the same material, which is how tutoring actually goes. A
question about something entirely different retrieves all-fresh units and saves nothing, by design.

## Assessment and the learner model

Question generation is scoped — to a course, a topic or a source — and every generated question is
put through two filters before it is stored:

- **Cross-model verification.** A different model family (Qwen, against the gpt-oss generator)
  checks that the question is answerable from the cited excerpts. Genuine cross-model validation,
  not a model checking itself. If the verifier is unreachable the question is kept, because an
  outage must not silently discard a whole batch.
- **Novelty.** A fingerprint plus an embedding similarity check against existing questions, so a
  course does not accumulate the same question five times.

Each question is bound to a topic, inferred from the units it cites when the generator did not
supply one — without that link the learner model has nothing to update.

Grading is deterministic where it can be (MCQ, numerical with tolerance) and model-assisted only
for short answers. Then:

| Component | What it does |
|---|---|
| `learner/bkt.py` | Bayesian knowledge tracing with difficulty-conditioned slip and guess |
| `learner/irt.py` | 2PL ability estimation across the course |
| `learner/scheduler.py` | SM-2 intervals and a forgetting curve for retention forecasting |
| `learner/profile.py` | Persistence, propagation to parent topics, mastery snapshots |

**None of these make an LLM call.** They are closed-form maths over interaction rows, which is why
the learner model stays responsive and free regardless of the token budget.

## Personalization memory

`learner/memory.py` builds a durable picture of the learner — preferences, goals, recurring
confusions — from regex patterns over what they type, from assessment outcomes and from explicit
feedback. It is rule-based on purpose: an LLM call per message to "extract preferences" would be
the single most wasteful thing the system could spend tokens on.

The result is injected into the tutor prompt as a short block, and is fully visible and editable by
the learner on the Memory page. Nothing is remembered that they cannot see and delete.

## Background work

Two queues, both in-process thread pools, both reporting through the realtime transport:

- **Ingestion worker** (`ingestion/jobs.py`) — one worker, because Docling and the local embedder
  already saturate the CPU. State lives in `ingestion_jobs`.
- **Generation queue** (`tasks.py`) — notes, assessments, revision packs, audio briefs and study
  plans. Handlers register against a kind with a decorator (`generation_handlers.py`), so adding a
  background job is one function. State lives in `generation_tasks`.

Both exist for the same reason: a long generation must survive navigation. Work started on one page
keeps running when the learner moves to another, and announces itself when it finishes. A course
with a task in flight reports itself busy, so further uploads queue rather than collide.

## Realtime transport

Progress reaches the browser over SSE. What sits behind the SSE endpoint is pluggable, chosen at
startup and reported by `/health`:

| Transport | When | Mechanism |
|---|---|---|
| **Upstash** | `USE_UPSTASH_FOR_EVENTS` and credentials present (the default) | Capped Redis stream per channel, read forward from a cursor |
| **Redis** | `REDIS_URL` set | Real pub/sub |
| **In-process** | neither | Queues in memory — correct for a single instance |

Upstash speaks Redis over HTTP, which rules out `SUBSCRIBE`, so events have to be polled. Polling
naively is what makes a per-command free tier expensive, so:

- Events are appended with `XADD` to a capped stream and read with `XRANGE` from an exclusive
  cursor — **one command per poll, returning only what is new.**
- **One poller serves every browser watching a channel.** A second viewer of the same ingestion
  adds no traffic.
- It **backs off** from `UPSTASH_POLL_SECONDS` to `UPSTASH_IDLE_POLL_SECONDS` when nothing is
  happening, and snaps back on the first event.
- It **stops entirely when nobody is watching**, so an idle app costs nothing.

The SSE endpoints are the one async part of the API, for a specific reason: a sync generator in the
threadpool cannot notice that the browser has gone, and uvicorn waits for in-flight requests before
it will shut down — a held-open stream otherwise pins the server forever. They are async, check
`request.is_disconnected()`, stop on a terminal event or `SSE_MAX_SECONDS` (after which the browser
reconnects by itself), and a signal hook ends them on Ctrl-C.

`EventSource` cannot send headers, so authenticated streams take the access key as a query
parameter.

## Voice

Spoken tutoring is optional and uses a Sarvam key the learner supplies, stored per account and
never sent to the browser. **Sarvam is given a voice and an ear; nothing else.** Retrieval,
grounding, citation and the learner model all stay inside Lucify — Sarvam receives microphone audio
and finished reply text, and returns a transcript and audio.

The conversation is hands-free. Microphone audio is streamed as 16 kHz PCM through the app's own
WebSocket (`/api/voice/stream`), which proxies to Sarvam's realtime transcriber; Sarvam's voice
activity detection decides when a turn ends. A turn lock stops the tutor answering its own echo,
and barge-in is phrase-gated ("stop", "wait") after a short grace window rather than triggered by
any detected speech, because the tutor's own voice leaks into the microphone.

## Authentication and profiles

There is no signup. `ACCESS_KEYS` holds `key:Name` pairs; each key maps to one learner, whose row
is provisioned on startup, and keys are compared with `hmac.compare_digest`. This is a deliberate
scope choice: it bounds who can spend the hosting and token budget without building account
management.

Each learner owns **profiles** — separate workspaces such as "My studies" and "Side projects" —
and courses belong to a profile, so unrelated material stays unrelated.

## Rate-limit engineering

With 8,000 tokens per minute, a naive implementation fails on the first real textbook.

1. **Token and request buckets** (`llm/rate_limit.py`). Every call reserves `prompt_estimate +
   max_tokens` before it is sent, because Groq admits against `max_completion_tokens`, not against
   what is actually produced. The difference is returned afterwards.
2. **A shared budget across processes** (`upstash.py`). A fixed per-minute window in Upstash, so
   the API and the evaluation harness cannot each believe they own the whole cap and together trip
   the provider's limit.
3. **Persistent response cache** (`llm_cache`, keyed on a hash of model plus full payload).
   Deterministic calls (temperature ≤ 0.3) are cached permanently, so re-running an evaluation
   costs nothing.
4. **Backoff with jitter** on 429/503, with a real duration parser — Groq returns values like
   `1h46m33.599s`, and naive parsing of that produced a four-hour sleep. Backoff is capped at
   `max_backoff_seconds`.
5. **A circuit breaker** plus a consecutive-page-failure limit, so a provider outage mid-ingestion
   stops cleanly instead of burning the daily quota on retries.
6. **Embeddings run locally.** Retrieval, unit tagging, question-novelty checks and semantic
   similarity consume zero API budget.
7. **Daily quota is parsed out of the 429 body** (`tokens per day (TPD): Limit, Used`) and raised
   as its own error, because it appears in no header. Chat still returns its citations when this
   happens, so the grounding is visible even when generation cannot run.

A smaller one: structured-output calls that truncate mid-JSON are retried with doubled headroom and
`reasoning_effort="low"`, because `gpt-oss` spends completion tokens reasoning before it emits the
object.

## Data model

28 tables, grouped by what they are for:

| Group | Tables |
|---|---|
| Access | `students`, `profiles`, `voice_credentials` |
| Knowledge base | `courses`, `sources`, `content_units`, `ingestion_jobs` |
| Structure | `topics`, `concepts`, `topic_prerequisites`, `unit_topics`, `unit_concepts` |
| Tutoring | `chat_sessions`, `chat_messages`, `learner_memories` |
| Assessment | `questions`, `assessments`, `assessment_items`, `assessment_reports` |
| Learner model | `topic_mastery`, `interactions` |
| Study aids | `flashcards`, `study_plans`, `revision_assets` |
| Operations | `generation_tasks`, `llm_cache`, `eval_runs`, `eval_cases` |

## Module map

```
backend/app/
  main.py                lifespan, routers, health, shutdown signals
  config.py              settings, model ids, thresholds — every tunable
  auth.py                access keys, identities, per-request student
  realtime.py            broker selection, Upstash streams, SSE
  upstash.py             REST client, shared token budget
  tasks.py               background generation queue
  generation_handlers.py what that queue knows how to run
  db/models.py           28 tables
  llm/
    groq_client.py       budget, backoff, cache, structured output, vision, ASR
    rate_limit.py        token + request buckets, circuit breaker
  ingestion/
    documents.py         Docling → units with page/slide/bbox
    media.py             yt-dlp, ffmpeg, Whisper, keyframes
    figures.py           vision descriptions of diagrams
    chunking.py          heading-aware packing, transcript windowing
    taxonomy.py          topic/concept/prerequisite extraction, unit tagging
    pipeline.py          orchestration and progress reporting
    jobs.py              background worker
  retrieval/
    embedder.py          local sentence-transformers
    hybrid.py            pgvector + FTS + RRF
    context.py           per-session context ledger, history folding
    grounding.py         coverage gate, cited generation, refusal
  assessment/
    generator.py         scoped question generation
    verifier.py          cross-model validation
    novelty.py           fingerprint + embedding dedup
    grading.py           deterministic + model grading
    report.py            post-assessment analysis
  learner/
    bkt.py  irt.py  scheduler.py  profile.py    the learner model, no LLM calls
    memory.py            rule-based personalization memory
  enhancements/
    flowmap.py           course flow map and learning path
    notes.py             multi-format note generation
    revision.py          flashcards, audio briefs
    schedule.py          exam-aware study plan
  voice/sarvam.py        TTS and one-shot transcription
  api/routes/            auth, profiles, courses, chat, assessments, learner,
                         notes, memory, tasks, voice, voice_ws, media
```

```
frontend/
  app/
    page.tsx             hero
    about/  login/
    dashboard/           sidebar: Courses · Planner · Insights · Memory · Settings
    courses/[courseId]/  tabs: Overview · Chat · Voice · Notes · Assess · Material
  components/
    app-frame.tsx        navigation shell, theme
    session-context.tsx  signed-in learner, profile, persistence
    task-center.tsx      background task stream and completion toasts
    chat-workspace.tsx   split view: chat beside the cited material
    source-viewer.tsx    citation chips and the modal that opens them
    pdf-viewer.tsx       in-app PDF with bounding-box highlighting
    voice-tutor.tsx      hands-free spoken tutoring
    course-*.tsx         overview, material, assess
    sections/*.tsx       the dashboard sections
  lib/
    api.ts               fetch wrapper, access key, error extraction
    use-ingestion-events.ts   live ingestion progress
    voice-session.ts     microphone capture + voice WebSocket
    speech-player.ts     reply playback with a live amplitude
```

## Frontend architecture

A static Next.js shell that talks to the API; no secrets and no data access live on the Next
server. The access key is held in `localStorage` and attached per request, or as a query parameter
on the two streams, since `EventSource` and `WebSocket` cannot carry headers.

Citations are the centre of the interface rather than a footnote. A citation chip opens the source
in place — a PDF at the right page with the cited lines boxed, a video at the right second, or the
extracted figure — using a custom viewer rather than the browser's, so the material can sit beside
the conversation in a split view instead of replacing it.

## Evaluation

The harness is a **separate program** at the repository root (`evaluation/`), not part of the app.
It drives the running app over HTTP only, which means it measures what a user would actually get,
and it brings its own RAGAS and judge dependencies so the app does not carry them.

It reports RAGAS faithfulness, context recall and precision and answer relevancy; retrieval quality
as `source_hit_rate`, `source_precision_at_k`, `source_recall` and `mean_reciprocal_rank`; and —
unusually — `correct_refusal_rate`, `false_refusal_rate` and `refusal_f1`, since refusal behaviour
is half of what source grounding means. A simulated-student run measures whether adaptivity
actually helps.

A run writes `rag.json`, `personalization.json` and a generated `RESULTS.md` into
`evaluation/results/`. Method and caveats are in `evaluation/METHODOLOGY.md`.

## Notable trade-offs

**Unit→topic tagging uses embeddings, not an LLM call per unit.** A 500-unit textbook would be 500
calls, which the token cap makes impossible. Topic and concept names are embedded once, units are
assigned by cosine similarity with a confidence threshold, and the primary topic plus its parent
are always linked. Cheap, deterministic, fast; the cost is that tagging is only as good as the
topic names the taxonomy step produced.

**Simulated-student evaluation uses MCQ only.** Short-answer grading needs a model call per answer,
which would make a multi-learner run take hours under the cap. MCQ grading is deterministic, so
personalization runs are fast and free. Stated in the evaluation report rather than hidden.

**Sync throughout, except event streams.** Ingestion is dominated by Docling and local embedding,
both CPU-bound and both releasing the GIL, so async would have bought little and cost correctness.
Event streams are async because they need to notice a disconnect, which a threadpool generator
cannot.

**One ingestion worker.** Parallel ingestion would contend for the same CPU that Docling and the
embedder already saturate, and would multiply the vision calls hitting a shared token budget.
Queueing is the honest behaviour.

**The learner supplies the speech key, not the app.** Voice is the one feature with a per-use cost
the project does not control, so it is opt-in and the key belongs to whoever uses it.

## Related docs

- `STACK.md` — what is used where, API versus local
- `GROUNDING.md` — the citation and refusal contract in detail
- `LEARNER_MODEL.md` — the maths behind mastery and scheduling
- `PERFORMANCE.md` — measured latencies and the bottleneck analysis
- `EVALUATION.md` — how the harness works
- `FILE_GUIDE.md` — every file and what it is for
