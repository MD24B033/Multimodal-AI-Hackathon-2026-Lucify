# Evaluation results
Course **Deep Learning Foundations** — 327 content units, 37 topics, 3 sources.
Generated 2026-10-14 18:26 UTC by the standalone harness, driving the running app over its public HTTP API.
App models: generation `openai/gpt-oss-120b`, vision `qwen/qwen3.8-27b`, verifier `qwen/qwen3.8-27b`. Harness judge: `openai/gpt-oss-120b`. Embeddings `BAAI/bge-small-en-v1.5` (local).
Methodology is in [METHODOLOGY.md](../METHODOLOGY.md).
## Retrieval and generation
12 test cases: 8 answerable with known source locations, 4 off-material.
### RAGAS

| Metric | Score |
|---|---|
| Faithfulness | 65.3% |
| Answer relevancy | 91.0% |
| Context precision | 68.8% |
| Context recall | 62.5% |

### Source-location accuracy

| Metric | Score |
|---|---|
| Source hit rate | 75.0% |
| Mean reciprocal rank | 75.0% |
| Source recall | 75.0% |
| Source precision@k | 50.0% |

### Refusal behaviour

| Metric | Score |
|---|---|
| Correct refusal rate | 100.0% |
| False refusal rate | 0.0% |
| Refusal F1 | 100.0% |

### Answer latency

| Metric | Score |
|---|---|
| median ms | 58456 ms |
| p90 ms | 60134 ms |
| max ms | 61112 ms |

The harness and the app share one free-tier key, so each answer waits in the token bucket behind the harness's own judge calls. These are queueing figures, not the latency a single user sees — see METHODOLOGY.md.

### Cases the system got wrong

- **What is the main focus of the book and what will readers be able to do after completing it?**
  - expected source: Neural Networks and Deep Learning (Nielsen) — Chapters 1-2 — Page 5
  - status: `grounded`
- **What is the title text displayed on the slide described in the excerpt?**
  - expected source: MIT 6.S191 Lecture 1 — Intro to Deep Learning — Slide 13
  - status: `grounded`
## Personalization
| Arm | True mastery gain | Estimated gain | Calibration error | Question repetition | Questions |
|---|---|---|---|---|---|
| adaptive | 1.6% | 3.6% | 24.4% | 0.0% | 12 |
| control | 1.5% | 4.5% | 25.6% | 0.0% | 12 |
**Adaptive advantage: 0.2% additional true mastery gain over the non-adaptive control arm, 11.6% relative.**
### True mastery gain by persona

| Persona | Gain |
|---|---|
| novice | 2.5% |
| advanced | 0.8% |