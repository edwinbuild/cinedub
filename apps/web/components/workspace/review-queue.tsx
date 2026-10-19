"use client";

import type { ProjectDetail } from "@cinedub/contracts";
import { useMemo, useState } from "react";
import { attentionItems, type AttentionKind } from "@/lib/review-queue";

const FILTERS: Array<{ value: "all" | AttentionKind; label: string }> = [
  { value: "all", label: "All" },
  { value: "unapproved", label: "Unapproved" },
  { value: "untranslated", label: "Untranslated" },
  { value: "no_speaker", label: "No speaker" },
  { value: "take_overrun", label: "Timing" },
  { value: "line_warning", label: "Warnings" },
];

/** One place for everything that still needs a human decision, in urgency order. */
export function ReviewQueue({ project, onGoTo }: {
  project: ProjectDetail; onGoTo: (lineId: string, startMs: number) => void;
}) {
  const items = useMemo(() => attentionItems(project), [project]);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["value"]>("all");
  const shown = items.filter((item) => filter === "all" || item.kind === filter);
  if (!project.segments.length) return null;
  return <details className="dubPreview reviewQueue" aria-label="Needs attention">
    <summary>Needs attention · {items.length}</summary>
    {items.length === 0 ? <p>Every line is translated, assigned, approved and timed. Listen once more before delivery.</p> : <>
      <div className="reviewFilters" role="group" aria-label="Attention filter">{FILTERS.map((option) =>
        <button key={option.value} className={`smallButton ${filter === option.value ? "selected" : ""}`} aria-pressed={filter === option.value}
          onClick={() => setFilter(option.value)}>{option.label}</button>)}</div>
      <ul className="attentionList">{shown.map((item) =>
        <li key={item.key} className={`attention ${item.kind}`}>
          <span>{item.message}</span>
          {item.lineId && item.start_ms !== null && <button className="smallButton" onClick={() => onGoTo(item.lineId!, item.start_ms!)}>Go to line</button>}
        </li>)}</ul>
    </>}
  </details>;
}
