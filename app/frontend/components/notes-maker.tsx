"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import {
  BookMarked,
  Columns2,
  Download,
  Layers,
  NotebookPen,
  ScrollText,
  Compass,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { CitationList } from "@/components/source-viewer";
import { RichLine, RichText } from "@/components/rich-text";
import { Blank, Chip, Field, Notice, Panel, SectionHead, Spinner } from "@/components/ui";
import { useTasks } from "@/components/task-center";
import { API_BASE, del, get } from "@/lib/api";
import type { Citation, Source, Topic } from "@/lib/types";

type Note = {
  id?: string;
  format: string;
  title: string;
  overview: string;
  body: string;
  cues: string[];
  summary_strip: string;
  cards: { front: string; back: string }[];
  key_terms: string[];
  gaps: string;
  citations: Citation[];
};

type SavedNote = { id: string; title: string; format: string; created_at: string; payload: Note };

const FORMATS = [
  { value: "summary", label: "Summary", icon: ScrollText, hint: "Headings and bullets" },
  { value: "cornell", label: "Cornell", icon: Columns2, hint: "Cue column + recall" },
  { value: "cheatsheet", label: "Cheat sheet", icon: Layers, hint: "Dense one-pager" },
  { value: "flashcards", label: "Flashcards", icon: BookMarked, hint: "Q and A pairs" },
];

export function NotesMaker({
  courseId,
  studentId,
  topics,
  sources,
  onOpenCitation,
}: {
  courseId: string;
  studentId: string;
  topics: Topic[];
  sources: Source[];
  onOpenCitation: (citation: Citation) => void;
}) {
  const [noteFormat, setNoteFormat] = useState("summary");
  const [topicId, setTopicId] = useState("");
  const [freeText, setFreeText] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [depth, setDepth] = useState("standard");
  const [language, setLanguage] = useState("en");
  const [extra, setExtra] = useState("");
  const [note, setNote] = useState<Note | null>(null);
  const [saved, setSaved] = useState<SavedNote[]>([]);
  const [error, setError] = useState<string | null>(null);
  const { enqueue, busyFor, tasks } = useTasks();
  const busy = busyFor(courseId);

  const loadSaved = useCallback(async () => {
    try {
      setSaved(await get<SavedNote[]>(`/api/notes?course_id=${courseId}&student_id=${studentId}`));
    } catch {
      setSaved([]);
    }
  }, [courseId, studentId]);

  useEffect(() => {
    void loadSaved();
  }, [loadSaved]);

  async function generate() {
    if (!topicId && !freeText.trim()) {
      setError("Pick a topic, or describe what the notes should cover");
      return;
    }
    setError(null);
    try {
      await enqueue({
        course_id: courseId,
        kind: "notes",
        label: `${noteFormat} notes${topicId ? "" : `: ${freeText.trim().slice(0, 40)}`}`,
        params: {
          note_format: noteFormat,
          topic_id: topicId || null,
          free_text: freeText.trim() || null,
          source_ids: sourceId ? [sourceId] : [],
          depth,
          language,
          extra_instructions: extra.trim() || null,
        },
      });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start that");
    }
  }

  const lastNoteTaskId = tasks.find((t) => t.kind === "notes" && t.status === "succeeded")?.id;
  useEffect(() => {
    if (!lastNoteTaskId) return;
    void loadSaved();
  }, [lastNoteTaskId, loadSaved]);

  const cornellPairs = note
    ? note.cues.map((cue, index) => ({
        cue,
        body: note.body.split("\n\n").filter(Boolean)[index] ?? "",
      }))
    : [];

  return (
    <div className="grid gap-4 lg:grid-cols-[330px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Panel>
          <SectionHead eyebrow="Notes maker" title="What should it write?" />

          <div className="space-y-4">
            <div>
              <label className="label">Format</label>
              <div className="grid grid-cols-2 gap-2">
                {FORMATS.map((item) => {
                  const Icon = item.icon;
                  const active = noteFormat === item.value;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      onClick={() => setNoteFormat(item.value)}
                      className={clsx(
                        "flex flex-col items-start gap-1 rounded-xl border p-2.5 text-left transition",
                        active
                          ? "border-[var(--iris)] bg-[var(--iris-soft)]"
                          : "hover:bg-[var(--glass-strong)]",
                      )}
                    >
                      <Icon
                        className={clsx(
                          "h-4 w-4",
                          active ? "text-[var(--iris)]" : "text-[var(--ink-faint)]",
                        )}
                      />
                      <span className="text-xs font-medium">{item.label}</span>
                      <span className="text-[10px] text-[var(--ink-faint)]">{item.hint}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <Field label="Topic">
              <select className="input" value={topicId} onChange={(e) => setTopicId(e.target.value)}>
                <option value="">I&apos;ll describe it myself</option>
                {topics.map((topic) => (
                  <option key={topic.id} value={topic.id}>
                    {topic.kind === "subtopic" ? "   " : ""}
                    {topic.name}
                  </option>
                ))}
              </select>
            </Field>

            {!topicId ? (
              <Field label="Subject">
                <input
                  className="input"
                  placeholder="how backpropagation computes gradients"
                  value={freeText}
                  onChange={(e) => setFreeText(e.target.value)}
                />
              </Field>
            ) : null}

            <div className="grid grid-cols-2 gap-2.5">
              <Field label="Depth">
                <select className="input" value={depth} onChange={(e) => setDepth(e.target.value)}>
                  <option value="brief">Brief</option>
                  <option value="standard">Standard</option>
                  <option value="deep">Deep</option>
                </select>
              </Field>
              <Field label="Language">
                <select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
                  <option value="en">English</option>
                  <option value="hi">हिंदी</option>
                  <option value="hinglish">Hinglish</option>
                </select>
              </Field>
            </div>

            <details className="text-xs text-[var(--ink-soft)]">
              <summary className="cursor-pointer select-none">More options</summary>
              <div className="mt-3 space-y-3">
                <Field label="Only from one source">
                  <select className="input" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
                    <option value="">All course material</option>
                    {sources
                      .filter((item) => item.status === "ready")
                      .map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.title}
                        </option>
                      ))}
                  </select>
                </Field>
                <Field label="Extra instruction">
                  <input
                    className="input"
                    placeholder="focus on the maths, skip history"
                    value={extra}
                    onChange={(e) => setExtra(e.target.value)}
                  />
                </Field>
              </div>
            </details>

            <button type="button" className="btn btn-primary w-full" disabled={busy} onClick={generate}>
              {busy ? <Spinner /> : <Compass className="h-4 w-4" />}
              {busy ? "Writing in background" : "Generate notes"}
            </button>
            {error ? <Notice message={error} /> : null}
          </div>
        </Panel>

        {saved.length > 0 ? (
          <Panel>
            <p className="eyebrow mb-2.5">Saved</p>
            <ul className="scroll-slim max-h-64 space-y-1 overflow-auto">
              {saved.map((item) => (
                <li key={item.id} className="flex items-center gap-1.5">
                  <button
                    type="button"
                    className="min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left text-xs hover:bg-[var(--glass-strong)]"
                    onClick={() => setNote({ ...item.payload, id: item.id })}
                  >
                    <span className="block truncate">{item.title}</span>
                    <span className="text-[10px] text-[var(--ink-faint)]">{item.format}</span>
                  </button>
                  <button
                    type="button"
                    className="btn px-1.5 py-1"
                    onClick={async () => {
                      await del(`/api/notes/${item.id}`);
                      if (note?.id === item.id) setNote(null);
                      await loadSaved();
                    }}
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        ) : null}
      </div>

      <div className="min-w-0">
        {note === null ? (
          <Panel className="flex h-full items-center justify-center">
            <Blank
              icon={<NotebookPen className="h-5 w-5" />}
              title="No notes open"
              description="Choose a format and a topic. Notes are written only from your material, with sources at the end."
            />
          </Panel>
        ) : (
          <motion.div
            key={note.id ?? note.title}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Panel className="overflow-hidden" padded={false}>
              <header className="flex flex-wrap items-start justify-between gap-3 border-b px-6 py-5">
                <div className="min-w-0">
                  <Chip tone="iris">{note.format}</Chip>
                  <h2 className="display mt-2 text-2xl">{note.title}</h2>
                </div>
                {note.id ? (
                  <a className="btn text-xs" href={`${API_BASE}/api/notes/${note.id}/markdown`} download>
                    <Download className="h-3.5 w-3.5" /> Markdown
                  </a>
                ) : null}
              </header>

              <div className="px-6 py-5">
                {note.overview ? (
                  <p className="rail mb-6 pl-4 text-sm leading-relaxed text-[var(--ink-soft)]">
                    {note.overview}
                  </p>
                ) : null}

                {note.format === "cornell" ? (
                  <div className="space-y-0">
                    {cornellPairs.map((pair, index) => (
                      <div
                        key={pair.cue}
                        className={clsx(
                          "grid gap-5 py-4 sm:grid-cols-[200px_minmax(0,1fr)]",
                          index > 0 && "border-t",
                        )}
                      >
                        <p className="text-sm font-medium text-[var(--iris)]">{pair.cue}</p>
                        <div className="prose-tutor min-w-0">
                          <RichText>{pair.body}</RichText>
                        </div>
                      </div>
                    ))}
                    {note.summary_strip ? (
                      <div className="mt-5 rounded-xl border border-[var(--iris)] bg-[var(--iris-soft)] p-4">
                        <p className="eyebrow mb-1.5">Summary</p>
                        <RichText className="text-sm leading-relaxed">{note.summary_strip}</RichText>
                      </div>
                    ) : null}
                  </div>
                ) : note.format === "flashcards" ? (
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    {note.cards.map((card, index) => (
                      <details key={index} className="glass group rounded-xl p-3.5">
                        <summary className="cursor-pointer select-none text-sm font-medium marker:content-none">
                          <span className="mr-2 text-[var(--iris)]">{String(index + 1).padStart(2, "0")}</span>
                          <RichLine>{card.front}</RichLine>
                        </summary>
                        <div className="mt-2.5 border-t pt-2.5 text-sm leading-relaxed text-[var(--ink-soft)]">
                          <RichText>{card.back}</RichText>
                        </div>
                      </details>
                    ))}
                  </div>
                ) : (
                  <div className="prose-tutor max-w-[68ch]">
                    <RichText>{note.body}</RichText>
                  </div>
                )}

                {note.key_terms.length > 0 ? (
                  <div className="mt-7 border-t pt-5">
                    <p className="eyebrow mb-2.5">Key terms</p>
                    <div className="flex flex-wrap gap-1.5">
                      {note.key_terms.map((term) => (
                        <Chip key={term}>{term}</Chip>
                      ))}
                    </div>
                  </div>
                ) : null}

                {note.gaps ? (
                  <div
                    className="mt-5 rounded-xl border p-3.5"
                    style={{
                      borderColor: "var(--amber)",
                      background: "color-mix(in srgb, var(--amber) 9%, transparent)",
                    }}
                  >
                    <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-[var(--amber)]">
                      <TriangleAlert className="h-3.5 w-3.5" /> Not covered by your material
                    </p>
                    <p className="text-xs leading-relaxed">{note.gaps}</p>
                  </div>
                ) : null}

                <div className="mt-6 border-t pt-5">
                  <p className="eyebrow mb-2.5">Sources</p>
                  <CitationList citations={note.citations} onOpen={onOpenCitation} />
                </div>
              </div>
            </Panel>
          </motion.div>
        )}
      </div>
    </div>
  );
}
