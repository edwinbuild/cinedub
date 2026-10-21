"use client";

import type { ProjectDetail } from "@cinedub/contracts";
import { Minus, MousePointer2, Plus, ScanLine, Scissors } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from "react";
import { DemoBadge } from "@/components/demo-badge";
import { TooltipButton } from "@/components/tooltip-button";
import { API_URL } from "@/lib/api";
import {
  ZOOM_LEVELS, buildTracks, formatMs, moveEdge, moveRange, neighboursOf, nextZoom, snap, ticks, type Range,
} from "@/lib/timeline";

export type TimingEditor = (range: Range) => void;
interface Waveform { duration_ms: number; peaks: number[] }

const FIT_LABEL = { ready: "fits its window", overrun: "does not fit", missing: "no take selected", unknown: "unknown fit" };

/**
 * Time-based view of the scene: waveform, dialogue blocks, selected takes and approved stems.
 * Dragging or nudging an edge only changes that line's unsaved draft; saving, conflicts and
 * undo stay with the dialogue line editor.
 */
export function TimelineView({ project, sourceId, mediaRef, drafts, editors, disabled, onSeek, onSelectLine, onSplit, selectedLineId, onToggle, collapsed }: {
  project: ProjectDetail; sourceId: string | null; mediaRef: RefObject<HTMLMediaElement | null>;
  drafts: Record<string, Range>; editors: RefObject<Map<string, TimingEditor>>; disabled: boolean;
  onSeek: (ms: number) => void;
  onSelectLine?: (lineId: string, startMs: number) => void;
  onSplit?: () => void; selectedLineId?: string | null;
  onToggle?: () => void; collapsed?: boolean;
}) {
  const tracks = useMemo(() => buildTracks(project, sourceId), [project, sourceId]);
  const [pxPerMs, setPxPerMs] = useState<number>(ZOOM_LEVELS[1]);
  const [wave, setWave] = useState<Waveform | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const playhead = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: string; edge: "start" | "end" } | null>(null);
  const clipDrag = useRef<{ id: string; clientX: number; range: Range; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  // Edits applied since the last render: rapid key repeats must build on each other.
  const pending = useRef<Record<string, Range>>({});
  const width = Math.max(1, Math.round(tracks.durationMs * pxPerMs));
  const lines = tracks.dialogue.map((line) => ({ ...line, ...(drafts[line.id] ?? {}) }));
  const waveform = project.artifacts.find((item) => item.kind === "waveform" && item.metadata_json.source_asset_id === sourceId);
  const waveformUrl = waveform ? `${API_URL}${waveform.content_url}` : null;

  useEffect(() => { pending.current = {}; }, [drafts, project]);
  const zoomed = useRef(false);
  useEffect(() => {
    // Fit the scene to the available width until the editor chooses a zoom level.
    const box = scroller.current; if (!box) return;
    const observer = new ResizeObserver(() => {
      if (zoomed.current || !box.clientWidth) return;
      const target = box.clientWidth / Math.max(1, tracks.durationMs);
      setPxPerMs([...ZOOM_LEVELS].reverse().find((level) => level <= target) ?? ZOOM_LEVELS[0]);
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [tracks.durationMs]);
  useEffect(() => {
    if (!waveformUrl) return;
    const controller = new AbortController();
    fetch(waveformUrl, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((value: Waveform | null) => setWave(value))
      .catch(() => undefined);
    return () => controller.abort();
  }, [waveformUrl]);

  useEffect(() => {
    // Move the playhead every frame without re-rendering React.
    let frame = 0;
    const tick = () => {
      const media = mediaRef.current;
      if (media && playhead.current) playhead.current.style.transform = `translateX(${media.currentTime * 1000 * pxPerMs}px)`;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [mediaRef, pxPerMs]);

  function zoom(direction: 1 | -1) {
    zoomed.current = true;
    const box = scroller.current;
    const centerMs = box ? (box.scrollLeft + box.clientWidth / 2) / pxPerMs : 0;
    const next = nextZoom(pxPerMs, direction);
    setPxPerMs(next);
    requestAnimationFrame(() => { if (box) box.scrollLeft = Math.max(0, centerMs * next - box.clientWidth / 2); });
  }
  function fit() {
    const box = scroller.current; if (!box) return;
    const target = box.clientWidth / Math.max(1, tracks.durationMs);
    setPxPerMs([...ZOOM_LEVELS].reverse().find((level) => level <= target) ?? ZOOM_LEVELS[0]);
    box.scrollLeft = 0;
  }
  function msAt(clientX: number) {
    const box = content.current?.getBoundingClientRect();
    return box ? Math.max(0, Math.min(tracks.durationMs, (clientX - box.left) / pxPerMs)) : 0;
  }
  function apply(id: string, edge: "start" | "end", targetMs: number, announce: boolean, snapping = true) {
    const index = lines.findIndex((line) => line.id === id);
    const editor = editors.current.get(id);
    if (index < 0 || !editor || disabled) return;
    const edges = lines.flatMap((line, position) => position === index ? [] : [line.start_ms, line.end_ms]);
    const snapped = snapping ? snap(targetMs, edges, 8 / pxPerMs) : targetMs;
    const current = pending.current[id] ?? lines[index];
    const next = moveEdge(current, edge, snapped, neighboursOf(lines, index), tracks.durationMs);
    pending.current[id] = next;
    editor(next);
    if (announce) setAnnouncement(`Line ${lines[index].index + 1} draft ${edge} ${formatMs(edge === "start" ? next.start_ms : next.end_ms)}; save the line to keep it`);
  }
  function startDrag(event: PointerEvent<HTMLSpanElement>, id: string, edge: "start" | "end") {
    if (disabled) return;
    event.preventDefault(); event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { id, edge };
  }
  function moveDrag(event: PointerEvent<HTMLSpanElement>) {
    if (drag.current) apply(drag.current.id, drag.current.edge, msAt(event.clientX), false);
  }
  function endDrag(event: PointerEvent<HTMLSpanElement>) {
    if (!drag.current) return;
    apply(drag.current.id, drag.current.edge, msAt(event.clientX), true);
    drag.current = null;
  }
  function nudge(event: KeyboardEvent<HTMLSpanElement>, id: string, edge: "start" | "end", rendered: number) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    const step = (event.shiftKey ? 100 : 10) * (event.key === "ArrowLeft" ? -1 : 1);
    const latest = pending.current[id];
    const current = latest ? (edge === "start" ? latest.start_ms : latest.end_ms) : rendered;
    // Nudges are exact: no snapping to nearby edges.
    apply(id, edge, current + step, true, false);
  }

  function moveClip(id: string, range: Range, target: number, announce: boolean, snapping = true) {
    const index = lines.findIndex((line) => line.id === id);
    const editor = editors.current.get(id);
    if (index < 0 || !editor || disabled) return;
    const edges = lines.flatMap((line, position) => position === index ? [] : [line.start_ms, line.end_ms]);
    const duration = range.end_ms - range.start_ms;
    const start = snapping ? snap(target, [...edges, ...edges.map((ms) => ms - duration)], 8 / pxPerMs) : target;
    const next = moveRange(range, start, neighboursOf(lines, index), tracks.durationMs);
    pending.current[id] = next; editor(next);
    if (announce) setAnnouncement(`Line ${lines[index].index + 1} draft moved to ${formatMs(next.start_ms)}; save the line to keep it`);
  }
  function startClipDrag(event: PointerEvent<HTMLButtonElement>, line: typeof lines[number]) {
    suppressClick.current = false;
    if (disabled || !editors.current.get(line.id) || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    clipDrag.current = { id: line.id, clientX: event.clientX, range: { start_ms: line.start_ms, end_ms: line.end_ms }, moved: false };
  }
  function moveClipDrag(event: PointerEvent<HTMLButtonElement>, finish = false) {
    const current = clipDrag.current; if (!current) return;
    if (Math.abs(event.clientX - current.clientX) > 3) current.moved = true;
    if (current.moved) moveClip(current.id, current.range, current.range.start_ms + (event.clientX - current.clientX) / pxPerMs, finish);
    if (finish) {
      suppressClick.current = current.moved; clipDrag.current = null;
      if (current.moved) onSelectLine?.(current.id, pending.current[current.id]?.start_ms ?? current.range.start_ms);
    }
  }

  const peaks = wave?.peaks ?? [];
  return <section className="timelineView" aria-label="Scene timeline">
    <div className="timelineToolbar">
      <strong>Timeline</strong>
      <span className="timelineMode"><MousePointer2 size={13} aria-hidden="true" /> Select</span>
      {onSplit && <TooltipButton label="Split / merge" description="Open the selected line's text and timing structure for review." className="smallButton" disabled={disabled || !project.segments.length} onClick={onSplit}><Scissors size={13} aria-hidden="true" /> Split / merge</TooltipButton>}
      <TooltipButton label="Zoom timeline out" description="Show more of the scene without changing clip timing." className="iconButton" disabled={pxPerMs <= ZOOM_LEVELS[0]} onClick={() => zoom(-1)}><Minus size={14} /></TooltipButton>
      <TooltipButton label="Zoom timeline in" description="Enlarge the timeline for more precise timing edits." className="iconButton" disabled={pxPerMs >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]} onClick={() => zoom(1)}><Plus size={14} /></TooltipButton>
      <TooltipButton label="Fit timeline to view" description="Fit the full scene into the available timeline width." className="iconButton" onClick={fit}><ScanLine size={14} /></TooltipButton>
      <small>Drag to move · edges to trim · {Math.round(pxPerMs * 1000)} px/s</small>
      {onToggle && <TooltipButton label={collapsed ? "Show timeline" : "Hide timeline"} description="Change the workspace layout while keeping your timing drafts." className="smallButton" onClick={onToggle} aria-expanded={!collapsed} aria-controls="timeline-tracks">{collapsed ? "Show timeline" : "Hide timeline"}</TooltipButton>}
    </div>
    <div id="timeline-tracks" className="timelineTracks" hidden={collapsed}>
      <div className="trackLabels" aria-hidden="true"><span>TRACKS</span><strong>Source</strong><strong>Dialogue</strong><strong>Voice takes</strong>
        {tracks.stems.map((stem) => <strong key={stem.name}>{stem.name}</strong>)}
      </div>
    <div className="timelineScroller" ref={scroller} onWheel={(event) => {
      if (!event.ctrlKey) return;
      event.preventDefault(); zoom(event.deltaY < 0 ? 1 : -1);
    }}>
      <div className="timelineContent" ref={content} style={{ width }}
        onClick={(event) => { if (event.target === event.currentTarget || (event.target as HTMLElement).dataset.track) onSeek(Math.round(msAt(event.clientX))); }}>
        <div className="timelineRuler" aria-hidden="true">{ticks({ pxPerMs, scrollMs: 0, widthPx: width }, tracks.durationMs).map((ms) =>
          <span key={ms} style={{ left: ms * pxPerMs }}>{formatMs(ms)}</span>)}</div>
        <div className="timelineTrack waveTrack" data-track="wave" aria-label="Source waveform">
          {peaks.length > 0 && <svg width={width} height="40" viewBox={`0 0 ${peaks.length} 40`} preserveAspectRatio="none" aria-hidden="true">
            {peaks.map((peak, index) => <rect key={index} x={index} y={20 - peak * 19} width="1" height={Math.max(1, peak * 38)} />)}
          </svg>}
        </div>
        <div className="timelineTrack" data-track="dialogue" role="group" aria-label="Dialogue track">
          {lines.map((line) => {
            const changed = !!drafts[line.id];
            return <div key={line.id} className={`timelineBlock ${line.approved ? "approved" : ""} ${changed ? "drafted" : ""} ${selectedLineId === line.id ? "clipSelected" : ""}`}
              style={{ left: line.start_ms * pxPerMs, width: Math.max(4, (line.end_ms - line.start_ms) * pxPerMs) }}>
              {(["start", "end"] as const).map((edge) => {
                const value = edge === "start" ? line.start_ms : line.end_ms;
                return <span key={edge} className={`timelineEdge ${edge}`} role="slider" tabIndex={disabled ? -1 : 0}
                  aria-label={`${edge === "start" ? "Start" : "End"} of line ${line.index + 1} on timeline`}
                  aria-valuemin={0} aria-valuemax={tracks.durationMs} aria-valuenow={value} aria-valuetext={formatMs(value)}
                  aria-disabled={disabled}
                  onPointerDown={(event) => startDrag(event, line.id, edge)} onPointerMove={moveDrag} onPointerUp={endDrag}
                  onPointerCancel={() => { drag.current = null; }}
                  onKeyDown={(event) => nudge(event, line.id, edge, value)} />;
              })}
              <button className="timelineLabel" onPointerDown={(event) => startClipDrag(event, line)}
                onPointerMove={(event) => moveClipDrag(event)} onPointerUp={(event) => moveClipDrag(event, true)}
                onPointerCancel={() => { clipDrag.current = null; suppressClick.current = true; }}
                onKeyDown={(event) => {
                  if (disabled || event.nativeEvent.isComposing || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
                  event.preventDefault(); const range = pending.current[line.id] ?? line;
                  moveClip(line.id, range, range.start_ms + (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 100 : 10), true, false);
                }}
                onClick={() => { if (suppressClick.current) { suppressClick.current = false; return; } onSeek(line.start_ms); onSelectLine?.(line.id, line.start_ms); }}
                title={`${formatMs(line.start_ms)}–${formatMs(line.end_ms)}${changed ? " · unsaved timing draft" : ""}`}>
                <span className="timelineText"><b>{line.index + 1}</b> {line.speaker ? `${line.speaker}: ` : ""}{line.label}</span>
              </button>
            </div>;
          })}
        </div>
        <div className="timelineTrack" data-track="takes" role="group" aria-label="Selected takes track">
          {tracks.takes.map((take) => <div key={take.lineId} className={`timelineTake ${take.fit}`}
            style={{ left: take.start_ms * pxPerMs, width: Math.max(4, (take.end_ms - take.start_ms) * pxPerMs) }}
            title={`Take ${FIT_LABEL[take.fit]}${take.rawDurationMs ? ` · raw ${formatMs(take.rawDurationMs)}` : ""}${take.demo ? " · DEMO tone" : ""}`}>
            {take.demo && take.fit !== "missing" ? "DEMO" : take.fit === "ready" ? "" : FIT_LABEL[take.fit]}</div>)}
        </div>
        {tracks.stems.map((stem) => <div key={stem.name} className="timelineTrack stemTrack" data-track={stem.name} aria-label={`${stem.name} stem`}>
          <span>{stem.demo && <DemoBadge />}{stem.name}</span></div>)}
        <div className="timelinePlayhead" ref={playhead} aria-hidden="true" />
      </div>
    </div>
    </div>
    <p className="visuallyHidden" aria-live="polite">{announcement}</p>
  </section>;
}
