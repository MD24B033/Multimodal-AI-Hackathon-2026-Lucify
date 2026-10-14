"use client";

import { motion, useMotionValue, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import {
  ArrowRight,
  BrainCircuit,
  FileSearch,
  FileText,
  MonitorPlay,
  Quote,
  Shapes,
  Target,
  Timer,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useSession } from "@/components/session-context";
import { Panel } from "@/components/ui";

const PILLARS = [
  {
    icon: Quote,
    title: "Cited, or it does not ship",
    body: "Every factual sentence carries the page, slide or timestamp it came from, and the citation opens it.",
  },
  {
    icon: FileSearch,
    title: "Reads what you actually have",
    body: "Textbooks, slide decks and lecture recordings. Diagrams are read by a vision model so they are searchable too.",
  },
  {
    icon: Target,
    title: "Knows when to say no",
    body: "If retrieval cannot cover your question, it declines before the model ever speaks. No confident guessing.",
  },
  {
    icon: BrainCircuit,
    title: "Models you, not an average",
    body: "Bayesian knowledge tracing per topic, difficulty targeted by ability, and a memory of how you like to learn.",
  },
  {
    icon: Waypoints,
    title: "Knows what comes first",
    body: "Prerequisites are derived from the material, so revision follows the order the subject actually demands.",
  },
  {
    icon: Timer,
    title: "Fights the forgetting curve",
    body: "Spaced repetition and a study plan built from the time left before your exam.",
  },
];

const STEPS = [
  { step: "01", title: "Upload", body: "Drop in a textbook, deck or recording. No preprocessing." },
  { step: "02", title: "It builds", body: "Topics, concepts and prerequisites, each unit linked to its origin." },
  { step: "03", title: "You learn", body: "Ask, read cited answers, make notes, then test yourself." },
];

const SOURCES = [
  { icon: FileText, label: "Textbook · page 42" },
  { icon: MonitorPlay, label: "Lecture · 18:04" },
  { icon: Shapes, label: "Slide 12 · figure" },
  { icon: FileText, label: "Chapter 2 · equation" },
  { icon: MonitorPlay, label: "Recording · 41:27" },
  { icon: Shapes, label: "Deck · diagram" },
];

const EXCHANGES = [
  {
    ask: "What is the difference between mitosis and meiosis?",
    answer: "Mitosis makes two identical cells for growth and repair; meiosis makes four cells with half the chromosomes, for reproduction.",
    cites: ["Biology · p.212", "Lecture · 18:04"],
  },
  {
    ask: "Explain supply and demand in simple terms.",
    answer: "Price settles where what people want to buy matches what sellers will supply; a shortage pushes it up, a surplus pulls it down.",
    cites: ["Economics · p.47", "Slide 11"],
  },
  {
    ask: "Who won the 2019 cricket world cup?",
    answer: "That is not in the uploaded material, so it will not be answered. Grounding means declining rather than guessing.",
    cites: [],
    refused: true,
  },
];function Aurora() {
  return (
    <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <div
        className="aurora-a absolute -left-32 -top-40 h-[32rem] w-[32rem] rounded-full blur-3xl"
        style={{ background: "var(--aurora-a)" }}
      />
      <div
        className="aurora-b absolute -right-40 top-10 h-[28rem] w-[28rem] rounded-full blur-3xl"
        style={{ background: "var(--aurora-c)" }}
      />
      <div
        className="absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, color-mix(in srgb, var(--ink) 16%, transparent) 1px, transparent 0)",
          backgroundSize: "26px 26px",
          maskImage: "radial-gradient(ellipse 80% 60% at 50% 0%, #000 40%, transparent 100%)",
          WebkitMaskImage: "radial-gradient(ellipse 80% 60% at 50% 0%, #000 40%, transparent 100%)",
        }}
      />
    </div>
  );
}

/** The product in miniature: a question lands, a cited answer comes back, and one of
 *  them is refused on purpose. It loops, so the refusal is never missed. */
function LiveAnswer() {
  const [index, setIndex] = useState(0);
  const [typed, setTyped] = useState("");
  const reduced = useReducedMotion();
  const current = EXCHANGES[index];

  useEffect(() => {
    if (reduced) {
      setTyped(current.ask);
      return;
    }
    setTyped("");
    let cursor = 0;
    const type = window.setInterval(() => {
      cursor += 1;
      setTyped(current.ask.slice(0, cursor));
      if (cursor >= current.ask.length) window.clearInterval(type);
    }, 26);
    return () => window.clearInterval(type);
  }, [index, current.ask, reduced]);

  useEffect(() => {
    const next = window.setTimeout(() => setIndex((value) => (value + 1) % EXCHANGES.length), 7200);
    return () => window.clearTimeout(next);
  }, [index]);

  return (
    <Panel raised className="relative min-h-[270px] overflow-hidden">
      <div
        className="scan-line pointer-events-none absolute inset-x-0 top-0 h-px"
        style={{ background: "linear-gradient(90deg, transparent, var(--iris), transparent)" }}
      />

      <p className="eyebrow mb-3">Example · how an answer comes back</p>

      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-2xl rounded-br-sm px-3.5 py-2.5 text-sm" style={{ background: "var(--iris)", color: "var(--bg-0)" }}>
          {typed}
          {typed.length < current.ask.length ? <span className="cursor-blink">▍</span> : null}
        </p>
      </div>

      <motion.div
        key={index}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: reduced ? 0 : 1.1, duration: 0.45 }}
        className="mt-3"
      >
        <p className="text-sm leading-relaxed">{current.answer}</p>

        <div className="mt-3 flex flex-wrap gap-1.5">
          {current.refused ? (
            <span
              className="rounded-lg border px-2 py-1 text-[11px]"
              style={{ borderColor: "var(--amber)", color: "var(--amber)" }}
            >
              refused — outside the sources
            </span>
          ) : (
            current.cites.map((cite) => (
              <span
                key={cite}
                className="rounded-lg border px-2 py-1 text-[11px]"
                style={{ borderColor: "var(--edge-strong)", background: "var(--glass)" }}
              >
                {cite}
              </span>
            ))
          )}
        </div>
      </motion.div>

      <div className="mt-4 flex gap-1.5">
        {EXCHANGES.map((item, dot) => (
          <span
            key={item.ask}
            className="h-1 rounded-full transition-all duration-500"
            style={{
              width: dot === index ? 22 : 7,
              background: dot === index ? "var(--iris)" : "var(--edge-strong)",
            }}
          />
        ))}
      </div>
    </Panel>
  );
}

function SourceMarquee() {
  const row = [...SOURCES, ...SOURCES];
  return (
    <div
      className="relative overflow-hidden py-1"
      style={{
        maskImage: "linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent)",
        WebkitMaskImage: "linear-gradient(90deg, transparent, #000 12%, #000 88%, transparent)",
      }}
    >
      <div className="marquee-track flex w-max gap-2.5">
        {row.map((item, index) => {
          const Icon = item.icon;
          return (
            <span
              key={`${item.label}-${index}`}
              className="flex shrink-0 items-center gap-2 rounded-xl border px-3 py-1.5 text-xs"
              style={{ borderColor: "var(--edge)", background: "var(--glass)" }}
            >
              <Icon className="h-3.5 w-3.5 text-[var(--iris)]" />
              {item.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** Upload → build → learn, with a dot actually travelling the path. */
function Pipeline() {
  return (
    <svg viewBox="0 0 600 70" className="h-16 w-full" fill="none" aria-hidden>
      <path
        id="pipeline-path"
        d="M30 35 C 170 35, 170 35, 300 35 S 430 35, 570 35"
        stroke="var(--edge-strong)"
        strokeWidth="1.5"
        strokeDasharray="4 6"
      />
      {[30, 300, 570].map((cx) => (
        <circle key={cx} cx={cx} cy="35" r="5" fill="var(--bg-0)" stroke="var(--iris)" strokeWidth="2" />
      ))}
      <circle
        r="4"
        fill="var(--iris)"
        className="beam-run"
        style={{ offsetPath: "path('M30 35 C 170 35, 170 35, 300 35 S 430 35, 570 35')" }}
      />
    </svg>
  );
}

export default function HomePage() {
  const { student, courses } = useSession();
  const heroRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const { scrollYProgress } = useScroll({ target: heroRef, offset: ["start start", "end start"] });
  const slow = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : 90]);
  const fast = useTransform(scrollYProgress, [0, 1], [0, reduced ? 0 : -120]);
  const fade = useTransform(scrollYProgress, [0, 0.8], [1, reduced ? 1 : 0.25]);

  // Pointer parallax, springy so it never feels twitchy.
  const px = useMotionValue(0);
  const py = useMotionValue(0);
  const tiltX = useSpring(useTransform(py, [-0.5, 0.5], [6, -6]), { stiffness: 140, damping: 18 });
  const tiltY = useSpring(useTransform(px, [-0.5, 0.5], [-8, 8]), { stiffness: 140, damping: 18 });

  return (
    <div
      className="space-y-24 pb-20"
      onPointerMove={(event) => {
        if (reduced) return;
        px.set(event.clientX / window.innerWidth - 0.5);
        py.set(event.clientY / window.innerHeight - 0.5);
      }}
    >
      <section ref={heroRef} className="relative pt-10 sm:pt-14">
        <Aurora />

        <div className="grid items-center gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
          <motion.div style={{ y: slow, opacity: fade }}>
            <motion.h1
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.55, ease: [0.2, 0.7, 0.3, 1] }}
              className="display text-5xl leading-[1.04] sm:text-6xl"
            >
              Study from <span className="gradient-text">what you were actually taught.</span>
            </motion.h1>

            <motion.p
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="mt-6 max-w-xl text-base leading-relaxed text-[var(--ink-soft)]"
            >
              Lucify turns your lecture videos, textbooks and slides into one cited knowledge base,
              then tutors and tests you from it. Nothing invented, nothing off-syllabus.
            </motion.p>

            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.18 }}
              className="mt-8 flex flex-wrap items-center gap-3"
            >
              <Link href="/dashboard" className="btn btn-primary px-5 py-2.5">
                {courses.length > 0 ? "Open dashboard" : "Get started"}
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link href="/about" className="btn px-4 py-2.5">
                How it works
              </Link>
            </motion.div>

            {student ? (
              <p className="mt-5 text-xs text-[var(--ink-faint)]">
                Signed in as {student.name}
                {courses.length > 0
                  ? ` · ${courses.length} course${courses.length === 1 ? "" : "s"} in this profile`
                  : ""}
              </p>
            ) : null}

            <div className="mt-9">
              <SourceMarquee />
            </div>
          </motion.div>

          <motion.div
            style={{ y: fast, rotateX: tiltX, rotateY: tiltY, transformPerspective: 1000 }}
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, delay: 0.15 }}
            className="min-w-0"
          >
            <LiveAnswer />
          </motion.div>
        </div>
      </section>

      <section>
        <Pipeline />
        <div className="grid gap-4 md:grid-cols-3">
          {STEPS.map((item, index) => (
            <motion.div
              key={item.step}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-80px" }}
              transition={{ duration: 0.45, delay: index * 0.1 }}
            >
              <Panel hover className="h-full">
                <span className="display num text-3xl text-[var(--iris)]">{item.step}</span>
                <h3 className="display mt-3 text-lg">{item.title}</h3>
                <p className="mt-1.5 text-sm text-[var(--ink-soft)]">{item.body}</p>
              </Panel>
            </motion.div>
          ))}
        </div>
      </section>

      <section>
        <motion.h2
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-60px" }}
          className="display text-2xl"
        >
          Why it is different
        </motion.h2>
        <p className="mt-2 max-w-xl text-sm text-[var(--ink-soft)]">
          A general chatbot answers from the internet. This answers from your syllabus, and shows
          its working.
        </p>

        <div className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {PILLARS.map((pillar, index) => {
            const Icon = pillar.icon;
            return (
              <motion.div
                key={pillar.title}
                initial={{ opacity: 0, y: 18 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, margin: "-60px" }}
                transition={{ duration: 0.42, delay: (index % 3) * 0.08 }}
              >
                <Panel hover className="h-full">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl border bg-[var(--glass)]">
                    <Icon className="h-4 w-4 text-[var(--iris)]" />
                  </span>
                  <h3 className="display mt-3.5 text-base">{pillar.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-soft)]">{pillar.body}</p>
                </Panel>
              </motion.div>
            );
          })}
        </div>
      </section>

      <section>
        <Panel raised className="relative overflow-hidden p-9 text-center">
          <div className="aurora-a pointer-events-none absolute -left-16 -top-20 h-56 w-56 rounded-full bg-[var(--iris)] opacity-25 blur-3xl" />
          <div className="aurora-b pointer-events-none absolute -bottom-24 -right-10 h-56 w-56 rounded-full bg-[var(--cyan)] opacity-20 blur-3xl" />
          <h2 className="display relative text-3xl">Ready when your material is.</h2>
          <p className="relative mx-auto mt-3 max-w-md text-sm text-[var(--ink-soft)]">
            One upload is enough to get a cited tutor, a topic map and your first adaptive quiz.
          </p>
          <Link href="/dashboard" className="btn btn-primary relative mt-6 px-5 py-2.5">
            Open dashboard <ArrowRight className="h-4 w-4" />
          </Link>
        </Panel>
      </section>
    </div>
  );
}
