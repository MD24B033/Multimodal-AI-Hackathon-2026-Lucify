"use client";

import {
  BadgeCheck,
  Brain,
  CheckCircle2,
  FilePlus2,
  Lightbulb,
  Target,
  TrendingDown,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { SessionRail, type SessionRow } from "@/components/session-rail";
import { useSession } from "@/components/session-context";
import { CitationList } from "@/components/source-viewer";
import { useTasks } from "@/components/task-center";
import { RichLine, RichText } from "@/components/rich-text";
import { Blank, Chip, Field, Meter, Metric, Notice, Panel, SectionHead, Spinner } from "@/components/ui";
import { get, post } from "@/lib/api";
import type { Assessment, AssessmentReport, Citation, Topic } from "@/lib/types";

const QUESTION_TYPES = [
  { value: "mcq", label: "Multiple choice" },
  { value: "short_answer", label: "Short answer" },
  { value: "numerical", label: "Numerical" },
];

type Phase = "build" | "take" | "review";

/** What the list endpoint returns: the assessment without its questions, plus the
 *  score and length that make a history rail worth looking at. */
type AssessmentSummary = Assessment & {
  score_percent?: number | null;
  question_count?: number;
};

const KIND_LABEL: Record<string, string> = {
  quiz: "Practice quiz",
  mock_exam: "Mock exam",
  diagnostic: "Diagnostic",
};

export function CourseAssess({
  courseId,
  unitCount,
  onOpenCitation,
}: {
  courseId: string;
  unitCount: number;
  onOpenCitation: (citation: Citation) => void;
}) {
  const { student } = useSession();
  const [phase, setPhase] = useState<Phase>("build");
  const [history, setHistory] = useState<AssessmentSummary[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [report, setReport] = useState<AssessmentReport | null>(null);
  const [responses, setResponses] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { enqueue, tasks, busyFor } = useTasks();
  const claimedTask = useRef<string | null>(null);
  const running = busyFor(courseId);


  const [kind, setKind] = useState("quiz");
  const [count, setCount] = useState(5);
  const [qtypes, setQtypes] = useState<string[]>(["mcq", "short_answer"]);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [adaptive, setAdaptive] = useState(true);
  const [verify, setVerify] = useState(true);

  const loadHistory = useCallback(async () => {
    if (!student) return;
    try {
      setHistory(
        await get<AssessmentSummary[]>(
          `/api/assessments?course_id=${courseId}&student_id=${student.id}`,
        ),
      );
    } catch {
      /* the rail is not worth an error banner over */
    }
  }, [courseId, student]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const loadTopics = useCallback(async () => {
    const list = await get<Topic[]>(`/api/courses/${courseId}/topics`);
    setTopics(list.filter((topic) => topic.kind === "subtopic"));
  }, [courseId]);

  useEffect(() => {
    void loadTopics();
  }, [loadTopics]);

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      // Queued rather than awaited: writing and verifying questions takes long enough
      // that nobody should have to sit on this page while it happens.
      await enqueue({
        course_id: courseId,
        kind: "assessment",
        label: `${KIND_LABEL[kind] ?? "Assessment"} · ${count} questions`,
        params: {
          kind,
          num_questions: count,
          qtypes,
          topic_ids: selectedTopics.length > 0 ? selectedTopics : null,
          adaptive,
          verify,
        },
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start the assessment");
    } finally {
      setBusy(false);
    }
  }

  const openAssessment = useCallback(async (assessmentId: string) => {
    const full = await get<Assessment>(`/api/assessments/${assessmentId}`);
    setAssessment(full);
    setResponses({});

    // A graded attempt reopens as its report, an unfinished one as the paper itself.
    if (full.status === "graded") {
      try {
        setReport(await get<AssessmentReport>(`/api/assessments/${assessmentId}/report`));
        setPhase("review");
        return;
      } catch {
        /* no report stored; fall through and show the questions */
      }
    }
    setReport(null);
    setPhase("take");
  }, []);

  // A finished assessment opens itself, whichever page it finished on.
  useEffect(() => {
    const done = tasks.find(
      (task) =>
        task.kind === "assessment" &&
        task.status === "succeeded" &&
        task.course_id === courseId &&
        typeof task.result?.assessment_id === "string",
    );
    if (!done || done.id === claimedTask.current) return;
    claimedTask.current = done.id;
    void loadHistory();
    void openAssessment(done.result.assessment_id as string).catch(() => undefined);
  }, [tasks, courseId, openAssessment]);

  async function submit() {
    if (!assessment) return;
    setBusy(true);
    setError(null);
    try {
      const result = await post<{ assessment: Assessment; report: AssessmentReport }>(
        `/api/assessments/${assessment.id}/submit`,
        { responses },
      );
      setAssessment(result.assessment);
      setReport(result.report);
      setPhase("review");
      void loadHistory();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit");
    } finally {
      setBusy(false);
    }
  }

  const rows: SessionRow[] = history.map((item) => ({
    id: item.id,
    title: item.title,
    updated_at: item.submitted_at ?? item.created_at,
    subtitle:
      item.status === "graded"
        ? `${item.question_count ?? 0} questions`
        : item.status === "in_progress"
          ? "not finished"
          : item.status,
    badge: typeof item.score_percent === "number" ? `${Math.round(item.score_percent)}%` : undefined,
  }));

  return (
    <div className="grid gap-4 lg:grid-cols-[auto_minmax(0,1fr)]">
      <SessionRail
        sessions={rows}
        activeId={assessment?.id ?? null}
        onSelect={(id) => void openAssessment(id).catch(() => undefined)}
        onCreate={() => {
          setAssessment(null);
          setReport(null);
          setPhase("build");
        }}
        storageKey="companion.rail.assessments"
        label="Attempts"
        newLabel="New assessment"
        newIcon={FilePlus2}
        emptyNote="Your past assessments appear here."
      />

      <div className="min-w-0 space-y-5">
      {error ? <Notice message={error} /> : null}

      {phase === "build" ? (
        <Panel>
          <SectionHead
            eyebrow="Assess"
            title="Build an assessment"
            description="Questions are written from your material, tagged to a topic and source, and checked by a second model before they reach you."
          />

          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Type">
              <select className="input" value={kind} onChange={(event) => setKind(event.target.value)}>
                <option value="quiz">Practice quiz</option>
                <option value="mock_exam">Mock exam</option>
                <option value="diagnostic">Diagnostic</option>
              </select>
            </Field>

            <Field label={`Questions — ${count}`}>
              <input
                type="range"
                min={1}
                max={12}
                value={count}
                className="w-full accent-[var(--iris)]"
                onChange={(event) => setCount(Number(event.target.value))}
              />
            </Field>

            <Field label="Formats">
              <div className="flex flex-wrap gap-1.5">
                {QUESTION_TYPES.map((type) => {
                  const on = qtypes.includes(type.value);
                  return (
                    <button
                      key={type.value}
                      type="button"
                      className={`btn px-2.5 py-1 text-xs ${on ? "btn-primary" : ""}`}
                      onClick={() =>
                        setQtypes((current) =>
                          on ? current.filter((item) => item !== type.value) : [...current, type.value],
                        )
                      }
                    >
                      {type.label}
                    </button>
                  );
                })}
              </div>
            </Field>

            <Field label="Options">
              <div className="flex flex-col gap-2">
                <label className="flex items-center gap-2 text-sm text-[var(--ink-soft)]">
                  <input
                    type="checkbox"
                    className="accent-[var(--iris)]"
                    checked={adaptive}
                    onChange={(event) => setAdaptive(event.target.checked)}
                  />
                  Target my weak topics and difficulty
                </label>
                <label className="flex items-center gap-2 text-sm text-[var(--ink-soft)]">
                  <input
                    type="checkbox"
                    className="accent-[var(--iris)]"
                    checked={verify}
                    onChange={(event) => setVerify(event.target.checked)}
                  />
                  Cross-model verification
                </label>
              </div>
            </Field>
          </div>

          <div className="mt-5">
            <label className="label">
              Scope {selectedTopics.length > 0 ? `— ${selectedTopics.length} selected` : "— whole course"}
            </label>
            {topics.length === 0 ? (
              <p className="text-sm text-[var(--ink-soft)]">Ingest material to pick topics.</p>
            ) : (
              <div className="scroll-slim flex max-h-28 flex-wrap gap-1.5 overflow-auto">
                {topics.map((topic) => {
                  const on = selectedTopics.includes(topic.id);
                  return (
                    <button
                      key={topic.id}
                      type="button"
                      className={`btn px-2 py-1 text-xs ${on ? "btn-primary" : ""}`}
                      onClick={() =>
                        setSelectedTopics((current) =>
                          on ? current.filter((item) => item !== topic.id) : [...current, topic.id],
                        )
                      }
                    >
                      {topic.name}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <button
            type="button"
            className="btn btn-primary mt-5"
            disabled={busy || running || qtypes.length === 0 || unitCount === 0}
            onClick={generate}
          >
            {busy || running ? <Spinner /> : <Target className="h-4 w-4" />}
            {running ? "Writing and verifying" : "Generate"}
          </button>
          {unitCount === 0 ? (
            <p className="mt-2 text-xs text-[var(--ink-faint)]">Add course material first.</p>
          ) : running ? (
            <p className="mt-2 text-xs text-[var(--ink-soft)]">
              This runs in the background. Move to another page if you like — it carries on and
              tells you when the paper is ready.
            </p>
          ) : null}
        </Panel>
      ) : null}

      {phase === "take" && assessment?.items ? (
        <>
          {assessment.generation ? (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Metric label="Questions" value={assessment.generation.generated} />
              <Metric
                label="Duplicates rejected"
                value={assessment.generation.rejected_duplicate}
                hint="novelty filter"
              />
              <Metric
                label="Failed verification"
                value={assessment.generation.rejected_verification}
                hint="second model disagreed"
                tone="amber"
              />
              <Metric label="Topics" value={assessment.generation.topics_covered.length} />
            </div>
          ) : null}

          <Panel>
            <SectionHead title={assessment.title} description="Blank answers score zero." />
            <div className="space-y-7">
              {assessment.items.map((item, index) => (
                <div key={item.id} className="border-b pb-6 last:border-0 last:pb-0">
                  <div className="mb-2.5 flex flex-wrap items-center gap-2">
                    <span className="num text-sm font-semibold">Question {index + 1}</span>
                    <Chip tone="iris">{item.question.difficulty}</Chip>
                    <Chip>{item.question.qtype.replace("_", " ")}</Chip>
                    {item.question.verified ? (
                      <Chip tone="mint">
                        <BadgeCheck className="h-3 w-3" /> verified
                      </Chip>
                    ) : null}
                  </div>

                  <RichText className="mb-3.5 text-sm leading-relaxed">{item.question.stem}</RichText>

                  {item.question.qtype === "mcq" && item.question.options ? (
                    <div className="space-y-2">
                      {item.question.options.map((option) => {
                        const chosen = responses[item.question.id] === option;
                        return (
                          <label
                            key={option}
                            className={`flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 text-sm transition ${
                              chosen
                                ? "border-[var(--iris)] bg-[var(--iris-soft)]"
                                : "hover:bg-[var(--glass-strong)]"
                            }`}
                          >
                            <input
                              type="radio"
                              className="mt-0.5 accent-[var(--iris)]"
                              name={item.question.id}
                              checked={chosen}
                              onChange={() =>
                                setResponses((current) => ({ ...current, [item.question.id]: option }))
                              }
                            />
                            <RichLine>{option}</RichLine>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <textarea
                      className="input resize-y"
                      rows={item.question.qtype === "numerical" ? 1 : 3}
                      placeholder={
                        item.question.qtype === "numerical"
                          ? `Your answer${item.question.answer_units ? ` (${item.question.answer_units})` : ""}`
                          : "Your answer"
                      }
                      value={responses[item.question.id] ?? ""}
                      onChange={(event) =>
                        setResponses((current) => ({
                          ...current,
                          [item.question.id]: event.target.value,
                        }))
                      }
                    />
                  )}

                  <CitationList citations={item.question.citations} onOpen={onOpenCitation} />
                </div>
              ))}
            </div>

            <div className="mt-6 flex gap-2">
              <button type="button" className="btn btn-primary" disabled={busy} onClick={submit}>
                {busy ? <Spinner /> : <CheckCircle2 className="h-4 w-4" />} Submit
              </button>
              <button type="button" className="btn" onClick={() => setPhase("build")}>
                Discard
              </button>
            </div>
          </Panel>
        </>
      ) : null}

      {phase === "review" && report && assessment?.items ? (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Metric
              label="Score"
              value={`${report.score_percent.toFixed(0)}%`}
              tone={report.score_percent >= 70 ? "mint" : report.score_percent >= 40 ? "amber" : "rose"}
            />
            <Metric label="Weak topics" value={report.weak_topics.length} tone="amber" />
            <Metric label="Strong topics" value={report.strong_topics.length} tone="mint" />
            <Metric label="Misconceptions" value={report.misconceptions.length} />
          </div>

          <Panel>
            <SectionHead title="Your report" />
            <p className="text-sm leading-relaxed">{report.summary}</p>

            {report.mastery_delta.length > 0 ? (
              <div className="mt-5">
                <p className="eyebrow mb-2.5">Mastery change</p>
                <div className="space-y-2.5">
                  {report.mastery_delta.map((entry) => (
                    <div key={entry.topic_id} className="flex items-center gap-3">
                      <span className="w-44 shrink-0 truncate text-sm">{entry.topic}</span>
                      <div className="flex-1">
                        <Meter value={entry.after} />
                      </div>
                      <span
                        className={`num flex w-16 shrink-0 items-center justify-end gap-1 text-xs ${
                          entry.delta >= 0 ? "text-[var(--mint)]" : "text-[var(--rose)]"
                        }`}
                      >
                        {entry.delta >= 0 ? (
                          <TrendingUp className="h-3 w-3" />
                        ) : (
                          <TrendingDown className="h-3 w-3" />
                        )}
                        {entry.delta >= 0 ? "+" : ""}
                        {(entry.delta * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {report.misconceptions.length > 0 ? (
              <div className="mt-5">
                <p className="eyebrow mb-2.5">Likely misconceptions</p>
                <div className="space-y-2.5">
                  {report.misconceptions.map((item, index) => (
                    <div
                      key={index}
                      className="rounded-xl border p-3.5"
                      style={{
                        borderColor: "var(--amber)",
                        background: "color-mix(in srgb, var(--amber) 10%, transparent)",
                      }}
                    >
                      <p className="flex items-center gap-1.5 text-sm font-medium">
                        <Brain className="h-3.5 w-3.5" /> {item.misconception}
                      </p>
                      <p className="mt-1 text-xs text-[var(--ink-soft)]">{item.evidence}</p>
                      <p className="mt-1.5 text-xs">{item.correction}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {report.recommendations.length > 0 ? (
              <div className="mt-5">
                <p className="eyebrow mb-2.5">What to do next</p>
                <ul className="space-y-2">
                  {report.recommendations.map((item, index) => (
                    <li key={index} className="flex gap-2.5 text-sm">
                      <Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--iris)]" />
                      <span>
                        <strong>{item.action}</strong>
                        <span className="text-[var(--ink-soft)]"> — {item.reason}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Panel>

          <Panel>
            <SectionHead
              title="Answer by answer"
              description="Every piece of feedback cites the material it came from."
            />
            <div className="space-y-6">
              {assessment.items.map((item, index) => (
                <div key={item.id} className="border-b pb-5 last:border-0 last:pb-0">
                  <div className="mb-2 flex items-center gap-2">
                    {item.is_correct ? (
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-[var(--mint)]" />
                    ) : (
                      <XCircle className="h-4 w-4 shrink-0 text-[var(--rose)]" />
                    )}
                    <span className="num text-sm font-medium">Question {index + 1}</span>
                    <Chip tone={item.is_correct ? "mint" : "rose"}>
                      {((item.score ?? 0) * 100).toFixed(0)}%
                    </Chip>
                  </div>
                  <RichText className="mb-2.5 text-sm">{item.question.stem}</RichText>
                  <div className="space-y-1 text-xs text-[var(--ink-soft)]">
                    <p>
                      <span className="text-[var(--ink-faint)]">Your answer: </span>
                      {item.response || <em>blank</em>}
                    </p>
                    <p>
                      <span className="text-[var(--ink-faint)]">Expected: </span>
                      {item.question.answer_key}
                    </p>
                  </div>
                  {item.feedback ? (
                    <p className="glass mt-2.5 p-3 text-sm leading-relaxed">{item.feedback}</p>
                  ) : null}
                  {item.misconception ? (
                    <p className="mt-2 text-xs text-[var(--amber)]">
                      Misconception: {item.misconception}
                    </p>
                  ) : null}
                  <CitationList citations={item.feedback_citations ?? []} onOpen={onOpenCitation} />
                </div>
              ))}
            </div>

            <button type="button" className="btn btn-primary mt-6" onClick={() => setPhase("build")}>
              Build another
            </button>
          </Panel>
        </>
      ) : null}

      {phase === "build" && unitCount === 0 ? (
        <Blank
          icon={<Target className="h-5 w-5" />}
          title="Nothing to assess yet"
          description="Add material to this course and questions will be generated from it."
        />
      ) : null}
      </div>
    </div>
  );
}
