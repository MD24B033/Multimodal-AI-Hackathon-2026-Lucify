"use client";

import { motion } from "motion/react";
import {
  ArrowRight,
  BookOpen,
  CircleDot,
  Flame,
  NotebookPen,
  Target,
  TrendingUp,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { FlowMap } from "@/components/flow-map";
import { Blank, Chip, Meter, Metric, Panel, SectionHead, Spinner } from "@/components/ui";
import { get } from "@/lib/api";
import type { Course, Dashboard, FlowMap as FlowMapData, Topic } from "@/lib/types";

export function CourseOverview({
  course,
  studentId,
  topics,
  onGoTo,
}: {
  course: Course;
  studentId: string;
  topics: Topic[];
  onGoTo: (tab: "learn" | "assess" | "notes" | "material") => void;
}) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [flow, setFlow] = useState<FlowMapData | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [data, flowMap] = await Promise.all([
        get<Dashboard>(`/api/learner/students/${studentId}/dashboard?course_id=${course.id}`),
        get<FlowMapData>(`/api/courses/${course.id}/flow-map?student_id=${studentId}`),
      ]);
      setDashboard(data);
      setFlow(flowMap);
    } finally {
      setLoading(false);
    }
  }, [course.id, studentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center gap-2.5 py-14 text-sm text-[var(--ink-soft)]">
        <Spinner /> Reading your progress
      </div>
    );
  }

  const tracked = dashboard?.mastery.filter((item) => item.attempts > 0) ?? [];
  const subtopics = dashboard?.mastery.filter((item) => item.kind === "subtopic") ?? [];
  const covered = subtopics.filter((item) => item.attempts > 0).length;
  const coverage = subtopics.length > 0 ? covered / subtopics.length : 0;
  const majors = topics.filter((topic) => topic.kind === "major");

  const suggestion =
    dashboard && dashboard.interactions === 0
      ? {
          label: "Start with a diagnostic",
          body: "Take a short quiz so the tutor learns where you already are.",
          action: "assess" as const,
          cta: "Take a quiz",
        }
      : dashboard && dashboard.weak_topics.length > 0
        ? {
            label: `Shore up ${dashboard.weak_topics[0].topic}`,
            body: "Your weakest topic by urgency. Ask the tutor about it, then test yourself.",
            action: "learn" as const,
            cta: "Ask the tutor",
          }
        : {
            label: "Keep the streak going",
            body: "Nothing is urgently weak. Try a harder quiz or make revision notes.",
            action: "assess" as const,
            cta: "Challenge me",
          };

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Metric
          label="Course covered"
          value={`${Math.round(coverage * 100)}%`}
          hint={`${covered} of ${subtopics.length} subtopics touched`}
          tone={coverage >= 0.6 ? "mint" : coverage >= 0.25 ? "amber" : "neutral"}
          icon={<CircleDot className="h-4 w-4" />}
        />
        <Metric
          label="Mastery"
          value={`${Math.round((dashboard?.overall_mastery ?? 0) * 100)}%`}
          tone={
            (dashboard?.overall_mastery ?? 0) >= 0.7
              ? "mint"
              : (dashboard?.overall_mastery ?? 0) >= 0.45
                ? "amber"
                : "rose"
          }
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <Metric
          label="Due for review"
          value={dashboard?.due_for_review ?? 0}
          tone="amber"
          hint="spaced repetition"
          icon={<Flame className="h-4 w-4" />}
        />
        <Metric
          label="Knowledge base"
          value={course.unit_count}
          hint={`${course.topic_count} topics · ${course.source_count} sources`}
          icon={<BookOpen className="h-4 w-4" />}
        />
      </div>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        <Panel raised className="relative overflow-hidden">
          <div className="pointer-events-none absolute -right-12 -top-16 h-40 w-40 rounded-full bg-[var(--iris)] opacity-25 blur-3xl" />
          <p className="eyebrow relative mb-2">Suggested next step</p>
          <h3 className="display relative text-xl">{suggestion.label}</h3>
          <p className="relative mt-1.5 max-w-xl text-sm text-[var(--ink-soft)]">{suggestion.body}</p>
          <div className="relative mt-4 flex flex-wrap gap-2">
            <button type="button" className="btn btn-primary" onClick={() => onGoTo(suggestion.action)}>
              {suggestion.cta} <ArrowRight className="h-4 w-4" />
            </button>
            <button type="button" className="btn" onClick={() => onGoTo("notes")}>
              <NotebookPen className="h-4 w-4" /> Make notes
            </button>
          </div>
        </Panel>
      </motion.div>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Panel className="min-w-0">
          <SectionHead title="Course flow" description="Prerequisites, coloured by how well you know each area." />
          {flow ? <FlowMap data={flow} /> : <Spinner />}
        </Panel>

        <div className="space-y-4">
          <Panel>
            <SectionHead title="Weak topics" description="Where your attention pays off most." />
            {!dashboard || dashboard.weak_topics.length === 0 ? (
              <Blank
                icon={<Target className="h-5 w-5" />}
                title="Nothing flagged yet"
                description="Take a quiz and weak areas surface here."
              />
            ) : (
              <div className="space-y-3">
                {dashboard.weak_topics.slice(0, 5).map((item) => (
                  <div key={item.topic_id}>
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <span className="truncate text-sm">{item.topic}</span>
                      <span className="num shrink-0 text-xs text-[var(--ink-faint)]">
                        {item.attempts > 0 ? `${item.correct}/${item.attempts}` : "untested"}
                      </span>
                    </div>
                    <Meter value={item.mastery} />
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {tracked.length > 0 ? (
            <Panel>
              <SectionHead title="Strongest" />
              <div className="flex flex-wrap gap-1.5">
                {tracked
                  .slice()
                  .sort((a, b) => b.mastery - a.mastery)
                  .slice(0, 6)
                  .map((item) => (
                    <Chip key={item.topic_id} tone="mint">
                      {item.topic} · {Math.round(item.mastery * 100)}%
                    </Chip>
                  ))}
              </div>
            </Panel>
          ) : null}
        </div>
      </div>

      <Panel>
        <SectionHead title="Topic tree" description="Everything this course covers, as derived from your material." />
        {majors.length === 0 ? (
          <Blank title="No topics yet" description="Add material and the structure appears." />
        ) : (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {majors.map((major) => {
              const children = topics.filter((topic) => topic.parent_id === major.id);
              return (
                <div key={major.id} className="rail pl-4">
                  <h4 className="display text-sm">{major.name}</h4>
                  <ul className="mt-2 space-y-2">
                    {children.map((sub) => {
                      const mastery = dashboard?.mastery.find((item) => item.topic_id === sub.id);
                      return (
                        <li key={sub.id}>
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-xs text-[var(--ink-soft)]">{sub.name}</span>
                            {mastery && mastery.attempts > 0 ? (
                              <span className="num shrink-0 text-[10px] text-[var(--ink-faint)]">
                                {Math.round(mastery.mastery * 100)}%
                              </span>
                            ) : null}
                          </div>
                          {mastery && mastery.attempts > 0 ? (
                            <div className="mt-1">
                              <Meter value={mastery.mastery} showLabel={false} />
                            </div>
                          ) : null}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
