"use client";

import clsx from "clsx";
import { motion } from "motion/react";
import {
  AlertTriangle,
  BadgeCheck,
  Highlighter,
  Info,
  Mic,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Square,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { MaterialPane } from "@/components/material-pane";
import { RichText } from "@/components/rich-text";
import { SessionRail } from "@/components/session-rail";
import { CitationChip } from "@/components/source-viewer";
import { Blank, Chip, Notice, Panel, Spinner } from "@/components/ui";
import { API_BASE, del, get, post } from "@/lib/api";
import type { AskResponse, ChatMessage, ChatSession, Citation, Source } from "@/lib/types";

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिंदी" },
  { value: "hinglish", label: "Hinglish" },
];

type SessionRow = ChatSession & { message_count?: number; updated_at?: string };

function GroundingChip({ status }: { status: ChatMessage["grounding_status"] }) {
  if (!status) return null;
  if (status === "grounded")
    return (
      <Chip tone="mint">
        <BadgeCheck className="h-3 w-3" /> grounded
      </Chip>
    );
  if (status === "partial")
    return (
      <Chip tone="amber">
        <Info className="h-3 w-3" /> partial
      </Chip>
    );
  return (
    <Chip tone="rose">
      <AlertTriangle className="h-3 w-3" /> not in your material
    </Chip>
  );
}

export function ChatWorkspace({
  courseId,
  courseTitle,
  studentId,
  sources,
  onOpenCitation,
  quoted,
  onQuotedConsumed,
}: {
  courseId: string;
  courseTitle: string;
  studentId: string;
  sources: Source[];
  onOpenCitation: (citation: Citation) => void;
  quoted?: string | null;
  onQuotedConsumed?: () => void;
}) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState("en");
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [followups, setFollowups] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [splitOpen, setSplitOpen] = useState(false);
  const [highlight, setHighlight] = useState<Citation | null>(null);
  const [paneSourceId, setPaneSourceId] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const pending = useRef(0);

  const loadSessions = useCallback(async () => {
    const list = await get<SessionRow[]>(
      `/api/chat/sessions?course_id=${courseId}&student_id=${studentId}`,
    );
    setSessions(list);
    return list;
  }, [courseId, studentId]);

  const openSession = useCallback(async (id: string) => {
    const full = await get<ChatSession>(`/api/chat/sessions/${id}`);
    setSessionId(full.id);
    setMessages(full.messages ?? []);
    setFollowups([]);
    setHighlight(null);
  }, []);

  const newSession = useCallback(async () => {
    const created = await post<ChatSession>("/api/chat/sessions", {
      course_id: courseId,
      student_id: studentId,
    });
    await loadSessions();
    setSessionId(created.id);
    setMessages([]);
    setFollowups([]);
    setHighlight(null);
  }, [courseId, studentId, loadSessions]);

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      try {
        const list = await loadSessions();
        if (cancelled) return;
        if (list.length > 0) await openSession(list[0].id);
        else await newSession();
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load sessions");
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, [loadSessions, openSession, newSession]);

  useEffect(() => {
    setPaneSourceId((current) => current ?? sources.find((s) => s.status === "ready")?.id ?? null);
  }, [sources]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    if (!quoted) return;
    setInput((current) =>
      current ? current : `About this passage:
"${quoted.slice(0, 400)}"

`,
    );
    onQuotedConsumed?.();
  }, [quoted, onQuotedConsumed]);

  async function send(text: string) {
    if (!sessionId || !text.trim() || sending) return;
    setSending(true);
    setError(null);
    setFollowups([]);
    pending.current += 1;

    const optimistic: ChatMessage = {
      id: `pending-${pending.current}`,
      role: "user",
      content: text,
      citations: [],
      grounding_status: null,
      coverage: null,
      outside_knowledge: null,
      language,
      audio_url: null,
      latency_ms: null,
      created_at: "",
    };
    setMessages((current) => [...current, optimistic]);
    setInput("");

    try {
      const response = await post<AskResponse>(`/api/chat/sessions/${sessionId}/ask`, {
        message: text,
        language,
        speak: false,
      });
      setMessages((current) => [
        ...current.filter((item) => item.id !== optimistic.id),
        response.user_message,
        response.message,
      ]);
      setFollowups(response.followups);
      void loadSessions();
    } catch (cause) {
      setMessages((current) => current.filter((item) => item.id !== optimistic.id));
      setInput(text);
      setError(cause instanceof Error ? cause.message : "The tutor could not answer");
    } finally {
      setSending(false);
    }
  }

  async function toggleRecording() {
    if (recording) {
      recorderRef.current?.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => chunks.push(event.data);
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const form = new FormData();
        form.append("file", new Blob(chunks, { type: "audio/webm" }), "question.webm");
        try {
          const response = await fetch(`${API_BASE}/api/chat/transcribe`, { method: "POST", body: form });
          if (!response.ok) throw new Error("Transcription failed");
          const payload = (await response.json()) as { text: string };
          setInput(payload.text);
        } catch {
          setError("Could not transcribe that recording");
        }
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
    } catch {
      setError("Microphone access was denied");
    }
  }

  function pin(citation: Citation) {
    setHighlight(citation);
    setSplitOpen(true);
  }

  const chatPane = (
    <Panel className="flex h-full min-h-0 flex-col overflow-hidden" padded={false}>
      <div className="flex flex-wrap items-center gap-2 border-b px-3.5 py-2.5">
        <span className="min-w-0 flex-1 truncate text-xs text-[var(--ink-soft)]">
          {sessions.find((s) => s.id === sessionId)?.title ?? courseTitle}
        </span>

        <select
          className="input h-7 w-auto py-0.5 text-xs"
          value={language}
          onChange={(event) => setLanguage(event.target.value)}
        >
          {LANGUAGES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={clsx("btn px-2 py-1", splitOpen && "btn-primary")}
          onClick={() => setSplitOpen((v) => !v)}
          title={splitOpen ? "Close material pane" : "Open material alongside"}
        >
          {splitOpen ? (
            <PanelRightClose className="h-3.5 w-3.5" />
          ) : (
            <PanelRightOpen className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      <div className="scroll-slim min-h-0 flex-1 space-y-4 overflow-auto px-4 py-4">
        {messages.length === 0 ? (
          <Blank
            title="Ask about your course material"
            description="Every factual sentence is cited. Press the highlighter on a citation to see that passage in place."
          />
        ) : null}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[var(--iris)] px-3.5 py-2.5 text-sm text-white">
                {message.content}
              </div>
            </div>
          ) : (
            <motion.div
              key={message.id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
              className="max-w-[92%]"
            >
              <div className="glass rounded-2xl rounded-bl-sm px-3.5 py-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <GroundingChip status={message.grounding_status} />
                  {message.latency_ms ? (
                    <span className="num text-[10px] text-[var(--ink-faint)]">
                      {(message.latency_ms / 1000).toFixed(1)}s
                    </span>
                  ) : null}
                </div>

                <div className="prose-tutor">
                  <RichText>{message.content}</RichText>
                </div>

                {message.outside_knowledge ? (
                  <div
                    className="mt-3 rounded-xl border p-2.5"
                    style={{
                      borderColor: "var(--amber)",
                      background: "color-mix(in srgb, var(--amber) 10%, transparent)",
                    }}
                  >
                    <p className="mb-1 text-[11px] font-semibold text-[var(--amber)]">
                      Outside your course material
                    </p>
                    <p className="text-xs leading-relaxed">{message.outside_knowledge}</p>
                  </div>
                ) : null}

                {message.citations.length > 0 ? (
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                    {message.citations.map((citation) => (
                      <span key={`${citation.unit_id}-${citation.marker}`} className="flex items-center gap-1">
                        <CitationChip citation={citation} onOpen={onOpenCitation} />
                        <button
                          type="button"
                          className="btn px-1.5 py-1"
                          title="Show this passage alongside"
                          onClick={() => pin(citation)}
                        >
                          <Highlighter className="h-3 w-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </motion.div>
          ),
        )}

        {sending ? (
          <div className="flex items-center gap-2 text-sm text-[var(--ink-soft)]">
            <Spinner /> Searching your material
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      {followups.length > 0 ? (
        <div className="flex flex-wrap gap-1.5 border-t px-4 py-2">
          {followups.map((item) => (
            <button key={item} type="button" className="btn px-2 py-1 text-[11px]" onClick={() => send(item)}>
              {item}
            </button>
          ))}
        </div>
      ) : null}

      <div className="border-t px-4 py-3">
        {error ? (
          <div className="mb-2">
            <Notice message={error} />
          </div>
        ) : null}
        <div className="flex gap-2">
          <button
            type="button"
            className={clsx("btn px-2.5", recording && "btn-primary")}
            onClick={toggleRecording}
            title={recording ? "Stop" : "Dictate"}
          >
            {recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </button>
          <textarea
            className="input resize-none"
            rows={1}
            placeholder={`Ask about ${courseTitle}`}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send(input);
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary px-3"
            disabled={sending || !input.trim()}
            onClick={() => send(input)}
          >
            {sending ? <Spinner /> : <Send className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </Panel>
  );

  return (
    <div
      className={clsx(
        "grid h-[calc(100vh-240px)] min-h-[520px] gap-4",
        splitOpen ? "lg:grid-cols-[auto_minmax(0,1fr)] xl:grid-cols-[auto_1fr_1fr]" : "lg:grid-cols-[auto_minmax(0,1fr)]",
      )}
    >
      <div className="min-h-0">
        <SessionRail
          sessions={sessions}
          activeId={sessionId}
          onSelect={(id) => void openSession(id)}
          onCreate={() => void newSession()}
          onDelete={async (id) => {
            await del(`/api/chat/sessions/${id}`);
            const list = await loadSessions();
            if (id === sessionId) {
              if (list.length > 0) await openSession(list[0].id);
              else await newSession();
            }
          }}
          storageKey="lucify.chatRail"
          label="Sessions"
          newLabel="New chat session"
          emptyNote="No past chats yet."
        />
      </div>

      {chatPane}
      {splitOpen ? (
        <motion.div
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.28 }}
          className="hidden min-h-0 xl:block"
        >
          <MaterialPane
            courseId={courseId}
            sources={sources}
            highlight={highlight}
            selectedSourceId={paneSourceId}
            onSelectSource={setPaneSourceId}
            onClearHighlight={() => setHighlight(null)}
          />
        </motion.div>
      ) : null}
    </div>
  );
}
