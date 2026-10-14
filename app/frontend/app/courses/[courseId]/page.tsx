"use client";

import clsx from "clsx";
import {
  ArrowLeft,
  AudioLines,
  LayoutDashboard,
  MessagesSquare,
  NotebookPen,
  Target,
  UploadCloud,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ChatWorkspace } from "@/components/chat-workspace";
import { CourseAssess } from "@/components/course-assess";
import { CourseMaterial } from "@/components/course-material";
import { CourseOverview } from "@/components/course-overview";
import { NotesMaker } from "@/components/notes-maker";
import { useSession } from "@/components/session-context";
import { SourceViewer } from "@/components/source-viewer";
import { VoiceTutor } from "@/components/voice-tutor";
import { Blank, Chip, Panel, Spinner } from "@/components/ui";
import { get } from "@/lib/api";
import type { Citation, Course, Source, Topic } from "@/lib/types";

type Tab = "overview" | "learn" | "voice" | "notes" | "assess" | "material";

const SECTIONS: { value: Tab; label: string; icon: ReactNode; hint: string }[] = [
  {
    value: "overview",
    label: "Overview",
    icon: <LayoutDashboard className="h-4 w-4" />,
    hint: "Where you stand",
  },
  {
    value: "learn",
    label: "Chat",
    icon: <MessagesSquare className="h-4 w-4" />,
    hint: "Ask, with sources",
  },
  {
    value: "voice",
    label: "Voice",
    icon: <AudioLines className="h-4 w-4" />,
    hint: "Talk it through",
  },
  {
    value: "notes",
    label: "Notes",
    icon: <NotebookPen className="h-4 w-4" />,
    hint: "Write it up",
  },
  {
    value: "assess",
    label: "Assess",
    icon: <Target className="h-4 w-4" />,
    hint: "Test yourself",
  },
  {
    value: "material",
    label: "Material",
    icon: <UploadCloud className="h-4 w-4" />,
    hint: "Add and review",
  },
];

export default function CoursePage() {
  const params = useParams<{ courseId: string }>();
  const router = useRouter();
  const courseId = params.courseId;
  const { student, courses } = useSession();

  const [tab, setTab] = useState<Tab>("overview");
  const [course, setCourse] = useState<Course | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [active, setActive] = useState<Citation | null>(null);
  const [quoted, setQuoted] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [detail, sourceList, topicList] = await Promise.all([
        get<Course>(`/api/courses/${courseId}`),
        get<Source[]>(`/api/courses/${courseId}/sources`),
        get<Topic[]>(`/api/courses/${courseId}/topics`),
      ]);
      setCourse(detail);
      setSources(sourceList);
      setTopics(topicList);
    } catch {
      setCourse(null);
    } finally {
      setLoading(false);
    }
  }, [courseId]);

  useEffect(() => {
    void load();
  }, [load, courses]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-[var(--ink-soft)]">
        <Spinner className="mr-2.5" /> Opening course
      </div>
    );
  }

  if (!course || !student) {
    return (
      <Blank
        title="Course not found"
        description="It may have been deleted, or belongs to another profile."
        action={
          <button type="button" className="btn btn-primary" onClick={() => router.push("/dashboard")}>
            Back to dashboard
          </button>
        }
      />
    );
  }

  const figures = (course.modalities.figure ?? 0) + (course.modalities.table ?? 0);
  const empty = course.unit_count === 0;

  return (
    <div className="mx-auto grid w-full max-w-[1460px] gap-5 lg:grid-cols-[228px_minmax(0,1fr)]">
      <aside className="space-y-3 lg:sticky lg:top-4 lg:self-start">
        <button type="button" className="btn btn-ghost px-2" onClick={() => router.push("/dashboard")}>
          <ArrowLeft className="h-4 w-4" /> Dashboard
        </button>

        <Panel className="p-3.5">
          <h1 className="display text-base leading-snug">{course.title}</h1>
          {course.description ? (
            <p className="mt-1.5 line-clamp-3 text-xs leading-relaxed text-[var(--ink-soft)]">
              {course.description}
            </p>
          ) : null}
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <Chip>{course.unit_count} units</Chip>
            <Chip>{course.topic_count} topics</Chip>
            {figures > 0 ? <Chip tone="iris">{figures} figures</Chip> : null}
            {course.exam_date ? <Chip tone="amber">exam {course.exam_date}</Chip> : null}
          </div>
        </Panel>

        <nav
          aria-label="Course sections"
          className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0"
        >
          {SECTIONS.map((section) => {
            const selected = tab === section.value;
            return (
              <button
                key={section.value}
                type="button"
                onClick={() => setTab(section.value)}
                aria-current={selected ? "page" : undefined}
                aria-label={section.label}
                className={clsx(
                  "group flex shrink-0 items-center gap-2.5 rounded-xl border px-3 py-2 text-left transition lg:w-full",
                  selected
                    ? "border-[var(--edge-strong)] bg-[var(--glass-strong)]"
                    : "border-transparent hover:border-[var(--edge)] hover:bg-[var(--glass)]",
                )}
              >
                <span
                  className="shrink-0"
                  style={{ color: selected ? "var(--iris)" : "var(--ink-soft)" }}
                >
                  {section.icon}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm leading-tight">{section.label}</span>
                  <span className="hidden text-[11px] leading-tight opacity-70 lg:block">
                    {section.hint}
                  </span>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="min-w-0">
        {empty && tab !== "material" ? (
          <Blank
            icon={<UploadCloud className="h-5 w-5" />}
            title="This course has no material yet"
            description="Add a document or lecture video, and the tutor, notes and assessments light up."
            action={
              <button type="button" className="btn btn-primary" onClick={() => setTab("material")}>
                <UploadCloud className="h-4 w-4" /> Add material
              </button>
            }
          />
        ) : (
          <>
            {tab === "overview" ? (
              <CourseOverview
                course={course}
                studentId={student.id}
                topics={topics}
                onGoTo={(next) => setTab(next)}
              />
            ) : null}

            {tab === "learn" ? (
              <ChatWorkspace
                courseId={course.id}
                courseTitle={course.title}
                studentId={student.id}
                sources={sources}
                onOpenCitation={setActive}
                quoted={quoted}
                onQuotedConsumed={() => setQuoted(null)}
              />
            ) : null}

            {tab === "voice" ? (
              <VoiceTutor
                courseId={course.id}
                courseTitle={course.title}
                studentId={student.id}
                onOpenCitation={setActive}
              />
            ) : null}

            {tab === "notes" ? (
              <NotesMaker
                courseId={course.id}
                studentId={student.id}
                topics={topics}
                sources={sources}
                onOpenCitation={setActive}
              />
            ) : null}

            {tab === "assess" ? (
              <CourseAssess
                courseId={course.id}
                unitCount={course.unit_count}
                onOpenCitation={setActive}
              />
            ) : null}

            {tab === "material" ? <CourseMaterial courseId={course.id} /> : null}
          </>
        )}
      </main>

      <SourceViewer
        citation={active}
        onClose={() => setActive(null)}
        onAskAbout={(text) => {
          setQuoted(text);
          setTab("learn");
        }}
      />
    </div>
  );
}
