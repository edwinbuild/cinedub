"use client";

import type { CharacterDirection, DialogueBriefContent, DialogueReviewReport, JobRequest, ProjectDetail } from "@cinedub/contracts";
import { useEffect, useState } from "react";
import { API_URL, api } from "@/lib/api";

type Props = {
  project: ProjectDetail;
  disabled: boolean;
  unsaved: boolean;
  onRun: (payload: JobRequest) => Promise<void>;
  onSaved: () => Promise<void>;
  onDirty: (id: string, dirty: boolean) => void;
  onPlayRange: (start: number, end: number) => Promise<void>;
  canPlay: boolean;
};
const empty: DialogueBriefContent = { scene_summary: "", adaptation_notes: "", glossary: [], characters: [] };

function reviewIsCurrent(report: DialogueReviewReport, project: ProjectDetail) {
  return report.brief.version === project.dialogue_brief?.version
    && report.context_lines.length === project.segments.length
    && report.context_lines.every((saved) => {
      const line = project.segments.find((item) => item.id === saved.segment_id);
      return line && line.source_text === saved.source_text && line.translated_text === saved.translated_text
        && line.start_ms === saved.start_ms && line.end_ms === saved.end_ms && line.speaker_id === saved.speaker_id
        && (project.speakers.find((speaker) => speaker.id === line.speaker_id)?.display_name ?? null) === saved.speaker_name;
    });
}

export function DialogueBriefPanel({ project, disabled, unsaved, onRun, onSaved, onDirty, onPlayRange, canPlay }: Props) {
  const [content, setContent] = useState<DialogueBriefContent>(project.dialogue_brief?.content ?? empty);
  const [baseline, setBaseline] = useState(project.dialogue_brief?.content ?? empty);
  const [version, setVersion] = useState(project.dialogue_brief?.version ?? 0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<DialogueReviewReport | null>(null);
  const dirtyKey = `brief:${project.active_revision_id}`;
  const dirty = JSON.stringify(content) !== JSON.stringify(baseline);
  const conflict = version !== project.dialogue_brief?.version;
  const reports = project.artifacts.filter((item) => item.kind === "dialogue_review_report" && item.metadata_json.revision_id === project.active_revision_id);
  useEffect(() => { onDirty(dirtyKey, dirty); }, [dirtyKey, dirty, onDirty]);
  useEffect(() => () => onDirty(dirtyKey, false), [dirtyKey, onDirty]);

  function changeDirection(speakerId: string, changes: Partial<CharacterDirection>) {
    const previous = content.characters.find((item) => item.speaker_id === speakerId)
      ?? { speaker_id: speakerId, intent: "", delivery_notes: "" };
    const next = { ...previous, ...changes };
    setContent({ ...content, characters: [
      ...content.characters.filter((item) => item.speaker_id !== speakerId),
      ...(next.intent || next.delivery_notes ? [next] : []),
    ] });
  }
  async function save() {
    try {
      setBusy(true); setError(null);
      const saved = await api.saveDialogueBrief(project.id, project.active_revision_id!, { expected_version: version, content });
      setContent(saved.content); setBaseline(saved.content); setVersion(saved.version);
      await onSaved();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save dialogue brief"); }
    finally { setBusy(false); }
  }
  async function inspect(id: string) {
    try { setBusy(true); setError(null); setReport(await api.dialogueReviewReport(id)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load editorial checks"); }
    finally { setBusy(false); }
  }
  function loadLatest() {
    if (dirty && !window.confirm("Discard unsaved brief changes and load the latest saved brief?")) return;
    setContent(project.dialogue_brief?.content ?? empty); setBaseline(project.dialogue_brief?.content ?? empty);
    setVersion(project.dialogue_brief?.version ?? 0); setError(null);
  }
  return <details className="dubPreview dialogueBriefPanel" aria-label="Dialogue brief and editorial checks">
    <summary>Dialogue brief & editorial checks · version {version}{dirty ? " · unsaved" : ""}</summary>
    <p>Keep scene context, character intent and preferred names beside the dialogue. Current translation models do not receive this brief. Checks below are local editorial aids, not AI adaptation or Malayalam quality scores.</p>
    <form aria-label="Dialogue brief" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <fieldset disabled={disabled || busy}><legend>Editorial direction</legend>
        <label className="fieldLabel">Scene summary<textarea aria-label="Scene summary" rows={3} maxLength={4000} value={content.scene_summary} onChange={(event) => setContent({ ...content, scene_summary: event.target.value })} /></label>
        <label className="fieldLabel">Adaptation notes<textarea aria-label="Adaptation notes" rows={3} maxLength={4000} value={content.adaptation_notes} onChange={(event) => setContent({ ...content, adaptation_notes: event.target.value })} /></label>
        <p>Human direction only: describe relationships, subtext and delivery. This does not infer emotion from speech.</p>
        {project.speakers.map((speaker) => {
          const direction = content.characters.find((item) => item.speaker_id === speaker.id);
          return <div className="briefCharacter" key={speaker.id}><h3>{speaker.display_name}</h3>
            <label className="fieldLabel">Character intent<textarea aria-label={`Character intent for ${speaker.display_name}`} rows={2} maxLength={1000} value={direction?.intent ?? ""} onChange={(event) => changeDirection(speaker.id, { intent: event.target.value })} /></label>
            <label className="fieldLabel">Delivery notes<textarea aria-label={`Delivery notes for ${speaker.display_name}`} rows={2} maxLength={1000} value={direction?.delivery_notes ?? ""} onChange={(event) => changeDirection(speaker.id, { delivery_notes: event.target.value })} /></label>
          </div>;
        })}
        <h3>Names & glossary</h3><p>Use preferred Malayalam forms. Checks flag missing literal text; nothing is automatically replaced, because grammar and inflection need review.</p>
        {content.glossary.map((term, index) => <div className="briefTerm" key={index}>
          <label className="fieldLabel">Source term {index + 1}<input required maxLength={120} aria-label={`Source term ${index + 1}`} value={term.source} onChange={(event) => setContent({ ...content, glossary: content.glossary.map((item, i) => i === index ? { ...item, source: event.target.value } : item) })} /></label>
          <label className="fieldLabel">Preferred Malayalam {index + 1}<input required maxLength={120} aria-label={`Preferred Malayalam ${index + 1}`} value={term.preferred_target} onChange={(event) => setContent({ ...content, glossary: content.glossary.map((item, i) => i === index ? { ...item, preferred_target: event.target.value } : item) })} /></label>
          <label className="fieldLabel">Term note {index + 1}<input maxLength={500} aria-label={`Term note ${index + 1}`} value={term.note} onChange={(event) => setContent({ ...content, glossary: content.glossary.map((item, i) => i === index ? { ...item, note: event.target.value } : item) })} /></label>
          <button type="button" className="smallButton" aria-label={`Remove term ${index + 1}`} onClick={() => setContent({ ...content, glossary: content.glossary.filter((_, i) => i !== index) })}>Remove term</button>
        </div>)}
        <div className="briefActions"><button type="button" className="smallButton" disabled={content.glossary.length >= 80} onClick={() => setContent({ ...content, glossary: [...content.glossary, { source: "", preferred_target: "", note: "" }] })}>Add glossary term</button>
          <button type="submit" className="smallButton" disabled={!dirty || conflict}>Save dialogue brief</button>
          <button type="button" className="smallButton" onClick={loadLatest} disabled={!dirty && !conflict}>Load latest saved brief</button></div>
      </fieldset>
    </form>
    {conflict && <p className="lineWarning">Another editor saved a newer brief. Your draft is preserved; load the latest version before saving.</p>}
    {unsaved && <p className="lineWarning">Save dialogue and brief drafts before running editorial checks.</p>}
    <button className="smallButton" disabled={disabled || busy || unsaved || dirty || conflict || !project.segments.length} onClick={() => onRun({ stage: "review_translation", revision_id: project.active_revision_id! })}>Check saved dialogue</button>
    {reports.map((artifact, index) => <div className="alignmentReportChoice" key={artifact.id}>
      <button className="smallButton" disabled={busy} onClick={() => inspect(artifact.id)}>Inspect editorial checks {reports.length - index}</button>
      <a className="smallButton" href={`${API_URL}${artifact.download_url}`}>Download editorial review JSON</a>
    </div>)}
    {error && <p className="inlineError" role="alert">{error}</p>}
    {report && <section aria-label="Editorial review results">
      {(report.stale_reason || !reviewIsCurrent(report, project)) && <p className="lineWarning">{report.stale_reason ?? "Saved brief or dialogue context changed; review again"}</p>}
      <p>Saved brief version {report.brief.version} · scene: {report.brief.content.scene_summary || "not specified"}</p>
      <p>Adaptation direction: {report.brief.content.adaptation_notes || "not specified"}</p>
      {report.lines.map((line) => <article className="alignmentLine" key={line.segment_id} aria-label={`Editorial checks for line ${1 + project.segments.findIndex((item) => item.id === line.segment_id)}`}>
        <h3>{line.speaker_name ?? "Unassigned speaker"} · {(line.slot_duration_ms / 1000).toFixed(2)}s saved window</h3>
        <p>{line.source_text}</p><p lang="ml">{line.translated_text || "No saved Malayalam translation"}</p>
        <p>{line.target_character_count} Unicode characters; spoken duration is not estimated. Synthesize and listen to check timing.</p>
        {line.character_direction && <p>Intent: {line.character_direction.intent || "not specified"} · Delivery: {line.character_direction.delivery_notes || "not specified"}</p>}
        <details><summary>Surrounding dialogue & preferred terms</summary>
          <p>Before: {line.previous_line?.source_text ?? "Start of scene"}</p><p>After: {line.next_line?.source_text ?? "End of scene"}</p>
          {line.matched_glossary.map((term) => <p key={term.source}>{term.source} → {term.preferred_target}{term.note ? ` · ${term.note}` : ""}</p>)}</details>
        {line.findings.length ? line.findings.map((finding, index) => <p className="lineWarning" key={index}>{finding.message}</p>) : <p>No issues found by these limited checks. Meaning and naturalness still need human review.</p>}
        <button className="smallButton" disabled={!canPlay} onClick={() => onPlayRange(line.start_ms, line.end_ms)}>Listen to dialogue window</button>
      </article>)}
      {report.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
    </section>}
  </details>;
}
