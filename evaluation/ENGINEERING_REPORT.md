# Evaluation engineering report

An audit of Lucify's evaluation, the defects it found, the changes made, and what the
numbers do and do not support. Written against commit history on `main`; every figure
below came from a run recorded in this repository.

**Headline: the two largest problems were in the measurement, not the system.** The
reported retrieval metrics scored citations rather than retrieval, and the refusal
gate the architecture documents describe never fired once. Both are now fixed, and
both fixes move numbers for honest reasons.

---

## 1. What the baseline actually measured

The published baseline (`results/rag.json`, 12 cases: 8 answerable, 4 off-material):

| Metric | Published |
|---|---|
| Faithfulness | 65.3% |
| Answer relevancy | 91.0% |
| Context precision | 68.8% |
| Context recall | 62.5% |
| Source hit rate | 75.0% |
| MRR | 75.0% |
| Source precision@k | 50.0% |
| Correct refusal rate | 100.0% |
| False refusal rate | 0.0% |
| Latency median / p90 / max | 58,456 / 60,134 / 61,112 ms |

I reproduced the pipeline and audited each metric's implementation before changing
anything. Four findings, in order of how much they distort the picture.

### 1.1 The retrieval metrics scored citations

`harness/client.py` built `retrieved_unit_ids` from `message.citations`, so
`source_hit_rate`, `MRR`, `source_recall` and `source_precision_at_k` all measured
**which passages the model chose to cite**, not what retrieval found. A case counted
as a total retrieval miss whenever the model cited a neighbouring passage.

Measured directly against the app's retrieval path (local embeddings + Postgres, no
tokens), on the same 8 answerable cases:

| | Published (citation-based) | Measured (retrieval) |
|---|---|---|
| Hit rate | 75.0% | **87.5%** |
| MRR | 75.0% | **81.2%** |
| Locator hit rate (right page/slide) | not measured | **100%** |

Reproduce with `python run_retrieval_eval.py --dataset results/testset.json`; it costs
no tokens, and the output is in `results/retrieval_heldout.json`. The single unit-level
miss is case 6, where the ground-truth chunk ("What this book is about", page 5) ranks
below a sibling chunk from the same page — so the learner is still sent to page 5.

`source_precision_at_k` is worse than mislabelled: its denominator was the number of
cited passages (1–2), not `k` (8).

### 1.2 The judge saw the wrong context

`metrics.collect()` passed `citation["excerpt"]` to RAGAS as `retrieved_contexts`.
Faithfulness, context precision and context recall were therefore judged against the
passages the model *cited* rather than the eight it was *given*. This biases two ways
at once:

- a claim supported by a retrieved-but-uncited passage scores as unfaithful, pushing
  faithfulness down;
- a wrong answer that cites whatever it used scores as perfectly faithful.

Case 7 is the clean example. The question asks for a slide's title text; retrieval put
the ground-truth Slide 13 at **rank 1**; the model answered with Slide 27's title
("The Perceptron: Example") and cited Slide 27. RAGAS scored it **faithfulness 1.0**.
It is a wrong answer scored perfect, because the judge was shown the model's own
choice of evidence.

### 1.3 The coverage gate never fired

`answer_question` refuses when `best_score < grounding_threshold` (0.38), where
`best_score` is the top cosine similarity. On this corpus that threshold is unreachable:

| | n | range | mean |
|---|---|---|---|
| answerable | 8 | 0.591 – 0.865 | 0.793 |
| off-material | 4 | 0.728 – 0.780 | 0.755 |

Off-material questions score *higher* than the weakest answerable one. bge-small places
any deep-learning question within 0.63–0.87 of any deep-learning passage, so absolute
similarity barely orders the two classes, let alone separates them at 0.38. **Every
refusal in the published run came from the model's own `status: "unsupported"` after a
full generation.** The 100% correct-refusal rate was real, but it was the language
model's judgement, not the retrieval gate the architecture describes — and each
refusal cost a full generation call.

### 1.4 Smaller defects

- **Test-set sampling truncation.** `testset.build()` called `client.units(limit=200)`
  against an endpoint that caps a page at 200, with no pagination: generated cases could
  only ever come from the first 200 of 327 units. Fixed with `all_units()`.
- **Latency conflated work with queueing.** See §5.
- **A flawed test case.** Case 7 ("What is the title text displayed on the slide
  described in the excerpt?") has no referent — the generator leaked the artefact it
  was shown, and *any* slide title answers it. It is left in the canonical set
  unchanged, and categorised rather than deleted.

---

## 2. Development set

Tuning on the canonical 12 cases would have destroyed their value as a held-out set, so
`datasets/dev.json` holds **26 hand-authored cases** across 9 categories (17 answerable,
8 off-material, 1 ambiguous). Every case was written from a passage I read, with the
ground-truth unit id and locator verified against the database.

| category | n | | category | n |
|---|---|---|---|---|
| direct | 8 | | exact_title | 2 |
| structured | 3 | | misleading | 2 |
| paraphrase | 3 | | multi | 1 |
| off_material | 5 | | ambiguous | 1 |
| insufficient | 1 | | | |

---

## 3. Retrieval: a negative result

Hypothesis: the lexical arm of the hybrid search is dead, and reviving it will improve
retrieval. The first half is true and measurable — `websearch_to_tsquery` ANDs every
content word, so it returns **0 rows for 6 of the 8** canonical questions, and the
"hybrid" search is dense-only in practice for nearly every real question.

The second half is false. Five variants on the dev set, k=8:

| variant | unit hit | MRR | locator hit | ms/query |
|---|---|---|---|---|
| A: current (dense + websearch) | 1.000 | 0.814 | 1.000 | 21.7 |
| B: dense only | 1.000 | **0.843** | 1.000 | 16.3 |
| C: dense + OR-of-terms | 1.000 | 0.716 | 1.000 | 64.7 |
| D: dense + OR-of-terms (w=0.5) | 1.000 | 0.745 | 1.000 | 54.5 |
| E: C + locator dedupe | 0.941 | 0.701 | 1.000 | 48.4 |

The OR-of-terms lexical arm I expected to help **hurts** ranking (0.814 → 0.716) and
triples query latency. **No retrieval change was shipped.** Retrieval is at ceiling on
this dev set, which is itself a limitation: see §7.

---

## 4. The refusal gate, rebuilt on a signal that separates

If absolute similarity cannot tell the two classes apart, what can? When the corpus
holds the answer, one passage pulls away from the rest; when it does not, everything
sits at the same middling similarity. Measured on dev (17 answerable, 8 off-material),
with 95% bootstrap intervals over 4,000 resamples:

| signal | AUC | 95% interval |
|---|---|---|
| **top-1 margin** (top cosine − mean of the rest) | **0.963** | [0.868, 1.000] |
| spread (top − min) | 0.949 | [0.846, 1.000] |
| best cosine *(what the gate used)* | 0.868 | [0.699, 0.978] |
| query-term coverage | 0.853 | [0.629, 1.000] |

Threshold sweep on the margin:

| threshold | answerable answered | false refusal | off-material refused |
|---|---|---|---|
| 0.024 | 17/17 | 0.000 | 0.500 |
| **0.028** | **17/17** | **0.000** | **0.625** |
| 0.036 | 15/17 | 0.118 | 0.875 |
| 0.039 (Youden-optimal) | 15/17 | 0.118 | 1.000 |

Shipped at **0.028**: the point that costs no answerable dev case while catching five
of eight off-material questions *before any token is spent*. The Youden-optimal 0.039
would refuse 100% of off-material but at an 11.8% false-refusal rate, far outside the
≤2% target. The model's own `unsupported` verdict remains the second line of defence
for what the gate passes.

The same signal on the **held-out** canonical set, which was not used to choose the
threshold: margin AUC **0.906** against best-cosine's **0.750**. Per case at 0.028:

| margin | gate | case |
|---|---|---|
| 0.013 | refuse | off-material: reinforcement learning |
| 0.015 | refuse | off-material: Bayesian hyperparameter optimisation |
| 0.040 | pass | off-material: GANs *(model refuses it downstream)* |
| 0.040 | pass | answerable: perceptron forward propagation |
| 0.048 | pass | answerable: main focus of the book |
| 0.053 | pass | answerable: slide title text |
| 0.055 | pass | off-material: attention *(model refuses it downstream)* |
| 0.072–0.140 | pass | the remaining five answerable cases |

**8 of 8 answerable cases pass the gate — no false refusals — and 2 of 4 off-material
questions are refused before any token is spent.** The other two reach the model, which
refused both in the published run through its own `unsupported` verdict.

Measured end to end against the running app:

| question | before | after |
|---|---|---|
| "What are the gates inside an LSTM cell?" | full generation, ~57 s | **refused in 294 ms, 0 tokens** |
| "How does batch normalisation stabilise training?" | full generation, ~57 s | **refused in 241 ms, 0 tokens** |
| "Which technique sets a random half of activations to zero?" (margin 0.0305, the lowest answerable dev case) | answered | **answered, cited 45:23 and 46:04** |

---

## 5. Latency: separating work from queueing

The published 58 s median is almost entirely waiting for quota. Per-stage timings now
travel with every answer (`app/llm/timing.py`). Three consecutive questions on an
otherwise idle instance:

| ask | total | provider | shared budget wait | local bucket wait | embed | vector | lexical |
|---|---|---|---|---|---|---|---|
| 1 (cold, just after reload) | 33,388 ms | 2,737 | 117 | 0 | 71 | 25 | 3 |
| 2 (warm) | **1,106 ms** | 659 | 127 | 0 | 61 | 25 | 3 |
| 3 (budget exhausted) | 52,461 ms | 1,286 | **42,494** | **8,386** | 70 | 23 | 4 |

The same four canonical questions, published run against the run after the fix (asking
phase only, same order, same corpus):

| case | published | after |
|---|---|---|
| perceptron with no inputs | 22,239 ms | **1,470 ms** |
| activation functions | 58,456 ms | **6,083 ms** |
| the symbol rho-C | 60,134 ms | **7,361 ms** |
| 784 input neurons | 61,112 ms | 50,605 ms |

Indicative, not controlled: four cases, and the second run was interrupted (§10). The
fourth case shows the ceiling reasserting itself once the minute's budget is genuinely
spent.

Retrieval is not the bottleneck and never was: embedding, vector search and lexical
search together cost **~100 ms**. A warm answer costs **1.1 s**. The rest is the 8,000
token-per-minute free tier.

One genuine inefficiency was found and fixed: the shared Upstash budget charged each
call's *reservation* (`prompt_estimate + max_tokens`, ~4,000 tokens for a chat turn)
and never reconciled it against actual usage (~half that), unlike the local bucket
which already did. The unspent half stayed booked for the remainder of the minute.
Reservations are now refunded.

What remains is a real constraint, not an artifact: three grounded answers genuinely
exceed 8,000 tokens, so sustained throughput on the free tier is about **two to three
answers per minute**. No latency target below that is achievable without a paid quota.

---

## 6. Personalization: the calibration number was measuring the wrong thing

Published: mean calibration error 24.4% (adaptive) and 25.6% (control). Per learner:

| arm | persona | true mastery | estimated | calibration error |
|---|---|---|---|---|
| adaptive | novice | 0.259 → 0.283 | 0.250 → 0.277 | **0.006** |
| adaptive | advanced | 0.769 → 0.777 | 0.250 → 0.295 | **0.482** |
| control | novice | 0.242 → 0.262 | 0.250 → 0.296 | 0.034 |
| control | advanced | 0.763 → 0.772 | 0.250 → 0.295 | 0.477 |

The aggregate is dominated by the advanced learners, and the cause is not a modelling
error. `calibration_error` compared two quantities over two different topic sets:

- **estimate** — mean `p_known` over *every subtopic in the course*, most of which no
  question ever touched and which therefore sit at the cold-start prior of 0.25;
- **truth** — the simulated learner's ability over *the topics a session reached*.

Six questions cannot produce evidence for 37 topics. An advanced learner is genuinely
strong everywhere, the model has evidence nowhere except the handful it asked about, and
the difference was being recorded as a calibration failure. The novice learners score
0.006 and 0.034 precisely because their true ability happens to sit near the prior.

The harness now also reports `calibration_error_on_evidence`, restricted to topics with
`attempts > 0`, together with `evidence_coverage` so the figure can be read in context —
a well-calibrated estimate over 3 of 37 topics is not the same claim as one over all 37.
The original whole-course number is kept unchanged for continuity.

This is a measurement fix. It does **not** establish that the learner model is well
calibrated; it establishes that the published number did not measure calibration. The
adaptive advantage (0.2 points of true mastery, 4 learners, 12 questions per arm)
remains far too small a sample to support any claim, and nothing here changes that.

---

## 7. Limitations

- **The dev set is at ceiling for retrieval** (100% hit at k=8 for every variant), so it
  cannot discriminate between retrieval strategies. Its value is in the refusal signal,
  where it separates cleanly. A harder set — distractor-heavy, long-context,
  cross-source — is needed before any reranking work can be justified.
- **Small samples throughout.** 8 answerable and 4 off-material canonical cases; 17 and
  8 on dev; 4 simulated learners. The bootstrap interval on the gate's AUC
  [0.868, 1.000] is the honest width. No conclusion here deserves a third significant
  figure.
- **The gate threshold is tuned on 25 cases.** 0.028 sits just below the lowest
  answerable dev margin (0.030), which is a thin buffer. Expect to revisit it on a
  larger set, and note that a corpus change moves the distribution.
- **One judge family.** The RAGAS judge (`gpt-oss-120b`) also generates the answers it
  judges. Self-preference bias is possible and unmeasured.
- **The ambiguous category has one case.** Not enough to claim anything about
  clarification behaviour.

---

## 8. The blocked experiment

**The held-out generation benchmark has not been re-run to completion.** The Groq free
tier's daily allowance ran out part-way through: the app began returning *"Daily token
quota exhausted: 198,715 of 200,000 tokens"* from case 7 onward. Cases 1–6 produced
genuine answers; 7–12 are quota artifacts, and RAGAS could not score at all.

Nothing partial was written to `results_v2/`, and no number in this report comes from
those six cases. The baseline in §1 remains the only complete generation run, and the
comparison it belongs to is outstanding.

To finish it, once the daily quota resets:

```bash
cd evaluation
export GROQ_API_KEY=... ACCESS_KEY=...
python run_eval.py --course "Deep Learning Foundations" \
    --testset results/testset.json --out results_v2
```

Expected from the changes already verified, and worth checking against:

- **source_hit_rate 0.75 → 0.875** and **MRR 0.75 → 0.812** — already measured
  token-free on the held-out set, so these should reproduce exactly.
- **false_refusal_rate stays 0.0** — all 8 answerable cases clear the gate by margin.
- **correct_refusal_rate stays 1.0**, with 2 of 4 now refused pre-generation.
- **faithfulness should move, and may move down** — it is now judged against the eight
  passages the generator saw rather than the one or two it cited. That is a fairer and
  harder test, and case 7's undeserved 1.0 should fall. A lower number here would be a
  more honest one; it is not a regression.

Run everything else first — the token-free benchmark and both test suites — since they
need no quota and catch most regressions.

## 9. Reproducing

```bash
# token-free: retrieval and the refusal signal, any number of times
cd evaluation
python run_retrieval_eval.py --course "Deep Learning Foundations" --dataset datasets/dev.json

# the full held-out benchmark (spends Groq quota)
export GROQ_API_KEY=...
export ACCESS_KEY=...            # one of the app's ACCESS_KEYS
python run_eval.py --course "Deep Learning Foundations" --testset results/testset.json

# tests
cd app/backend && python -m pytest tests/ -q
cd evaluation   && python -m pytest tests/ -q
```

---

## 10. Changes made

| File | Change |
|---|---|
| `app/retrieval/hybrid.py` | `coverage_margin()`; `RetrievalResult.margin` |
| `app/retrieval/grounding.py` | gate refuses on margin as well as absolute score |
| `app/config.py` | `grounding_margin = 0.028`, with its provenance in a comment |
| `app/api/serializers.py` | expose `retrieved_unit_ids` |
| `app/api/routes/chat.py` | return `retrieval` (score, margin, context) and `timing` |
| `app/llm/timing.py` | **new** — per-request stage timings |
| `app/llm/groq_client.py` | stage timing; refund unspent reservations |
| `app/upstash.py` | `SharedTokenBudget.refund()` |
| `evaluation/harness/client.py` | retrieved vs cited; `all_units()` pagination |
| `evaluation/harness/metrics.py` | retrieval/locator/citation as three metrics; RAGAS judged on real context; per-metric `n` |
| `evaluation/harness/personalization.py` | `calibration_on_evidence()` |
| `evaluation/harness/testset.py` | `category` field; sample the whole corpus |
| `evaluation/datasets/dev.json` | **new** — 26 hand-authored cases |
| `evaluation/run_retrieval_eval.py` | **new** — token-free benchmark |
| `app/backend/tests/`, `evaluation/tests/` | **new** — 35 tests |
