"use client";

import clsx from "clsx";
import { ChevronLeft, ChevronRight, MessageSquarePlus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Hint } from "@/components/hint";
import { Panel } from "@/components/ui";

export type SessionRow = {
  id: string;
  title: string;
  message_count?: number;
  updated_at?: string;
};

function when(value?: string): string {
  if (!value) return "";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days}d ago`;
}

/** The list of past conversations, as a rail that can be folded away when the
 *  conversation itself needs the room. */
export function SessionRail({
  sessions,
  activeId,
  onSelect,
  onCreate,
  onDelete,
  storageKey,
  label = "Sessions",
  newLabel = "New session",
  emptyNote = "Nothing here yet.",
}: {
  sessions: SessionRow[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete?: (id: string) => void;
  storageKey: string;
  label?: string;
  newLabel?: string;
  emptyNote?: string;
}) {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(storageKey) === "1");
    } catch {
      /* private mode, keep the default */
    }
  }, [storageKey]);

  function toggle() {
    setCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(storageKey, next ? "1" : "0");
      } catch {
        /* nothing to do */
      }
      return next;
    });
  }

  if (collapsed) {
    return (
      <div className="flex flex-row gap-2 lg:flex-col">
        <Hint label={`Show ${label.toLowerCase()}`} side="right">
          <button
            type="button"
            className="btn px-2 py-2"
            onClick={toggle}
            aria-expanded={false}
            aria-label={`Show ${label.toLowerCase()}`}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </Hint>
        <Hint label={newLabel} side="right">
          <button type="button" className="btn px-2 py-2" onClick={onCreate} aria-label={newLabel}>
            <MessageSquarePlus className="h-4 w-4" />
          </button>
        </Hint>
      </div>
    );
  }

  return (
    <Panel className="flex max-h-[calc(100vh-7rem)] w-full flex-col overflow-hidden p-0 lg:w-[198px]">
      <div
        className="flex items-center justify-between gap-1 border-b px-2.5 py-2"
        style={{ borderColor: "var(--edge)" }}
      >
        <span className="eyebrow pl-1">{label}</span>
        <div className="flex items-center gap-1">
          <Hint label={newLabel}>
            <button type="button" className="btn px-1.5 py-1" onClick={onCreate} aria-label={newLabel}>
              <MessageSquarePlus className="h-3.5 w-3.5" />
            </button>
          </Hint>
          <Hint label={`Hide ${label.toLowerCase()}`}>
            <button
              type="button"
              className="btn px-1.5 py-1"
              onClick={toggle}
              aria-expanded
              aria-label={`Hide ${label.toLowerCase()}`}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
          </Hint>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {sessions.length === 0 ? (
          <p className="px-2 py-4 text-center text-[11px] leading-relaxed opacity-70">{emptyNote}</p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((item) => {
              const selected = item.id === activeId;
              return (
                <li key={item.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-current={selected ? "true" : undefined}
                    className={clsx(
                      "w-full rounded-lg px-2.5 py-2 pr-7 text-left transition",
                      selected ? "bg-[var(--glass-strong)]" : "hover:bg-[var(--glass)]",
                    )}
                  >
                    <span
                      className="block truncate text-[13px] leading-tight"
                      style={{ color: selected ? "var(--iris)" : "var(--ink)" }}
                    >
                      {item.title}
                    </span>
                    <span className="mt-0.5 block text-[10.5px] leading-tight opacity-65">
                      {item.message_count ? `${item.message_count} messages` : "empty"}
                      {item.updated_at ? ` · ${when(item.updated_at)}` : ""}
                    </span>
                  </button>

                  {onDelete ? (
                    <button
                      type="button"
                      aria-label={`Delete ${item.title}`}
                      onClick={() => onDelete(item.id)}
                      className="absolute right-1.5 top-1/2 hidden -translate-y-1/2 rounded-md p-1 opacity-70 transition hover:opacity-100 group-hover:block"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Panel>
  );
}
