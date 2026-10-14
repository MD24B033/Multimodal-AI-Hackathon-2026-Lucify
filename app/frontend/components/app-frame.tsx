"use client";

import clsx from "clsx";

import { Logo } from "@/components/logo";
import { motion, useMotionValueEvent, useScroll } from "motion/react";
import {
  BrainCircuit,
  CalendarRange,
  Gauge,
  Layers,
  LogOut,
  Moon,
  Settings2,
  Sun,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useSession } from "@/components/session-context";
import { Notice, Spinner } from "@/components/ui";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/about", label: "About" },
];

export const SIDEBAR_SECTIONS = [
  { key: "courses", label: "Courses", icon: Layers },
  { key: "planner", label: "Planner", icon: CalendarRange },
  { key: "insights", label: "Insights", icon: Gauge },
  { key: "memory", label: "Memory", icon: BrainCircuit },
  { key: "settings", label: "Settings", icon: Settings2 },
] as const;


function ThemeAndAccount() {
  const { authRequired, student, signOut, theme, toggleTheme } = useSession();
  return (
    <div className="flex items-center gap-2">
      {student ? (
        <span className="hidden items-center gap-2 rounded-full border px-2.5 py-1 text-xs text-[var(--ink-soft)] sm:flex">
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--iris)] text-[10px] font-semibold text-white">
            {student.name.slice(0, 1).toUpperCase()}
          </span>
          {student.name}
        </span>
      ) : null}
      <button
        type="button"
        className="btn btn-ghost px-2"
        onClick={toggleTheme}
        title={theme === "dark" ? "Switch to light" : "Switch to dark"}
      >
        {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </button>
      {authRequired ? (
        <button type="button" className="btn btn-ghost px-2" onClick={signOut} title="Sign out">
          <LogOut className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

function MarketingNav() {
  const pathname = usePathname();
  const { scrollY } = useScroll();
  const [lifted, setLifted] = useState(false);

  useMotionValueEvent(scrollY, "change", (value) => setLifted(value > 12));

  return (
    <motion.header
      initial={{ y: -64, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.5, ease: [0.2, 0.7, 0.3, 1] }}
      className={clsx(
        "sticky top-0 z-40 border-b transition-[background,border-color,box-shadow] duration-300",
        lifted
          ? "border-[var(--edge-strong)] bg-[color-mix(in_srgb,var(--bg-0)_88%,transparent)] shadow-[0_12px_30px_-22px_rgba(0,0,0,0.9)] backdrop-blur-2xl"
          : "border-transparent bg-[color-mix(in_srgb,var(--bg-0)_60%,transparent)] backdrop-blur-xl",
      )}
    >
      {/* A hairline that only appears once the page has moved, so the bar reads as
          floating over the content rather than welded to it. */}
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-px"
        style={{
          background:
            "linear-gradient(90deg, transparent, color-mix(in srgb, var(--iris) 70%, transparent), transparent)",
        }}
        animate={{ opacity: lifted ? 1 : 0, scaleX: lifted ? 1 : 0.4 }}
        transition={{ duration: 0.4 }}
      />

      <div className="mx-auto flex max-w-[1240px] items-center gap-5 px-5 py-3">
        <Link href="/" className="group flex items-center gap-2.5">
          <motion.span
            whileHover={{ rotate: -6, scale: 1.06 }}
            whileTap={{ scale: 0.95 }}
            transition={{ type: "spring", stiffness: 420, damping: 16 }}
            className="inline-flex"
          >
            <Logo size={30} />
          </motion.span>
          <span className="display text-[15px] tracking-tight">Lucify</span>
        </Link>

        <nav className="ml-3 flex items-center gap-1">
          {NAV_LINKS.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={clsx(
                  "relative rounded-xl px-3 py-1.5 text-sm transition-colors",
                  active ? "text-[var(--ink)]" : "text-[var(--ink-soft)] hover:text-[var(--ink)]",
                )}
              >
                {/* One shared element slides between tabs instead of each one
                    fading its own background in and out. */}
                {active ? (
                  <motion.span
                    layoutId="nav-pill"
                    className="absolute inset-0 -z-10 rounded-xl bg-[var(--glass-strong)] ring-1 ring-[var(--edge)]"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  />
                ) : null}
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto">
          <ThemeAndAccount />
        </div>
      </div>
    </motion.header>
  );
}

function WorkspaceRail() {
  const { profiles, profile, selectProfile } = useSession();
  return (
    <header className="sticky top-0 z-40 border-b border-[var(--edge)] bg-[color-mix(in_srgb,var(--bg-0)_74%,transparent)] backdrop-blur-xl">
      <div className="flex items-center gap-4 px-5 py-3">
        <Link href="/" className="flex items-center gap-2.5" title="Back to home">
          <Logo size={30} />
          <span className="display text-[15px] tracking-tight">Lucify</span>
        </Link>

        <div className="ml-auto flex items-center gap-2">
          {profiles.length > 0 ? (
            <div className="relative hidden items-center sm:flex">
              <Layers className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-[var(--ink-faint)]" />
              <select
                className="input h-8 w-auto py-1 pl-7 text-xs"
                value={profile?.id ?? ""}
                onChange={(event) => selectProfile(event.target.value)}
                title="Switch profile"
              >
                {profiles.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
          <ThemeAndAccount />
        </div>
      </div>
    </header>
  );
}

export function AppFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { ready, authRequired, student, error } = useSession();

  const onLogin = pathname === "/login";
  const inWorkspace = pathname.startsWith("/dashboard") || pathname.startsWith("/courses");
  const locked = ready && authRequired && student === null;

  useEffect(() => {
    if (locked && !onLogin) router.replace("/login");
  }, [locked, onLogin, router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--ink-soft)]">
        <Spinner className="mr-2.5" />
        <span className="text-sm">Waking the companion</span>
      </div>
    );
  }

  if (onLogin) return <main className="min-h-screen">{children}</main>;

  if (locked) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--ink-soft)]">
        <Spinner className="mr-2.5" />
        <span className="text-sm">Redirecting to sign in</span>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      {inWorkspace ? <WorkspaceRail /> : <MarketingNav />}

      <motion.main
        key={pathname}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: [0.2, 0.7, 0.3, 1] }}
        className={clsx(
          "flex-1",
          inWorkspace ? "w-full px-5 py-6" : "mx-auto w-full max-w-[1240px] px-5 py-8",
        )}
      >
        {error ? (
          <div className="mb-5">
            <Notice message={`${error}. Is the backend running?`} />
          </div>
        ) : null}
        {children}
      </motion.main>
    </div>
  );
}
