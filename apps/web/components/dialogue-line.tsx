"use client";

import type { Artifact, Segment, SegmentBatchItem, Speaker } from "@cinedub/contracts";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { VoiceCandidates } from "@/components/voice-candidates";
import { LineHistory } from "@/components/line-history";

function draft(line: Segment) {
  return { source_text: line.source_text, translated_text: line.translated_text,
    start_ms: line.start_ms, end_ms: line.end_ms, speaker_id: line.speaker_id, status: line.status };
}

export type GroupedDraft = {
  item: SegmentBatchItem; blocked: boolean; accept: (saved: Segment) => void;
};

export function DialogueLine({ segment, speakers, artifacts, disabled, structureLocked, active, canPlay, hidden, onPlay, onSaved, onDirty, onRegenerate, onGenerate, onGroupedDraft, onTimingEditor, onTimingDraft }: {
  segment: Segment; speakers: Speaker[]; active: boolean; canPlay: boolean; hidden: boolean;
  onPlay: (segment: Segment) => void; onSaved: () => void; onDirty: (id: string, dirty: boolean) => void;
  onRegenerate: (id: string) => void;
  artifacts: Artifact[]; disabled: boolean;
  structureLocked: boolean;
  onGenerate: (id: string) => void;
  onGroupedDraft: (id: string, value: GroupedDraft | null) => void;
  /** Lets the timeline edit this line's unsaved timing draft (never saves directly). */
  onTimingEditor?: (id: string, apply: ((range: { start_ms: number; end_ms: number }) => void) | null) => void;
  onTimingDraft?: (id: string, range: { start_ms: number; end_ms: number } | null) => void;
}) {
  const [base, setBase] = useState(segment);
  const [values, setValues] = useState(() => draft(segment));
  const [saving, setSaving] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const root = useRef<HTMLElement>(null);
  const saveFocus = useRef<HTMLElement | null>(null);
  const dirty = JSON.stringify(values) !== JSON.stringify(draft(base));
  const stale = segment.version > base.version;

  useEffect(() => {
    if (!dirty) { onGroupedDraft(segment.id, null); return; }
    const changes = Object.fromEntries(Object.entries(values).filter(([key, value]) =>
      value !== draft(base)[key as keyof typeof values]));
    onGroupedDraft(segment.id, {
      item: { ...changes, segment_id: segment.id, expected_version: base.version },
      blocked: segment.retired || saving || restoring || stale,
      accept: (saved) => {
        setBase(saved); setValues(draft(saved)); setError(null);
        onDirty(segment.id, false); setNotice("Line saved in grouped edit. Review is still required unless already approved.");
      },
    });
    return () => onGroupedDraft(segment.id, null);
  }, [base, values, dirty, segment.id, segment.retired, saving, restoring, stale, onGroupedDraft, onDirty]);

  useLayoutEffect(() => {
    if (saving || !saveFocus.current) return;
    const target = saveFocus.current; saveFocus.current = null;
    if (document.activeElement !== document.body || !target.isConnected || target.closest("[hidden]")) return;
    if (!target.matches(":disabled")) target.focus();
    else root.current?.focus();
  }, [saving]);

  useEffect(() => {
    if (dirty || !stale) return;
    const timer = window.setTimeout(() => { setBase(segment); setValues(draft(segment)); setNotice(""); }, 0);
    return () => window.clearTimeout(timer);
  }, [segment, dirty, stale]);

  const editable = !disabled && !segment.retired && !saving && !restoring && !stale;
  useEffect(() => {
    if (!onTimingEditor) return;
    // Re-registered each render so the timeline always edits the latest draft.
    onTimingEditor(segment.id, editable ? (range) => change({ start_ms: range.start_ms, end_ms: range.end_ms }) : null);
    return () => onTimingEditor(segment.id, null);
  });
  useEffect(() => {
    const moved = values.start_ms !== base.start_ms || values.end_ms !== base.end_ms;
    onTimingDraft?.(segment.id, moved ? { start_ms: values.start_ms, end_ms: values.end_ms } : null);
  }, [values.start_ms, values.end_ms, base.start_ms, base.end_ms, segment.id, onTimingDraft]);
  useEffect(() => () => onTimingDraft?.(segment.id, null), [segment.id, onTimingDraft]);

  function change(next: Partial<typeof values>) {
    const updated = { ...values, ...next }; setValues(updated); setNotice("");
    onDirty(segment.id, JSON.stringify(updated) !== JSON.stringify(draft(base)));
  }
  async function save() {
    if (segment.retired || saving || restoring || structureLocked || stale || !dirty) return;
    saveFocus.current = document.activeElement instanceof HTMLElement && root.current?.contains(document.activeElement)
      ? document.activeElement : null;
    setSaving(true); setError(null); setNotice("Saving line…");
    try {
      const changes = Object.fromEntries(Object.entries(values).filter(([key, value]) =>
        value !== draft(base)[key as keyof typeof values]));
      const saved = await api.updateSegment(base, changes);
      setBase(saved); setValues(draft(saved)); onDirty(segment.id, false); onSaved();
      setNotice(saved.status === "approved" ? "Line saved and approved." : "Line saved. Review is still required.");
    } catch (cause) { setNotice(""); setError(cause instanceof Error ? cause.message : "Save failed"); }
    finally { setSaving(false); }
  }

  function downloadDraft() {
    const file = new Blob([JSON.stringify({ segment_id: base.id, revision_id: base.revision_id,
      based_on_version: base.version, warning: "Removed from current timeline; not saved dialogue", ...values }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(file);
    const link = document.createElement("a"); link.href = url; link.download = `cinedub-preserved-draft-${base.id}.json`;
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <article ref={root} id={`line-${segment.id}`} hidden={hidden} tabIndex={-1} data-dialogue-line className={`dialogueLine ${active ? "playing" : ""}`} aria-label={segment.retired ? `Preserved draft for removed line ${segment.index + 1}` : `Dialogue line ${segment.index + 1}`}
    onKeyDown={(event) => {
      if (!event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229 && !event.repeat && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && event.key === "Enter") {
        event.preventDefault();
        if (dirty && !segment.retired && !saving && !restoring && !structureLocked && !stale) void save();
      }
    }}>
    {segment.retired && <div className="lineWarning" role="status"><p>This line is no longer in the active timeline. Your unsaved dialogue draft is preserved below, not applied to its replacement.</p>
      <button className="smallButton" onClick={downloadDraft}>Download preserved dialogue draft</button>
      <button className="smallButton" onClick={() => { if (window.confirm("Discard this preserved dialogue draft? Download or copy it first if needed.")) onDirty(segment.id, false); }}>Discard preserved dialogue draft</button>
    </div>}
    <fieldset className="lineFields" disabled={saving || restoring || structureLocked} aria-label={`Editable fields for line ${segment.index + 1}`}>
    <div className="lineHeader"><strong>Line {segment.index + 1}</strong>
      <button className="smallButton" onClick={() => onPlay(segment)} disabled={!canPlay}>Play this line</button>
      <label>Speaker<select disabled={segment.retired} aria-label={`Speaker for line ${segment.index + 1}`} value={values.speaker_id ?? ""}
        onChange={(event) => change({ speaker_id: event.target.value || null })}>
        <option value="">Unassigned</option>{speakers.map((speaker) => <option key={speaker.id} value={speaker.id}>{speaker.display_name}</option>)}
      </select></label>
      <label>Start (s)<input type="number" min="0" step="0.001" value={values.start_ms / 1000}
        onChange={(event) => change({ start_ms: Math.round(Number(event.target.value) * 1000) })} /></label>
      <label>End (s)<input type="number" min="0" step="0.001" value={values.end_ms / 1000}
        onChange={(event) => change({ end_ms: Math.round(Number(event.target.value) * 1000) })} /></label>
    </div>
    <div className="lineTexts"><label>English<textarea aria-label="English" value={values.source_text}
      onChange={(event) => change({ source_text: event.target.value })} maxLength={4000} /></label>
      <label>Malayalam<textarea aria-label="Malayalam" lang="ml" value={values.translated_text}
        onChange={(event) => change({ translated_text: event.target.value })} maxLength={4000} /></label></div>
    <div className="lineFooter"><span>{segment.human_edited ? "Human edited" : "Provider draft"}
      {segment.emotion_label ? ` · Demo emotion: ${segment.emotion_label}` : " · Emotion not analyzed"}</span>
      <label>Review<select aria-label={`Review state for line ${segment.index + 1}`} value={values.status}
        onChange={(event) => change({ status: event.target.value as Segment["status"] })}>
        <option value="draft">Draft</option><option value="translated">Translated</option>
        <option value="needs_review">Needs review</option><option value="approved">Approved</option>
        <option value="voiced">Voiced</option></select></label>
      <button className="smallButton" onClick={() => onRegenerate(segment.id)} disabled={segment.retired || dirty || saving}>Regenerate translation</button>
      <button className="smallButton" onClick={() => onGenerate(segment.id)} disabled={segment.retired || disabled || dirty || saving || segment.status !== "approved"}>Generate voice</button>
      <button className="smallButton" aria-keyshortcuts="Control+Enter Meta+Enter" onClick={save} disabled={segment.retired || !dirty || saving || stale}>{saving ? "Saving…" : "Save line"}</button>
    </div>
    </fieldset>
    {segment.warnings_json.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
    {stale && dirty && !segment.retired && <p className="lineWarning">This line changed on the server. Your draft is preserved.
      <button className="smallButton" onClick={() => { if (window.confirm("Discard your unsaved draft and load the saved line?")) {
        setBase(segment); setValues(draft(segment)); onDirty(segment.id, false); setError(null); setNotice("");
      } }}>Load saved line</button></p>}
    {dirty && <small className="muted">Unsaved changes. Changing dialogue or timing requires approval again.</small>}
    <p className="muted lineSaveStatus" role="status" aria-atomic="true">{notice}</p>
    {error && <p className="inlineError" role="alert">{error}</p>}
    <LineHistory segment={segment} disabled={segment.retired || disabled || dirty || saving || restoring || stale} onRestoring={setRestoring} onRestored={(saved) => {
      setBase(saved); setValues(draft(saved)); onDirty(segment.id, false); setNotice(""); onSaved();
    }} />
    <VoiceCandidates segment={segment} artifacts={artifacts} disabled={segment.retired || disabled || dirty || saving || restoring || stale} onSaved={onSaved} />
  </article>;
}
