"use client";

import {
  AlertTriangle,
  BadgeCheck,
  FileText,
  Info,
  Mic,
  Send,
  Square,
  Volume2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { CitationList } from "@/components/source-viewer";
import { RichText } from "@/components/rich-text";
import { Chip, Panel, Blank, Notice, Spinner } from "@/components/ui";
import { API_BASE, get, mediaUrl, post } from "@/lib/api";
import type { AskResponse, ChatMessage, ChatSession, Citation, Source } from "@/lib/types";

const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "hi", label: "हिंदी" },
  { value: "hinglish", label: "Hinglish" },
];

function GroundingBadge({ status }: { status: ChatMessage["grounding_status"] }) {
  if (!status) return null;
  if (status === "grounded") {
    return (
      <Chip tone="mint">
        <BadgeCheck className="h-3 w-3" /> grounded
      </Chip>
    );
  }
  if (status === "partial") {
    return (
      <Chip tone="amber">
        <Info className="h-3 w-3" /> partially covered
      </Chip>
    );
  }
  return (
    <Chip tone="rose">
      <AlertTriangle className="h-3 w-3" /> not in your material
    </Chip>
  );
}

export function GroundedChat({
  courseId,
  courseTitle,
  studentId,
  studentName,
  sources,
  scopedSourceId,
  onScopeChange,
  onOpenCitation,
  storageKey,
}: {
  courseId: string;
  courseTitle: string;
  studentId: string;
  studentName: string;
  sources: Source[];
  scopedSourceId: string | null;
  onScopeChange?: (sourceId: string | null) => void;
  onOpenCitation: (citation: Citation) => void;
  storageKey: string;
}) {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [language, setLanguage] = useState("en");
  const [speak, setSpeak] = useState(false);
  const [sending, setSending] = useState(false);
  const [recording, setRecording] = useState(false);
  const [followups, setFollowups] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const pendingCounter = useRef(0);

  const startSession = useCallback(async () => {
    try {
      const created = await post<ChatSession>("/api/chat/sessions", {
        course_id: courseId,
        student_id: studentId,
        title: storageKey === "pdf" ? "Document chat" : null,
      });
      setSession(created);
      setMessages([]);
      setFollowups([]);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start a session");
    }
  }, [courseId, studentId, storageKey]);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      try {
        const existing = await get<ChatSession[]>(
          `/api/chat/sessions?course_id=${courseId}&student_id=${studentId}`,
        );
        if (cancelled) return;
        if (existing.length > 0) {
          const full = await get<ChatSession>(`/api/chat/sessions/${existing[0].id}`);
          if (cancelled) return;
          setSession(full);
          setMessages(full.messages ?? []);
        } else {
          await startSession();
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load sessions");
      }
    }

    void restore();
    return () => {
      cancelled = true;
    };
  }, [courseId, studentId, startSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function send(text: string) {
    if (!session || !text.trim() || sending) return;
    setSending(true);
    setError(null);
    setFollowups([]);
    pendingCounter.current += 1;

    const optimistic: ChatMessage = {
      id: `pending-${pendingCounter.current}`,
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
      const response = await post<AskResponse>(`/api/chat/sessions/${session.id}/ask`, {
        message: text,
        language,
        speak,
        source_ids: scopedSourceId ? [scopedSourceId] : null,
      });
      setMessages((current) => [
        ...current.filter((item) => item.id !== optimistic.id),
        response.user_message,
        response.message,
      ]);
      setFollowups(response.followups);
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
          const response = await fetch(`${API_BASE}/api/chat/transcribe`, {
            method: "POST",
            body: form,
          });
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

  const scopedSource = sources.find((item) => item.id === scopedSourceId) ?? null;

  return (
    <Panel className="flex h-[calc(100vh-190px)] flex-col" padded={false}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold">
            {scopedSource ? `Chatting with ${scopedSource.title}` : "Grounded tutor"}
          </h2>
          <p className="truncate text-xs text-[var(--ink-soft)]">
            {scopedSource
              ? "Answers come only from this document."
              : `Answers come only from ${courseTitle}, adapted to ${studentName}.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {onScopeChange ? (
            <select
              className="input h-8 w-auto max-w-[220px] py-1 text-xs"
              value={scopedSourceId ?? ""}
              onChange={(event) => onScopeChange(event.target.value || null)}
            >
              <option value="">Whole course</option>
              {sources
                .filter((item) => item.status === "ready")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
            </select>
          ) : null}
          <select
            className="input h-8 w-auto py-1 text-xs"
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
            className={`btn px-2 py-1 ${speak ? "btn-primary" : ""}`}
            title="Read answers aloud"
            onClick={() => setSpeak((current) => !current)}
          >
            <Volume2 className="h-3.5 w-3.5" />
          </button>
          <button type="button" className="btn px-2 py-1 text-xs" onClick={startSession}>
            New chat
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-auto px-4 py-4">
        {messages.length === 0 ? (
          <Blank
            title={scopedSource ? "Ask about this document" : "Ask about your course material"}
            description="Every factual sentence is cited, and anything your sources do not cover is flagged rather than guessed."
            icon={<FileText className="h-6 w-6" />}
          />
        ) : null}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="flex justify-end">
              <div className="max-w-[78%] rounded-xl rounded-br-sm bg-[var(--iris)] px-3.5 py-2.5 text-sm text-white">
                {message.content}
              </div>
            </div>
          ) : (
            <div key={message.id} className="max-w-[90%]">
              <div className="rounded-xl rounded-bl-sm border bg-[var(--glass-strong)] px-3.5 py-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <GroundingBadge status={message.grounding_status} />
                  {message.latency_ms ? (
                    <span className="text-[11px] text-[var(--ink-soft)]">
                      {(message.latency_ms / 1000).toFixed(1)}s
                    </span>
                  ) : null}
                </div>

                <div className="prose-tutor">
                  <RichText>{message.content}</RichText>
                </div>

                {message.outside_knowledge ? (
                  <div className="mt-3 rounded-lg border border-[var(--amber)] bg-[var(--warning-soft)] p-2.5">
                    <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-[var(--amber)]">
                      <Info className="h-3.5 w-3.5" /> Outside your course material
                    </p>
                    <p className="text-xs leading-relaxed">{message.outside_knowledge}</p>
                  </div>
                ) : null}

                <CitationList citations={message.citations} onOpen={onOpenCitation} />

                {message.audio_url ? (
                  <audio controls className="mt-2.5 h-8 w-full" src={mediaUrl(message.audio_url)} />
                ) : null}
              </div>
            </div>
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
            <button key={item} type="button" className="btn px-2 py-1 text-xs" onClick={() => send(item)}>
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
            className={`btn px-2.5 ${recording ? "btn-primary" : ""}`}
            onClick={toggleRecording}
            title={recording ? "Stop recording" : "Ask by voice"}
          >
            {recording ? <Square className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
          </button>
          <textarea
            className="input resize-none"
            rows={1}
            placeholder={scopedSource ? `Ask about ${scopedSource.title}` : `Ask about ${courseTitle}`}
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
}
