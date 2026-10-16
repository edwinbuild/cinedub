"use client";

import { useRef, type ReactNode } from "react";

export function DialogueTimeline({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const lastFocused = useRef<HTMLElement | null>(null);
  function move(direction: number, from?: HTMLElement | null) {
    const lines = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-dialogue-line]:not([hidden])") ?? []);
    const anchor = from ?? lastFocused.current;
    const index = anchor ? lines.indexOf(anchor) : -1;
    const next = index < 0 ? (direction > 0 ? 0 : lines.length - 1) : index + direction;
    const line = lines[next];
    if (line) { line.focus(); lastFocused.current = line; }
  }
  return <div ref={root} onFocusCapture={(event) => {
    const line = event.target.closest<HTMLElement>("[data-dialogue-line]");
    if (line) lastFocused.current = line;
  }} onKeyDown={(event) => {
    if (event.nativeEvent.isComposing || event.repeat || !event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    if (event.target instanceof HTMLElement && event.target.closest("select,[role=combobox],audio,video,[contenteditable=true]")) return;
    const line = event.target instanceof HTMLElement ? event.target.closest<HTMLElement>("[data-dialogue-line]") : null;
    if (!line) return;
    event.preventDefault(); move(event.key === "ArrowDown" ? 1 : -1, line);
  }}>
    <div className="reviewFilters" role="group" aria-label="Dialogue navigation">
      <button className="smallButton" onClick={() => move(-1)}>Previous line</button>
      <button className="smallButton" onClick={() => move(1)}>Next line</button>
    </div>
    <p className="muted">Alt+↑/↓ moves between visible lines. Ctrl/⌘+Enter saves the focused line. Text undo stays native; saved undo/redo is in each line’s history.</p>
    <div className="segments">{children}</div>
  </div>;
}
