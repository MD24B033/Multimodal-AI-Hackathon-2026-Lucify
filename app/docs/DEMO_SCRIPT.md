# Demo video script

Target length 6–8 minutes. The grading rubric rewards grounding accuracy, assessment quality,
personalization, UX and honest evaluation, so the script spends time in proportion to those weights.

Record at 1920×1080. Have the backend and frontend running, the demo course already ingested, and a
**second, empty course** ready so the ingestion workflow can be shown live without waiting.

---

## 0:00 — The problem (30s)

> "Course material is scattered across lecture videos, textbooks and slides, and a general chatbot
> will happily answer from its own knowledge instead of yours. This is a study companion that only
> answers from material you upload, cites the exact page, slide or timestamp, and models what you
> personally already know."

Show the Library tab with the Deep Learning Foundations course populated.

## 0:30 — Multimodal ingestion (1:15)

On the empty course, upload the MIT 6.S191 Lecture 3 slide deck. While the progress bar moves:

> "No manual preprocessing. These particular slides are image-only PDFs with no text layer at all,
> so OCR would only recover words. Instead every slide is read by a vision model that transcribes
> the text *and* explains the diagram. Consecutive slides from the same animation build are
> collapsed first, so we pay for seventy-three slides instead of a hundred and four."

Switch to the already-ingested course. Point at the stats row, then the Topics and concepts panel.

> "Topics, subtopics, concepts and prerequisite edges are all derived from the material, and every
> content unit is tagged to them."

Show the **course flow map** and click a node.

## 1:45 — Source grounding (1:45) — *the most heavily weighted section*

Tutor tab. Ask something the material covers:

> **"What problem does the sigmoid neuron solve that the perceptron doesn't?"**

Point at the **grounded** badge, then click a citation chip — the PDF opens at that exact page.

Ask something answered by a *diagram* on a slide:

> **"Explain the structure of a convolutional neural network."**

> "That came from a slide with no text layer. It is retrievable because the vision model described
> the diagram at ingestion time."

Now ask something the course does **not** cover:

> **"How does a transformer's multi-head attention work?"**

Point at the **not covered** badge.

> "Retrieval similarity fell below the coverage threshold, so the system refused *before* calling
> the generation model. The model never got the chance to improvise. And where general knowledge
> would be useful, it goes in a separate panel, clearly marked as outside your material."

Switch the language selector to Hinglish, re-ask a covered question, and show the citations are
unchanged. Optionally click the microphone and ask by voice.

## 3:30 — Adaptive assessment (1:30)

Assess tab. Generate a 5-question quiz, mixed MCQ and short answer, verification on.

> "Questions are written only from retrieved excerpts, then checked by a second model from a
> different family — Qwen checking GPT-OSS — which answers independently and rejects the question if
> it disagrees or if more than one option is defensible."

Point at the generation stats: generated / rejected as duplicate / failed verification.

> "Novelty is enforced against the entire question bank, by normalised fingerprint and by embedding
> similarity, so repeat quizzes don't repeat questions."

Answer deliberately: some right, some wrong, one blank. Submit.

Walk through the report: score, **mastery change per topic**, likely misconceptions, recommended
next actions, and per-answer feedback with citations.

> "Feedback cites the material, so a wrong answer tells you what the source actually says and lets
> you open it."

## 5:00 — Learner model (1:00)

Progress tab.

> "Mastery is Bayesian knowledge tracing, per topic, where slip and guess depend on question
> difficulty — an easy question answered correctly is weak evidence, because the guess rate is high.
> It decays with a forgetting curve between sessions, and failing a topic propagates partial doubt
> back onto its prerequisites."

Show mastery bars, "what to study next" with prerequisite blocking, the retention forecast, the
exam-date study plan, and generate flashcards for a weak topic.

Go back to Tutor and ask about a topic now known to be weak.

> "Same question, different explanation depth, because the tutor is given the learner's mastery on
> the topics the question touches."

## 6:00 — Evaluation (1:00)

Evaluation tab. Open a completed RAG run.

> "RAGAS faithfulness, answer relevancy, context precision and recall, on a test set built from this
> course's own material so every answerable question has a known ground-truth location. Plus two
> things RAGAS doesn't measure: whether we retrieved the *right page*, and whether off-material
> questions were correctly refused."

Scroll the per-case list showing expected source vs retrieved.

Open the personalization run.

> "Simulated learners with a hidden true ability, run across multiple sessions against a
> non-adaptive control arm. Mastery gain alone would prove nothing, since simulated learners improve
> by construction — the number that matters is the adaptive arm minus the control."

Point at adaptive advantage, calibration error and question repetition rate.

## 7:00 — Architecture close (45s)

> "FastAPI and Postgres with pgvector, hybrid retrieval fusing vector and full-text search with
> reciprocal rank fusion, Docling for layout-aware parsing, Whisper for timestamped transcription,
> and local embeddings. All generation runs on a Groq free tier capped at eight thousand tokens a
> minute, so there's a shared token bucket, a persistent response cache and resumable ingestion —
> without those, ingesting a real textbook simply fails."

End on the course flow map.

---

## Things to have ready

- Both servers running, embedding model already warm (ask one question before recording).
- A completed RAG eval run and a completed personalization run, so nothing is generated live.
- A second empty course for the upload demo.
- Browser zoom at 110% so text is readable in the recording.
