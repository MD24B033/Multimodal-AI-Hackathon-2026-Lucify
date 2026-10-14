"use client";

import { useEffect, useState } from "react";

import { API_BASE, readAccessKey } from "@/lib/api";

export type IngestionEvent = {
  source_id: string;
  course_id: string;
  title: string;
  status: string;
  stage: string;
  progress: number;
  detail: Record<string, unknown> & { done?: number; total?: number };
  elapsed_seconds?: number;
  eta_seconds?: number | null;
  error: string | null;
  terminal?: boolean;
  at?: number;
};

export function useIngestionEvents(courseId: string | null) {
  const [events, setEvents] = useState<Record<string, IngestionEvent>>({});
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!courseId) {
      return;
    }

    const key = readAccessKey();
    const url = new URL(`${API_BASE}/api/courses/${courseId}/events`);
    if (key) url.searchParams.set("access_key", key);

    const source = new EventSource(url.toString());

    source.onopen = () => setConnected(true);

    source.onmessage = (message) => {
      if (!message.data) return;
      try {
        const payload = JSON.parse(message.data) as IngestionEvent;
        if (!payload.source_id) return;
        setEvents((current) => ({ ...current, [payload.source_id]: payload }));
      } catch {
        return;
      }
    };

    source.onerror = () => setConnected(false);

    return () => {
      source.close();
      setConnected(false);
      setEvents({});
    };
  }, [courseId]);

  return { events, connected };
}
