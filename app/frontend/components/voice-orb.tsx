"use client";

import clsx from "clsx";
import { motion } from "motion/react";

export type OrbPhase = "off" | "connecting" | "listening" | "thinking" | "speaking";

const ACCENT: Record<OrbPhase, string> = {
  off: "var(--iris)",
  connecting: "var(--amber)",
  listening: "var(--iris)",
  thinking: "var(--amber)",
  speaking: "var(--mint)",
};

const SECOND: Record<OrbPhase, string> = {
  off: "var(--cyan)",
  connecting: "var(--iris)",
  listening: "var(--cyan)",
  thinking: "var(--iris)",
  speaking: "var(--cyan)",
};

/** The voice stage. Continuous motion comes from CSS so it costs nothing per frame;
 *  only the amplitude-driven scale is animated from React. */
export function VoiceOrb({
  phase,
  level,
  size = 232,
}: {
  phase: OrbPhase;
  level: number;
  size?: number;
}) {
  const live = phase !== "off";
  const amplitude = Math.min(1, level * 9);
  const accent = ACCENT[phase];
  const second = SECOND[phase];

  return (
    <div
      className="relative grid place-items-center"
      style={
        {
          width: size,
          height: size,
          "--orb": accent,
          "--orb-2": second,
        } as React.CSSProperties
      }
    >
      <motion.div
        className="pointer-events-none absolute inset-0 rounded-full"
        style={{
          background:
            "radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--orb) 34%, transparent) 0%, transparent 68%)",
          filter: "blur(22px)",
        }}
        animate={{ scale: live ? 1 + amplitude * 0.42 : 0.82, opacity: live ? 0.65 + amplitude * 0.35 : 0.25 }}
        transition={{ type: "spring", stiffness: 190, damping: 22 }}
      />

      <svg
        viewBox="0 0 100 100"
        className="absolute inset-0 h-full w-full"
        aria-hidden
        style={{ opacity: live ? 1 : 0.55 }}
      >
        <g className="orb-spin" style={{ transformOrigin: "50% 50%" }}>
          <circle
            cx="50"
            cy="50"
            r="47"
            fill="none"
            stroke="var(--orb)"
            strokeWidth="0.4"
            strokeDasharray="1 5"
            opacity="0.75"
          />
        </g>

        <g className={live ? "orb-spin-fast" : undefined} style={{ transformOrigin: "50% 50%" }}>
          <circle
            cx="50"
            cy="50"
            r="41"
            fill="none"
            stroke="var(--orb-2)"
            strokeWidth="0.6"
            strokeDasharray="26 140"
            strokeLinecap="round"
            opacity="0.85"
          />
          <circle
            cx="50"
            cy="50"
            r="41"
            fill="none"
            stroke="var(--orb-2)"
            strokeWidth="0.6"
            strokeDasharray="9 140"
            strokeDashoffset="-70"
            strokeLinecap="round"
            opacity="0.5"
          />
        </g>

        <circle
          cx="50"
          cy="50"
          r="34"
          fill="none"
          stroke="var(--orb)"
          strokeWidth="0.3"
          opacity="0.35"
        />
      </svg>

      {live ? (
        <div
          className="orb-scan pointer-events-none absolute rounded-full"
          style={{
            inset: "12%",
            background:
              "conic-gradient(from 0deg, transparent 0deg, color-mix(in srgb, var(--orb) 30%, transparent) 42deg, transparent 96deg)",
            maskImage: "radial-gradient(circle, transparent 56%, #000 60%, #000 78%, transparent 82%)",
            WebkitMaskImage:
              "radial-gradient(circle, transparent 56%, #000 60%, #000 78%, transparent 82%)",
          }}
        />
      ) : null}

      <motion.div
        className={clsx("relative rounded-full", live ? "orb-morph orb-drift" : "orb-morph")}
        style={{
          width: size * 0.46,
          height: size * 0.46,
          background:
            "radial-gradient(circle at 34% 30%, color-mix(in srgb, var(--orb-2) 85%, white 10%) 0%, var(--orb) 52%, color-mix(in srgb, var(--orb) 55%, black 30%) 100%)",
          boxShadow:
            "0 0 34px -6px color-mix(in srgb, var(--orb) 70%, transparent), inset 0 2px 14px rgba(255,255,255,0.28)",
        }}
        animate={{ scale: live ? 1 + amplitude * 0.17 : 0.9, opacity: live ? 1 : 0.72 }}
        transition={{ type: "spring", stiffness: 240, damping: 18 }}
      >
        <span
          className="absolute rounded-full"
          style={{
            inset: "14%",
            background:
              "radial-gradient(circle at 36% 26%, rgba(255,255,255,0.55) 0%, transparent 46%)",
          }}
        />
        {live ? (
          <span
            className="orb-flicker absolute rounded-full"
            style={{
              inset: 0,
              background:
                "radial-gradient(circle at 68% 74%, color-mix(in srgb, var(--orb-2) 60%, transparent) 0%, transparent 52%)",
            }}
          />
        ) : null}
      </motion.div>

      {live ? (
        <>
          <div className="orb-orbit pointer-events-none absolute inset-[6%]">
            <span
              className="absolute left-1/2 top-0 block h-1.5 w-1.5 -translate-x-1/2 rounded-full"
              style={{
                background: "var(--orb-2)",
                boxShadow: "0 0 10px 1px color-mix(in srgb, var(--orb-2) 80%, transparent)",
              }}
            />
          </div>
          <div className="orb-orbit-slow pointer-events-none absolute inset-[18%]">
            <span
              className="absolute left-1/2 top-0 block h-1 w-1 -translate-x-1/2 rounded-full"
              style={{
                background: "var(--orb)",
                boxShadow: "0 0 8px 1px color-mix(in srgb, var(--orb) 80%, transparent)",
              }}
            />
          </div>
        </>
      ) : null}
    </div>
  );
}

/** A compact level meter for the moments the orb is not the focus. */
export function VoiceWave({ active, level }: { active: boolean; level: number }) {
  const amplitude = Math.min(1, level * 9);
  return (
    <div className="flex h-5 items-center gap-[3px]" aria-hidden>
      {[0, 1, 2, 3, 4, 5, 6].map((index) => (
        <span
          key={index}
          className={active ? "wave-bar block w-[3px] rounded-full" : "block w-[3px] rounded-full"}
          style={{
            height: "100%",
            background: "var(--iris)",
            opacity: active ? 0.45 + amplitude * 0.55 : 0.2,
            transform: active ? undefined : "scaleY(0.3)",
            animationDelay: `${index * 0.09}s`,
          }}
        />
      ))}
    </div>
  );
}
