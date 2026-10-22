"use client";

import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

type Panel = "tools" | "inspector" | "timeline";
type Sizes = Record<Panel, number>;
const DEFAULTS: Sizes = { tools: 310, inspector: 370, timeline: 258 };
const MINIMUM: Sizes = { tools: 240, inspector: 310, timeline: 160 };
const MAXIMUM: Sizes = { tools: 480, inspector: 520, timeline: 560 };
const STORAGE_KEY = "cinedub.workspace-layout.v1";
const clamp = (value: number, min: number, max: number) => Math.round(Math.max(min, Math.min(max, value)));

/** Layout preferences are independent of the project and never contain editing data. */
export function WorkspaceLayout({ children, toolsOpen, inspectorOpen, timelineOpen }: {
  children: ReactNode; toolsOpen: boolean; inspectorOpen: boolean; timelineOpen: boolean;
}) {
  const grid = useRef<HTMLElement>(null);
  const [sizes, setSizes] = useState<Sizes>(DEFAULTS);
  const sizesRef = useRef(DEFAULTS);
  const [space, setSpace] = useState({ width: 1440, height: 842 });
  const [resizing, setResizing] = useState<Panel | null>(null);
  const drag = useRef<{ panel: Panel; coordinate: number; value: number; previous: Sizes } | null>(null);

  useEffect(() => {
    const element = grid.current;
    if (!element) return;
    function measure() {
      if (!element) return;
      const height = window.innerWidth > 1100 ? element.clientHeight : window.innerHeight - element.getBoundingClientRect().top;
      setSpace((current) => current.width === element.clientWidth && current.height === height
        ? current : { width: element.clientWidth, height });
    }
    const frame = requestAnimationFrame(() => {
      try {
        const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
        if (saved && typeof saved === "object") {
          const next = { ...DEFAULTS };
          for (const panel of ["tools", "inspector", "timeline"] as const) {
            const value = (saved as Record<string, unknown>)[panel];
            if (typeof value === "number" && Number.isFinite(value)) next[panel] = clamp(value, MINIMUM[panel], MAXIMUM[panel]);
          }
          sizesRef.current = next; setSizes(next);
        }
      } catch { /* Layout still works when browser storage is unavailable. */ }
      measure();
    });
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    window.addEventListener("resize", measure);
    return () => { cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener("resize", measure); };
  }, []);

  const desktop = space.width > 1100;
  const sideSpace = space.width - 320 - (toolsOpen ? 6 : 0) - (desktop && inspectorOpen ? 6 : 0);
  let tools = toolsOpen ? sizes.tools : 0;
  let inspector = desktop && inspectorOpen ? sizes.inspector : 0;
  // Keep a usable monitor when saved preferences exceed a smaller window.
  if (space.width > 760 && tools + inspector > sideSpace) {
    const excess = tools + inspector - sideSpace;
    const toolsRoom = toolsOpen ? tools - MINIMUM.tools : 0;
    const inspectorRoom = inspector ? inspector - MINIMUM.inspector : 0;
    const totalRoom = toolsRoom + inspectorRoom;
    if (totalRoom > 0) {
      tools -= excess * toolsRoom / totalRoom;
      inspector -= excess * inspectorRoom / totalRoom;
    }
  }
  tools = Math.round(tools); inspector = Math.floor(inspector);
  const bounds: Record<Panel, { min: number; max: number }> = {
    tools: { min: MINIMUM.tools, max: Math.max(MINIMUM.tools, Math.min(MAXIMUM.tools, sideSpace - inspector)) },
    inspector: { min: MINIMUM.inspector, max: Math.max(MINIMUM.inspector, Math.min(MAXIMUM.inspector, sideSpace - tools)) },
    timeline: { min: MINIMUM.timeline, max: Math.max(MINIMUM.timeline, Math.min(MAXIMUM.timeline, space.height - 48 - 6 - 250)) },
  };
  const fitted: Sizes = { tools, inspector, timeline: clamp(sizes.timeline, bounds.timeline.min, bounds.timeline.max) };

  function remember() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(sizesRef.current)); } catch { /* Storage is optional. */ }
  }
  function resize(panel: Panel, value: number, persist = false) {
    const next = { ...sizesRef.current, [panel]: clamp(value, bounds[panel].min, bounds[panel].max) };
    // A resize acts on the visible panes, even when older preferences were larger.
    if (panel === "tools" && desktop && inspectorOpen) next.inspector = fitted.inspector;
    if (panel === "inspector" && toolsOpen) next.tools = fitted.tools;
    sizesRef.current = next; setSizes(next);
    if (persist) remember();
  }
  function start(panel: Panel, event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    event.preventDefault(); event.currentTarget.focus({ preventScroll: true });
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { panel, coordinate: panel === "timeline" ? event.clientY : event.clientX, value: fitted[panel], previous: sizesRef.current };
    setResizing(panel);
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const active = drag.current;
    if (!active) return;
    const coordinate = active.panel === "timeline" ? event.clientY : event.clientX;
    resize(active.panel, active.value + (coordinate - active.coordinate) * (active.panel === "tools" ? 1 : -1));
  }
  function finish(cancel = false) {
    const active = drag.current;
    if (!active) return;
    if (cancel) { sizesRef.current = active.previous; setSizes(active.previous); }
    else remember();
    drag.current = null; setResizing(null);
  }
  function keyboard(panel: Panel, event: KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const directions: Record<string, number> = panel === "timeline"
      ? { ArrowUp: 1, ArrowDown: -1 } : panel === "tools" ? { ArrowRight: 1, ArrowLeft: -1 } : { ArrowLeft: 1, ArrowRight: -1 };
    let value: number;
    if (event.key in directions) value = fitted[panel] + directions[event.key] * (event.shiftKey ? 50 : 10);
    else if (event.key === "Home") value = bounds[panel].min;
    else if (event.key === "End") value = bounds[panel].max;
    else if (event.key === "Enter") value = DEFAULTS[panel];
    else return;
    event.preventDefault(); resize(panel, value, true);
  }
  function separator(panel: Panel, label: string, controls: string, open: boolean) {
    return <div className={`workspaceResizer ${panel}Resizer`} role="separator" tabIndex={0} hidden={!open}
      aria-label={label} aria-controls={controls} aria-orientation={panel === "timeline" ? "horizontal" : "vertical"}
      aria-valuemin={bounds[panel].min} aria-valuemax={bounds[panel].max} aria-valuenow={fitted[panel]} aria-valuetext={`${fitted[panel]} pixels`}
      title="Drag to resize. Arrow keys adjust; Enter or double-click resets."
      onPointerDown={(event) => start(panel, event)} onPointerMove={move} onPointerUp={() => finish()}
      onPointerCancel={() => finish(true)} onLostPointerCapture={() => finish()}
      onDoubleClick={() => resize(panel, DEFAULTS[panel], true)} onKeyDown={(event) => keyboard(panel, event)} />;
  }
  const style = {
    "--tools-width": `${toolsOpen ? fitted.tools : 0}px`, "--tools-handle": toolsOpen ? "6px" : "0px",
    "--inspector-width": `${inspectorOpen ? fitted.inspector : 0}px`, "--inspector-handle": inspectorOpen ? "6px" : "0px",
    "--timeline-height": `${timelineOpen ? fitted.timeline : 49}px`, "--timeline-handle": timelineOpen ? "6px" : "0px",
  } as CSSProperties;
  return <section ref={grid} style={style} className={`studioGrid ${resizing ? `resizing resizing-${resizing}` : ""} ${toolsOpen ? "" : "toolsCollapsed"} ${inspectorOpen ? "" : "inspectorCollapsed"} ${timelineOpen ? "" : "timelineCollapsed"}`}>
    {children}
    {separator("tools", "Resize tools panel", "scene-tools", toolsOpen)}
    {separator("inspector", "Resize dialogue inspector", "dialogue-inspector", inspectorOpen)}
    {separator("timeline", "Resize timeline", "timeline-workspace", timelineOpen)}
  </section>;
}
