// Pure timeline geometry and track assembly. No React or DOM: unit-tested with node:test.
import type { Artifact, ProjectDetail, Segment, StemSet } from "@cinedub/contracts";

export const MIN_LINE_MS = 200;
export const ZOOM_LEVELS = [0.02, 0.05, 0.1, 0.2, 0.4, 0.8] as const; // pixels per millisecond

export interface View { pxPerMs: number; scrollMs: number; widthPx: number }
export interface Range { start_ms: number; end_ms: number }

export function msToPx(ms: number, view: View): number {
  return (ms - view.scrollMs) * view.pxPerMs;
}

export function pxToMs(px: number, view: View): number {
  return Math.round(px / view.pxPerMs + view.scrollMs);
}

export function visibleRange(view: View): Range {
  return { start_ms: view.scrollMs, end_ms: view.scrollMs + view.widthPx / view.pxPerMs };
}

export function clampScroll(scrollMs: number, durationMs: number, view: View): number {
  const span = view.widthPx / view.pxPerMs;
  return Math.max(0, Math.min(scrollMs, Math.max(0, durationMs - span)));
}

/** Zoom around an anchor time so the point under the cursor stays put. */
export function zoomAround(view: View, nextPxPerMs: number, anchorMs: number, durationMs: number): View {
  const anchorPx = msToPx(anchorMs, view);
  const scrollMs = anchorMs - anchorPx / nextPxPerMs;
  const next = { ...view, pxPerMs: nextPxPerMs };
  return { ...next, scrollMs: clampScroll(scrollMs, durationMs, next) };
}

export function nextZoom(current: number, direction: 1 | -1): number {
  const index = ZOOM_LEVELS.findIndex((level) => level >= current - 1e-9);
  const position = index < 0 ? ZOOM_LEVELS.length - 1 : index;
  return ZOOM_LEVELS[Math.max(0, Math.min(ZOOM_LEVELS.length - 1, position + direction))];
}

/** Snap to the nearest candidate edge within a tolerance (milliseconds). */
export function snap(ms: number, edges: number[], toleranceMs: number): number {
  let best = ms;
  let distance = toleranceMs;
  for (const edge of edges) {
    const delta = Math.abs(edge - ms);
    if (delta <= distance) { best = edge; distance = delta; }
  }
  return best;
}

/**
 * Move one edge of a line, keeping a minimum duration, the scene bounds and no overlap with
 * neighbouring lines. The backend validates again on save; this keeps drafts plausible.
 */
export function moveEdge(
  line: Range, edge: "start" | "end", targetMs: number,
  neighbours: { previousEnd: number | null; nextStart: number | null }, durationMs: number,
): Range {
  if (edge === "start") {
    const floor = Math.max(0, neighbours.previousEnd ?? 0);
    const start = Math.round(Math.min(Math.max(targetMs, floor), line.end_ms - MIN_LINE_MS));
    return { start_ms: Math.max(floor, start), end_ms: line.end_ms };
  }
  const ceiling = Math.min(durationMs, neighbours.nextStart ?? durationMs);
  const end = Math.round(Math.max(Math.min(targetMs, ceiling), line.start_ms + MIN_LINE_MS));
  return { start_ms: line.start_ms, end_ms: Math.min(ceiling, end) };
}

export function neighboursOf(lines: Range[], index: number) {
  return {
    previousEnd: index > 0 ? lines[index - 1].end_ms : null,
    nextStart: index < lines.length - 1 ? lines[index + 1].start_ms : null,
  };
}

export type TakeFit = "ready" | "overrun" | "missing" | "unknown";

export interface DialogueBlock extends Range {
  id: string; index: number; label: string; speaker: string | null; approved: boolean;
}
export interface TakeBlock extends Range {
  lineId: string; artifactId: string | null; fit: TakeFit; demo: boolean; rawDurationMs: number | null;
}
export interface StemTrack { name: string; artifactId: string; demo: boolean }
export interface Tracks { durationMs: number; dialogue: DialogueBlock[]; takes: TakeBlock[]; stems: StemTrack[] }

function takeFor(line: Segment, artifacts: Artifact[]): TakeBlock {
  const artifact = line.selected_candidate_id
    ? artifacts.find((item) => item.id === line.selected_candidate_id) : undefined;
  const meta = artifact?.metadata_json ?? {};
  const raw = typeof meta.raw_duration_ms === "number" ? meta.raw_duration_ms : null;
  const fit: TakeFit = !artifact ? "missing" : meta.fit_status === "ready" ? "ready"
    : meta.fit_status ? "overrun" : "unknown";
  return {
    lineId: line.id, artifactId: artifact?.id ?? null, start_ms: line.start_ms, end_ms: line.end_ms,
    fit, demo: !!meta.demo || meta.provider === "fake", rawDurationMs: raw,
  };
}

export function buildTracks(project: ProjectDetail, sourceId: string | null): Tracks {
  const source = project.assets.find((asset) => asset.id === sourceId);
  const lines = project.segments.filter((line) => !line.retired);
  const durationMs = Math.max(source?.duration_ms ?? 0, ...lines.map((line) => line.end_ms), 1);
  const speakers = new Map(project.speakers.map((speaker) => [speaker.id, speaker.display_name]));
  const active: StemSet | undefined = project.stem_sets.find((stems) =>
    stems.id === source?.active_stem_set_id && stems.status === "approved");
  const stems: StemTrack[] = active ? ["dialogue", "music", "effects"].flatMap((name) => {
    const preview = project.artifacts.find((item) => item.kind === "stem_preview"
      && item.metadata_json.stem_set_id === active.id && item.metadata_json.stem === name);
    return preview ? [{ name, artifactId: preview.id, demo: active.provider === "fake" }] : [];
  }) : [];
  return {
    durationMs,
    dialogue: lines.map((line) => ({
      id: line.id, index: line.index, start_ms: line.start_ms, end_ms: line.end_ms,
      label: line.translated_text.trim() || line.source_text,
      speaker: line.speaker_id ? speakers.get(line.speaker_id) ?? null : null,
      approved: line.status === "approved",
    })),
    takes: lines.map((line) => takeFor(line, project.artifacts)),
    stems,
  };
}

export function formatMs(ms: number): string {
  const total = Math.max(0, Math.round(ms));
  const minutes = Math.floor(total / 60000);
  const seconds = ((total % 60000) / 1000).toFixed(2).padStart(5, "0");
  return `${minutes}:${seconds}`;
}

/** Tick marks every 1/2/5/10/30/60 seconds so labels stay readable at any zoom. */
export function ticks(view: View, durationMs: number): number[] {
  const steps = [1000, 2000, 5000, 10000, 30000, 60000];
  const step = steps.find((value) => value * view.pxPerMs >= 70) ?? 60000;
  const range = visibleRange(view);
  const first = Math.ceil(range.start_ms / step) * step;
  const out: number[] = [];
  for (let ms = first; ms <= Math.min(range.end_ms, durationMs); ms += step) out.push(ms);
  return out;
}
