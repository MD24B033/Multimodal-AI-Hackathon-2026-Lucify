# What's used, and where

A quick map of the system: which parts call an API, which run locally, and how a request flows.

## The one design rule

**Anything that can run locally, does.** Groq is the only API available and it is capped at 8,000
tokens/minute and 200,000 tokens/day. So embeddings, search, parsing, scheduling and all the learner
maths are local and free. The API is reserved for things that genuinely need a language model.

## API calls (Groq) — the only external service

| Model | Used for | Where |
|---|---|---|
| `openai/gpt-oss-120b` | Chat answers, notes, question writing, short-answer grading, reports, topic extraction | `retrieval/grounding.py`, `enhancements/notes.py`, `assessment/*` |
| `qwen/qwen3.8-27b` | **Vision**: reading diagrams, figures and image-only slides | `ingestion/figures.py` |
| `qwen/qwen3.8-27b` | **Cross-model verification** of generated questions | `assessment/verifier.py` |
| `whisper-large-v3` | Video/audio transcription, and voice input in chat | `ingestion/media.py`, `enhancements/tts.py` |
| `canopylabs/orpheus-v1-english` | Text-to-speech for audio briefs | `enhancements/tts.py` |

Qwen is used as the verifier deliberately: it's a **different model family** from the generator, so
"cross-model validation" is genuine rather than a model checking itself.

> TTS needs one-time terms acceptance on the Groq console. Until then the app shows the brief's
> script as text instead of playing it.

## Sarvam — the voice, and only the voice

Spoken tutoring is optional and uses a key the learner supplies on the Voice tab. It is stored per
account and never leaves the backend. Sarvam is given a voice and an ear; nothing else.

| Model | Used for | Where |
|---|---|---|
| `bulbul:v3` | Speaking the tutor's reply | `voice/sarvam.py` |
| `saaras:v3-realtime` | Live transcription over a WebSocket, with VAD endpointing | `api/routes/voice_ws.py` |
| `saaras:v3` | One-shot transcription for the microphone button in text chat | `voice/sarvam.py` |

What stays inside Lucify: which passages are retrieved, what the answer says, which sources are cited,
and how the learner model updates. Sarvam receives the microphone audio and the finished reply text,
and returns a transcript and audio. It never sees the course material or the retrieval.

The browser streams 16 kHz PCM through the app's own WebSocket (`/api/voice/stream`), which proxies
to Sarvam with the stored key, so the key never reaches the browser. Sarvam's voice activity
detection decides when a turn ends, which is what makes the session hands-free rather than
press-to-talk. Saying "stop" or "wait" while the tutor is speaking cuts the answer short.

## Local — no API, no cost, no rate limit

| Component | What it does |
|---|---|
| **`BAAI/bge-small-en-v1.5`** (sentence-transformers) | **All embeddings**, 384-dim. Search, topic tagging, question dedup, note retrieval |
| **Docling** | PDF/PPTX/DOCX parsing with layout, tables, figures and page numbers |
| **PostgreSQL + pgvector** | Vector store with HNSW cosine index |
| **Postgres full-text search** | Lexical half of retrieval, GIN-indexed `tsvector` |
| **pypdfium2** | Renders PDF pages to images when a PDF has no text layer |
| **pypdf** | Cheap PDF inspection (orientation, text density) before the expensive parse |
| **ffmpeg** (bundled via `imageio-ffmpeg`) | Audio extraction, chunking, keyframe sampling |
| **Pillow** | Perceptual hashing to collapse animated slide builds |
| Pure Python | RRF fusion, BKT, IRT, SM-2 scheduling, forgetting curve, study plans |

The learner model involves **no LLM at all** — it's Bayesian knowledge tracing, IRT ability
estimation and SM-2 scheduling, all closed-form maths in `learner/`.

## How a document gets ingested

```
Upload ─► pypdf inspects it (landscape? has text layer?)
           │
           ├─ Has text  ─► Docling ─► text + tables + figure crops (page/slide + bbox kept)
           │                            └─ each figure ─► Qwen vision ─► searchable description
           │
           └─ No text   ─► pypdfium2 renders pages ─► collapse animation builds (local hashing)
                                                    └─ each page ─► Qwen vision ─► text + diagram
           │
           ▼
      local embeddings ─► Postgres (vector + tsvector + page/slide/timestamp)
           │
           └─ gpt-oss builds the topic tree; units tagged to it by embedding similarity (no LLM)
```

Video takes the same path via ffmpeg → Whisper for timestamped transcript, plus keyframes through
the vision model so slides shown on screen are captured too.

## How a question gets answered

```
Question ─► local embedding (44ms)
          ─► pgvector search + Postgres full-text search, top 40 each
          ─► RRF fusion (local), keep top 8
          ─► coverage gate: best score < 0.38 ? refuse WITHOUT calling the LLM
          ─► gpt-oss writes a cited answer as strict JSON
          ─► drop any citation number the model invented
          ─► answer + openable citations
```

**Only one API call per answer.** Everything before and after it is local, which is why retrieval is
90ms and the LLM is the only slow part.

## Settings that matter

| Setting | Value | Meaning |
|---|---|---|
| `grounding_threshold` | 0.38 | Below this similarity, the tutor refuses before generating |
| `novelty_threshold` | 0.88 | Question embedding similarity above this counts as a repeat |
| `retrieval_top_k` / `candidates` | 8 / 40 | Final context size / per-engine candidate pool |
| `rrf_k` | 60 | Reciprocal rank fusion constant |
| `tokens_per_minute` | 8000 | Shared token bucket; raise it if you upgrade the Groq tier |

All in `backend/app/config.py`, overridable by environment variable.

## Supporting pieces

- **Upstash Redis** — carries everything live: ingestion progress and background generation
  tasks. Because it is shared state rather than process memory, progress survives a restart and
  reaches a browser even when another process is doing the work. It also holds the shared token
  budget, so the app and the evaluation harness cannot each spend the full 8,000/minute.
- **SSE** — pages stream progress instead of polling. Streams end when the browser leaves, when
  the job reports it is finished, or after `SSE_MAX_SECONDS`, after which the browser reconnects
  by itself.

  Upstash speaks Redis over HTTP, so there is no `SUBSCRIBE`. Events are appended to a capped
  Redis **stream** per channel and read forward from a cursor: one command per poll, returning
  only what is new. One poller serves every browser watching the same channel, it backs off from
  `UPSTASH_POLL_SECONDS` to `UPSTASH_IDLE_POLL_SECONDS` when nothing is happening, and it stops
  entirely when nobody is watching — an idle app costs nothing.

  Self-hosted Redis (`REDIS_URL`) uses real pub/sub, and with neither configured the app falls
  back to in-process events, which is correct for a single instance. `/health` reports which
  transport is live.
- **Evaluation harness** — a separate program in `evaluation/`, not part of the app. It drives the
  running app over HTTP only, and brings its own RAGAS + judge dependencies.

## Related docs

[Architecture](ARCHITECTURE.md) · [Grounding](GROUNDING.md) · [Learner model](LEARNER_MODEL.md) ·
[Performance](PERFORMANCE.md)
