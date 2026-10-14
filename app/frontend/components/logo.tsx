"use client";

import clsx from "clsx";

export type LogoState = "cycle" | "rest" | "pulse" | "flip" | "connect";

/** The Lucify mark: an open book with a circuit brain between its pages.
 *  Left to itself it cycles through four states — rest, brain pulse, book flip,
 *  tech connection — and a single state can be pinned for export. */
export function Logo({
  size = 30,
  state = "cycle",
  className,
}: {
  size?: number;
  state?: LogoState;
  className?: string;
}) {
  const cycling = state === "cycle";

  return (
    <span
      className={clsx(
        "relative flex shrink-0 items-center justify-center overflow-hidden rounded-[10px] border",
        className,
      )}
      style={{
        height: size,
        width: size,
        borderColor: "var(--edge-strong)",
        background: "var(--ink)",
      }}
      aria-hidden
    >
      <svg viewBox="0 0 64 64" className="h-[88%] w-[88%]" fill="none">
        <ellipse
          cx="32"
          cy="21"
          rx="19"
          ry="15"
          fill="var(--iris)"
          className={clsx("mk-glow", cycling && "mk-glow-cycle")}
          opacity={state === "pulse" ? 0.8 : 0}
          style={{ filter: "blur(5px)" }}
        />

        <g
          stroke="var(--bg-0)"
          strokeWidth="2.6"
          strokeLinejoin="round"
          strokeLinecap="round"
          fill="none"
        >
          <path d="M32 56 5 46V22l27 10Z" />
          <path
            d="M32 56 59 46V22L32 32Z"
            className={clsx("mk-page", cycling && "mk-page-cycle")}
            style={{
              transformBox: "view-box",
              transformOrigin: "32px 46px",
              transform: state === "flip" ? "scaleX(0.12)" : undefined,
            }}
          />
          <path d="M32 32v24" strokeWidth="2.2" />
        </g>

        <g
          className={clsx("mk-brain", cycling && "mk-brain-cycle")}
          style={{
            transformBox: "view-box",
            transformOrigin: "32px 21px",
            transform: state === "pulse" ? "scale(1.07)" : undefined,
          }}
        >
          <g stroke="var(--iris)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" fill="none">
            <path d="M32 6c-8-1.6-14.5 3-14.5 9.4-4.4 1.5-4.4 8.7 0 11 1.2 5 7.3 6.7 14.5 5.7Z" />
            <path d="M32 6c8-1.6 14.5 3 14.5 9.4 4.4 1.5 4.4 8.7 0 11-1.2 5-7.3 6.7-14.5 5.7Z" />
          </g>

          <g
            stroke="var(--iris)"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
            fill="none"
            className={clsx("mk-trace", cycling && "mk-trace-cycle")}
            style={{ strokeDashoffset: state === "connect" ? 0 : undefined }}
          >
            <path d="M25 11v5h-5.6" />
            <path d="M27.5 30h-5v-5.6" />
            <path d="M39 11v5h5.6" />
            <path d="M36.5 30h5v-5.6" />
          </g>

          <g
            fill="var(--iris)"
            className={clsx("mk-node", cycling && "mk-node-cycle")}
            opacity={state === "connect" ? 1 : 0.32}
          >
            <circle cx="18.9" cy="16" r="2" />
            <circle cx="22.1" cy="24.4" r="1.8" />
            <circle cx="45.1" cy="16" r="2" />
            <circle cx="41.9" cy="24.4" r="1.8" />
          </g>
        </g>
      </svg>
    </span>
  );
}

export function Wordmark({
  size = 30,
  state = "cycle",
  className,
}: {
  size?: number;
  state?: LogoState;
  className?: string;
}) {
  return (
    <span className={clsx("flex items-center gap-2.5", className)}>
      <Logo size={size} state={state} />
      <span className="display tracking-tight" style={{ fontSize: size * 0.5 }}>
        Lucify
      </span>
    </span>
  );
}
