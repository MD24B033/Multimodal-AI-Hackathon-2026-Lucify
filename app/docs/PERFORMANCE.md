# Performance: where the time goes

Every number here was measured on this machine against the real corpus (225 content units, 23
topics), not estimated.

## Summary

**The database, retrieval and API layers are not the bottleneck. Two Groq free-tier limits account
for essentially all user-visible latency, and the second one is the real ceiling:**

| Limit | Value | What it costs you |
|---|---|---|
| Tokens per minute | 8,000 | Queueing delay on every call |
| **Tokens per day** | **200,000** | **A hard stop. Nothing works until it resets.** |

The per-day limit is the one that bites. Ingesting a single 73-slide deck costs roughly 150,000
tokens of vision calls — **three quarters of an entire day's budget in one operation.** Observed
directly during this build:

```
Rate limit reached ... on tokens per day (TPD):
Limit 200000, Used 199421, Requested 2342. Please try again in 12m41.616s.
```

Critically, **the response headers do not expose the daily figure** — `x-ratelimit-remaining-tokens`
reported a healthy `8000` while the day was in fact exhausted. The only signal is the 429 body. The
client now parses it and raises `GroqDailyQuotaExhausted` with a clear message, instead of backing
off blindly against a limit that will not reset for hours. When it fires during chat, retrieval
still runs and the cited sources are returned so the student can open them directly.

| Layer | Measured | Share of a slow request |
|---|---|---|
| API endpoints (courses, topics, flow map, dashboard) | 11–90 ms | negligible |
| Hybrid retrieval: embed + pgvector + FTS + RRF | 90 ms | negligible |
| Query embedding alone | 44 ms | negligible |
| Postgres queries | < 25 ms | negligible |
| **Waiting on the LLM token budget** | **seconds to minutes** | **~99%** |

## The arithmetic that explains everything

The bucket refills at `8000 / 60 = 133 tokens per second`. So the floor on any request is:

```
wait_seconds ≈ (tokens_needed - tokens_available) / 133
```

A 3,000-token request against an empty bucket waits **22 seconds** before it is even sent. That is
not model inference; it is queueing.

### The pathological case I found and fixed

A notes request was built with ~3,000 prompt tokens and `max_tokens=7000`:

```
3,000 + 7,000 = 10,000 tokens  >  8,000 tokens/minute
```

**A request larger than the per-minute budget can never be served cleanly.** It 429s, backs off,
retries, and eventually squeezes through. Measured end to end: **445 seconds for one note.**

The client now logs a warning whenever `prompt + max_tokens` exceeds the per-minute limit, because
that condition is always a bug, not bad luck.

## Fixes applied

| # | Fix | Effect |
|---|---|---|
| 1 | Reserve a realistic completion estimate (600 tokens) instead of `max_tokens / 4` | Stops over-reserving ~50% on every call |
| 2 | Cap request budgets below the per-minute limit: chat 1,500, notes 3,200 (5,500 chars of context), questions 4,000 | Removes the 429-and-retry death spiral |
| 3 | Priority lane: interactive requests pre-empt batch work | A chat turn waits at most one in-flight ingestion call, not the whole queue |
| 4 | Warm the embedding model at startup | Removes a **29-second** cold start from the first query after boot |
| 5 | Persistent LLM response cache | Repeat calls go from **1.82 s to 0.006 s** |
| 6 | Collapse progressive slide builds before vision calls | 104 slides → 73 real ones, ~30% fewer vision calls |
| 7 | Skip Docling OCR when a text layer exists; use the vision model for image-only PDFs | Avoids minutes of CPU OCR per deck |

## What is still slow, and why

**Ingestion is token-bound and cannot be made much faster on this tier.** Each slide costs roughly
1,200 tokens of vision call, so 8,000 tokens/minute allows about **6 slides per minute**. The 73-slide
deck therefore takes ~12 minutes of pure budget, regardless of CPU. Parallelism does not help: the
constraint is tokens per minute, not concurrency.

**Docling parsing is CPU-bound** on this machine (no CUDA, 8 cores). The 64-page textbook took
several minutes of layout and table analysis before any LLM call happened.

## The multi-process trap

The token bucket lives **in the process**. Running the evaluation harness beside the app means two
buckets each believing they own 8,000 tokens/minute, so together they exceed the real limit and
Groq throttles both. This was observed directly: a notes request issued while an evaluation was
running took minutes and logged `429 Too Many Requests`.

Two ways out:

1. **Run the harness when the app is idle**, or give it a smaller budget. The harness defaults to
   `--tokens-per-minute 4000` for exactly this reason.
2. **Move the bucket into Redis** so every process shares one budget. This is the genuinely correct
   fix and the strongest argument for Redis in this system — stronger than the progress streaming it
   is currently used for.

## What Redis does and does not fix

| Concern | Does Redis help? |
|---|---|
| Live ingestion progress without polling | **Yes** — pub/sub, already implemented |
| Sharing one token budget across processes | **Yes** — the right fix for the trap above, not yet implemented |
| Caching across restarts | Partly; the Postgres `llm_cache` table already does this durably |
| Making a single LLM call faster | **No.** Nothing in Redis changes the 8,000 token ceiling |

The app degrades cleanly without Redis: `realtime` reports `in-process` and progress still streams
over SSE. Redis is an upgrade, not a dependency.

## A bug this investigation uncovered

Groq returns retry delays in a compound format: `"1h46m33.599s"`. The original backoff parser
stripped non-digits, turning that into `14633.599` seconds — **it slept for four hours instead of
one hour forty-six.** A single chat request hung indefinitely because of it.

Fixed with a proper duration parser (`1h46m33.599s` → `6393.6s`, `577ms` → `0.577s`) and a hard
`max_backoff_seconds = 45` cap, so no single retry can ever stall a request for hours regardless of
what the provider reports.

## The honest conclusion

On this API tier the app is as fast as it can be for cached and non-LLM work (sub-100 ms), and
fundamentally limited by the token budget for anything that calls a model.

The highest-leverage change available is **not** a code change. It is the Groq tier:

- **200,000 tokens/day** means roughly **one slide-deck ingestion per day**, after which the tutor,
  notes and assessments all stop until reset. That is the constraint that actually breaks the
  product.
- Upgrading lifts both limits. `tokens_per_minute` in `config.py` is then the single switch that
  makes ingestion, chat, notes and assessment generation proportionally faster.

Practical advice while on the free tier: **ingest once, early in the day**, and keep the evaluation
harness for a separate day or a separate key. Ingestion and evaluation together will consume the
entire daily budget and leave nothing for the demo.
