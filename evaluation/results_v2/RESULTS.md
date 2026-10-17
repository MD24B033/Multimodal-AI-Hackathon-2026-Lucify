# Evaluation results
Course **Deep Learning Foundations** — 327 content units, 37 topics, 3 sources.
Generated 2026-10-15 23:14 UTC by the standalone harness, driving the running app over its public HTTP API.
App models: generation `openai/gpt-oss-120b`, vision `qwen/qwen3.8-27b`, verifier `qwen/qwen3.8-27b`. Harness judge: `openai/gpt-oss-120b`. Embeddings `BAAI/bge-small-en-v1.5` (local).
Methodology is in [METHODOLOGY.md](../METHODOLOGY.md).
> **1 of 12 cases never reached the model** ({'provider_unavailable': 1}). They are excluded from every metric below, so the denominators are smaller than the test set. Treat this run as incomplete.
## Retrieval and generation
12 test cases: 7 answerable with known source locations, 4 off-material.
### RAGAS

| Metric | Score |
|---|---|
| Faithfulness | 95.6% |
| Answer relevancy | 91.5% |
| Context precision | 90.2% |
| Context recall | 100.0% |

### Source-location accuracy

| Metric | Score |
|---|---|
| Source hit rate | 85.7% |
| Mean reciprocal rank | 78.6% |
| Source recall | 85.7% |
| Source precision@k | 10.7% |

### Refusal behaviour

| Metric | Score |
|---|---|
| Correct refusal rate | 100.0% |
| False refusal rate | 0.0% |
| Refusal F1 | 100.0% |

### Answer latency

| Metric | Score |
|---|---|
| median ms | 2044 ms |
| p90 ms | 56539 ms |
| max ms | 57130 ms |
The harness and the app share one free-tier key, so each answer waits in the token bucket behind the harness's own judge calls. These are queueing figures, not the latency a single user sees — see METHODOLOGY.md.

### Cases the system got wrong

- **What is the main focus of the book and what will readers be able to do after completing it?**
  - expected source: Neural Networks and Deep Learning (Nielsen) — Chapters 1-2 — Page 5
  - status: `grounded`