"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  FileText,
  Image as ImageIcon,
  MessageSquareQuote,
  Presentation,
  Table,
  Video,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Hint } from "@/components/hint";
import { PdfViewer } from "@/components/pdf-viewer";
import { Chip } from "@/components/ui";
import { mediaUrl } from "@/lib/api";
import type { Citation } from "@/lib/types";

export function formatTimestamp(seconds: number): string {
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

function modalityIcon(modality: string) {
  const className = "h-3 w-3";
  if (modality === "figure") return <ImageIcon className={className} />;
  if (modality === "table") return <Table className={className} />;
  if (modality === "transcript") return <Video className={className} />;
  return <FileText className={className} />;
}

function sourceIcon(kind: string) {
  const className = "h-3.5 w-3.5";
  if (kind === "pptx") return <Presentation className={className} />;
  if (kind === "video" || kind === "youtube" || kind === "audio") return <Video className={className} />;
  return <FileText className={className} />;
}

export function CitationChip({
  citation,
  onOpen,
}: {
  citation: Citation;
  onOpen: (citation: Citation) => void;
}) {
  return (
    <Hint label={citation.excerpt.slice(0, 160)} side="top">
      <button
        type="button"
        onClick={() => onOpen(citation)}
        className="inline-flex max-w-full items-center gap-1.5 rounded-lg border bg-[var(--glass)] px-2 py-1 text-[11px] transition hover:border-[var(--iris)] hover:bg-[var(--iris-soft)]"
      >
        {citation.marker !== undefined ? (
          <span className="num flex h-4 w-4 shrink-0 items-center justify-center rounded border border-[var(--iris)] text-[9px] font-semibold text-[var(--iris)]">
            {citation.marker}
          </span>
        ) : null}
        {sourceIcon(citation.source_kind)}
        <span className="truncate font-medium">{citation.source_title}</span>
        <span className="shrink-0 opacity-70">{citation.label}</span>
      </button>
    </Hint>
  );
}

export function CitationList({
  citations,
  onOpen,
}: {
  citations: Citation[];
  onOpen: (citation: Citation) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {citations.map((citation) => (
        <CitationChip key={`${citation.unit_id}-${citation.marker}`} citation={citation} onOpen={onOpen} />
      ))}
    </div>
  );
}

export function SourceViewer({
  citation,
  onClose,
  onAskAbout,
}: {
  citation: Citation | null;
  onClose: () => void;
  onAskAbout?: (text: string) => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const citationUnitId = citation?.unit_id;
  useEffect(() => {
    if (citationUnitId) setImageFailed(false);
  }, [citationUnitId]);

  const kind = citation?.source_kind ?? "";
  const isMedia = kind === "video" || kind === "youtube" || kind === "audio";
  const isPdf = kind === "pdf" || kind === "pptx";
  const startTime = citation?.locator.start_time_s ?? 0;
  const page = citation?.locator.page ?? citation?.locator.slide ?? 1;

  return (
    <AnimatePresence>
      {citation ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "color-mix(in srgb, var(--bg-0) 78%, transparent)" }}
          onClick={onClose}
          role="presentation"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.97, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 6 }}
            transition={{ duration: 0.22, ease: [0.2, 0.7, 0.3, 1] }}
            className="glass-raised flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-start justify-between gap-4 border-b px-4 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  {sourceIcon(kind)}
                  <h3 className="truncate text-sm font-semibold">{citation.source_title}</h3>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                  <Chip tone="iris">{citation.label}</Chip>
                  <Chip>
                    <span className="flex items-center gap-1">
                      {modalityIcon(citation.modality)}
                      {citation.modality}
                    </span>
                  </Chip>
                  {citation.heading_path.length > 0 ? (
                    <span className="truncate text-[11px] opacity-70">
                      {citation.heading_path.join(" › ")}
                    </span>
                  ) : null}
                </div>
              </div>
              <Hint label="Close (Esc)">
                <button type="button" className="btn px-2 py-1" onClick={onClose}>
                  <X className="h-4 w-4" />
                </button>
              </Hint>
            </header>

            <div className="grid min-h-0 flex-1 lg:grid-cols-[320px_minmax(0,1fr)]">
              <div className="scroll-slim min-h-0 overflow-auto border-b p-4 lg:border-b-0 lg:border-r">
                <p className="eyebrow mb-2">Cited lines</p>
                <p
                  className="rounded-lg p-3 text-sm leading-relaxed"
                  style={{
                    background: "color-mix(in srgb, var(--iris) 12%, transparent)",
                    borderLeft: "3px solid var(--iris)",
                  }}
                >
                  {citation.excerpt}
                </p>

                {citation.has_image && !imageFailed ? (
                  <img
                    src={mediaUrl(`/api/media/figure/${citation.unit_id}`)}
                    alt=""
                    className="mt-3 w-full rounded-lg border"
                    onError={() => setImageFailed(true)}
                  />
                ) : null}

                {onAskAbout ? (
                  <button
                    type="button"
                    className="btn mt-3 w-full text-xs"
                    onClick={() => {
                      onAskAbout(citation.excerpt);
                      onClose();
                    }}
                  >
                    <MessageSquareQuote className="h-3.5 w-3.5" /> Ask about this passage
                  </button>
                ) : null}
              </div>

              <div className="min-h-0 bg-[var(--bg-1)]">
                {isMedia ? (
                  <video
                    key={`${citation.source_id}-${startTime}`}
                    controls
                    autoPlay
                    className="h-full w-full bg-black"
                    src={`${mediaUrl(`/api/media/source/${citation.source_id}`)}#t=${startTime}`}
                  />
                ) : isPdf ? (
                  <PdfViewer
                    url={mediaUrl(`/api/media/source/${citation.source_id}`)}
                    page={page}
                    bbox={citation.locator.bbox}
                    onSelectText={onAskAbout}
                  />
                ) : (
                  <div className="scroll-slim h-full overflow-auto p-5">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">{citation.excerpt}</p>
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
