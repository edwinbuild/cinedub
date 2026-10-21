"use client";

import type { ProjectDetail, Speaker, SpeakerReuse, SpeakerReusePreview } from "@cinedub/contracts";
import { useState } from "react";
import { api } from "@/lib/api";

export function SpeakerReusePanel({ project, disabled, unsaved, onSaved }: {
  project: ProjectDetail; disabled: boolean; unsaved: boolean; onSaved: () => Promise<void>;
}) {
  const [sources, setSources] = useState<Speaker[]>([]);
  const [targetId, setTargetId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [copy, setCopy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<SpeakerReusePreview | null>(null);
  const [history, setHistory] = useState<SpeakerReuse[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  function resetPreview() { setPreview(null); setConfirmed(false); setError(null); }
  async function action(run: () => Promise<void>) {
    try { setBusy(true); setError(null); await run(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Character reuse failed"); }
    finally { setBusy(false); }
  }
  async function load() {
    await action(async () => { setSources(await api.earlierSpeakers(project.id)); setLoaded(true); });
  }
  async function apply() {
    if (!preview || !confirmed || disabled || unsaved || busy) return;
    await action(async () => {
      await api.reuseSpeaker(targetId, { source_speaker_id: sourceId, copy_stock_voice: copy,
        expected_fingerprint: preview.fingerprint, identity_confirmed: confirmed });
      resetPreview(); setHistory(await api.speakerReuseHistory(targetId)); await onSaved();
    });
  }
  return <details className="dubPreview" aria-label="Reuse earlier character" onToggle={(event) => {
    if (event.currentTarget.open && !loaded && !busy) void load();
  }}>
    <summary>Reuse earlier character · reviewed identity mapping</summary>
    <p>Speaker numbers can change on every transcription. Audition the earlier and current speakers before explicitly reusing a name. This is not automatic speaker recognition.</p>
    <button className="smallButton" disabled={busy} onClick={load}>Refresh earlier characters</button>
    {loaded && !sources.length && <p>No earlier revision speakers are available yet.</p>}
    <fieldset disabled={disabled || busy}><legend>Reviewed character reuse</legend>
      <label className="fieldLabel">Current speaker<select aria-label="Current speaker to map" value={targetId} onChange={(event) => {
        setTargetId(event.target.value); resetPreview(); setHistory([]);
      }}><option value="">Choose current speaker</option>{project.speakers.map((speaker) => <option key={speaker.id} value={speaker.id}>{speaker.display_name}</option>)}</select></label>
      <label className="fieldLabel">Earlier character<select aria-label="Earlier character to reuse" value={sourceId} onChange={(event) => {
        setSourceId(event.target.value); resetPreview();
      }}><option value="">Choose earlier character</option>{sources.map((speaker) => <option key={speaker.id} value={speaker.id}>{speaker.display_name} · {speaker.revision_id?.slice(0, 8)}</option>)}</select></label>
      <label className="stemAttestation"><input type="checkbox" checked={copy} onChange={(event) => { setCopy(event.target.checked); resetPreview(); }} />Also copy the selected stock voice and pace</label>
      <p>Cloned voices, consent and scene/character briefs are never copied. Name-only reuse keeps the current voice selection; check its permissions separately.</p>
      <button className="smallButton" disabled={!targetId || !sourceId} onClick={() => action(async () => {
        setConfirmed(false); setPreview(await api.speakerReusePreview(targetId, sourceId, copy));
      })}>Preview character reuse</button>
      {preview && <section aria-label="Character reuse preview">
        <p>{preview.target.display_name} → {preview.source.display_name} · {preview.affected_line_ids.length} affected lines</p>
        {copy && <p>Stock voice: {String(preview.voice.provider)} / {String(preview.voice.voice_id)}. A separate current-speaker profile will be created.</p>}
        {preview.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
        <label className="stemAttestation"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I reviewed the identity; replace this name and optional stock voice, clear affected approvals and selected takes.</label>
        <button className="smallButton" disabled={!confirmed || unsaved} onClick={apply}>Apply reviewed character reuse</button>
      </section>}
      <button className="smallButton" disabled={!targetId} onClick={() => action(async () => setHistory(await api.speakerReuseHistory(targetId)))}>Load character reuse history</button>
    </fieldset>
    {unsaved && <p className="lineWarning">Save or discard current drafts before applying character reuse.</p>}
    {history.length > 0 && <section aria-label="Character reuse history">{history.map((operation) => <p key={operation.id}>Saved identity reuse · {new Date(operation.created_at).toLocaleString()} · source {operation.source_speaker_id.slice(0, 8)} · operation {operation.id.slice(0, 8)}</p>)}</section>}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </details>;
}
