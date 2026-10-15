# Lucify

**Multimodal AI Hackathon 2026 — Track D: Personalized Tutoring & Adaptive Learning**

Lucify is an AI study companion that ingests lecture videos, textbooks and slide decks into a single
source-cited knowledge base, then uses it to run grounded tutoring, adaptive assessment and a
per-topic learner model.

Every answer cites the exact page, slide or video timestamp it came from, and anything the uploaded
material does not cover is declined rather than guessed.

## Try it

| | |
|---|---|
| **Live app** | https://lucify-tau.vercel.app |
| **API** | https://multimodal-ai-hackathon-2026-lucify-production.up.railway.app/health |
| **Demo video** | YouTube: _add link_ · in-repo copy: [docs/demo/lucify_demo.mp4](docs/demo/lucify_demo.mp4) (8:31, narrated) |
| **Evaluation results** | [../evaluation/results/](../evaluation/results/) |

The live app needs an access key — there is no signup. It is deployed on free Railway and
Neon tiers, so access is limited to pre-shared keys to bound who can spend those resources.
Ask for one, or run it locally with the setup below.

## What it does

- **Multimodal ingestion** — PDFs, slide decks, DOCX, video, audio and lecture URLs, with no manual
  preprocessing. Diagrams and figures are read by a vision model so they are searchable as text;
  video is transcribed with real timestamps and on-screen slides are read from keyframes.
- **Source grounding** — hybrid retrieval over pgvector and PostgreSQL full-text search, a coverage
  gate that refuses before generating, structured answers that keep outside knowledge in a separate
  field, and citation markers validated against what was actually retrieved.
- **Adaptive assessment** — MCQ, short-answer and numerical questions generated from a chosen scope,
  each tagged to a topic, a source location and a difficulty; verified by a second model from a
  different family; deduplicated against the whole question bank by fingerprint and embedding.
- **Learner model** — Bayesian knowledge tracing with difficulty-conditioned slip and guess, IRT
  ability estimation for difficulty targeting, SM-2 scheduling with a forgetting curve, and
  prerequisite-aware propagation.
- **System evaluation** — RAGAS faithfulness, answer relevancy, context precision and recall on a
  test set built from your own material with known source locations, plus retrieval and refusal
  metrics, plus simulated-learner runs against a non-adaptive control arm.
- **All five optional enhancements** — course flow map, targeted revision material (flashcards and
  audio briefs), exam-aware study schedule, Hindi and Hinglish interaction, and voice tutoring.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — stack, data flow, module map, trade-offs
- [Grounding method](docs/GROUNDING.md) — how citations are kept honest
- [Learner model](docs/LEARNER_MODEL.md) — BKT, IRT, spaced repetition, cold start
- [Evaluation](docs/EVALUATION.md) — methodology, metrics and measured results

## Requirements

- Python 3.12
- Node.js 20+
- PostgreSQL 16+ with the `pgvector` extension available
- A Groq API key

ffmpeg is **not** a prerequisite — a static build ships with `imageio-ffmpeg`.

## Setup

### 1. Database

Create a database and make sure `pgvector` is installable. The migration creates the extension
itself, so the database user needs permission to run `CREATE EXTENSION`.

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/app/.env`:

```
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=your_database_name

GROQ_API_KEY=gsk_...

# Comma separated `key:Name` pairs — one per person who may sign in.
# Leave empty and the API is open, which is fine locally and nowhere else.
ACCESS_KEYS=k_you_change_me:Your Name
```

`backend/app/.env.example` lists every setting, including the optional Upstash pair that
carries live progress across processes. `GROQ_API_KEY` may also be set in the shell
environment instead of the file.

**To enable spoken answers and audio briefs**, accept the model terms once at
[console.groq.com](https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english).
Until that is done the API returns `model_terms_required`, and the app falls back to showing the
brief's script as text instead of playing it. Voice *input* needs no such step.

Apply the schema and start the API:

```bash
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```

The first request that needs embeddings downloads the sentence-transformers model (~130 MB) once.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. The API is expected at `http://localhost:8000`; override with
`NEXT_PUBLIC_BACKEND_URL` in `frontend/.env`.

## Demo corpus

The demo course is built from openly licensed material, downloaded by script so the result is
reproducible:

```bash
cd backend
python scripts/fetch_demo_corpus.py
python scripts/seed_demo.py                 # add --with-video to include the lecture recording
```

| Material | Source | Licence |
|---|---|---|
| *Neural Networks and Deep Learning*, ch. 1–2 | Michael A. Nielsen, Determination Press 2015 | CC BY-NC 3.0 |
| MIT 6.S191 Lecture 1 slides | introtodeeplearning.com | MIT License |
| MIT 6.S191 Lecture 3 slides | introtodeeplearning.com | MIT License |
| MIT 6.S191 Lecture 1 recording | introtodeeplearning.com | MIT License |

Ingestion is a background job with live progress in the UI. The slide decks are image-only PDFs, so
each slide is read by the vision model; expect roughly ten seconds per slide, and longer when the
rate limit throttles.

## Evaluation

Measured on the Deep Learning Foundations course, 2026-10-15 — full report in
[../evaluation/results/RESULTS.md](../evaluation/results/RESULTS.md), methodology in
[docs/EVALUATION.md](docs/EVALUATION.md).

| | | | |
|---|---|---|---|
| Faithfulness | 96.4% | Source hit rate | 85.7% |
| Answer relevancy | 89.6% | Mean reciprocal rank | 78.6% |
| Context precision | 90.4% | Locator hit rate | 100% |
| Context recall | 100% | Correct / false refusal | 100% / 0% |

Scored on 11 of 12 cases; one hit a transient provider error and is declared rather than counted,
leaving an answerable denominator of 7. The previous run is kept beside it as
`rag_baseline_2026-10-14.json`, and the two are **not** like for like: the judge now sees the
passages the generator was given rather than only those it cited.

The adaptive learner model gains 11.6% more true mastery than an otherwise identical non-adaptive
control arm, with lower calibration error and no repeated questions.

The harness is a separate process that drives a running instance over its public HTTP API, so it
cannot shortcut retrieval. Start the app, then:

```bash
cd ../evaluation
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...        # the judge calls Groq directly
export ACCESS_KEY=...              # one of the app's ACCESS_KEYS
python run_eval.py --course "Deep Learning Foundations" --answerable 8 --off-material 4
```

## Deploying

The frontend is a static Next.js build on Vercel; the backend runs on Railway against a Neon
database. The frontend needs no environment variable — the API URL is compiled into
`frontend/lib/api.ts` — but the backend must be told which site is allowed to call it:

| Variable | Value |
|---|---|
| `CORS_ORIGINS` | `https://your-app.vercel.app` (comma-separated for several) |
| `CORS_ORIGIN_REGEX` | optional, e.g. `https://lucify-.*\.vercel\.app` to cover preview deploys |
| `DATABASE_URL` | the Neon connection string |
| `ACCESS_KEYS` | `key:Name`, comma-separated — one per person |
| `GROQ_API_KEY` | required |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | optional, for live progress and a shared token budget |

If `CORS_ORIGINS` does not list the site, the browser blocks every call: the login screen cannot
even check whether a key is needed. The app will say so rather than silently letting you through.
Check it from a terminal — a healthy pairing echoes the site back:

```bash
curl -i -H "Origin: https://your-app.vercel.app" \
  https://your-api.up.railway.app/api/auth/status | grep -i access-control-allow-origin
```

## Rate limits

The system is built for a Groq free tier of **8,000 tokens per minute**. A shared token bucket,
a persistent response cache, exponential backoff, and local embeddings keep it inside that budget.
If your key has a higher limit, raise `tokens_per_minute` in `backend/app/config.py` and ingestion
and evaluation get proportionally faster.

## Project layout

```
app/
  backend/
    app/            config, db, llm, ingestion, retrieval, assessment, learner, enhancements, evaluation, api
    alembic/        migrations
    scripts/        demo corpus download and seeding
    demo_corpus/    downloaded material (git-ignored)
  frontend/
    app/            Library, Tutor, Assess, Progress, Evaluation pages
    components/     shell, citations and source viewer, flow map, shared UI
    lib/            API client and types
  docs/             architecture, grounding, learner model, evaluation
```
