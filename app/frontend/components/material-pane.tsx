"use client";

import { motion } from "motion/react";
import { ExternalLink, FileText, Highlighter, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Blank, Chip, Panel, Spinner } from "@/components/ui";
import { get, mediaUrl } from "@/lib/api";
import type { Citation, Source } from "@/lib/types";

type WindowUnit = {
  id: string;
  text: string;
  modality: string;
  page_no: number | null;
  slide_no: number | null;
  start_time_s: number | null;
  is_target: boolean;
  has_image: boolean;
};

type UnitContext = {
  unit_id: string;
  source: { id: string; title: string; kind: string };
  window: WindowUnit[];
};

function locatorOf(unit: WindowUnit): string {
  if (unit.slide_no !== null) return `Slide ${unit.slide_no}`;
  if (unit.start_time_s !== null) {
    const seconds = Math.floor(unit.start_time_s);
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  }
  if (unit.page_no !== null) return `Page ${unit.page_no}`;
  return "";
}

export function MaterialPane({
  courseId,
  sources,
  highlight,
  selectedSourceId,
  onSelectSource,
  onClearHighlight,
}: {
  courseId: string;
  sources: Source[];
  highlight: Citation | null;
  selectedSourceId: string | null;
  onSelectSource: (id: string) => void;
  onClearHighlight: () => void;
}) {
  const [context, setContext] = useState<UnitContext | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!highlight) {
      setContext(null);
      return;
    }
    setLoading(true);
    try {
      setContext(
        await get<UnitContext>(
          `/api/courses/${courseId}/units/${highlight.unit_id}/context?window=3`,
        ),
      );
    } catch {
      setContext(null);
    } finally {
      setLoading(false);
    }
  }, [courseId, highlight]);

  useEffect(() => {
    void load();
  }, [load]);

  const ready = sources.filter((item) => item.status === "ready");
  const source = sources.find((item) => item.id === selectedSourceId) ?? null;
  const viewable = source ? ["pdf", "pptx", "docx", "html"].includes(source.kind) : false;

  return (
    <Panel className="flex h-full flex-col overflow-hidden" padded={false}>
      <div className="flex items-center gap-2 border-b px-3.5 py-2.5">
        {highlight ? (
          <>
            <Highlighter className="h-3.5 w-3.5 shrink-0 text-[var(--amber)]" />
            <span className="min-w-0 flex-1 truncate text-xs">
              {highlight.source_title} · {highlight.label}
            </span>
            <button
              type="button"
              className="btn px-2 py-1"
              title="Back to document"
              onClick={onClearHighlight}
            >
              <X className="h-3 w-3" />
            </button>
          </>
        ) : (
          <>
            <FileText className="h-3.5 w-3.5 shrink-0 text-[var(--ink-faint)]" />
            <select
              className="input h-7 min-w-0 flex-1 py-0.5 text-xs"
              value={selectedSourceId ?? ""}
              onChange={(event) => onSelectSource(event.target.value)}
            >
              {ready.length === 0 ? <option value="">No documents ready</option> : null}
              {ready.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </>
        )}
      </div>

      <div className="scroll-slim min-h-0 flex-1 overflow-auto">
        {loading ? (
          <div className="flex items-center gap-2 p-5 text-sm text-[var(--ink-soft)]">
            <Spinner /> Finding that passage
          </div>
        ) : context ? (
          <div className="space-y-2 p-3.5">
            <p className="eyebrow">In context</p>
            {context.window.map((unit) => (
              <motion.div
                key={unit.id}
                initial={unit.is_target ? { backgroundColor: "rgba(255,180,84,0.28)" } : false}
                animate={unit.is_target ? { backgroundColor: "rgba(255,180,84,0.12)" } : {}}
                transition={{ duration: 1.1 }}
                className={`rounded-xl border p-3 text-sm leading-relaxed ${
                  unit.is_target
                    ? "border-[var(--amber)]"
                    : "border-transparent text-[var(--ink-soft)] opacity-70"
                }`}
              >
                <div className="mb-1.5 flex items-center gap-2">
                  <Chip tone={unit.is_target ? "amber" : "neutral"}>{locatorOf(unit)}</Chip>
                  {unit.is_target ? <span className="text-[10px] text-[var(--amber)]">cited here</span> : null}
                </div>
                {unit.has_image ? (
                  <img
                    src={mediaUrl(`/api/media/figure/${unit.id}`)}
                    alt=""
                    className="mb-2 max-h-56 w-full rounded-lg border object-contain"
                  />
                ) : null}
                <p className="whitespace-pre-wrap">{unit.text}</p>
              </motion.div>
            ))}

            {highlight?.source_id ? (
              <a
                className="btn w-full text-xs"
                href={mediaUrl(`/api/media/source/${highlight.source_id}`)}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink className="h-3.5 w-3.5" /> Open the full source
              </a>
            ) : null}
          </div>
        ) : source && viewable ? (
          <iframe
            key={source.id}
            title={source.title}
            className="h-full w-full"
            src={mediaUrl(`/api/media/source/${source.id}`)}
          />
        ) : (
          <div className="flex h-full items-center justify-center p-5">
            <Blank
              icon={<Highlighter className="h-5 w-5" />}
              title="Nothing pinned yet"
              description="Pick a document, or press the highlighter on any citation to see that passage in place."
            />
          </div>
        )}
      </div>
    </Panel>
  );
}
