"use client";

import { motion } from "motion/react";
import {
  Archive,
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
      await post("/api/memory", { kind: draftKind, content: draft.trim() });
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

  const grouped = (["preference", "goal", "struggle", "strength", "context"] as MemoryKind[])
    .map((kind) => ({ kind, items: memories.filter((item) => item.kind === kind) }))
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
        <div className="grid gap-3 md:grid-cols-[150px_minmax(0,1fr)_auto]">
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
        {courses.length > 0 ? " Items tied to a course only apply inside that course." : ""}
      </p>
    </div>
  );
}
