"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import { ArrowUpRight, BookOpen, Compass, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { SIDEBAR_SECTIONS } from "@/components/app-frame";
import { CourseCreate } from "@/components/course-create";
import { AnalyticsSection } from "@/components/sections/analytics-section";
import { MemorySection } from "@/components/sections/memory-section";
import { PlannerSection } from "@/components/sections/planner-section";
import { SettingsSection } from "@/components/sections/settings-section";
import { useSession } from "@/components/session-context";
import { Blank, Chip, Panel, SectionHead, Spinner } from "@/components/ui";
import type { Course } from "@/lib/types";

type Section = (typeof SIDEBAR_SECTIONS)[number]["key"];

function CourseCard({ course, onOpen }: { course: Course; onOpen: () => void }) {
  const pending = course.source_count - course.ready_source_count;
  const figures = (course.modalities.figure ?? 0) + (course.modalities.table ?? 0);

  return (
    <button type="button" onClick={onOpen} className="group text-left">
      <Panel hover className="relative h-full overflow-hidden">
        <div className="pointer-events-none absolute -right-10 -top-12 h-28 w-28 rounded-full bg-[var(--iris)] opacity-20 blur-3xl transition group-hover:opacity-35" />
        <div className="flex items-start justify-between gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl border bg-[var(--glass)]">
            <BookOpen className="h-4 w-4 text-[var(--iris)]" />
          </span>
          <ArrowUpRight className="h-4 w-4 text-[var(--ink-faint)] transition group-hover:text-[var(--ink)]" />
        </div>
        <h3 className="display mt-3.5 text-lg">{course.title}</h3>
        {course.description ? (
          <p className="mt-1.5 line-clamp-2 text-sm text-[var(--ink-soft)]">{course.description}</p>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-1.5">
          <Chip>{course.unit_count} units</Chip>
          <Chip>{course.topic_count} topics</Chip>
          {figures > 0 ? <Chip tone="iris">{figures} figures</Chip> : null}
          {pending > 0 ? <Chip tone="amber">{pending} processing</Chip> : null}
        </div>
        <div className="mt-4 flex items-center justify-between border-t pt-3 text-xs text-[var(--ink-faint)]">
          <span>{course.source_count} sources</span>
          {course.exam_date ? <span>exam {course.exam_date}</span> : null}
        </div>
      </Panel>
    </button>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const { courses, student, profile, loadingCourses } = useSession();
  const [section, setSection] = useState<Section>("courses");
  const [creating, setCreating] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-[1420px] gap-6">
      <aside className="sticky top-[72px] hidden h-[calc(100vh-104px)] w-56 shrink-0 lg:block">
        <Panel className="flex h-full flex-col" padded={false}>
          <div className="border-b px-4 py-3.5">
            <p className="eyebrow">Workspace</p>
            <p className="display mt-1 truncate text-sm">{profile?.name ?? "My studies"}</p>
          </div>

          <nav className="flex flex-col gap-1 p-2.5">
            {SIDEBAR_SECTIONS.map((item) => {
              const Icon = item.icon;
              const active = section === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => {
                    setSection(item.key);
                    setCreating(false);
                  }}
                  className={clsx(
                    "relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition",
                    active
                      ? "text-[var(--ink)]"
                      : "text-[var(--ink-soft)] hover:bg-[var(--glass)] hover:text-[var(--ink)]",
                  )}
                >
                  {active ? (
                    <motion.span
                      layoutId="sidebar-active"
                      className="absolute inset-0 rounded-xl bg-[var(--iris-soft)] ring-1 ring-[var(--iris)]"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  ) : null}
                  <Icon className="relative h-4 w-4" />
                  <span className="relative">{item.label}</span>
                </button>
              );
            })}
          </nav>

          <div className="mt-auto p-2.5">
            <button
              type="button"
              className="btn btn-primary w-full"
              onClick={() => {
                setSection("courses");
                setCreating(true);
              }}
            >
              <Plus className="h-4 w-4" /> New course
            </button>
          </div>
        </Panel>
      </aside>

      <div className="min-w-0 flex-1 space-y-5">
        <div className="flex gap-1.5 overflow-x-auto lg:hidden">
          {SIDEBAR_SECTIONS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setSection(item.key)}
              className={clsx(
                "btn whitespace-nowrap px-3 py-1.5 text-xs",
                section === item.key ? "btn-primary" : "",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>

        {section === "courses" ? (
          creating ? (
            <>
              <button type="button" className="btn btn-ghost" onClick={() => setCreating(false)}>
                Back to courses
              </button>
              <CourseCreate
                onDone={(course) => {
                  setCreating(false);
                  router.push(`/courses/${course.id}`);
                }}
              />
            </>
          ) : (
            <>
              <SectionHead
                eyebrow={student ? `Signed in as ${student.name}` : "Library"}
                title="Courses"
                description="Each course is its own knowledge base. Open one to learn from it and test yourself."
                action={
                  <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                    <Plus className="h-4 w-4" /> New course
                  </button>
                }
              />

              {loadingCourses ? (
                <div className="flex items-center gap-2.5 py-10 text-sm text-[var(--ink-soft)]">
                  <Spinner /> Loading your courses
                </div>
              ) : courses.length === 0 ? (
                <Blank
                  icon={<Compass className="h-5 w-5" />}
                  title="No courses in this profile"
                  description="Create one from your lecture videos, textbooks or slide decks. One upload is enough to start."
                  action={
                    <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                      <Compass className="h-4 w-4" /> Create your first course
                    </button>
                  }
                />
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
                  {courses.map((course, index) => (
                    <motion.div
                      key={course.id}
                      initial={{ opacity: 0, y: 12 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: Math.min(index * 0.05, 0.3) }}
                    >
                      <CourseCard course={course} onOpen={() => router.push(`/courses/${course.id}`)} />
                    </motion.div>
                  ))}
                </div>
              )}
            </>
          )
        ) : null}

        {section === "planner" ? <PlannerSection /> : null}
        {section === "insights" ? <AnalyticsSection /> : null}
        {section === "memory" ? <MemorySection /> : null}
        {section === "settings" ? <SettingsSection /> : null}
      </div>
    </div>
  );
}
