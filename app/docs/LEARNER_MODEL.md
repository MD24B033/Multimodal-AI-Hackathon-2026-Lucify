# Learner model

The requirement is per-topic mastery that updates after every quiz and conversation, and sensible
handling of a new student with no history.

Three estimators run together, because they answer different questions:

| Estimator | Question it answers | Where it is used |
|---|---|---|
| Bayesian Knowledge Tracing | *Does this student know this topic?* | mastery bars, weak-topic selection, tutor depth |
| IRT ability (`θ`) | *How hard should the next question be?* | adaptive difficulty targeting |
| SM-2 + forgetting curve | *When should they see this again?* | review scheduling, study plan, flashcards |

## Bayesian Knowledge Tracing

State per `(student, topic)` is a single probability `p_known`, updated on evidence.

On an observation, the posterior is the standard BKT update:

```
correct:    P(known | correct)   = p(1-slip) / [ p(1-slip) + (1-p)·guess ]
incorrect:  P(known | incorrect) = p·slip    / [ p·slip    + (1-p)(1-guess) ]
```

then a learning transition `p' = posterior + (1 - posterior)·learn`.

Parameters are `learn = 0.18`, and **slip and guess vary by question difficulty**:

| Difficulty | slip | guess |
|---|---|---|
| easy | 0.06 | 0.25 |
| medium | 0.10 | 0.18 |
| hard | 0.18 | 0.12 |

This is the part that makes the estimate honest. Getting an easy question right is weak evidence of
mastery, because the guess rate is high; getting a hard question wrong is weak evidence of ignorance,
because the slip rate is high. A model with fixed parameters would over-reward easy wins.

**Partial credit** (short answers score continuously in [0,1]) is handled by interpolating between
the correct and incorrect posteriors rather than thresholding, so a half-right answer moves the
estimate half as far.

## Forgetting

`p_known` decays between sessions before any new evidence is applied:

```
p_decayed = p_known · (1 - forget)^days_elapsed      forget = 0.02/day
```

So mastery measured three weeks ago is not treated as mastery today. Every update reads the decayed
prior, not the stored value.

## Prerequisite and hierarchy propagation

Topics form a tree (major → subtopic) with a separate prerequisite graph. Evidence propagates along
both, with asymmetry that reflects how learning actually works:

- **To the parent topic**: 35% of the change, in both directions. Doing well on "Backpropagation"
  is partial evidence about "Training Neural Networks".
- **To prerequisites**: 25% of the change, **only when negative**. Failing a topic is evidence that
  its prerequisites may be shaky. Succeeding at an advanced topic is *not* strong evidence you have
  mastered its prerequisites — you may have memorised a procedure — so positive evidence does not
  propagate backwards.

## IRT ability estimation

BKT gives a probability; it does not say which difficulty to serve next. A 2PL IRT model estimates
a per-topic ability `θ` by maximum a posteriori over the student's response history:

```
P(correct | θ, b, a) = 1 / (1 + exp(-a(θ - b)))
```

Difficulty labels map to `b`: easy `-1.0`, medium `0.0`, hard `+1.0`. `θ` is fitted by Newton
iteration against a `N(0, 1)` prior, with the standard error taken from the Fisher information. The
next question's target difficulty is read off `θ`: below `-0.5` serve easy, above `+0.6` serve hard,
otherwise medium.

The prior is what makes this work for a new student: with no responses, `θ = 0` and the student gets
medium questions, which is also the most informative place to start.

## Spaced repetition

Every graded response also updates an SM-2 schedule per topic: the continuous score is mapped to a
0–5 quality, the ease factor is adjusted and clamped to [1.3, 2.8], and the next interval is set
(1 day, then 6 days, then `interval × ease`). Review urgency combines mastery with predicted recall:

```
recall  = exp(-days_since_review / stability)
urgency = 1 - p_known · (0.4 + 0.6 · recall)
```

A topic that was once strong but has not been seen in a month ranks above a topic that is weak but
was reviewed yesterday. This is what orders both "what to study next" and the study plan.

## Cold start

A student with no history is not a special case in the maths — the BKT prior is `p_known = 0.25`
and the IRT prior is `θ = 0` — but it is a special case in the product:

- **Diagnostic quiz**: `POST /api/learner/students/{id}/diagnostic` generates a non-adaptive,
  medium-difficulty quiz spread across topics that actually have content, which is the
  highest-information first measurement.
- **Conversation as evidence**: chat turns feed the model too. The tutor's answer is tagged with the
  topics its retrieved units belong to, and the turn registers as a weak positive signal, or a
  negative one when the student's message shows confusion ("I don't understand", "explain again",
  "samajh nahi"). Weight is 0.06–0.12, roughly a fifth of a quiz answer, because a conversation is
  much weaker evidence than a graded response.
- **Untouched topics** still appear in the dashboard at the prior, marked with zero attempts, so the
  student can see what has not been measured rather than seeing a misleading 0%.

## How the tutor uses it

Before answering, the tutor is given the student's mastery on exactly the topics the question
touches:

```
Student mastery on the topics this question touches:
- Gradient Descent: 31% (weak, 4 attempts)
- Backpropagation: 78% (strong, 6 attempts)
```

with an instruction to build from fundamentals when mastery is low and to be concise and go deeper
when it is high. This is the mechanism behind "responsiveness of the tutor to student state".

## Honest limitations

- BKT parameters are hand-set, not fitted per topic from data. Fitting them needs more learners than
  a hackathon produces; the difficulty-conditioned slip/guess values are a principled substitute,
  not a replacement.
- IRT difficulty `b` comes from the generator's own `easy/medium/hard` label rather than from
  observed response data. With real traffic, `b` should be re-estimated from item statistics.
- Propagation weights (0.35, 0.25) are chosen by judgement, not tuned.
- Chat-derived evidence uses keyword matching to detect confusion, which is crude and will miss
  anything phrased unusually.
