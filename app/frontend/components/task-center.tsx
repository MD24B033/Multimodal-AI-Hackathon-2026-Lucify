"use client";

import { AnimatePresence, motion } from "motion/react";
import { CheckCircle2, Loader2, TriangleAlert, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useSession } from "@/components/session-context";
import { API_BASE, get, post, readAccessKey } from "@/lib/api";
import {
  describeIngestion,
  formatEta,
  useIngestionFeed,
  type IngestionEvent,
} from "@/lib/use-ingestion-events";

export type GenerationTask = {
  id: string;
  kind: string;
  label: string;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress: number;
  course_id: string;
  result: Record<string, unknown>;
  error: string | null;
  acknowledged: boolean;
  created_at: string;
  finished_at: string | null;
};

type ToastItem = {
  id: string;
  label: string;
  ok: boolean;
  error: string | null;
};

type TaskValue = {
  tasks: GenerationTask[];
  active: GenerationTask[];
  busyFor: (courseId: string) => boolean;
  enqueue: (input: {
    course_id: string;
    kind: string;
    label: string;
    params: Record<string, unknown>;
  }) => Promise<GenerationTask>;
  refresh: () => Promise<void>;
};

const TaskContext = createContext<TaskValue | null>(null);

export function TaskProvider({ children }: { children: ReactNode }) {
  const { student } = useSession();
  const [tasks, setTasks] = useState<GenerationTask[]>([]);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const announced = useRef<Set<string>>(new Set());
  const ingestion = useIngestionFeed(Boolean(student));

  const refresh = useCallback(async () => {
    if (!student) return;
    try {
      setTasks(await get<GenerationTask[]>("/api/tasks?limit=20"));
    } catch {
      /* ignore */
    }
  }, [student]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const announce = useCallback((task: GenerationTask) => {
    if (announced.current.has(task.id)) return;
    announced.current.add(task.id);
    setToasts((current) => [
      ...current,
      { id: task.id, label: task.label, ok: task.status === "succeeded", error: task.error },
    ]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== task.id));
      void post(`/api/tasks/${task.id}/acknowledge`).catch(() => undefined);
    }, 9000);
  }, []);

  // Ingestion finishing deserves the same notice as a generation task, wherever you are.
  useEffect(() => {
    for (const done of ingestion.finished) {
      const id = `ingest:${done.source_id}`;
      if (announced.current.has(id)) continue;
      announced.current.add(id);
      setToasts((current) => [
        ...current,
        {
          id,
          label: `${done.title} · ingested`,
          ok: done.status !== "failed",
          error: done.error,
        },
      ]);
      window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 9000);
      ingestion.dismiss(done.source_id);
    }
  }, [ingestion]);

  useEffect(() => {
    if (!student) return;
    const key = readAccessKey();
    const url = new URL(`${API_BASE}/api/tasks/stream/events`);
    if (key) url.searchParams.set("access_key", key);

    const source = new EventSource(url.toString());
    source.onmessage = (event) => {
      if (!event.data) return;
      try {
        const task = JSON.parse(event.data) as GenerationTask;
        setTasks((current) => {
          const rest = current.filter((item) => item.id !== task.id);
          return [task, ...rest].slice(0, 20);
        });
        if (task.status === "succeeded" || task.status === "failed") announce(task);
      } catch {
        /* ignore */
      }
    };
    return () => source.close();
  }, [student, announce]);

  const active = useMemo(
    () => tasks.filter((task) => task.status === "queued" || task.status === "running"),
    [tasks],
  );

  const enqueue = useCallback(
    async (input: { course_id: string; kind: string; label: string; params: Record<string, unknown> }) => {
      const task = await post<GenerationTask>("/api/tasks", input);
      setTasks((current) => [task, ...current].slice(0, 20));
      return task;
    },
    [],
  );

  const value = useMemo<TaskValue>(
    () => ({
      tasks,
      active,
      busyFor: (courseId: string) => active.some((task) => task.course_id === courseId),
      enqueue,
      refresh,
    }),
    [tasks, active, enqueue, refresh],
  );

  return (
    <TaskContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-[90] flex w-[min(21rem,calc(100vw-2rem))] flex-col gap-2">
        <Toasts toasts={toasts} onDismiss={(id) => setToasts((c) => c.filter((t) => t.id !== id))} />
        <TaskDock active={active} ingesting={ingestion.jobs} />
      </div>
    </TaskContext.Provider>
  );
}

function TaskDock({
  active,
  ingesting,
}: {
  active: GenerationTask[];
  ingesting: IngestionEvent[];
}) {
  const [hidden, setHidden] = useState<string[]>([]);
  const everything = [
    ...active.map((task) => task.id),
    ...ingesting.map((job) => `ingest:${job.source_id}`),
  ];
  const showing = active.filter((task) => !hidden.includes(task.id));
  const showingIngests = ingesting.filter((job) => !hidden.includes(`ingest:${job.source_id}`));

  // Anything newly started is worth showing again, even after an earlier dismissal.
  useEffect(() => {
    setHidden((current) => current.filter((id) => everything.includes(id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [everything.join("|")]);

  if (showing.length === 0 && showingIngests.length === 0) return null;

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        className="toast pointer-events-auto p-3"
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <p className="eyebrow">Working in the background</p>
          <button
            type="button"
            aria-label="Hide background work"
            className="btn btn-ghost px-1 py-0.5"
            onClick={() => setHidden(everything)}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
        <ul className="space-y-2.5">
          {showingIngests.map((job) => {
            const eta = formatEta(job.eta_seconds);
            return (
              <li key={job.source_id} className="text-xs">
                <div className="flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[var(--iris)]" />
                  <span className="min-w-0 flex-1 truncate font-medium">{job.title}</span>
                  <span className="shrink-0 text-[10px] opacity-70">
                    {Math.round((job.progress ?? 0) * 100)}%
                  </span>
                </div>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--line)]">
                  <div
                    className="h-full rounded-full bg-[var(--iris)] transition-[width] duration-500"
                    style={{ width: `${Math.max(2, Math.round((job.progress ?? 0) * 100))}%` }}
                  />
                </div>
                <p className="mt-1 truncate text-[10px] text-[var(--ink-soft)]">
                  {describeIngestion(job)}
                  {eta ? ` · ${eta} left` : ""}
                </p>
              </li>
            );
          })}
          {showing.map((task) => (
            <li key={task.id} className="flex items-center gap-2 text-xs">
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[var(--iris)]" />
              <span className="min-w-0 flex-1 truncate">{task.label}</span>
              <span className="shrink-0 text-[10px] opacity-70">
                {task.status === "queued" ? "queued" : task.stage}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[10px] opacity-70">
          Keeps running if you move to another page. You will be told when it is done.
        </p>
      </motion.div>
    </>
  );
}

function Toasts({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  return (
    <AnimatePresence>
        {toasts.map((task) => (
          <motion.div
            key={task.id}
            initial={{ opacity: 0, y: -14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 32 }}
            className="toast pointer-events-auto flex items-start gap-2.5 p-3.5"
          >
            {task.ok ? (
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-[var(--mint)]" />
            ) : (
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--rose)]" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{task.ok ? "Ready" : "Could not finish"}</p>
              <p className="mt-0.5 truncate text-xs text-[var(--ink-soft)]">{task.label}</p>
              {task.error ? (
                <p className="mt-1 text-[11px] leading-relaxed text-[var(--rose)]">{task.error}</p>
              ) : null}
            </div>
            <button
              type="button"
              className="btn btn-ghost px-1.5 py-0.5"
              onClick={() => onDismiss(task.id)}
            >
              <X className="h-3 w-3" />
            </button>
          </motion.div>
      ))}
    </AnimatePresence>
  );
}

export function useTasks(): TaskValue {
  const value = useContext(TaskContext);
  if (value === null) throw new Error("useTasks must be used inside TaskProvider");
  return value;
}
