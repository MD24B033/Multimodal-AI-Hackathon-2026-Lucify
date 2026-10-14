# Deploying Lucify

Three services: **Neon** holds Postgres, **Railway** runs the API, **Vercel** serves the
frontend. Upstash carries live progress and the shared token budget.

The repository root is the git root; the frontend and backend live under `app/`, so both
platforms need their project root set explicitly.

---

## 1. Neon — the database

1. Create a project. Any region; pick the one nearest the Railway region.
2. Copy the **pooled** connection string. It looks like:
   `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`
3. Nothing else to do. The API runs `CREATE EXTENSION IF NOT EXISTS vector` on startup
   and `alembic upgrade head` before it serves, so the schema builds itself.

Neon ships pgvector, so the HNSW index works unchanged.

> Use the pooled string. Ingestion and the request pool together open more connections
> than a direct Neon endpoint will hold.

---

## 2. Railway — the API

**Root directory:** `app/backend`

Railway reads `railway.json`, which already sets the start command
(`alembic upgrade head && uvicorn app.main:app …`) and health-checks `/health`.

### Variables

| Variable | Value |
|---|---|
| `DATABASE_URL` | the Neon pooled string |
| `GROQ_API_KEY` | your Groq key |
| `ACCESS_KEYS` | `key1:Name1,key2:Name2` — one per person you let in |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://lucify.vercel.app` |
| `UPSTASH_REDIS_REST_URL` | from the Upstash console |
| `UPSTASH_REDIS_REST_TOKEN` | from the Upstash console |
| `TOKENS_PER_MINUTE` | `8000` unless you upgrade the Groq tier |

`PORT` is injected by Railway; do not set it.

### A volume for uploads

Railway's filesystem is wiped on every deploy. Attach a **volume mounted at
`/app/storage`** so uploaded PDFs, extracted figures and audio survive a restart —
without it, citations will stop opening after the next deploy.

Then set `STORAGE_DIR=/app/storage`.

### Build size

`requirements.txt` pins the CPU torch wheel through the PyTorch CPU index. Leave that
line in place: the default CUDA build is several gigabytes and will exhaust the build.
The evaluation stack is deliberately absent — it lives in `evaluation/requirements.txt`.

---

## 3. Vercel — the frontend

**Root directory:** `app/frontend`

Framework preset: Next.js. Build and output settings are the defaults.

### Variables

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_BACKEND_URL` | your Railway URL, e.g. `https://lucify-api.up.railway.app` |

This is inlined at build time, so **changing it needs a redeploy**, not just a restart.

---

## 4. Wire the two together

The browser talks to the API directly, so the API must allow the Vercel origin:

1. Deploy the backend, copy its URL.
2. Set `NEXT_PUBLIC_BACKEND_URL` on Vercel, deploy the frontend, copy its URL.
3. Set `CORS_ORIGINS` on Railway to that URL and redeploy.

For preview deployments, `CORS_ORIGIN_REGEX` accepts a pattern such as
`https://lucify-.*\.vercel\.app`.

---

## 5. Check it

```bash
curl https://your-api.up.railway.app/health
```

Expect `status: ok`, `database: true`, `llm_configured: true` and
`realtime: upstash`. If `realtime` says `in-process`, the Upstash variables did not
arrive — progress will still work, but only within a single instance.

Then open the Vercel URL, sign in with one of your access keys, and ingest a small PDF.
Live progress proves the whole chain: browser → Vercel → Railway → Upstash → browser.

---

## Notes and limits

- **One worker.** `--workers 1` is deliberate. The ingestion worker and generation queue
  are in-process threads; a second worker would run a second copy of each and double the
  spend against the same token budget. Scale by raising the Groq tier, not the workers.
- **Voice** needs the learner's own Sarvam key, entered in the app. Nothing to configure.
- **Cold starts.** The first request loads the embedding model (~30s). Railway keeps the
  service warm; `WARM_EMBEDDER_ON_START=true` (the default) does this during startup
  rather than on the first learner's question.
- **Free tiers.** Groq caps at 8,000 tokens/minute and 200,000 per day. A day of demos
  fits comfortably; re-ingesting a large image-only slide deck does not.
