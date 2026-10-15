"use client";

import { Activity, Brain, Flame, Gauge, Target, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useSession } from "@/components/session-context";
import { Blank, Chip, Meter, Metric, Panel, SectionHead, Spinner } from "@/components/ui";
import { get } from "@/lib/api";
import type { Course, Dashboard } from "@/lib/types";

const CHART_AXIS = { fontSize: 11, fill: "var(--ink-faint)" };

const TOOLTIP_STYLE = {
  background: "var(--bg-1)",
  border: "1px solid var(--edge-strong)",
  borderRadius: 12,
  fontSize: 12,
  color: "var(--ink)",
};

function masteryColor(value: number): string {
  if (value >= 0.75) return "var(--mint)";
  if (value >= 0.45) return "var(--amber)";
  return "var(--rose)";
}

export function AnalyticsSection() {
  const { courses, student } = useSession();
  const [courseId, setCourseId] = useState<string>("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [forecast, setForecast] = useState<{ day: number; projected_mastery: number | null }[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setCourseId((current) => current || courses[0]?.id || "");
  }, [courses]);

  const load = useCallback(async () => {
    if (!courseId || !student) return;
    setLoading(true);
    try {
      const [data, forecastData] = await Promise.all([
        get<Dashboard>(`/api/learner/students/${student.id}/dashboard?course_id=${courseId}`),
        get<{ day: number; projected_mastery: number | null }[]>(
          `/api/learner/students/${student.id}/retention-forecast?course_id=${courseId}`,
        ),
      ]);
      setDashboard(data);
      setForecast(forecastData);
    } catch {
      setDashboard(null);
    } finally {
      setLoading(false);
    }
  }, [courseId, student]);

  useEffect(() => {
    void load();
  }, [load]);

  const course = courses.find((item) => item.id === courseId) as Course | undefined;

  if (courses.length === 0) {
    return (
      <Blank
        icon={<Gauge className="h-5 w-5" />}
        title="No data yet"
        description="Create a course and study it — your mastery, learning curve and weak spots appear here."
      />
    );
  }

  const weakChart =
    dashboard?.weak_topics.slice(0, 7).map((item) => ({
      topic: item.topic.length > 20 ? `${item.topic.slice(0, 19)}…` : item.topic,
      mastery: Number((item.mastery * 100).toFixed(1)),
      raw: item.mastery,
    })) ?? [];

  const tracked = dashboard?.mastery.filter((item) => item.attempts > 0) ?? [];

  return (
    <div className="fade-rise space-y-5">
      <SectionHead
        eyebrow="Insights"
        title="Analytics"
        description="How your understanding is actually moving, per course."
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

      {loading ? (
        <div className="flex items-center gap-2.5 py-10 text-sm text-[var(--ink-soft)]">
          <Spinner /> Crunching your history
        </div>
      ) : !dashboard ? (
        <Blank title="Nothing to show yet" description="Study this course and analytics will fill in." />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Metric
              label="Overall mastery"
              value={`${Math.round(dashboard.overall_mastery * 100)}%`}
              tone={
                dashboard.overall_mastery >= 0.7
                  ? "mint"
                  : dashboard.overall_mastery >= 0.45
                    ? "amber"
                    : "rose"
              }
              hint={`${dashboard.topics_tracked} topics practised`}
              icon={<Target className="h-4 w-4" />}
            />
            <Metric
              label="Learning events"
              value={dashboard.interactions}
              hint="quizzes and conversations"
              icon={<Activity className="h-4 w-4" />}
            />
            <Metric
              label="Due for review"
              value={dashboard.due_for_review}
              tone="amber"
              hint="spaced repetition"
              icon={<Flame className="h-4 w-4" />}
            />
            <Metric
              label="Knowledge base"
              value={course?.unit_count ?? 0}
              hint={`${course?.topic_count ?? 0} topics`}
              icon={<Brain className="h-4 w-4" />}
            />
          </div>

          {dashboard.interactions === 0 ? (
            <Panel>
              <Blank
                icon={<Target className="h-5 w-5" />}
                title="No learner history yet"
                description="Open this course and take a quiz or talk to the tutor. Mastery starts from a prior and updates from every interaction."
              />
            </Panel>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Panel>
              <SectionHead
                title="Weakest topics"
                description="Ranked by urgency: low mastery combined with predicted forgetting."
              />
              {weakChart.length === 0 ? (
                <p className="text-sm text-[var(--ink-soft)]">Nothing weak yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={weakChart} layout="vertical" margin={{ left: 6, right: 14 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--edge)" horizontal={false} />
                    <XAxis type="number" domain={[0, 100]} tick={CHART_AXIS} stroke="var(--edge)" />
                    <YAxis
                      type="category"
                      dataKey="topic"
                      width={128}
                      tick={CHART_AXIS}
                      stroke="var(--edge)"
                    />
                    <Tooltip
                      cursor={{ fill: "var(--glass)" }}
                      contentStyle={TOOLTIP_STYLE}
                      formatter={(value) => [`${Number(value ?? 0)}%`, "mastery"]}
                    />
                    <Bar dataKey="mastery" radius={[0, 6, 6, 0]}>
                      {weakChart.map((entry) => (
                        <Cell key={entry.topic} fill={masteryColor(entry.raw)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Panel>

            <Panel>
              <SectionHead
                title="Learning curve"
                description="Mastery estimate after each day of activity in this course."
              />
              {dashboard.mastery_history.length > 1 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={dashboard.mastery_history}>
                    <defs>
                      <linearGradient id="curve" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="var(--iris)" />
                        <stop offset="100%" stopColor="var(--cyan)" />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--edge)" />
                    <XAxis dataKey="date" tick={CHART_AXIS} stroke="var(--edge)" />
                    <YAxis domain={[0, 1]} tick={CHART_AXIS} stroke="var(--edge)" />
                    <Tooltip contentStyle={TOOLTIP_STYLE} />
                    <Line
                      type="monotone"
                      dataKey="mastery"
                      stroke="url(#curve)"
                      strokeWidth={2.5}
                      // A day backed by graded answers is stronger evidence than one
                      // inferred from conversation, so it is drawn as a filled point.
                      dot={(props) => {
                        const graded = Number(props.payload?.graded_events ?? 0) > 0;
                        return (
                          <circle
                            key={props.key}
                            cx={props.cx}
                            cy={props.cy}
                            r={graded ? 5 : 3}
                            fill={graded ? "var(--mint)" : "var(--bg-1)"}
                            stroke="var(--iris)"
                            strokeWidth={2}
                          />
                        );
                      }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <Blank
                  icon={<TrendingUp className="h-5 w-5" />}
                  title="Not enough history"
                  description="The curve appears once you have activity on more than one day in this course."
                />
              )}

              {dashboard.mastery_history.length > 1 ? (
                <p className="mt-3 text-[11px] leading-relaxed text-[var(--ink-faint)]">
                  {(dashboard.graded_interactions ?? 0) > 0 ? (
                    <>
                      Filled points are days with graded answers
                      {" "}({dashboard.graded_interactions} so far). Hollow points moved on
                      conversation alone, which is a weaker signal.
                    </>
                  ) : (
                    <>
                      No graded answers in this course yet, so every point here was inferred
                      from conversation. Take an assessment and the curve starts resting on
                      evidence instead.
                    </>
                  )}
                </p>
              ) : null}
            </Panel>
          </div>

          {forecast.some((point) => point.projected_mastery) ? (
            <Panel>
              <SectionHead
                title="Retention forecast"
                description="Projected mastery if you stop practising now — the cost of doing nothing."
              />
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={forecast}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--edge)" />
                  <XAxis dataKey="day" tick={CHART_AXIS} stroke="var(--edge)" />
                  <YAxis domain={[0, 1]} tick={CHART_AXIS} stroke="var(--edge)" />
                  <Tooltip contentStyle={TOOLTIP_STYLE} />
                  <Line
                    type="monotone"
                    dataKey="projected_mastery"
                    stroke="var(--amber)"
                    strokeWidth={2.5}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </Panel>
          ) : null}

          {tracked.length > 0 ? (
            <Panel>
              <SectionHead
                title="Topic mastery"
                description="Bayesian knowledge tracing, updated after every answer and conversation."
              />
              <div className="scroll-slim grid max-h-80 gap-3 overflow-auto pr-1 md:grid-cols-2">
                {tracked
                  .slice()
                  .sort((a, b) => a.mastery - b.mastery)
                  .map((item) => (
                    <div key={item.topic_id}>
                      <div className="mb-1.5 flex items-center justify-between gap-2">
                        <span className="truncate text-sm">{item.topic}</span>
                        <span className="num shrink-0 text-xs text-[var(--ink-faint)]">
                          {item.correct}/{item.attempts} · θ {item.theta.toFixed(2)}
                        </span>
                      </div>
                      <Meter value={item.mastery} />
                    </div>
                  ))}
              </div>
            </Panel>
          ) : null}

          {dashboard.next_up.length > 0 ? (
            <Panel>
              <SectionHead
                title="What to study next"
                description="Ordered by prerequisites, then urgency."
              />
              <ol className="space-y-3">
                {dashboard.next_up.map((item, index) => (
                  <li key={item.topic_id} className="flex items-start gap-3">
                    <span className="num mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border bg-[var(--glass)] text-xs font-semibold text-[var(--iris)]">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{item.topic}</span>
                        <Chip tone={item.mastery < 0.45 ? "rose" : item.mastery < 0.75 ? "amber" : "mint"}>
                          {Math.round(item.mastery * 100)}%
                        </Chip>
                      </div>
                      {item.blocked_by.length > 0 ? (
                        <p className="mt-1 text-xs text-[var(--amber)]">
                          Build up {item.blocked_by.join(", ")} first
                        </p>
                      ) : null}
                    </div>
                  </li>
                ))}
              </ol>
            </Panel>
          ) : null}
        </>
      )}
    </div>
  );
}
