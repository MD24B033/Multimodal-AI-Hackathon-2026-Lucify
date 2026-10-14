"use client";

import {
  CheckCircle2,
  FileText,
  Loader2,
  MonitorPlay,
  Plus,
  Compass,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { useRef, useState } from "react";

import { createCourse, useSession } from "@/components/session-context";
import { Chip, Field, Notice, Panel, Progress, SectionHead, Spinner } from "@/components/ui";
import { post, upload } from "@/lib/api";
import type { Course, Source } from "@/lib/types";
import { useIngestionEvents } from "@/lib/use-ingestion-events";

const ACCEPTED = ".pdf,.pptx,.docx,.html,.mp4,.mkv,.mov,.webm,.mp3,.wav,.m4a";

type Staged = { file: File; id: string };

export function CourseCreate({ onDone }: { onDone: (course: Course) => void }) {
  const { refreshCourses } = useSession();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [examDate, setExamDate] = useState("");
  const [weeklyHours, setWeeklyHours] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [goal, setGoal] = useState("");
  const [staged, setStaged] = useState<Staged[]>([]);
  const [links, setLinks] = useState<string[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [course, setCourse] = useState<Course | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const { events } = useIngestionEvents(course?.id ?? null);
  const live = Object.values(events);
  const allDone = live.length > 0 && live.every((item) => item.terminal);

  function addFiles(list: FileList | null) {
    if (!list) return;
    setStaged((current) => [
      ...current,
      ...Array.from(list).map((file) => ({ file, id: `${file.name}-${file.size}-${file.lastModified}` })),
    ]);
  }

  async function launch() {
    if (!title.trim()) {
      setError("Give the course a name first");
      return;
    }
    if (staged.length === 0 && links.length === 0) {
      setError("Add at least one document or lecture link");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const created = await createCourse({
        title: title.trim(),
        description: description.trim() || null,
        exam_date: examDate || null,
        weekly_hours: weeklyHours ? Number(weeklyHours) : null,
        difficulty: difficulty || null,
        goal: goal.trim() || null,
      });
      setCourse(created);

      for (const item of staged) {
        const form = new FormData();
        form.append("file", item.file);
        await upload<Source>(`/api/courses/${created.id}/sources`, form);
      }
      for (const url of links) {
        await post<Source>(`/api/courses/${created.id}/sources/youtube`, { url });
      }
      await refreshCourses();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create the course");
      setBusy(false);
    }
  }

  if (course) {
    return (
      <Panel raised className="fade-rise">
        <SectionHead
          eyebrow="Building"
          title={course.title}
          description="Material is being read, tagged and linked back to its exact page, slide or timestamp. You can leave this running."
        />

        <div className="space-y-2.5">
          {live.length === 0 ? (
            <div className="flex items-center gap-2.5 text-sm text-[var(--ink-soft)]">
              <Spinner /> Queueing sources
            </div>
          ) : null}

          {live.map((item) => (
            <div key={item.source_id} className="glass p-3.5">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="flex-1 truncate text-sm font-medium">{item.title}</span>
                {item.status === "failed" ? (
                  <Chip tone="rose">failed</Chip>
                ) : item.terminal ? (
                  <Chip tone="mint">
                    <CheckCircle2 className="h-3 w-3" /> ready
                  </Chip>
                ) : (
                  <Chip tone="iris">
                    <Loader2 className="h-3 w-3 animate-spin" /> {item.stage}
                  </Chip>
                )}
              </div>
              {!item.terminal ? <Progress value={item.progress} label={item.stage} /> : null}
              {item.error ? <p className="mt-2 text-xs text-[var(--rose)]">{item.error}</p> : null}
            </div>
          ))}
        </div>

        <button
          type="button"
          className="btn btn-primary mt-5"
          disabled={!allDone && live.length > 0}
          onClick={() => onDone(course)}
        >
          {allDone || live.length === 0 ? "Open course" : "Processing…"}
        </button>
      </Panel>
    );
  }

  return (
    <Panel raised className="fade-rise">
      <SectionHead
        eyebrow="New course"
        title="Start from your own material"
        description="Drop in a textbook, slide deck or lecture recording. Everything is parsed and cited automatically."
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Field label="Course name">
          <input
            className="input"
            placeholder="Deep Learning Foundations"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <Field label="Description" hint="Optional">
          <input
            className="input"
            placeholder="What this course covers"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Field label="Exam date" hint="Used to plan revision">
          <input
            type="date"
            className="input"
            value={examDate}
            onChange={(event) => setExamDate(event.target.value)}
          />
        </Field>
      </div>

      <details className="mt-4 text-xs text-[var(--ink-soft)]">
        <summary className="cursor-pointer select-none">Course details (optional)</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <Field label="Hours per week">
            <input
              type="number"
              min={1}
              max={80}
              className="input"
              placeholder="6"
              value={weeklyHours}
              onChange={(event) => setWeeklyHours(event.target.value)}
            />
          </Field>
          <Field label="Difficulty">
            <select className="input" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
              <option value="">Not sure</option>
              <option value="intro">Introductory</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </Field>
          <Field label="What are you aiming for?">
            <input
              className="input"
              placeholder="Pass the final, or build a project"
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
            />
          </Field>
        </div>
      </details>

      <div
        className={`mt-5 rounded-[var(--radius)] border border-dashed p-7 text-center transition ${
          dragging ? "border-[var(--iris)] bg-[var(--iris-soft)]" : ""
        }`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
      >
        <input
          ref={fileInput}
          type="file"
          multiple
          accept={ACCEPTED}
          className="hidden"
          onChange={(event) => addFiles(event.target.files)}
        />
        <UploadCloud className="mx-auto mb-2.5 h-7 w-7 text-[var(--ink-faint)]" />
        <p className="text-sm font-medium">Drop files here</p>
        <p className="mt-1 text-xs text-[var(--ink-faint)]">
          PDF, PPTX, DOCX, MP4, MP3 — no preprocessing needed
        </p>
        <button type="button" className="btn mt-3.5" onClick={() => fileInput.current?.click()}>
          <Plus className="h-4 w-4" /> Choose files
        </button>
      </div>

      {staged.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {staged.map((item) => (
            <span key={item.id} className="glass flex items-center gap-2 px-2.5 py-1.5 text-xs">
              <FileText className="h-3.5 w-3.5 text-[var(--ink-faint)]" />
              <span className="max-w-[200px] truncate">{item.file.name}</span>
              <button
                type="button"
                onClick={() => setStaged((current) => current.filter((x) => x.id !== item.id))}
                className="text-[var(--ink-faint)] hover:text-[var(--rose)]"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-5">
        <Field label="Lecture video link" hint="Transcribed with timestamps; on-screen slides are read too">
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="https://..."
              value={linkDraft}
              onChange={(event) => setLinkDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && linkDraft.trim()) {
                  setLinks((current) => [...current, linkDraft.trim()]);
                  setLinkDraft("");
                }
              }}
            />
            <button
              type="button"
              className="btn"
              disabled={!linkDraft.trim()}
              onClick={() => {
                setLinks((current) => [...current, linkDraft.trim()]);
                setLinkDraft("");
              }}
            >
              <MonitorPlay className="h-4 w-4" /> Add
            </button>
          </div>
        </Field>
        {links.length > 0 ? (
          <div className="mt-2.5 flex flex-wrap gap-2">
            {links.map((url) => (
              <span key={url} className="glass flex items-center gap-2 px-2.5 py-1.5 text-xs">
                <MonitorPlay className="h-3.5 w-3.5 text-[var(--ink-faint)]" />
                <span className="max-w-[240px] truncate">{url}</span>
                <button
                  type="button"
                  onClick={() => setLinks((current) => current.filter((x) => x !== url))}
                  className="text-[var(--ink-faint)] hover:text-[var(--rose)]"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="mt-4">
          <Notice message={error} />
        </div>
      ) : null}

      <button type="button" className="btn btn-primary mt-5" disabled={busy} onClick={launch}>
        {busy ? <Spinner /> : <Compass className="h-4 w-4" />}
        {busy ? "Creating" : "Create and ingest"}
      </button>
    </Panel>
  );
}
