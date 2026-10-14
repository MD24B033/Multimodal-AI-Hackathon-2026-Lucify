# Evaluation harness

A standalone benchmark for the Study Companion. It is **not** part of the app: it runs as its own
process and drives a running instance through its public HTTP API, exactly as a real client would.

That separation is deliberate. The harness cannot reach inside the app to shortcut retrieval, so a
good score means the deployed system is good, not that the test was generous.

```
run_eval.py  ──HTTP──►  POST /api/chat/sessions/{id}/ask
                        POST /api/assessments
                        GET  /api/courses/{id}/units      (ground-truth source locations)
                        GET  /api/learner/.../dashboard   (mastery readings)
```

## Setup

```bash
cd evaluation
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...
```

## Running

Start the app first, then:

```bash
python run_eval.py --course "Deep Learning Foundations"
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--app URL` | point at a different instance (default `http://localhost:8000`) |
| `--tokens-per-minute N` | harness budget. Keep it **below** the app's so the app stays responsive |
| `--answerable N` / `--off-material N` | test set size |
| `--sessions N` / `--questions N` | simulated-learner run size |
| `--testset path.json` | reuse a saved test set for a like-for-like comparison |
| `--skip-ragas` | retrieval and refusal metrics only, no judge calls |
| `--skip-rag` / `--skip-personalization` | run one half |

## A warning about rate limits

The app and the harness each hold their **own** token bucket. On a shared free tier they will
collectively exceed the provider's limit and both get throttled. Either run the harness when the app
is idle, or give it a smaller `--tokens-per-minute` so the app keeps priority. `--tokens-per-minute`
defaults to 4000 for that reason.

## Output

Written to `results/`:

| File | Contents |
|---|---|
| `RESULTS.md` | the readable report |
| `rag.json` | every test case with its answer, retrieved sources and per-case scores |
| `personalization.json` | per-learner trajectories for both arms |
| `testset.json` | the generated test set, reusable with `--testset` |
