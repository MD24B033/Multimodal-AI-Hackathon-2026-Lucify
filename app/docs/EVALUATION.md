# Evaluation

Two evaluations run against the system, both on the team's own course material: a retrieval and
generation evaluation using RAGAS, and a personalization evaluation using simulated learners.

A run writes its numbers to `evaluation/results/` as `rag.json`, `personalization.json` and a
generated `RESULTS.md`. This document is the methodology.

## Results

Latest run, 2026-10-15, against the **Deep Learning Foundations** course (327 units, 37 topics,
3 sources). Full report: [../../evaluation/results/RESULTS.md](../../evaluation/results/RESULTS.md).

| RAGAS | | Retrieval | | Refusal | |
|---|---|---|---|---|---|
| Faithfulness | 96.4% | Source hit rate | 85.7% | Correct refusal rate | 100% |
| Answer relevancy | 89.6% | Mean reciprocal rank | 78.6% | False refusal rate | 0% |
| Context precision | 90.4% | Locator hit rate | 100% | Refusal F1 | 100% |
| Context recall | 100% | Citation hit rate | 71.4% | | |

**Read these against three things.**

1. **One case never reached the model** (a transient provider error). It is declared under
   `failed_cases` and excluded from every metric, so the RAGAS and retrieval figures rest on 7
   answerable cases, not 8. A run with failures is reported as incomplete rather than quietly
   scored.
2. **They are not comparable with the 2026-10-14 baseline**, kept as `rag_baseline_2026-10-14.json`.
   That run judged faithfulness, context precision and context recall against the one or two
   passages the model *cited*; this one judges them against the eight it was *given*. The old
   measurement marked a claim unfaithful whenever its support sat in a retrieved-but-uncited
   passage, and marked a wrong answer faithful whenever it cited whatever it used. The jump from
   65.3% to 96.4% is mostly that correction, not the system improving overnight.
3. **Retrieval is reported at three levels now**, because they fail for different reasons: whether
   the exact chunk reached the context (85.7%), whether any chunk from the right page or slide did
   (100%), and whether the model then pointed the learner at it (71.4%).

`source_precision_at_k` reads 10.7% because it is now computed over the whole eight-passage context
rather than over the one or two citations. One relevant passage in eight is 12.5%, which is the
ceiling for a single-answer question; the figure is kept for completeness rather than as a target.

Personalization, adaptive against a non-adaptive control with everything else identical:

| Arm | True mastery gain | Estimated gain | Calibration error | Repetition |
|---|---|---|---|---|
| adaptive | 1.6% | 3.6% | 24.4% | 0.0% |
| control | 1.5% | 4.5% | 25.6% | 0.0% |

The adaptive arm gains 11.6% more true mastery than the control on twelve questions per arm —
indicative of direction, not a confidence-interval-bearing result. The calibration figure is
discussed in [../../evaluation/ENGINEERING_REPORT.md](../../evaluation/ENGINEERING_REPORT.md):
most of it is the model having no evidence for topics no question reached, not the model being
wrong where it does.

### Latency

| | |
|---|---|
| A single grounded answer, quota free | **~1.1–1.5 s** |
| Median across a back-to-back benchmark run | 56.3 s |

Both are true and they measure different things. One learner asking one question waits about a
second; twelve questions asked back to back exceed 8,000 tokens a minute and queue behind the free
tier. An off-material question is refused in ~250 ms without calling a model at all.

## Why these metrics

The track asks for faithfulness, answer relevancy, context precision and context recall from a
standard framework, on a test set with known source locations and off-material queries. RAGAS covers
the first four. It does **not** cover two things the track grades directly:

- whether the citation points at the *right* page, slide or timestamp;
- whether off-material questions are correctly refused.

So the harness reports RAGAS metrics alongside its own retrieval-location and refusal metrics. Both
are in the same run and the same report.

## Test set construction

`evaluation/harness/testset.py` builds the set from the ingested corpus, which is what makes ground-truth
source locations knowable rather than guessed.

**Answerable cases.** A content unit is sampled, and the model is asked to write a question that
*this excerpt alone* fully answers, plus a reference answer drawn only from it. The unit it came
from is recorded as the ground-truth location. The prompt forbids mentioning the document, page or
slide, so questions test the subject matter rather than the artefact.

**Off-material cases.** The course title, description and source titles are shown to the model,
which writes questions that are plausibly adjacent to the subject but not answerable from it. Near
misses are deliberate: refusing "what is the boiling point of nitrogen" in a deep-learning course is
easy, while refusing a question about a related technique the course never covers is the real test.

Generation is seeded, so a run can be repeated.

The obvious objection is that an LLM-generated test set inherits the generator's blind spots. It
does. The mitigation is that ground truth for *retrieval* is not model-generated — the unit the
question was written from is recorded directly — so the retrieval and refusal metrics do not depend
on the generator being right. Only the RAGAS reference answers do.

## Metrics

### From RAGAS

| Metric | What it measures |
|---|---|
| `faithfulness` | Fraction of claims in the answer that are entailed by the retrieved context |
| `answer_relevancy` | How well the answer addresses the question asked |
| `context_precision` | Whether relevant chunks rank above irrelevant ones, against the reference |
| `context_recall` | How much of the reference answer is covered by the retrieved context |

RAGAS is wired to Groq through its OpenAI-compatible endpoint with `LangchainLLMWrapper`, and to the
local sentence-transformers model for embeddings, so judging costs no extra embedding quota.

### Retrieval-location metrics

Computed directly, because RAGAS has no notion of "page 14 of this PDF":

| Metric | Definition |
|---|---|
| `source_hit_rate` | Fraction of answerable cases where the ground-truth unit appeared in the retrieved set |
| `mean_reciprocal_rank` | Mean of `1/rank` of the first ground-truth unit |
| `source_precision_at_k` | Fraction of retrieved units that were ground truth |
| `source_recall` | Fraction of ground-truth units retrieved |

`source_precision_at_k` is expected to be low and that is not a defect: each case has exactly one
ground-truth unit while retrieval returns eight, so the ceiling is 1/8 = 12.5%. It is reported for
completeness; `source_hit_rate` and MRR are the meaningful numbers.

### Refusal metrics

| Metric | Definition |
|---|---|
| `correct_refusal_rate` | Off-material questions refused or flagged unsupported |
| `false_refusal_rate` | Answerable questions wrongly refused |
| `refusal_f1` | Harmonic mean of refusal precision and recall |

These two rates trade off against each other through `grounding_threshold`, so both are always
reported. A system that refuses everything scores 100% on the first and is useless.

## Personalization evaluation

`evaluation/harness/personalization.py` runs synthetic learners through multiple study sessions.

Each learner has a **hidden true ability** per topic, drawn from a persona:

| Persona | Mean ability | Spread | Learning rate |
|---|---|---|---|
| novice | -1.0 | 0.5 | 0.42 |
| intermediate | 0.0 | 0.7 | 0.32 |
| advanced | +1.0 | 0.5 | 0.22 |
| uneven | 0.0 | 1.5 | 0.35 |

A session runs the real pipeline end to end: generate an assessment, answer each question with
probability `P(correct) = IRT(θ_true, b_question)`, grade, update the learner model, then increase
true ability on the topics studied. The system never sees `θ_true`; it only sees right and wrong
answers, exactly as with a real student.

**Control arm.** Every configuration also runs with `adaptive=False`, which selects topics at random
and ignores the learner's `θ` when choosing difficulty. Everything else is identical. Reporting
mastery gain without this comparison would say nothing — learners improve in the simulation by
construction, so the only meaningful number is adaptive gain *minus* control gain.

Reported per arm:

- `mean_true_mastery_gain` — change in hidden ability, the real outcome
- `mean_estimated_mastery_gain` — change in what the system believes
- `mean_calibration_error` — `|estimated − true|` at the end, i.e. is the learner model honest
- `question_repetition_rate` — repeated questions as a fraction of all questions served

Simulated learners are MCQ-only so grading is deterministic and costs no tokens; with short answers
each graded response would need an LLM call, and a multi-learner multi-session run would not fit in
the rate limit. This biases the run towards recognition rather than recall, and is a stated
limitation rather than a hidden one.

## Reproducing

The harness is a separate process that drives a running instance over its public HTTP API, so it
cannot shortcut retrieval. Start the app, then:

```bash
cd evaluation
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...        # the judge calls Groq directly
export ACCESS_KEY=...              # one of the app's ACCESS_KEYS
python run_eval.py --course "Deep Learning Foundations" --answerable 8 --off-material 4
```

Add `--testset results/testset.json` to reuse a saved test set for a like-for-like comparison, and
set `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` so the harness shares the app's token
budget instead of competing with it. `evaluation/README.md` lists every flag.

Each run writes `results/rag.json`, `results/personalization.json` and a generated `RESULTS.md`
holding every per-case score, so a reported aggregate can be traced back to the cases behind it.
The app also persists runs in `eval_runs` and cases in `eval_cases`.

## Threats to validity

1. The test set is model-generated, so it shares the generator's blind spots. Retrieval ground truth
   is not affected; RAGAS reference answers are.
2. The judge model (`gpt-oss-120b`) also generates the answers being judged. Self-preference bias is
   possible. The verifier in the assessment path uses a different family (Qwen) for exactly this
   reason; the RAGAS judge does not, because no third family is available on this key.
3. Simulated learners follow an IRT response model, which is also the model the system uses for
   difficulty targeting. The adaptive arm is therefore matched to the simulation's own assumptions,
   which flatters it. The control arm is the guard against reading too much into the absolute gain.
4. Sample sizes are small — a dozen questions and a handful of learners — because of the rate limit.
   Treat the numbers as indicative, not as confidence-interval-bearing results.
