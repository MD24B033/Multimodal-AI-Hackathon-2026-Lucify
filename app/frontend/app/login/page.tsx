"use client";

import { ArrowRight, KeyRound, Compass } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useSession } from "@/components/session-context";
import { Notice, Spinner } from "@/components/ui";

const HIGHLIGHTS = [
  "Lecture videos, textbooks and slides become one cited knowledge base",
  "Every answer opens the exact page, slide or timestamp it came from",
  "Quizzes adapt to what you actually know, and say when they do not know",
];

export default function LoginPage() {
  const router = useRouter();
  const { signInWithKey, authRequired, student, ready } = useSession();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && (!authRequired || student !== null)) router.replace("/");
  }, [ready, authRequired, student, router]);

  async function submit() {
    if (!key.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await signInWithKey(key);
      router.replace("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-5 py-12">
      <div className="fade-rise grid w-full max-w-4xl gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <div className="flex flex-col justify-center">
          <span className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-[var(--iris)] ">
            <Compass className="h-5 w-5 text-white" />
          </span>
          <h1 className="display text-4xl sm:text-5xl">
            Study from <span className="gradient-text">what you were actually taught.</span>
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-[var(--ink-soft)]">
            Lucify reads your course material and tutors you only from it. No invented facts, no
            answers that drift away from the syllabus.
          </p>

          <ul className="mt-7 space-y-3">
            {HIGHLIGHTS.map((item) => (
              <li key={item} className="rail flex gap-3 pl-4 text-sm text-[var(--ink-soft)]">
                {item}
              </li>
            ))}
          </ul>
        </div>

        <div className="glass-raised flex flex-col justify-center p-7">
          <p className="eyebrow mb-2">Private preview</p>
          <h2 className="display text-xl">Enter your access key</h2>
          <p className="mt-2 text-sm text-[var(--ink-soft)]">
            Keys are issued per person. Yours keeps its own progress, notes and quiz history.
          </p>

          <div className="mt-6">
            <label className="label">Access key</label>
            <div className="relative">
              <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--ink-faint)]" />
              <input
                className="input pl-9 font-mono"
                type="password"
                placeholder="your-key-here"
                value={key}
                autoFocus
                spellCheck={false}
                autoComplete="off"
                onChange={(event) => setKey(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && submit()}
              />
            </div>
          </div>

          {error ? (
            <div className="mt-4">
              <Notice message={error} />
            </div>
          ) : null}

          <button
            type="button"
            className="btn btn-primary mt-5 w-full py-2.5"
            disabled={busy || !key.trim()}
            onClick={submit}
          >
            {busy ? <Spinner /> : null}
            {busy ? "Checking" : "Continue"}
            {!busy ? <ArrowRight className="h-4 w-4" /> : null}
          </button>

          <p className="mt-5 text-xs leading-relaxed text-[var(--ink-faint)]">
            No sign-up. If you need a key, ask whoever shared this instance with you.
          </p>
        </div>
      </div>
    </div>
  );
}
