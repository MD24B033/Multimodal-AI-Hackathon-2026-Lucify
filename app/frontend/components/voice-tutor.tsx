"use client";

import clsx from "clsx";
import {
  AudioLines,
  KeyRound,
  Loader2,
  Mic,
  ScrollText,
  Square,
  Trash2,
  Volume2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Hint } from "@/components/hint";
import { RichText } from "@/components/rich-text";
import { SessionRail, type SessionRow } from "@/components/session-rail";
import { CitationList } from "@/components/source-viewer";
import { Chip, Field, Notice, Panel, SectionHead, Spinner } from "@/components/ui";
import { VoiceOrb, VoiceWave } from "@/components/voice-orb";
import { API_BASE, del, get, post, readAccessKey } from "@/lib/api";
import { SpeechPlayer } from "@/lib/speech-player";
import type { AskResponse, ChatMessage, ChatSession, Citation } from "@/lib/types";
import { VoiceSession } from "@/lib/voice-session";

type VoiceStatus = {
  configured: boolean;
  hint: string | null;
  language_code: string;
  speaker: string;
  languages: { code: string; label: string }[];
  speakers: string[];
};

type Phase = "off" | "connecting" | "listening" | "thinking" | "speaking";

const BARGE_IN_GRACE_MS = 400;

const INTERRUPT_PHRASES = [
  "stop",
  "wait",
  "hold on",
  "one sec",
  "one second",
  "never mind",
  "ruko",
  "ruk jao",
  "bas",
];

function asksToStop(text: string): boolean {
  const normalised = text.toLowerCase();
  return INTERRUPT_PHRASES.some((phrase) => normalised.includes(phrase));
}

async function fetchSpeech(
  text: string,
  languageCode: string,
  speaker: string,
  signal: AbortSignal,
): Promise<ArrayBuffer> {
  const key = readAccessKey();
  const response = await fetch(`${API_BASE}/api/voice/speak`, {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      ...(key ? { "X-Access-Key": key } : {}),
    },
    body: JSON.stringify({ text, language_code: languageCode, speaker }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail.slice(0, 180) || "Speech synthesis failed");
  }
  return response.arrayBuffer();
}

export function VoiceTutor({
  courseId,
  courseTitle,
  studentId,
  onOpenCitation,
}: {
  courseId: string;
  courseTitle: string;
  studentId: string;
  onOpenCitation: (citation: Citation) => void;
}) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [language, setLanguage] = useState("en-IN");
  const [speaker, setSpeaker] = useState("priya");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [turns, setTurns] = useState<ChatMessage[]>([]);
  const [phase, setPhase] = useState<Phase>("off");
  const [partial, setPartial] = useState("");
  const [level, setLevel] = useState(0);

  const voiceRef = useRef<VoiceSession | null>(null);
  const playerRef = useRef<SpeechPlayer | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const turnLock = useRef(false);
  const graceUntil = useRef(0);
  const meterFrame = useRef<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const languageRef = useRef(language);
  const speakerRef = useRef(speaker);

  useEffect(() => {
    languageRef.current = language;
    speakerRef.current = speaker;
  }, [language, speaker]);

  const loadStatus = useCallback(async () => {
    try {
      const payload = await get<VoiceStatus>("/api/voice/status");
      setStatus(payload);
      setLanguage(payload.language_code);
      setSpeaker(payload.speaker);
    } catch {
      setStatus(null);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const loadSessions = useCallback(async () => {
    const list = await get<SessionRow[]>(
      `/api/chat/sessions?course_id=${courseId}&student_id=${studentId}&mode=voice`,
    );
    setSessions(list);
    return list;
  }, [courseId, studentId]);

  const openSession = useCallback(async (id: string) => {
    const full = await get<{ id: string; messages: ChatMessage[] }>(`/api/chat/sessions/${id}`);
    setSessionId(full.id);
    setTurns(full.messages);
    setPartial("");
  }, []);

  const newSession = useCallback(async () => {
    const created = await post<ChatSession>("/api/chat/sessions", {
      course_id: courseId,
      student_id: studentId,
      title: `Spoken session ${new Date().toLocaleDateString(undefined, { day: "numeric", month: "short" })}`,
      mode: "voice",
    });
    setSessionId(created.id);
    setTurns([]);
    setPartial("");
    await loadSessions();
  }, [courseId, studentId, loadSessions]);

  useEffect(() => {
    if (!status?.configured || sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const list = await loadSessions();
        if (cancelled) return;
        if (list.length > 0) await openSession(list[0].id);
        else await newSession();
      } catch {
        if (!cancelled) setError("Could not open a voice session.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status?.configured, sessionId, loadSessions, openSession, newSession]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns.length, partial]);

  const teardown = useCallback(async () => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (meterFrame.current !== null) {
      cancelAnimationFrame(meterFrame.current);
      meterFrame.current = null;
    }
    await playerRef.current?.dispose();
    playerRef.current = null;
    await voiceRef.current?.stop();
    voiceRef.current = null;
    turnLock.current = false;
    setPartial("");
    setLevel(0);
  }, []);

  useEffect(() => {
    return () => {
      void teardown();
    };
  }, [teardown]);

  async function saveKey() {
    if (!apiKey.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await post("/api/voice/credential", {
        api_key: apiKey.trim(),
        language_code: language,
        speaker,
      });
      setApiKey("");
      await loadStatus();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "That key was not accepted");
    } finally {
      setSaving(false);
    }
  }

  const interrupt = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    playerRef.current?.stop();
    turnLock.current = false;
    setPartial("");
    setPhase(voiceRef.current?.connected ? "listening" : "off");
  }, []);

  const runTurn = useCallback(
    async (spoken: string) => {
      if (!sessionId || turnLock.current) return;
      turnLock.current = true;

      const controller = new AbortController();
      abortRef.current = controller;
      setPartial("");
      setPhase("thinking");

      try {
        const answer = await post<AskResponse>(`/api/chat/sessions/${sessionId}/ask`, {
          message: spoken,
          language: languageRef.current.startsWith("hi") ? "hi" : "en",
          speak: false,
        });
        if (controller.signal.aborted) return;
        setTurns((current) => [...current, answer.user_message, answer.message]);
        void loadSessions().catch(() => undefined);

        const audio = await fetchSpeech(
          answer.message.content,
          languageRef.current,
          speakerRef.current,
          controller.signal,
        );
        if (controller.signal.aborted) return;

        graceUntil.current = Date.now() + BARGE_IN_GRACE_MS;
        setPhase("speaking");
        await playerRef.current?.play(audio);
        if (controller.signal.aborted) return;
        setPhase(voiceRef.current?.connected ? "listening" : "off");
      } catch (cause) {
        if (controller.signal.aborted || (cause as Error)?.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "That turn did not go through");
        setPhase(voiceRef.current?.connected ? "listening" : "off");
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        turnLock.current = false;
      }
    },
    [sessionId, loadSessions],
  );

  const startMeter = useCallback(() => {
    const tick = () => {
      const player = playerRef.current;
      if (player?.playing) {
        setLevel(player.level());
      } else if (!voiceRef.current?.connected) {
        setLevel(0);
      }
      meterFrame.current = requestAnimationFrame(tick);
    };
    meterFrame.current = requestAnimationFrame(tick);
  }, []);

  async function startConversation() {
    setError(null);
    setPhase("connecting");

    const player = new SpeechPlayer();
    playerRef.current = player;

    const session = new VoiceSession();
    voiceRef.current = session;

    session.on((event) => {
      switch (event.type) {
        case "level":
          if (!player.playing) setLevel(event.rms);
          break;
        case "partial":
          if (turnLock.current) {
            if (Date.now() >= graceUntil.current && asksToStop(event.text)) interrupt();
          } else {
            setPartial(event.text);
          }
          break;
        case "final":
          if (event.text.trim()) void runTurn(event.text.trim());
          break;
        case "error":
          setError(event.message);
          break;
        case "closed":
          setPhase("off");
          setLevel(0);
          break;
        default:
          break;
      }
    });

    try {
      await session.start("auto");
      startMeter();
      setPhase("listening");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The microphone could not be opened");
      await teardown();
      setPhase("off");
    }
  }

  async function replay(text: string) {
    const controller = new AbortController();
    try {
      const audio = await fetchSpeech(text, languageRef.current, speakerRef.current, controller.signal);
      playerRef.current ??= new SpeechPlayer();
      if (meterFrame.current === null) startMeter();
      await playerRef.current.play(audio);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not play that back");
    }
  }

  if (!loaded) {
    return (
      <Panel className="mx-auto max-w-xl">
        <div className="flex items-center justify-center gap-2 py-8 text-sm">
          <Spinner />
          Checking your voice setup
        </div>
      </Panel>
    );
  }

  if (!status) {
    return (
      <Panel raised className="mx-auto max-w-xl">
        <SectionHead
          eyebrow="Spoken tutoring"
          title="The voice service is out of reach"
          description="Lucify could not ask the server whether a Sarvam key is set up. That usually means the backend is still starting."
        />
        <button type="button" className="btn btn-primary w-full" onClick={() => void loadStatus()}>
          Try again
        </button>
      </Panel>
    );
  }

  if (!status.configured) {
    return (
      <Panel raised className="mx-auto max-w-xl">
        <SectionHead
          eyebrow="Spoken tutoring"
          title="Connect a Sarvam key"
          description="Sarvam lends a voice and an ear, nothing more. Which sources get quoted, what gets said and how your mastery updates all stay inside Lucify."
        />

        <div className="space-y-3">
          <Field
            label="Sarvam API key"
            hint="Held against your account and only ever shown as the last four characters"
          >
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 opacity-70" />
              <input
                className="input pl-9 font-mono"
                type="password"
                placeholder="your Sarvam subscription key"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && saveKey()}
              />
            </div>
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Speaking language">
              <select className="input" value={language} onChange={(event) => setLanguage(event.target.value)}>
                {status.languages.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Voice">
              <select className="input" value={speaker} onChange={(event) => setSpeaker(event.target.value)}>
                {status.speakers.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          {error ? <Notice message={error} /> : null}

          <button
            type="button"
            className="btn btn-primary w-full"
            disabled={saving || !apiKey.trim()}
            onClick={saveKey}
          >
            {saving ? <Spinner /> : <AudioLines className="h-4 w-4" />}
            {saving ? "Checking the key" : "Connect and verify"}
          </button>
          <p className="text-xs opacity-80">
            Keys come from sarvam.ai. Yours is checked with one short spoken phrase before it is stored.
          </p>
        </div>
      </Panel>
    );
  }

  const live = phase !== "off";
  const exchanges = turns.filter((turn) => turn.role === "user").length;
  const caption =
    phase === "off"
      ? "Start talking whenever you like"
      : phase === "connecting"
        ? "Opening the microphone"
        : phase === "listening"
          ? "Listening — just speak"
          : phase === "thinking"
            ? "Looking it up in your material"
            : "Speaking — say “stop” to cut in";

  return (
    <div className="grid gap-4 lg:grid-cols-[auto_minmax(0,1fr)_300px]">
      <div className="lg:sticky lg:top-4 lg:self-start">
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
          storageKey="lucify.voiceRail"
          label="Sessions"
          newLabel="New spoken session"
          emptyNote="No spoken sessions yet."
        />
      </div>

      <Panel className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px"
          style={{
            background:
              "linear-gradient(90deg, transparent, color-mix(in srgb, var(--iris) 60%, transparent), transparent)",
          }}
        />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="eyebrow mb-1">Spoken tutoring</p>
            <h3 className="display text-lg">Talk through {courseTitle}</h3>
          </div>
          <div className="flex items-center gap-2">
            {status.hint ? <Chip tone="mint">key {status.hint}</Chip> : null}
            <Hint label="Language the reply is spoken in. Your own speech is detected automatically.">
              <select
                className="input h-8 w-auto py-1 text-xs"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              >
                {status.languages.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.label}
                  </option>
                ))}
              </select>
            </Hint>
            <Hint label="Which Sarvam voice reads the answers">
              <select
                className="input h-8 w-auto py-1 text-xs"
                value={speaker}
                onChange={(event) => setSpeaker(event.target.value)}
              >
                {status.speakers.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </Hint>
            <Hint label="Forget the stored Sarvam key">
              <button
                type="button"
                className="btn px-2 py-1"
                onClick={async () => {
                  await teardown();
                  setPhase("off");
                  await del("/api/voice/credential");
                  await loadStatus();
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </Hint>
          </div>
        </div>

        <div className="mt-4 flex flex-col items-center gap-5 pb-1">
          <VoiceOrb phase={phase} level={level} />

          <div className="flex flex-col items-center gap-2">
            <div className="flex items-center gap-2.5">
              <span
                className={clsx("h-1.5 w-1.5 rounded-full", live && "tick")}
                style={{ background: live ? "var(--iris)" : "var(--ink-faint)" }}
              />
              <p className="text-sm">{caption}</p>
            </div>
            {live ? (
              <VoiceWave active={phase === "listening" || phase === "speaking"} level={level} />
            ) : null}
          </div>

          {partial ? (
            <p className="max-w-xl text-balance text-center text-sm opacity-80">{partial}</p>
          ) : (
            <p className="max-w-sm text-balance text-center text-xs opacity-70">
              {live
                ? "Nothing to press. It works out when you have finished speaking."
                : "Once started it stays open, and you can talk over an answer to cut it short."}
            </p>
          )}

          <Hint label={live ? "End the spoken session" : "Begin a hands-free spoken session"}>
            <button
              type="button"
              onClick={
                live ? () => void teardown().then(() => setPhase("off")) : () => void startConversation()
              }
              className={clsx(
                "btn gap-2 px-5",
                live ? "border-[var(--rose)] text-[var(--rose)]" : "btn-primary",
              )}
            >
              {phase === "thinking" || phase === "connecting" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : live ? (
                <Square className="h-4 w-4" />
              ) : (
                <Mic className="h-4 w-4" />
              )}
              {live ? "End session" : "Start talking"}
            </button>
          </Hint>
        </div>

        {error ? (
          <div className="mt-4">
            <Notice message={error} />
          </div>
        ) : null}
      </Panel>

      <aside className="lg:sticky lg:top-4 lg:self-start">
        <Panel className="flex max-h-[calc(100vh-7rem)] flex-col overflow-hidden p-0">
          <div
            className="flex items-center justify-between gap-2 border-b px-3.5 py-3"
            style={{ borderColor: "var(--edge)" }}
          >
            <div className="flex items-center gap-2">
              <ScrollText className="h-3.5 w-3.5 opacity-80" />
              <span className="eyebrow">Transcript</span>
            </div>
            {exchanges > 0 ? (
              <span className="text-[11px] opacity-70">
                {exchanges} {exchanges === 1 ? "exchange" : "exchanges"}
              </span>
            ) : null}
          </div>

          <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3.5 py-3">
            {turns.length === 0 ? (
              <p className="py-6 text-center text-xs leading-relaxed opacity-70">
                Nothing spoken yet. What you say and what comes back lands here, with the sources
                behind every answer.
              </p>
            ) : (
              turns.map((turn) =>
                turn.role === "user" ? (
                  <div key={turn.id} className="flex justify-end">
                    <p
                      className="max-w-[92%] rounded-xl rounded-br-sm px-2.5 py-1.5 text-[13px] leading-snug"
                      style={{ background: "var(--iris)", color: "var(--bg-0)" }}
                    >
                      {turn.content}
                    </p>
                  </div>
                ) : (
                  <div
                    key={turn.id}
                    className="rounded-xl border px-2.5 py-2"
                    style={{ borderColor: "var(--edge)", background: "var(--glass)" }}
                  >
                    <RichText className="text-[13px] leading-snug">{turn.content}</RichText>
                    <div className="mt-1.5 flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <CitationList citations={turn.citations} onOpen={onOpenCitation} />
                      </div>
                      <Hint label="Hear this answer again" side="left">
                        <button
                          type="button"
                          className="btn shrink-0 px-1.5 py-0.5"
                          onClick={() => void replay(turn.content)}
                        >
                          <Volume2 className="h-3 w-3" />
                        </button>
                      </Hint>
                    </div>
                  </div>
                ),
              )
            )}
            <div ref={bottomRef} />
          </div>
        </Panel>
      </aside>
    </div>
  );
}
