"use client";

import { motion } from "motion/react";
import {
  Archive,
  BookMarked,
  Globe,
  BrainCircuit,
  Flag,
  Pencil,
  Pin,
  Plus,
  Compass,
  Target,
  Trash2,
  TriangleAlert,
  Undo2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/session-context";
import { Blank, Chip, Field, Notice, Panel, SectionHead, Spinner } from "@/components/ui";
import { del, get, patch, post } from "@/lib/api";

type MemoryKind = "preference" | "goal" | "struggle" | "strength" | "context";

type Memory = {
  id: string;
  kind: MemoryKind;
  content: string;
  origin: string;
  confidence: number;
  pinned: boolean;
  archived: boolean;
  course_id: string | null;
  evidence: Record<string, unknown>;
  updated_at: string;
};

const KIND_META: Record<MemoryKind, { label: string; tone: "iris" | "mint" | "amber" | "rose" | "neutral"; icon: typeof Flag }> = {
  preference: { label: "Preference", tone: "iris", icon: Compass },
  goal: { label: "Goal", tone: "cyan" as never, icon: Flag },
  struggle: { label: "Struggle", tone: "rose", icon: TriangleAlert },
  strength: { label: "Strength", tone: "mint", icon: Target },
  context: { label: "Context", tone: "neutral", icon: BrainCircuit },
};

export function MemorySection() {
  const { courses } = useSession();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [draftKind, setDraftKind] = useState<MemoryKind>("preference");
  // "" means everywhere. A memory is either global or tied to exactly one course.
  const [draftCourse, setDraftCourse] = useState("");
  const [scopeFilter, setScopeFilter] = useState<"all" | "global" | string>("all");
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setMemories(await get<Memory[]>(`/api/memory?include_archived=${showArchived}`));
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load your memory");
    } finally {
      setLoading(false);
    }
  }, [showArchived]);

  useEffect(() => {
    void load();
  }, [load]);

  async function add() {
    if (!draft.trim()) return;
    try {
      await post("/api/memory", {
        kind: draftKind,
        content: draft.trim(),
        course_id: draftCourse || null,
      });
      setDraft("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save that");
    }
  }

  async function update(id: string, body: Record<string, unknown>) {
    await patch(`/api/memory/${id}`, body);
    await load();
  }

  async function remove(id: string) {
    await del(`/api/memory/${id}`);
    await load();
  }

  const courseName = (id: string | null) =>
    id ? (courses.find((course) => course.id === id)?.title ?? "A course") : null;

  const visible = memories.filter((item) => {
    if (scopeFilter === "all") return true;
    if (scopeFilter === "global") return item.course_id === null;
    return item.course_id === scopeFilter;
  });

  const globalCount = memories.filter((item) => item.course_id === null).length;
  const courseCount = memories.length - globalCount;

  const grouped = (["preference", "goal", "struggle", "strength", "context"] as MemoryKind[])
    .map((kind) => ({ kind, items: visible.filter((item) => item.kind === kind) }))
    .filter((group) => group.items.length > 0);

  return (
    <div className="space-y-5">
      <SectionHead
        eyebrow="Personalization"
        title="What Lucify remembers about you"
        description="Built from how you study — your questions, quiz results and stated goals. It shapes how the tutor explains things. Edit or delete anything; nothing here is fixed."
        action={
          <button
            type="button"
            className="btn"
            onClick={() => setShowArchived((current) => !current)}
          >
            <Archive className="h-4 w-4" /> {showArchived ? "Hide archived" : "Show archived"}
          </button>
        }
      />

      {error ? <Notice message={error} /> : null}

      <Panel>
        <p className="eyebrow mb-3">Tell it something directly</p>
        <div className="grid gap-3 md:grid-cols-[150px_170px_minmax(0,1fr)_auto]">
          <Field label="Type">
            <select
              className="input"
              value={draftKind}
              onChange={(event) => setDraftKind(event.target.value as MemoryKind)}
            >
              {Object.entries(KIND_META).map(([value, meta]) => (
                <option key={value} value={value}>
                  {meta.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Applies to">
            <select
              className="input"
              value={draftCourse}
              onChange={(event) => setDraftCourse(event.target.value)}
            >
              <option value="">Everywhere</option>
              {courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="What should it know?">
            <input
              className="input"
              placeholder="I learn best from worked examples, not proofs"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && add()}
            />
          </Field>
          <div className="flex items-end">
            <button type="button" className="btn btn-primary" disabled={!draft.trim()} onClick={add}>
              <Plus className="h-4 w-4" /> Add
            </button>
          </div>
        </div>
      </Panel>

      {memories.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="eyebrow mr-1">Scope</span>
          <button
            type="button"
            className={`btn px-2.5 py-1 text-xs ${scopeFilter === "all" ? "btn-primary" : ""}`}
            onClick={() => setScopeFilter("all")}
          >
            All {memories.length}
          </button>
          <button
            type="button"
            className={`btn px-2.5 py-1 text-xs ${scopeFilter === "global" ? "btn-primary" : ""}`}
            onClick={() => setScopeFilter("global")}
          >
            <Globe className="h-3 w-3" /> Everywhere {globalCount}
          </button>
          {courses
            .filter((course) => memories.some((item) => item.course_id === course.id))
            .map((course) => (
              <button
                key={course.id}
                type="button"
                className={`btn px-2.5 py-1 text-xs ${
                  scopeFilter === course.id ? "btn-primary" : ""
                }`}
                onClick={() => setScopeFilter(course.id)}
              >
                <BookMarked className="h-3 w-3" />
                {course.title.length > 24 ? `${course.title.slice(0, 24)}...` : course.title}
              </button>
            ))}
          {courseCount === 0 ? (
            <span className="text-[11px] text-[var(--ink-faint)]">
              Nothing is tied to a single course yet.
            </span>
          ) : null}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2.5 py-10 text-sm text-[var(--ink-soft)]">
          <Spinner /> Loading memory
        </div>
      ) : memories.length === 0 ? (
        <Blank
          icon={<BrainCircuit className="h-5 w-5" />}
          title="Nothing remembered yet"
          description="Ask the tutor a few questions or take a quiz, and Lucify starts noticing how you learn."
        />
      ) : (
        <div className="space-y-5">
          {grouped.map((group) => {
            const meta = KIND_META[group.kind];
            const Icon = meta.icon;
            return (
              <Panel key={group.kind}>
                <div className="mb-3 flex items-center gap-2">
                  <Icon className="h-4 w-4 text-[var(--iris)]" />
                  <h3 className="display text-base">{meta.label}</h3>
                  <Chip>{group.items.length}</Chip>
                </div>

                <div className="space-y-2">
                  {group.items.map((item, index) => (
                    <motion.div
                      key={item.id}
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.25, delay: Math.min(index * 0.03, 0.2) }}
                      className={`glass flex flex-wrap items-center gap-3 p-3 ${
                        item.archived ? "opacity-50" : ""
                      }`}
                    >
                      {editing === item.id ? (
                        <>
                          <input
                            className="input flex-1"
                            value={editText}
                            autoFocus
                            onChange={(event) => setEditText(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" && editText.trim()) {
                                void update(item.id, { content: editText.trim() });
                                setEditing(null);
                              }
                              if (event.key === "Escape") setEditing(null);
                            }}
                          />
                          <button
                            type="button"
                            className="btn btn-primary px-2.5 py-1 text-xs"
                            onClick={() => {
                              void update(item.id, { content: editText.trim() });
                              setEditing(null);
                            }}
                          >
                            Save
                          </button>
                          <button
                            type="button"
                            className="btn px-2.5 py-1 text-xs"
                            onClick={() => setEditing(null)}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <span className="min-w-0 flex-1 text-sm">{item.content}</span>
                          <select
                            className="input h-7 w-auto px-1.5 py-0 text-[11px]"
                            value={item.course_id ?? ""}
                            title="Where this applies"
                            aria-label="Where this applies"
                            onChange={(event) =>
                              update(item.id, { course_id: event.target.value || null })
                            }
                          >
                            <option value="">Everywhere</option>
                            {courses.map((course) => (
                              <option key={course.id} value={course.id}>
                                {course.title}
                              </option>
                            ))}
                          </select>
                          <span className="num text-[11px] text-[var(--ink-faint)]">
                            {Math.round(item.confidence * 100)}%
                          </span>
                          <Chip>{item.origin}</Chip>
                          <div className="flex gap-1">
                            <button
                              type="button"
                              className={`btn px-2 py-1 ${item.pinned ? "btn-primary" : ""}`}
                              title={item.pinned ? "Unpin" : "Always use this"}
                              onClick={() => update(item.id, { pinned: !item.pinned })}
                            >
                              <Pin className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              className="btn px-2 py-1"
                              title="Edit"
                              onClick={() => {
                                setEditing(item.id);
                                setEditText(item.content);
                              }}
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              className="btn px-2 py-1"
                              title={item.archived ? "Restore" : "Stop using this"}
                              onClick={() => update(item.id, { archived: !item.archived })}
                            >
                              {item.archived ? (
                                <Undo2 className="h-3 w-3" />
                              ) : (
                                <Archive className="h-3 w-3" />
                              )}
                            </button>
                            <button
                              type="button"
                              className="btn px-2 py-1"
                              title="Delete"
                              onClick={() => remove(item.id)}
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        </>
                      )}
                    </motion.div>
                  ))}
                </div>
              </Panel>
            );
          })}
        </div>
      )}

      <p className="text-xs leading-relaxed text-[var(--ink-faint)]">
        Memory is derived from your own activity using rules, not an extra model call, so it costs
        nothing to maintain. Pinned items are always sent to the tutor; archived ones never are.
        {courses.length > 0
          ? " An item set to Everywhere is sent to the tutor in every course; one tied to a course is only sent inside it."
          : ""}
      </p>
    </div>
  );
}
