"use client";

import type { Job, Pipeline, ProjectEvent, ProjectStatus } from "@cinedub/contracts";
import { useEffect, useRef } from "react";
import { API_URL } from "@/lib/api";

export interface ProjectEventHandlers {
  onJob: (job: Job) => void;
  onPipeline: (pipeline: Pipeline) => void;
  onStatus: (status: ProjectStatus) => void;
  /** Lines, speakers, revisions or artifacts changed: refetch the project. */
  onStale: () => void;
}

const TYPES = ["job", "pipeline", "project", "timeline", "artifact", "error"] as const;

/**
 * Subscribe to typed server-sent project events. Falls back to polling every five seconds
 * while the stream is unavailable, and refetches once after every reconnect.
 */
export function useProjectEvents(projectId: string, handlers: ProjectEventHandlers) {
  const latest = useRef(handlers);
  useEffect(() => { latest.current = handlers; });
  useEffect(() => {
    let source: EventSource | null = null;
    let poll: number | null = null;
    let first = true;
    const stopPolling = () => { if (poll !== null) { window.clearInterval(poll); poll = null; } };
    const startPolling = () => { if (poll === null) poll = window.setInterval(() => latest.current.onStale(), 5000); };
    source = new EventSource(`${API_URL}/projects/${projectId}/events`);
    source.onopen = () => {
      stopPolling();
      if (!first) latest.current.onStale(); // Changes may have happened while disconnected.
      first = false;
    };
    source.onerror = () => startPolling();
    const listen = (type: (typeof TYPES)[number]) => source!.addEventListener(type, (message) => {
      let event: ProjectEvent;
      try { event = JSON.parse((message as MessageEvent<string>).data) as ProjectEvent; }
      catch { return; }
      if (event.type === "job") latest.current.onJob(event.job);
      else if (event.type === "pipeline") latest.current.onPipeline(event.pipeline);
      else if (event.type === "project") latest.current.onStatus(event.status);
      else if (event.type === "timeline" || event.type === "artifact") latest.current.onStale();
    });
    TYPES.forEach(listen);
    return () => { stopPolling(); source?.close(); };
  }, [projectId]);
}
