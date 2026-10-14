"use client";

import { useCallback, useEffect, useState } from "react";

import { API_BASE, get, readAccessKey } from "@/lib/api";

export type IngestionEvent = {
  source_id: string;
  course_id: string;
  title: string;
  kind?: string;
  status: string;
  stage: string;
  progress: number;
  detail: Record<string, unknown> & { done?: number; total?: number; item?: string };
  elapsed_seconds?: number;
  eta_seconds?: number | null;
  error: string | null;
  terminal?: boolean;
  at?: number;
};

/** "reading pages" + "page 12" + 12/64 reads as "Reading page 12 · 12 of 64". The
 *  stage alone never said which page, which is the one thing a slow ingest needs
 *  to show to look alive. */
export function describeIngestion(event: IngestionEvent | null | undefined): string {
  if (!event) return "";
  const stage = event.stage || "working";
  const item = typeof event.detail?.item === "string" ? event.detail.item : null;
  const { done, total } = event.detail ?? {};
  const counted =
    typeof done === "number" && typeof total === "number" && total > 0
      ? `${done} of ${total}`
      : null;

  const head = item ? `${stage} ${item}` : stage;
  const sentence = counted ? `${head} · ${counted}` : head;
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

export function formatEta(seconds: number | null | undefined): string | null {
  if (typeof seconds !== "number" || seconds <= 0) return null;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function subscribe(path: string, onEvent: (event: IngestionEvent) => void): () => void {
  const key = readAccessKey();
  const url = new URL(`${API_BASE}${path}`);
  if (key) url.searchParams.set("access_key", key);
  const stream = new EventSource(url.toString());
  stream.onmessage = (message) => {
    if (!message.data) return;
    try {
      const payload = JSON.parse(message.data) as IngestionEvent;
      if (payload.source_id) onEvent(payload);
    } catch {
      /* a malformed frame is not worth tearing the stream down for */
    }
  };
  return () => stream.close();
}

export function useIngestionEvents(courseId: string | null) {
  const [events, setEvents] = useState<Record<string, IngestionEvent>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!courseId) return;
    setConnected(true);
    const close = subscribe(`/api/courses/${courseId}/events`, (payload) =>
      setEvents((current) => ({ ...current, [payload.source_id]: payload })),
    );
    return () => {
      close();
      setConnected(false);
      setEvents({});
    };
  }, [courseId]);

  return { events, connected };
}

/** Ingestion runs in a backend worker, so it never stopped when you left the page —
 *  but nothing outside the material tab showed it. This watches every job for the
 *  whole app: a snapshot first, so work already in flight appears immediately on a
 *  fresh page, then the live feed. */
export function useIngestionFeed(enabled: boolean) {
  const [jobs, setJobs] = useState<Record<string, IngestionEvent>>({});
  const [finished, setFinished] = useState<IngestionEvent[]>([]);

  const dismiss = useCallback((sourceId: string) => {
    setFinished((current) => current.filter((item) => item.source_id !== sourceId));
  }, []);

  useEffect(() => {
    if (!enabled) {
      setJobs({});
      return;
    }

    let cancelled = false;

    void get<IngestionEvent[]>("/api/ingestion/active")
      .then((active) => {
        if (cancelled) return;
        setJobs((current) => {
          const next = { ...current };
          for (const job of active) next[job.source_id] = job;
          return next;
        });
      })
      .catch(() => undefined);

    const close = subscribe("/api/ingestion/events", (payload) => {
      if (cancelled) return;
      setJobs((current) => {
        const next = { ...current };
        if (payload.terminal || payload.status === "failed" || payload.status === "succeeded") {
          delete next[payload.source_id];
        } else {
          next[payload.source_id] = payload;
        }
        return next;
      });
      if (payload.terminal || payload.status === "failed") {
        setFinished((current) =>
          current.some((item) => item.source_id === payload.source_id)
            ? current
            : [...current, payload],
        );
      }
    });

    return () => {
      cancelled = true;
      close();
    };
  }, [enabled]);

  return { jobs: Object.values(jobs), finished, dismiss };
}
