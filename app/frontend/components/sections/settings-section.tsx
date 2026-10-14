"use client";

import { Check, FolderPlus, Layers, Moon, Palette, Server, Sun, Trash2, User } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useSession } from "@/components/session-context";
import { Blank, Chip, Field, Notice, Panel, SectionHead, Spinner } from "@/components/ui";
import { del, get, post } from "@/lib/api";
import type { Profile, RuntimeConfig } from "@/lib/types";

const ACCENTS: { value: Profile["accent"]; label: string }[] = [
  { value: "iris", label: "Iris" },
  { value: "cyan", label: "Cyan" },
  { value: "mint", label: "Mint" },
  { value: "amber", label: "Amber" },
  { value: "rose", label: "Rose" },
];

function accentVar(accent: Profile["accent"]): string {
  return `var(--${accent})`;
}

export function SettingsSection() {
  const {
    student,
    profiles,
    profile,
    selectProfile,
    refreshProfiles,
    theme,
    toggleTheme,
    authRequired,
    signOut,
  } = useSession();

  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [accent, setAccent] = useState<Profile["accent"]>("iris");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<RuntimeConfig>("/api/config")
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  const create = useCallback(async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await post<Profile>("/api/profiles", {
        name: name.trim(),
        description: description.trim() || null,
        accent,
      });
      setName("");
      setDescription("");
      setAccent("iris");
      await refreshProfiles();
      selectProfile(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create that profile");
    } finally {
      setBusy(false);
    }
  }, [name, description, accent, refreshProfiles, selectProfile]);

  const remove = useCallback(
    async (id: string) => {
      setError(null);
      try {
        await del(`/api/profiles/${id}`);
        await refreshProfiles();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not delete that profile");
      }
    },
    [refreshProfiles],
  );

  return (
    <div className="fade-rise space-y-5">
      <SectionHead
        eyebrow="Workspace"
        title="Settings"
        description="Organise your courses into profiles, and see how this instance is configured."
      />

      <Panel>
        <SectionHead
          title="Profiles"
          description="Keep separate spaces for different kinds of work — a profile for coursework, another for side projects."
        />

        {profiles.length === 0 ? (
          <Blank icon={<Layers className="h-5 w-5" />} title="No profiles yet" />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {profiles.map((item) => {
              const active = profile?.id === item.id;
              return (
                <div
                  key={item.id}
                  className={`glass glass-hover relative overflow-hidden p-4 ${
                    active ? "ring-1 ring-[var(--iris)]" : ""
                  }`}
                >
                  <div
                    className="pointer-events-none absolute -right-8 -top-10 h-20 w-20 rounded-full opacity-25 blur-2xl"
                    style={{ background: accentVar(item.accent) }}
                  />
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className="flex h-8 w-8 items-center justify-center rounded-xl border"
                      style={{
                        background: `color-mix(in srgb, ${accentVar(item.accent)} 16%, transparent)`,
                        borderColor: accentVar(item.accent),
                      }}
                    >
                      <Layers className="h-4 w-4" style={{ color: accentVar(item.accent) }} />
                    </span>
                    {active ? (
                      <Chip tone="iris">
                        <Check className="h-3 w-3" /> active
                      </Chip>
                    ) : null}
                  </div>

                  <p className="display mt-3 text-base">{item.name}</p>
                  {item.description ? (
                    <p className="mt-1 line-clamp-2 text-xs text-[var(--ink-soft)]">
                      {item.description}
                    </p>
                  ) : null}

                  <div className="mt-3.5 flex items-center justify-between">
                    <span className="num text-xs text-[var(--ink-faint)]">
                      {item.course_count} course{item.course_count === 1 ? "" : "s"}
                    </span>
                    <div className="flex gap-1">
                      {!active ? (
                        <button
                          type="button"
                          className="btn px-2 py-1 text-[11px]"
                          onClick={() => selectProfile(item.id)}
                        >
                          Switch
                        </button>
                      ) : null}
                      {profiles.length > 1 && item.course_count === 0 ? (
                        <button
                          type="button"
                          className="btn px-2 py-1"
                          title="Delete profile"
                          onClick={() => remove(item.id)}
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-5 border-t pt-5">
          <p className="eyebrow mb-3">New profile</p>
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto]">
            <Field label="Name">
              <input
                className="input"
                placeholder="Side projects"
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && create()}
              />
            </Field>
            <Field label="Description" hint="Optional">
              <input
                className="input"
                placeholder="Research papers and prototypes"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>
            <Field label="Accent">
              <div className="flex gap-1.5">
                {ACCENTS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    title={option.label}
                    onClick={() => setAccent(option.value)}
                    className={`h-8 w-8 rounded-xl border transition ${
                      accent === option.value ? "scale-110 ring-1 ring-[var(--ink)]" : ""
                    }`}
                    style={{
                      background: `color-mix(in srgb, ${accentVar(option.value)} 35%, transparent)`,
                      borderColor: accentVar(option.value),
                    }}
                  />
                ))}
              </div>
            </Field>
          </div>

          {error ? (
            <div className="mt-3">
              <Notice message={error} />
            </div>
          ) : null}

          <button
            type="button"
            className="btn btn-primary mt-4"
            disabled={busy || !name.trim()}
            onClick={create}
          >
            {busy ? <Spinner /> : <FolderPlus className="h-4 w-4" />} Create profile
          </button>
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <SectionHead title="Appearance" description="The interface follows a glass theme." />
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl border bg-[var(--glass)]">
                <Palette className="h-4 w-4 text-[var(--iris)]" />
              </span>
              <div>
                <p className="text-sm font-medium">{theme === "dark" ? "Dark" : "Light"}</p>
                <p className="text-xs text-[var(--ink-faint)]">
                  {theme === "dark" ? "Designed for long study sessions" : "Higher contrast in bright rooms"}
                </p>
              </div>
            </div>
            <button type="button" className="btn" onClick={toggleTheme}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              Switch
            </button>
          </div>

          <div className="mt-5 border-t pt-4">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl border bg-[var(--glass)]">
                <User className="h-4 w-4 text-[var(--cyan)]" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{student?.name ?? "Local learner"}</p>
                <p className="text-xs text-[var(--ink-faint)]">
                  {authRequired ? "Signed in with an access key" : "Running without access keys"}
                </p>
              </div>
              {authRequired ? (
                <button type="button" className="btn" onClick={signOut}>
                  Sign out
                </button>
              ) : null}
            </div>
          </div>
        </Panel>

        <Panel>
          <SectionHead title="Instance" description="Models and limits this deployment is using." />
          {config === null ? (
            <p className="text-sm text-[var(--ink-soft)]">Configuration unavailable.</p>
          ) : (
            <dl className="space-y-2.5 text-xs">
              {[
                ["Generation", config.models.generation],
                ["Vision", config.models.vision],
                ["Verifier", config.models.verifier],
                ["Transcription", config.models.transcription],
                ["Embeddings", `${config.embedding_model} (local)`],
                ["Tokens / minute", String(config.rate_limit.tokens_per_minute)],
                ["Retrieval top-k", String(config.retrieval.top_k)],
                ["Grounding threshold", String(config.retrieval.grounding_threshold)],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between gap-3 border-b pb-2">
                  <dt className="text-[var(--ink-faint)]">{label}</dt>
                  <dd className="truncate font-mono text-[11px]">{value}</dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-3 flex items-center gap-1.5 text-[11px] text-[var(--ink-faint)]">
            <Server className="h-3 w-3" /> Embeddings run locally, so search costs no API quota.
          </p>
        </Panel>
      </div>
    </div>
  );
}
