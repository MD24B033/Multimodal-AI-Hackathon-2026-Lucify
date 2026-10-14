"use client";

import { motion } from "motion/react";
import { ArrowRight, Cpu, Database, Eye, Mic, Shield } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Panel } from "@/components/ui";
import { get } from "@/lib/api";
import type { RuntimeConfig } from "@/lib/types";

const PIPELINE = [
  {
    icon: Database,
    title: "Ingestion",
    body: "Docling parses PDFs, slides and documents while keeping page numbers and bounding boxes. Video goes through ffmpeg and Whisper for timestamped transcripts. Slides with no text layer are rendered and read by a vision model.",
  },
  {
    icon: Eye,
    title: "Multimodal understanding",
    body: "Figures, plots and architecture diagrams are described in prose so they are retrievable by text search, with the original crop kept for display.",
  },
  {
    icon: Cpu,
    title: "Hybrid retrieval",
    body: "Vector search over pgvector is fused with PostgreSQL full-text search using reciprocal rank fusion. Embeddings run locally, so search costs no API quota.",
  },
  {
    icon: Shield,
    title: "Grounding",
    body: "A coverage gate refuses before the model is called. Answers come back as structured JSON that separates course-backed content from outside knowledge, and invented citation numbers are dropped.",
  },
  {
    icon: Mic,
    title: "Learner model",
    body: "Bayesian knowledge tracing with difficulty-conditioned slip and guess, IRT ability estimation for difficulty targeting, and SM-2 scheduling against the forgetting curve. No model calls involved.",
  },
];

export default function AboutPage() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);

  useEffect(() => {
    get<RuntimeConfig>("/api/config")
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  return (
    <div className="space-y-14 pb-16">
      <motion.section
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45 }}
        className="max-w-3xl pt-6"
      >
        <p className="eyebrow mb-3">How it works</p>
        <h1 className="display text-4xl sm:text-5xl">
          A tutor that <span className="gradient-text">shows its working.</span>
        </h1>
        <p className="mt-5 text-base leading-relaxed text-[var(--ink-soft)]">
          Most study assistants answer from whatever the model happened to learn. Lucify answers only
          from material you upload, and every claim carries a link back to the page, slide or second
          it came from. Where the material runs out, it says so.
        </p>
      </motion.section>

      <section className="space-y-4">
        {PIPELINE.map((item, index) => {
          const Icon = item.icon;
          return (
            <motion.div
              key={item.title}
              initial={{ opacity: 0, y: 14 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.38, delay: index * 0.05 }}
            >
              <Panel hover>
                <div className="flex gap-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-[var(--glass)]">
                    <Icon className="h-4 w-4 text-[var(--iris)]" />
                  </span>
                  <div>
                    <h2 className="display text-lg">{item.title}</h2>
                    <p className="mt-1.5 text-sm leading-relaxed text-[var(--ink-soft)]">{item.body}</p>
                  </div>
                </div>
              </Panel>
            </motion.div>
          );
        })}
      </section>

      {config ? (
        <section>
          <h2 className="display text-2xl">Running on</h2>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Generation", config.models.generation],
              ["Vision", config.models.vision],
              ["Verifier", config.models.verifier],
              ["Transcription", config.models.transcription],
              ["Embeddings", `${config.embedding_model} · local`],
              ["Retrieval top-k", String(config.retrieval.top_k)],
              ["Grounding threshold", String(config.retrieval.grounding_threshold)],
              ["Tokens / minute", String(config.rate_limit.tokens_per_minute)],
            ].map(([label, value]) => (
              <Panel key={label}>
                <p className="eyebrow">{label}</p>
                <p className="mt-2 truncate font-mono text-xs">{value}</p>
              </Panel>
            ))}
          </div>
          <p className="mt-4 text-xs text-[var(--ink-faint)]">
            The verifier is deliberately a different model family from the generator, so
            cross-checking a question is a genuine second opinion rather than a model marking its own
            work.
          </p>
        </section>
      ) : null}

      <section>
        <Panel raised className="p-8 text-center">
          <h2 className="display text-2xl">See it on your own notes.</h2>
          <Link href="/dashboard" className="btn btn-primary mt-5 px-5 py-2.5">
            Open dashboard <ArrowRight className="h-4 w-4" />
          </Link>
        </Panel>
      </section>
    </div>
  );
}
