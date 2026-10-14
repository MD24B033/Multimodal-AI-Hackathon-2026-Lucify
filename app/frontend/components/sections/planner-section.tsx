"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import {
  Bell,
  CalendarDays,
  CheckCircle2,
  Clock,
  Pause,
  Play,
  RotateCcw,
  Compass,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useSession } from "@/components/session-context";
import { useTasks } from "@/components/task-center";
import { Blank, Chip, Field, Meter, Metric, Notice, Panel, SectionHead, Spinner } from "@/components/ui";
import { get } from "@/lib/api";
import type { Dashboard, StudyPlan } from "@/lib/types";

const FOCUS_PRESETS = [
  { label: "Pomodoro", focus: 25, rest: 5 },
  { label: "Deep work", focus: 50, rest: 10 },
  { label: "Quick", focus: 15, rest: 3 },
];

const DONE_KEY = "companion.planner.done";

function readDone(): Record<string, boolean> {
  try {
    return JSON.parse(window.localStorage.getItem(DONE_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function FocusTimer() {
  const [preset, setPreset] = useState(FOCUS_PRESETS[0]);
  const [remaining, setRemaining] = useState(FOCUS_PRESETS[0].focus * 60);
  const [running, setRunning] = useState(false);
  const [onBreak, setOnBreak] = useState(false);
  const [completed, setCompleted] = useState(0);
  const tick = useRef<number | null>(null);

  const reset = useCallback(
    (next = preset, breakMode = false) => {
      setRunning(false);
      setOnBreak(breakMode);
      setRemaining((breakMode ? next.rest : next.focus) * 60);
    },
    [preset],
  );

  useEffect(() => {
    if (!running) return;
    tick.current = window.setInterval(() => {
      setRemaining((value) => {
        if (value > 1) return value - 1;
        window.clearInterval(tick.current ?? undefined);
        setRunning(false);
        if (!onBreak) {
          setCompleted((c) => c + 1);
          if (typeof Notification !== "undefined" && Notification.permission === "granted") {
            new Notification("Focus block done", { body: "Take a short break." });
          }
          setOnBreak(true);
          return preset.rest * 60;
        }
        setOnBreak(false);
        return preset.focus * 60;
      });
    }, 1000);
    return () => window.clearInterval(tick.current ?? undefined);
  }, [running, onBreak, preset]);

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;
  const total = (onBreak ? preset.rest : preset.focus) * 60;

  return (
    <Panel>
      <SectionHead title="Focus timer" description="Work in blocks; the planner counts what you finish." />

      <div className="flex flex-wrap items-center gap-2">
        {FOCUS_PRESETS.map((item) => (
          <button
            key={item.label}
            type="button"
            className={clsx("btn px-2.5 py-1 text-xs", preset.label === item.label && "btn-primary")}
            onClick={() => {
              setPreset(item);
              reset(item, false);
            }}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mt-6 flex flex-col items-center">
        <motion.p
          key={`${minutes}:${seconds}`}
          initial={{ opacity: 0.75 }}
          animate={{ opacity: 1 }}
          className="display num text-6xl tabular-nums"
          style={{ color: onBreak ? "var(--mint)" : "var(--ink)" }}
        >
          {String(minutes).padStart(2, "0")}:{String(seconds).padStart(2, "0")}
        </motion.p>
        <Chip tone={onBreak ? "mint" : "iris"} className="mt-2">
          {onBreak ? "break" : "focus"}
        </Chip>

        <div className="mt-4 w-full max-w-xs">
          <Meter value={1 - remaining / total} showLabel={false} tone={onBreak ? "mint" : "iris"} />
        </div>

        <div className="mt-5 flex gap-2">
          <button type="button" className="btn btn-primary" onClick={() => setRunning((v) => !v)}>
            {running ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {running ? "Pause" : "Start"}
          </button>
          <button type="button" className="btn" onClick={() => reset(preset, onBreak)}>
            <RotateCcw className="h-4 w-4" /> Reset
          </button>
          {typeof Notification !== "undefined" && Notification.permission === "default" ? (
            <button type="button" className="btn" onClick={() => Notification.requestPermission()}>
              <Bell className="h-4 w-4" /> Alerts
            </button>
          ) : null}
        </div>

        <p className="mt-4 text-xs text-[var(--ink-faint)]">
          {completed} block{completed === 1 ? "" : "s"} finished this sitting
        </p>
      </div>
    </Panel>
  );
}

export function PlannerSection() {
  const { courses, student } = useSession();
  const { enqueue, busyFor } = useTasks();

  const [courseId, setCourseId] = useState("");
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [examDate, setExamDate] = useState("");
  const [dailyMinutes, setDailyMinutes] = useState(60);
  const [done, setDone] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [today, setToday] = useState<number | null>(null);

  useEffect(() => {
    setCourseId((current) => current || courses[0]?.id || "");
    setDone(readDone());
    setToday(Date.now());
  }, [courses]);

  const course = courses.find((item) => item.id === courseId);

  useEffect(() => {
    if (course?.exam_date) setExamDate(course.exam_date);
  }, [course?.exam_date]);

  const load = useCallback(async () => {
    if (!courseId || !student) return;
    setLoading(true);
    try {
      const [data] = await Promise.all([
        get<Dashboard>(`/api/learner/students/${student.id}/dashboard?course_id=${courseId}`),
      ]);
      setDashboard(data);
      try {
        setPlan(await get<StudyPlan>(`/api/learner/students/${student.id}/study-plan?course_id=${courseId}`));
      } catch {
        setPlan(null);
      }
    } finally {
      setLoading(false);
    }
  }, [courseId, student]);

  useEffect(() => {
    void load();
  }, [load]);

  function toggleDone(key: string) {
    setDone((current) => {
      const next = { ...current, [key]: !current[key] };
      try {
        window.localStorage.setItem(DONE_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  async function buildPlan() {
    if (!courseId || !examDate) return;
    setError(null);
    try {
      await enqueue({
        course_id: courseId,
        kind: "study_plan",
        label: `Study plan for ${course?.title ?? "course"}`,
        params: { exam_date: examDate, daily_minutes: dailyMinutes },
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start planning");
    }
  }

  const grouped = useMemo(() => {
    if (!plan) return [];
    const byDate = new Map<string, typeof plan.sessions>();
    for (const item of plan.sessions) {
      byDate.set(item.date, [...(byDate.get(item.date) ?? []), item]);
    }
    return [...byDate.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [plan]);

  const daysLeft =
    examDate && today !== null
      ? Math.max(0, Math.ceil((new Date(examDate).getTime() - today) / 86400000))
      : null;

  if (courses.length === 0) {
    return (
      <Blank
        icon={<CalendarDays className="h-5 w-5" />}
        title="No courses to plan"
        description="Create a course first, then the planner builds a schedule around your exam date."
      />
    );
  }

  return (
    <div className="fade-rise space-y-5">
      <SectionHead
        eyebrow="Planner"
        title="Plan, focus, and keep the streak"
        description="A schedule weighted by your weak topics and the forgetting curve, plus a timer for actually doing it."
        action={
          <select
            className="input h-9 w-auto py-1.5 text-xs"
            value={courseId}
            onChange={(event) => setCourseId(event.target.value)}
          >
            {courses.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        }
      />

      {error ? <Notice message={error} /> : null}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Metric
          label="Days to exam"
          value={daysLeft ?? "—"}
          tone={daysLeft !== null && daysLeft <= 7 ? "rose" : daysLeft !== null && daysLeft <= 21 ? "amber" : "neutral"}
          icon={<CalendarDays className="h-4 w-4" />}
        />
        <Metric
          label="Planned sessions"
          value={plan?.sessions.length ?? 0}
          hint={plan ? `${grouped.length} days` : "none yet"}
          icon={<Clock className="h-4 w-4" />}
        />
        <Metric
          label="Due for review"
          value={dashboard?.due_for_review ?? 0}
          tone="amber"
          icon={<RotateCcw className="h-4 w-4" />}
        />
        <Metric
          label="Mastery"
          value={`${Math.round((dashboard?.overall_mastery ?? 0) * 100)}%`}
          tone={(dashboard?.overall_mastery ?? 0) >= 0.7 ? "mint" : "amber"}
          icon={<Compass className="h-4 w-4" />}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel>
          <SectionHead title="Your schedule" />
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Exam date">
              <input
                type="date"
                className="input"
                value={examDate}
                onChange={(event) => setExamDate(event.target.value)}
              />
            </Field>
            <Field label="Minutes per day">
              <input
                type="number"
                className="input"
                min={15}
                max={480}
                value={dailyMinutes}
                onChange={(event) => setDailyMinutes(Number(event.target.value))}
              />
            </Field>
            <button
              type="button"
              className="btn btn-primary"
              disabled={!examDate || busyFor(courseId)}
              onClick={buildPlan}
            >
              {busyFor(courseId) ? <Spinner /> : <CalendarDays className="h-4 w-4" />}
              {busyFor(courseId) ? "Planning" : "Build plan"}
            </button>
          </div>

          {loading ? (
            <div className="mt-5 flex items-center gap-2 text-sm text-[var(--ink-soft)]">
              <Spinner /> Loading
            </div>
          ) : !plan ? (
            <div className="mt-5">
              <Blank
                icon={<CalendarDays className="h-5 w-5" />}
                title="No plan yet"
                description="Set an exam date and the planner weights your weakest topics first, with spaced reviews built in."
              />
            </div>
          ) : (
            <>
              {plan.rationale ? (
                <p className="rail mt-5 pl-4 text-xs leading-relaxed text-[var(--ink-soft)]">
                  {plan.rationale}
                </p>
              ) : null}
              <div className="scroll-slim mt-4 max-h-[460px] space-y-4 overflow-auto pr-1">
                {grouped.map(([date, items]) => (
                  <div key={date}>
                    <p className="eyebrow mb-2">
                      {new Date(date).toLocaleDateString(undefined, {
                        weekday: "short",
                        day: "numeric",
                        month: "short",
                      })}
                    </p>
                    <div className="space-y-1.5">
                      {items.map((item, index) => {
                        const key = `${date}-${item.topic_id}-${index}`;
                        const checked = Boolean(done[key]);
                        return (
                          <button
                            key={key}
                            type="button"
                            onClick={() => toggleDone(key)}
                            className={clsx(
                              "glass flex w-full items-center gap-2.5 p-2.5 text-left text-xs transition",
                              checked && "opacity-50",
                            )}
                          >
                            <CheckCircle2
                              className={clsx(
                                "h-4 w-4 shrink-0",
                                checked ? "text-[var(--mint)]" : "text-[var(--ink-faint)]",
                              )}
                            />
                            <Chip
                              tone={
                                item.activity === "review" ? "iris" : item.activity === "learn" ? "amber" : "neutral"
                              }
                            >
                              {item.activity}
                            </Chip>
                            <span className={clsx("min-w-0 flex-1 truncate", checked && "line-through")}>
                              {item.topic}
                            </span>
                            <span className="num shrink-0 text-[var(--ink-faint)]">{item.minutes}m</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Panel>

        <div className="space-y-4">
          <FocusTimer />

          {dashboard && dashboard.weak_topics.length > 0 ? (
            <Panel>
              <SectionHead title="Prioritise" description="Where the plan spends your time." />
              <div className="space-y-3">
                {dashboard.weak_topics.slice(0, 5).map((item) => (
                  <div key={item.topic_id}>
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <span className="truncate text-xs">{item.topic}</span>
                      <span className="num shrink-0 text-[10px] text-[var(--ink-faint)]">
                        {Math.round(item.urgency * 100)}% urgent
                      </span>
                    </div>
                    <Meter value={item.mastery} showLabel={false} />
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>
      </div>
    </div>
  );
}
