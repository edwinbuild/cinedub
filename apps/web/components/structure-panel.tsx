"use client";

import type { ProjectDetail, Segment, TimelineStructureEdit } from "@cinedub/contracts";
import { useImperativeHandle, useRef, useState, type Ref } from "react";
import { api } from "@/lib/api";

type Props = {
  project: ProjectDetail; disabled: boolean; unsaved: boolean;
  onApply: (action: () => Promise<unknown>) => Promise<void>;
  onPlayRange: (start: number, end: number) => Promise<void>; canPlay: boolean;
  onDirty: (dirty: boolean) => void;
  editorRef?: Ref<{ open: (lineId: string | null) => void }>;
};

function StructureForm({ line, next, unavailable, disabled, onApply, onPlayRange, canPlay, onDirty }: {
  line: Segment; next?: Segment; disabled: boolean;
  onApply: Props["onApply"]; onPlayRange: Props["onPlayRange"]; canPlay: boolean;
  unavailable: boolean; onDirty: Props["onDirty"];
}) {
  const [base, setBase] = useState({ line, next });
  const [mode, setMode] = useState("split");
  const [splitTime, setSplitTime] = useState((line.start_ms + line.end_ms) / 2000);
  const [firstSource, setFirstSource] = useState(line.source_text);
  const [firstTarget, setFirstTarget] = useState(line.translated_text);
  const [secondSource, setSecondSource] = useState("");
  const [secondTarget, setSecondTarget] = useState("");
  const [mergedSource, setMergedSource] = useState(`${line.source_text} ${next?.source_text ?? ""}`.trim());
  const [mergedTarget, setMergedTarget] = useState(`${line.translated_text} ${next?.translated_text ?? ""}`.trim());
  const [confirmed, setConfirmed] = useState(false);
  const stale = unavailable || line.version !== base.line.version || next?.id !== base.next?.id || next?.version !== base.next?.version;
  const mergeAvailable = !!base.next && base.line.speaker_id === base.next.speaker_id;
  function refresh() {
    if (!window.confirm("Replace this split/merge form with the current saved lines? Unsaved form text will be discarded.")) return;
    setBase({ line, next }); setFirstSource(line.source_text); setFirstTarget(line.translated_text);
    setSecondSource(""); setSecondTarget(""); setSplitTime((line.start_ms + line.end_ms) / 2000);
    setMergedSource(`${line.source_text} ${next?.source_text ?? ""}`.trim());
    setMergedTarget(`${line.translated_text} ${next?.translated_text ?? ""}`.trim()); setConfirmed(false); onDirty(false);
  }
  async function submit() {
    if (disabled || stale || !confirmed || !base.line.revision_id) return;
    if (mode === "split") await onApply(() => api.splitSegment(base.line.id, {
      revision_id: base.line.revision_id!, expected_version: base.line.version,
      split_ms: Math.round(splitTime * 1000), first: { source_text: firstSource, translated_text: firstTarget },
      second: { source_text: secondSource, translated_text: secondTarget }, replacement_confirmed: confirmed,
    }));
    else if (base.next && mergeAvailable) await onApply(() => api.mergeSegment(base.line.id, {
      revision_id: base.line.revision_id!, next_segment_id: base.next!.id,
      expected_version: base.line.version, expected_next_version: base.next!.version,
      text: { source_text: mergedSource, translated_text: mergedTarget }, replacement_confirmed: confirmed,
    }));
  }
  return <div aria-label="Structure edit form" onChange={() => onDirty(true)}>
    {stale && <p className="lineWarning">Saved lines changed. This form is preserved; load current lines before applying.</p>}
    <button className="smallButton" disabled={disabled || unavailable} onClick={refresh}>Load current lines into form</button>
    <fieldset disabled={disabled}><legend>Manual line correction</legend>
      <label className="fieldLabel">Structure operation<select aria-label="Structure operation" value={mode} onChange={(event) => setMode(event.target.value)}>
        <option value="split">Split one line</option><option value="merge">Merge with next line</option></select></label>
      <p>Saved window: {(base.line.start_ms / 1000).toFixed(3)}–{(base.line.end_ms / 1000).toFixed(3)}s. No automatic word-boundary or translation guess.</p>
      <button className="smallButton" disabled={!canPlay} onClick={() => onPlayRange(base.line.start_ms, base.line.end_ms)}>Listen to line before restructuring</button>
      {mode === "split" ? <>
        <label className="fieldLabel">Split time in seconds<input aria-label="Split time in seconds" type="number" step="0.001" min={(base.line.start_ms + 1) / 1000} max={(base.line.end_ms - 1) / 1000}
          value={splitTime} onChange={(event) => setSplitTime(Number(event.target.value))} /></label>
        <label className="fieldLabel">First part English<textarea aria-label="First part English" maxLength={4000} value={firstSource} onChange={(event) => setFirstSource(event.target.value)} /></label>
        <label className="fieldLabel">First part Malayalam<textarea aria-label="First part Malayalam" lang="ml" maxLength={4000} value={firstTarget} onChange={(event) => setFirstTarget(event.target.value)} /></label>
        <label className="fieldLabel">Second part English<textarea aria-label="Second part English" maxLength={4000} value={secondSource} onChange={(event) => setSecondSource(event.target.value)} /></label>
        <label className="fieldLabel">Second part Malayalam<textarea aria-label="Second part Malayalam" lang="ml" maxLength={4000} value={secondTarget} onChange={(event) => setSecondTarget(event.target.value)} /></label>
      </> : <>
        <p>Next saved line: {base.next?.source_text ?? "none"}</p>
        {!mergeAvailable && <p className="lineWarning">Choose a line with a following line assigned to the same speaker. Correct speaker assignment first if needed.</p>}
        <label className="fieldLabel">Merged English<textarea aria-label="Merged English" maxLength={4000} value={mergedSource} onChange={(event) => setMergedSource(event.target.value)} /></label>
        <label className="fieldLabel">Merged Malayalam<textarea aria-label="Merged Malayalam" lang="ml" maxLength={4000} value={mergedTarget} onChange={(event) => setMergedTarget(event.target.value)} /></label>
      </>}
      <label className="performanceToggle"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Replace the saved lines, clear their selected takes and require approval again</label>
      <button className="smallButton" disabled={stale || !confirmed || (mode === "split" ? !firstSource.trim() || !secondSource.trim() : !mergeAvailable || !mergedSource.trim())}
        onClick={submit}>{mode === "split" ? "Split saved line" : "Merge saved lines"}</button>
    </fieldset>
  </div>;
}

export function StructurePanel({ project, disabled, unsaved, onApply, onPlayRange, canPlay, onDirty, editorRef }: Props) {
  const root = useRef<HTMLDetailsElement>(null);
  const [selection, setSelection] = useState<Segment | null>(null);
  const [formDirty, setFormDirty] = useState(false);
  const [history, setHistory] = useState<TimelineStructureEdit[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const savedSelection = selection ?? project.segments[0];
  const current = project.segments.find((line) => line.id === savedSelection?.id);
  const selected = current ?? savedSelection;
  const next = project.segments[project.segments.findIndex((line) => line.id === selected?.id) + 1];
  useImperativeHandle(editorRef, () => ({ open(lineId) {
    const line = project.segments.find((item) => item.id === lineId) ?? project.segments[0];
    if (line && line.id !== selected?.id) {
      if (formDirty && !window.confirm("Discard the current unsaved split/merge form and select another line?")) return;
      setSelection(line); setFormDirty(false); onDirty(false);
    }
    if (root.current) { root.current.open = true; root.current.scrollIntoView({ block: "start" }); }
  } }));
  async function loadHistory() {
    if (!project.active_revision_id) return;
    try { setBusy(true); setError(null); setHistory(await api.structureHistory(project.id, project.active_revision_id)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load structural history"); }
    finally { setBusy(false); }
  }
  async function apply(action: () => Promise<unknown>) {
    try { setBusy(true); setError(null); await onApply(action); setSelection(null); setFormDirty(false); onDirty(false); await loadHistory(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Structural edit failed"); }
    finally { setBusy(false); }
  }
  async function restore(operation: TimelineStructureEdit) {
    if (!window.confirm("Reverse this structural edit? Affected lines need approval again and their selected takes are cleared. Later edits will not be overwritten.")) return;
    const versions = Object.fromEntries([
      ...operation.before.map((line) => [line.id, line.version + 1]),
      ...operation.after.map((line) => [line.id, line.version]),
    ]);
    await apply(() => api.restoreStructure(operation.id, { revision_id: operation.revision_id,
      expected_versions: versions, restoration_confirmed: true }));
  }
  return <details ref={root} className="dubPreview structurePanel" aria-label="Split merge and structural history"
    onToggle={(event) => { if (event.target === event.currentTarget && event.currentTarget.open && history === null && !busy) {
      setSelection((value) => value ?? project.segments[0] ?? null); void loadHistory();
    } }}>
    <summary>Split, merge & structural history</summary>
    <p>Keep originals and previous artifacts as read-only history. Unchanged lines keep their identity and selected takes. Split/merge changes need fresh review; this does not splice or generate voice audio.</p>
    {unsaved && <p className="lineWarning">Save all dialogue and brief drafts before changing timeline structure.</p>}
    <label className="fieldLabel">Line to restructure<select aria-label="Line to restructure" value={selected?.id ?? ""} disabled={disabled || busy || unsaved} onChange={(event) => {
      if (formDirty && !window.confirm("Discard the current unsaved split/merge form and select another line?")) return;
      setSelection(project.segments.find((line) => line.id === event.target.value) ?? null); setFormDirty(false); onDirty(false);
    }}>
      {selected && !current && <option value={selected.id}>Replaced line · form preserved</option>}
      {project.segments.map((line) => <option key={line.id} value={line.id}>Line {line.index + 1} · {line.source_text.slice(0, 60)}</option>)}</select></label>
    {selected && <StructureForm key={selected.id} line={selected} next={next} unavailable={!current} disabled={disabled || busy || unsaved}
      onApply={apply} onPlayRange={onPlayRange} canPlay={canPlay} onDirty={(dirty) => { setFormDirty(dirty); onDirty(dirty); }} />}
    <button className="smallButton" disabled={busy} onClick={loadHistory}>Refresh structural history</button>
    {history?.map((operation, index) => <article className="alignmentLine" key={operation.id} aria-label={`Structural edit ${history.length - index}`}>
      <h3>{operation.action} · {new Date(operation.created_at).toLocaleString()}</h3>
      <p>Before: {operation.before.map((line) => line.source_text).join(" / ")}</p>
      <p>After: {operation.after.map((line) => line.source_text).join(" / ")}</p>
      {operation.unavailable_reason && <p className="lineWarning">{operation.unavailable_reason}</p>}
      <button className="smallButton" disabled={disabled || busy || unsaved || formDirty || !operation.restorable} onClick={() => restore(operation)}>Reverse structural edit</button>
    </article>)}
    {history?.length === 0 && <p>No structural edits yet.</p>}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </details>;
}
