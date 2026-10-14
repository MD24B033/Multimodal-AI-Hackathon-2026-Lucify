"use client";

import clsx from "clsx";
import type { ReactNode } from "react";

type Tone = "neutral" | "iris" | "mint" | "amber" | "rose";

const TONE_TEXT: Record<Tone, string> = {
  neutral: "text-[var(--ink-soft)]",
  iris: "text-[var(--iris)]",
  mint: "text-[var(--mint)]",
  amber: "text-[var(--amber)]",
  rose: "text-[var(--rose)]",
};

const TONE_VAR: Record<Tone, string> = {
  neutral: "var(--ink-faint)",
  iris: "var(--iris)",
  mint: "var(--mint)",
  amber: "var(--amber)",
  rose: "var(--rose)",
};

export function Panel({
  children,
  className,
  padded = true,
  raised = false,
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  raised?: boolean;
  hover?: boolean;
}) {
  return (
    <div
      className={clsx(
        raised ? "glass-raised" : "glass",
        hover && "glass-hover",
        padded && "p-5",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function SectionHead({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow ? <p className="eyebrow mb-1.5">{eyebrow}</p> : null}
        <h2 className="display text-xl">{title}</h2>
        {description ? (
          <p className="mt-1.5 max-w-2xl text-sm text-[var(--ink-soft)]">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}

export function Chip({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium",
        TONE_TEXT[tone],
        className,
      )}
      style={{
        borderColor: tone === "neutral" ? "var(--edge)" : TONE_VAR[tone],
        background: tone === "neutral" ? "var(--glass)" : `color-mix(in srgb, ${TONE_VAR[tone]} 13%, transparent)`,
      }}
    >
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  hint,
  tone = "neutral",
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: Tone;
  icon?: ReactNode;
}) {
  return (
    <Panel className="relative overflow-hidden" hover>
      <div
        className="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full opacity-25 blur-2xl"
        style={{ background: TONE_VAR[tone] }}
      />
      <div className="flex items-start justify-between gap-3">
        <p className="eyebrow">{label}</p>
        {icon ? <span className="text-[var(--ink-faint)]">{icon}</span> : null}
      </div>
      <p className={clsx("display num mt-2.5 text-3xl", TONE_TEXT[tone])}>{value}</p>
      {hint ? <p className="mt-1 text-xs text-[var(--ink-faint)]">{hint}</p> : null}
    </Panel>
  );
}

export function Meter({
  value,
  showLabel = true,
  tone,
}: {
  value: number;
  showLabel?: boolean;
  tone?: Tone;
}) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const resolved: Tone = tone ?? (percent >= 75 ? "mint" : percent >= 45 ? "amber" : "rose");

  return (
    <div className="flex items-center gap-2.5">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--glass-strong)]">
        <div
          className="h-full rounded-full transition-[width] duration-700 ease-out"
          style={{
            width: `${percent}%`,
            background: TONE_VAR[resolved],
          }}
        />
      </div>
      {showLabel ? (
        <span className="num w-9 text-right text-xs text-[var(--ink-soft)]">{percent}%</span>
      ) : null}
    </div>
  );
}

export function Progress({ value, label }: { value: number; label?: string }) {
  const percent = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div>
      {label ? (
        <div className="mb-1.5 flex justify-between text-[11px] text-[var(--ink-soft)]">
          <span className="capitalize">{label}</span>
          <span className="num">{percent}%</span>
        </div>
      ) : null}
      <div className="h-1.5 overflow-hidden rounded-full bg-[var(--glass-strong)]">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${percent}%`, background: "var(--iris)" }}
        />
      </div>
    </div>
  );
}

export function Blank({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--radius)] border border-dashed px-6 py-14 text-center">
      {icon ? (
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl border bg-[var(--glass)] text-[var(--ink-soft)]">
          {icon}
        </div>
      ) : null}
      <p className="display text-base">{title}</p>
      {description ? (
        <p className="mt-1.5 max-w-sm text-sm text-[var(--ink-soft)]">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        "inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent",
        className,
      )}
      role="status"
      aria-label="Loading"
    />
  );
}

export function Notice({ message, tone = "rose" }: { message: string; tone?: Tone }) {
  return (
    <div
      className="rounded-xl border px-3.5 py-2.5 text-sm"
      style={{
        borderColor: TONE_VAR[tone],
        background: `color-mix(in srgb, ${TONE_VAR[tone]} 12%, transparent)`,
        color: TONE_VAR[tone],
      }}
    >
      {message}
    </div>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint ? <p className="mt-1.5 text-xs text-[var(--ink-faint)]">{hint}</p> : null}
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string; icon?: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="glass inline-flex gap-1 p-1">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={clsx(
              "flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-medium transition",
              active
                ? "bg-[var(--ink)] text-[var(--bg-0)]"
                : "text-[var(--ink-soft)] hover:text-[var(--ink)]",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
