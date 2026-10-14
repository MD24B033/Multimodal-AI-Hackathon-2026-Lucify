"use client";

import clsx from "clsx";
import { AnimatePresence, motion } from "motion/react";
import { useRef, useState, type ReactNode } from "react";

type Side = "top" | "bottom" | "left" | "right";

const POSITION: Record<Side, string> = {
  top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
  bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
  left: "right-full top-1/2 -translate-y-1/2 mr-2",
  right: "left-full top-1/2 -translate-y-1/2 ml-2",
};

const OFFSET: Record<Side, { x?: number; y?: number }> = {
  top: { y: 4 },
  bottom: { y: -4 },
  left: { x: 4 },
  right: { x: -4 },
};

/** Explains a control after a short dwell, so the interface stays uncluttered
 *  for people who already know what it does. */
export function Hint({
  label,
  children,
  side = "top",
  delay = 550,
  className,
}: {
  label: ReactNode;
  children: ReactNode;
  side?: Side;
  delay?: number;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const timer = useRef<number | null>(null);

  function schedule() {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  }

  function cancel() {
    if (timer.current) window.clearTimeout(timer.current);
    setOpen(false);
  }

  return (
    <span
      className={clsx("relative inline-flex", className)}
      onMouseEnter={schedule}
      onMouseLeave={cancel}
      onFocus={schedule}
      onBlur={cancel}
    >
      {children}
      <AnimatePresence>
        {open ? (
          <motion.span
            role="tooltip"
            initial={{ opacity: 0, ...OFFSET[side] }}
            animate={{ opacity: 1, x: 0, y: 0 }}
            exit={{ opacity: 0, ...OFFSET[side] }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className={clsx(
              "pointer-events-none absolute z-[60] w-max max-w-[220px] rounded-lg border px-2.5 py-1.5",
              "text-[11px] leading-snug",
              POSITION[side],
            )}
            style={{
              background: "var(--bg-1)",
              borderColor: "var(--edge-strong)",
              color: "var(--ink)",
              boxShadow: "0 12px 28px -14px rgba(0,0,0,0.75)",
            }}
          >
            {label}
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  );
}
