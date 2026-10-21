"use client";

import type { Segment, SegmentContent, SegmentHistory } from "@cinedub/contracts";
import { useState } from "react";
import { api } from "@/lib/api";

function Snapshot({ value }: { value: SegmentContent | null }) {
  if (!value) return <p>Historical content unavailable</p>;
  return <div className="historySnapshot"><p>{(value.start_ms / 1000).toFixed(3)}–{(value.end_ms / 1000).toFixed(3)}s · speaker {value.speaker_id ?? "unassigned"}</p>
    <p>English: {value.source_text}</p><p lang="ml">Malayalam: {value.translated_text || "none"}</p></div>;
}

export function LineHistory({ segment, disabled, onRestored, onRestoring }: {
  segment: Segment; disabled: boolean; onRestored: (saved: Segment) => void;
  onRestoring: (busy: boolean) => void;
}) {
  const [history, setHistory] = useState<SegmentHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = history?.version === segment.version;
  async function load() {
    try { setBusy(true); setError(null); setHistory(await api.segmentHistory(segment.id)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load history"); }
    finally { setBusy(false); }
  }
  async function restore(action: "undo" | "redo") {
    const target = action === "undo" ? history?.undo_edit_id : history?.redo_edit_id;
    if (!history || !target || !current || disabled || !confirmed) return;
    try {
      setBusy(true); onRestoring(true); setError(null);
      const saved = await api.restoreSegmentHistory(segment.id, { action, expected_edit_id: target,
        expected_version: history.version, restoration_confirmed: confirmed });
      onRestored(saved); setHistory(await api.segmentHistory(segment.id));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not restore saved edit"); }
    finally { setBusy(false); onRestoring(false); }
  }
  return <details className="lineHistory" aria-label={`Saved history for line ${segment.index + 1}`}
    onToggle={(event) => { if (event.currentTarget.open && !current && !busy) void load(); }}>
    <summary>Saved edit history</summary>
    <p>Undo and redo saved English/Malayalam text, speaker and timing edits. Browser text undo still works inside text boxes. Approval, emotion settings and voice selection are not restored.</p>
    <button className="smallButton" disabled={busy} onClick={load}>Refresh saved history</button>
    {history && <>
      {!current && <p className="lineWarning">Line changed; refresh history before restoring.</p>}
      {history.unavailable_reason && <p className="lineWarning">{history.unavailable_reason}</p>}
      <label className="performanceToggle"><input type="checkbox" checked={confirmed} disabled={disabled || busy} onChange={(event) => setConfirmed(event.target.checked)} />Restoring clears selected voice audio and requires approval again</label>
      <button className="smallButton" disabled={disabled || busy || !current || !confirmed || !history.undo_edit_id} onClick={() => restore("undo")}>Undo saved edit</button>
      <button className="smallButton" disabled={disabled || busy || !current || !confirmed || !history.redo_edit_id} onClick={() => restore("redo")}>Redo saved edit</button>
      <p aria-live="polite">{history.total_entries} saved history records · showing latest {history.entries.length}</p>
      {history.entries.map((entry) => <details key={entry.id}><summary>Version {entry.version} · {entry.action} · {new Date(entry.created_at).toLocaleString()}</summary>
        <h4>Before</h4><Snapshot value={entry.before} /><h4>After</h4><Snapshot value={entry.after} /></details>)}
    </>}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </details>;
}
