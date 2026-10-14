"use client";

import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Loader2,
  MonitorPlay,
  RefreshCw,
  Trash2,
  UploadCloud,
  Video,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { FlowMap } from "@/components/flow-map";
import { useSession } from "@/components/session-context";
import { Blank, Chip, Notice, Panel, Progress, SectionHead, Spinner } from "@/components/ui";
import { del, get, post, upload } from "@/lib/api";
import type { FlowMap as FlowMapData, Source, Topic } from "@/lib/types";
import { describeIngestion, formatEta, useIngestionEvents } from "@/lib/use-ingestion-events";

const ACCEPTED = ".pdf,.pptx,.docx,.html,.mp4,.mkv,.mov,.webm,.mp3,.wav,.m4a";

function kindIcon(kind: string) {
  const className = "h-4 w-4 shrink-0 text-[var(--ink-faint)]";
  if (kind === "youtube") return <MonitorPlay className={className} />;
  if (kind === "video" || kind === "audio") return <Video className={className} />;
  return <FileText className={className} />;
}

export function CourseMaterial({ courseId }: { courseId: string }) {
  const { refreshCourses } = useSession();
  const { events } = useIngestionEvents(courseId);
  const [sources, setSources] = useState<Source[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [flow, setFlow] = useState<FlowMapData | null>(null);
  const [linkDraft, setLinkDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [sourceList, topicList, flowMap] = await Promise.all([
        get<Source[]>(`/api/courses/${courseId}/sources`),
        get<Topic[]>(`/api/courses/${courseId}/topics`),
        get<FlowMapData>(`/api/courses/${courseId}/flow-map`),
      ]);
      setError(null);
      setSources(sourceList);
      setTopics(topicList);
      setFlow(flowMap);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load material");
    }
  }, [courseId]);

  useEffect(() => {
    void load();
  }, [load]);

  const finished = Object.values(events).filter((item) => item.terminal).length;
  useEffect(() => {
    if (finished === 0) return;
    void load();
    void refreshCourses();
  }, [finished, load, refreshCourses]);

  async function addFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const file of Array.from(list)) {
        const form = new FormData();
        form.append("file", file);
        await upload<Source>(`/api/courses/${courseId}/sources`, form);
      }
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function addLink() {
    if (!linkDraft.trim()) return;
    setBusy(true);
    try {
      await post<Source>(`/api/courses/${courseId}/sources/youtube`, { url: linkDraft.trim() });
      setLinkDraft("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not queue that video");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      {error ? <Notice message={error} /> : null}

      <Panel>
        <SectionHead
          eyebrow="Ingest"
          title="Add material to this course"
          description="Anything you add is parsed, tagged and linked back to its exact page, slide or timestamp."
        />

        <div
          className={`rounded-[var(--radius)] border border-dashed p-6 text-center transition ${
            dragging ? "border-[var(--iris)] bg-[var(--iris-soft)]" : ""
          }`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void addFiles(event.dataTransfer.files);
          }}
        >
          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPTED}
            className="hidden"
            onChange={(event) => addFiles(event.target.files)}
          />
          <UploadCloud className="mx-auto mb-2 h-6 w-6 text-[var(--ink-faint)]" />
          <p className="text-sm">Drop files, or</p>
          <button
            type="button"
            className="btn mt-2.5"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            {busy ? <Spinner /> : null} Choose files
          </button>
        </div>

        <div className="mt-4 flex gap-2">
          <input
            className="input"
            placeholder="Or paste a lecture video URL"
            value={linkDraft}
            onChange={(event) => setLinkDraft(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && addLink()}
          />
          <button type="button" className="btn" disabled={busy || !linkDraft.trim()} onClick={addLink}>
            <MonitorPlay className="h-4 w-4" /> Add
          </button>
        </div>
      </Panel>

      <Panel>
        <SectionHead title="Sources" description="Progress streams live while each source is read." />
        {sources.length === 0 ? (
          <Blank
            icon={<UploadCloud className="h-5 w-5" />}
            title="No material yet"
            description="Add a document or lecture video above to build this course's knowledge base."
          />
        ) : (
          <ul className="divide-y">
            {sources.map((source) => {
              const live = events[source.id];
              const status =
                live?.status === "failed"
                  ? "failed"
                  : live
                    ? live.terminal
                      ? "ready"
                      : "processing"
                    : source.status;
              const stage = live?.stage ?? source.job?.stage ?? "";
              const progress = live?.progress ?? source.job?.progress ?? 0;
              const failure = live?.error ?? source.error;

              const doing = describeIngestion(live);
              const eta = formatEta(live?.eta_seconds);

              return (
                <li key={source.id} className="flex flex-wrap items-center gap-3 py-3">
                  {kindIcon(source.kind)}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium">{source.title}</span>
                      {status === "ready" ? (
                        <Chip tone="mint">
                          <CheckCircle2 className="h-3 w-3" /> ready
                        </Chip>
                      ) : status === "failed" ? (
                        <Chip tone="rose">
                          <AlertCircle className="h-3 w-3" /> failed
                        </Chip>
                      ) : (
                        <Chip tone="iris">
                          <Loader2 className="h-3 w-3 animate-spin" /> {stage || "queued"}
                        </Chip>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs text-[var(--ink-faint)]">
                      {source.page_count ? `${source.page_count} pages · ` : ""}
                      {source.duration_seconds
                        ? `${Math.round(source.duration_seconds / 60)} min · `
                        : ""}
                      {source.kind}
                    </p>
                    {status === "processing" ? (
                      <div className="mt-2 max-w-md">
                        <Progress value={progress} label={stage} />
                        <p className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-[var(--ink-soft)]">
                          <span>{Math.round(progress * 100)}%</span>
                          {doing ? <span>· {doing}</span> : null}
                          {eta ? <span>· {eta} left</span> : null}
                        </p>
                        <p className="mt-0.5 text-[10px] text-[var(--ink-faint)]">
                          Keeps going if you leave this page.
                        </p>
                      </div>
                    ) : null}
                    {failure ? (
                      <p className="mt-1.5 max-w-2xl text-xs text-[var(--rose)]">{failure}</p>
                    ) : null}
                  </div>
                  <div className="flex gap-1">
                    {status === "failed" ? (
                      <button
                        type="button"
                        className="btn px-2 py-1"
                        title="Retry"
                        onClick={async () => {
                          await post(`/api/courses/${courseId}/sources/${source.id}/reingest`);
                          await load();
                        }}
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="btn px-2 py-1"
                      title="Remove"
                      onClick={async () => {
                        await del(`/api/courses/${courseId}/sources/${source.id}`);
                        await load();
                        await refreshCourses();
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel>
          <SectionHead title="Course map" description="Topics and the prerequisites between them." />
          {flow ? <FlowMap data={flow} /> : <Spinner />}
        </Panel>

        <Panel>
          <SectionHead title="Topics and concepts" description="Every unit is tagged to this structure." />
          {topics.length === 0 ? (
            <Blank title="No topics yet" description="They appear once material is ingested." />
          ) : (
            <div className="scroll-slim max-h-[420px] space-y-4 overflow-auto pr-1">
              {topics
                .filter((topic) => topic.kind === "major")
                .map((major) => (
                  <div key={major.id} className="rail pl-4">
                    <h4 className="text-sm font-semibold">{major.name}</h4>
                    <div className="mt-2 space-y-2">
                      {topics
                        .filter((topic) => topic.parent_id === major.id)
                        .map((sub) => (
                          <div key={sub.id}>
                            <p className="text-sm text-[var(--ink-soft)]">{sub.name}</p>
                            {sub.concepts.length > 0 ? (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {sub.concepts.slice(0, 5).map((concept) => (
                                  <Chip key={concept}>{concept}</Chip>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
