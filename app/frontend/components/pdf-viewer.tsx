"use client";

import { ChevronLeft, ChevronRight, Minus, Plus, Quote } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Hint } from "@/components/hint";
import { Spinner } from "@/components/ui";

type Box = { left: number; top: number; width: number; height: number };

/** Docling reports bounding boxes bottom-left origin in PDF points. */
function toViewportBox(bbox: number[], pageHeight: number, scale: number): Box {
  const [l, t, r, b] = bbox;
  const top = Math.min(t, b);
  const bottom = Math.max(t, b);
  return {
    left: l * scale,
    top: (pageHeight - bottom) * scale,
    width: Math.max(2, (r - l) * scale),
    height: Math.max(2, (bottom - top) * scale),
  };
}

export function PdfViewer({
  url,
  page = 1,
  bbox,
  onSelectText,
}: {
  url: string;
  page?: number;
  bbox?: number[] | null;
  onSelectText?: (text: string) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const docRef = useRef<{ numPages: number; getPage: (n: number) => Promise<unknown> } | null>(null);
  const renderTask = useRef<{ cancel: () => void } | null>(null);

  const [current, setCurrent] = useState(page);
  const [pages, setPages] = useState(0);
  const [scale, setScale] = useState(1.25);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [highlight, setHighlight] = useState<Box | null>(null);
  const [selection, setSelection] = useState("");

  useEffect(() => setCurrent(page), [page, url]);

  useEffect(() => {
    let cancelled = false;

    async function open() {
      setLoading(true);
      setFailed(false);
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();

        const task = pdfjs.getDocument({ url, withCredentials: false });
        const doc = await task.promise;
        if (cancelled) return;
        docRef.current = doc as never;
        setPages(doc.numPages);
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void open();
    return () => {
      cancelled = true;
    };
  }, [url]);

  const render = useCallback(async () => {
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas) return;

    try {
      renderTask.current?.cancel();
    } catch {
      /* already finished */
    }

    const pageObject = (await doc.getPage(Math.min(Math.max(1, current), doc.numPages))) as {
      getViewport: (options: { scale: number }) => { width: number; height: number };
      render: (options: unknown) => { promise: Promise<void>; cancel: () => void };
    };

    const viewport = pageObject.getViewport({ scale });
    const context = canvas.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    canvas.width = viewport.width * ratio;
    canvas.height = viewport.height * ratio;
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    const task = pageObject.render({ canvasContext: context, viewport });
    renderTask.current = task;
    try {
      await task.promise;
    } catch {
      return;
    }

    if (bbox && bbox.length === 4 && current === page) {
      const unscaled = pageObject.getViewport({ scale: 1 });
      setHighlight(toViewportBox(bbox, unscaled.height, scale));
    } else {
      setHighlight(null);
    }
  }, [current, scale, bbox, page]);

  useEffect(() => {
    void render();
  }, [render, pages]);

  function captureSelection() {
    const text = window.getSelection()?.toString().trim() ?? "";
    setSelection(text);
  }

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <p className="text-sm">
          This document could not be rendered here.{" "}
          <a className="underline" href={url} target="_blank" rel="noreferrer">
            Open it directly
          </a>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <Hint label="Previous page">
          <button
            type="button"
            className="btn px-2 py-1"
            disabled={current <= 1}
            onClick={() => setCurrent((n) => Math.max(1, n - 1))}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
        </Hint>
        <span className="num px-1 text-xs">
          {current} / {pages || "—"}
        </span>
        <Hint label="Next page">
          <button
            type="button"
            className="btn px-2 py-1"
            disabled={pages > 0 && current >= pages}
            onClick={() => setCurrent((n) => (pages ? Math.min(pages, n + 1) : n + 1))}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </Hint>

        <span className="ml-auto flex items-center gap-1.5">
          <Hint label="Zoom out">
            <button
              type="button"
              className="btn px-2 py-1"
              onClick={() => setScale((z) => Math.max(0.6, Number((z - 0.2).toFixed(2))))}
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
          </Hint>
          <span className="num text-[11px]">{Math.round(scale * 100)}%</span>
          <Hint label="Zoom in">
            <button
              type="button"
              className="btn px-2 py-1"
              onClick={() => setScale((z) => Math.min(2.6, Number((z + 0.2).toFixed(2))))}
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </Hint>
        </span>
      </div>

      <div className="scroll-slim relative min-h-0 flex-1 overflow-auto bg-[var(--bg-1)] p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center gap-2 text-sm">
            <Spinner /> Opening document
          </div>
        ) : null}

        <div className="relative mx-auto w-fit" onMouseUp={captureSelection}>
          <canvas ref={canvasRef} className="block rounded-lg shadow-lg" />
          {highlight ? (
            <span
              className="pointer-events-none absolute rounded-[3px]"
              style={{
                left: highlight.left,
                top: highlight.top,
                width: highlight.width,
                height: highlight.height,
                background: "color-mix(in srgb, var(--iris) 30%, transparent)",
                outline: "2px solid var(--iris)",
                boxShadow: "0 0 0 9999px color-mix(in srgb, var(--bg-0) 42%, transparent)",
              }}
            />
          ) : null}
        </div>
      </div>

      {selection && onSelectText ? (
        <div className="flex items-center gap-2 border-t px-3 py-2">
          <Quote className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1 truncate text-xs">{selection}</span>
          <button
            type="button"
            className="btn btn-primary px-2.5 py-1 text-[11px]"
            onClick={() => {
              onSelectText(selection);
              setSelection("");
              window.getSelection()?.removeAllRanges();
            }}
          >
            Ask about this
          </button>
        </div>
      ) : null}
    </div>
  );
}
