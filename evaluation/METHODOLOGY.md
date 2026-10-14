# Evaluation methodology

## Why the harness is separate from the app

The app and the benchmark are different programs with different jobs. Keeping them apart buys three
things:

1. **It tests the real surface.** The harness can only reach the app through the same HTTP endpoints
   a browser uses. It cannot import the retrieval module and call it directly, so it cannot
   accidentally bypass the coverage gate, the citation validation or the rate limiter. A good score
   means the deployed system is good.
2. **It can point anywhere.** `--app https://staging.example.com` evaluates a deployed instance with
   no code change.
3. **It keeps benchmark cost out of the product.** The judge model, RAGAS and its LangChain
   dependencies live in the harness's own virtualenv. The app does not ship them.

The one thing that genuinely has to stay in the app is the ground truth for *retrieval*: the harness
reads `GET /api/courses/{id}/units`, which returns each unit with its page, slide or timestamp. That
is a read-only endpoint the app needs anyway.

## What is measured

### RAGAS metrics

Standard definitions, computed by RAGAS with Groq as the judge and local
`BAAI/bge-small-en-v1.5` embeddings.

| Metric | Question it answers |
|---|---|
| Faithfulness | Are the claims in the answer entailed by the retrieved context? |
| Answer relevancy | Does the answer address the question asked? |
| Context precision | Do relevant chunks rank above irrelevant ones, against the reference? |
| Context recall | How much of the reference answer is covered by the retrieved context? |

`ResponseRelevancy` runs with `strictness=1`. The default of 3 asks the provider for three
completions in one call (`n=3`), which Groq rejects with `'n' : number must be at most 1`.

### Source-location accuracy

RAGAS has no notion of "page 14 of this PDF", but the track grades citation accuracy directly, so
these are computed here:

| Metric | Definition |
|---|---|
| `source_hit_rate` | Fraction of answerable cases where the ground-truth unit was retrieved |
| `mean_reciprocal_rank` | Mean `1/rank` of the first ground-truth unit |
| `source_recall` | Fraction of ground-truth units retrieved |
| `source_precision_at_k` | Fraction of retrieved units that were ground truth |

`source_precision_at_k` is **expected to be low** and that is not a defect: each case has one
ground-truth unit while retrieval returns eight, so the ceiling is 1/8 = 12.5%. It is reported for
completeness. `source_hit_rate` and MRR are the meaningful numbers.

### Refusal behaviour

| Metric | Definition |
|---|---|
| `correct_refusal_rate` | Off-material questions refused or flagged unsupported |
| `false_refusal_rate` | Answerable questions wrongly refused |
| `refusal_f1` | Harmonic mean of refusal precision and recall |

Both rates are always reported together, because they trade off through the app's
`grounding_threshold`. A system that refuses everything scores 100% on the first and is useless.

### Latency

Median, p90 and max answer latency, taken from the app's own `latency_ms`. Useful only when the
harness is the sole consumer of the token budget — see the warning below.

## Test set construction

**Answerable cases.** A content unit is sampled from the app, and the judge writes a question that
*this excerpt alone* fully answers, plus a reference answer drawn only from it. The unit it came
from is recorded as ground truth. The prompt forbids mentioning the document, page or slide, so
questions test the subject, not the artefact.

**Off-material cases.** The judge is shown the course title, description and source titles, and
writes questions that are plausibly adjacent but not answerable. Near misses are deliberate:
refusing "what is the boiling point of nitrogen" in a deep-learning course is trivial; refusing a
question about a related technique the course never covers is the real test.

The set is saved to `results/testset.json` and can be replayed with `--testset` for a like-for-like
comparison across code changes.

The obvious objection is that an LLM-generated test set inherits the generator's blind spots. It
does. The mitigation is that ground truth for *retrieval* is not model-generated — the unit the
question was written from is recorded directly — so the retrieval and refusal metrics do not depend
on the judge being right. Only the RAGAS reference answers do.

## Personalization evaluation

Simulated learners with a **hidden true ability** per topic, drawn from a persona:

| Persona | Mean ability | Spread | Learning rate |
|---|---|---|---|
| novice | -1.0 | 0.5 | 0.42 |
| intermediate | 0.0 | 0.7 | 0.32 |
| advanced | +1.0 | 0.5 | 0.22 |

Each session runs the real pipeline over HTTP: create an assessment, answer each question with
probability `P(correct) = IRT(θ_true, b_question)`, submit, read the dashboard. The app never sees
`θ_true`; it sees only right and wrong answers, exactly as with a real student.

**The control arm is the point.** Every configuration also runs with `adaptive=false`, which picks
topics at random and ignores the learner's ability when choosing difficulty. Everything else is
identical. Reporting mastery gain alone would prove nothing, because simulated learners improve by
construction. The number that matters is **adaptive gain minus control gain**.

Reported per arm: true mastery gain, estimated mastery gain, calibration error
(`|estimated − true|`, i.e. is the learner model honest), and question repetition rate.

Simulated learners use MCQ only, so grading is deterministic and costs no judge tokens. With short
answers every response would need an LLM call and a multi-learner run would not fit in the rate
limit. This biases the run towards recognition over recall, and is stated rather than hidden.

## Rate limits: read this before trusting a latency number

The app and the harness each hold their **own** token bucket. On a shared free tier they will
collectively exceed the provider's real limit and both get throttled, producing 429s and inflated
latencies for both.

Either run the harness while the app is otherwise idle, or keep `--tokens-per-minute` below the
app's configured limit. It defaults to 4000 against the app's 8000 for this reason.

Any latency figure collected while something else was using the key is a worst case, not a
steady-state measurement.

## Threats to validity

1. The test set is judge-generated and shares the judge's blind spots. Retrieval ground truth is
   unaffected; RAGAS reference answers are not.
2. The judge model and the app's generation model are both `openai/gpt-oss-120b` on the only key
   available, so self-preference bias is possible. The app's *assessment verifier* deliberately uses
   a different family (Qwen); the RAGAS judge cannot, because no third family is on this key. Pass
   `--judge-model` if you have another.
3. Simulated learners follow an IRT response model, which is also the model the app uses for
   difficulty targeting. The adaptive arm is therefore matched to the simulation's own assumptions,
   which flatters it. The control arm is the guard against over-reading the absolute gain.
4. Sample sizes are small — around a dozen questions and a handful of learners — because of the rate
   limit. Treat the numbers as indicative, not as confidence-interval-bearing results.
