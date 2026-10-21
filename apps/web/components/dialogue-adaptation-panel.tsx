"use client";

import type { DialogueAdaptationLine, DialogueAdaptationReport, JobRequest, ProjectDetail, Segment } from "@cinedub/contracts";
import { useState } from "react";
import { API_URL, api } from "@/lib/api";

type Props = {
  project: ProjectDetail; available: boolean; disabled: boolean; unsaved: boolean;
  onRun: (payload: JobRequest) => Promise<void>; onSaved: () => Promise<void>;
  onPlayRange: (start: number, end: number) => Promise<void>; canPlay: boolean;
};

function currentContext(report: DialogueAdaptationReport, project: ProjectDetail) {
  return report.brief.version === project.dialogue_brief?.version
    && report.context_lines.length === project.segments.length
    && report.context_lines.every((saved) => {
      const line = project.segments.find((item) => item.id === saved.segment_id);
      return line && line.source_text === saved.source_text && line.start_ms === saved.start_ms
        && line.end_ms === saved.end_ms && line.speaker_id === saved.speaker_id
        && (project.speakers.find((speaker) => speaker.id === line.speaker_id)?.display_name ?? null) === saved.speaker_name
        && (line.translated_text === saved.translated_text || line.translated_text === report.applied_translations[line.id]);
    });
}

function Alternatives({ evidence, current, disabled, onApply, onPlayRange, canPlay }: {
  evidence: DialogueAdaptationLine; current?: Segment; disabled: boolean; canPlay: boolean;
  onApply: (kind: "faithful" | "concise", reviewed: boolean, replace: boolean, issues: boolean) => Promise<void>;
  onPlayRange: Props["onPlayRange"];
}) {
  const [reviewed, setReviewed] = useState(false);
  const [replace, setReplace] = useState(false);
  const [issues, setIssues] = useState(false);
  const replacing = !!current && (current.human_edited || current.status === "approved");
  return <article className="alignmentLine" aria-label={`Model alternatives for line ${current ? current.index + 1 : "historical"}`}>
    <h3>{evidence.speaker_name ?? "Unassigned speaker"} · {(evidence.slot_duration_ms / 1000).toFixed(2)}s saved window</h3>
    <p>English: {evidence.source_text}</p><p lang="ml">Previous draft: {evidence.translated_text || "none"}</p>
    {evidence.timing_feedback && <section aria-label="Measured synthesized timing feedback">
      <p>{evidence.timing_feedback.demo ? "DEMO TONES · " : evidence.timing_feedback.evaluation_fixture ? "SYNTHETIC EVALUATION · " : ""}
        Measured raw take: {(evidence.timing_feedback.raw_duration_ms / 1000).toFixed(3)}s for a {(evidence.timing_feedback.target_duration_ms / 1000).toFixed(3)}s slot.
        Raw/slot duration ratio {evidence.timing_feedback.required_speed_ratio.toFixed(3)}×; safe speed-up limit {evidence.timing_feedback.max_safe_speedup.toFixed(3)}×.
        {evidence.timing_feedback.safe_speedup_exceeded ? " The previous take exceeds its safe speed-up limit." : " The previous take does not exceed its safe speed-up limit."}</p>
      <p>This measurement was supplied to the model for the previous draft. Short takes are padded, not slowed to the raw/slot ratio. Synthesize the chosen new text and measure again; new timing fit is not verified.</p>
      <details><summary>Timing take provenance</summary><p>Candidate: {evidence.timing_feedback.candidate_id}</p>
        <p>Raw SHA256: {evidence.timing_feedback.raw_sha256}</p><p>{evidence.timing_feedback.raw_sample_count} PCM frames at {evidence.timing_feedback.raw_sample_rate} Hz</p></details>
    </section>}
    <button className="smallButton" disabled={!canPlay} onClick={() => onPlayRange(evidence.start_ms, evidence.end_ms)}>Listen to source window</button>
    <div className="adaptationOptions">{evidence.alternatives.map((option) => {
      const flagged = option.findings.length > 0 || option.warnings.length > 0;
      const selected = current?.translated_text === option.text;
      return <section className="adaptationOption" key={option.kind} aria-label={`${option.kind} alternative`}>
        <h4>{option.kind === "faithful" ? "Faithful draft" : "Concise draft"}</h4><p lang="ml">{option.text}</p>
        <p>{Array.from(option.text).length} Unicode characters; duration and naturalness are not verified.</p>
        {option.findings.map((finding, index) => <p className="lineWarning" key={`finding-${index}`}>{finding.message}</p>)}
        {option.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
        <button className="smallButton" disabled={disabled || !current || selected || !reviewed || (replacing && !replace) || (flagged && !issues) || !option.eligible_for_application}
          onClick={() => onApply(option.kind, reviewed, replace, issues)}>{selected ? `Current ${option.kind} draft` : `Use ${option.kind} draft`}</button>
      </section>;
    })}</div>
    <label className="performanceToggle"><input type="checkbox" checked={reviewed} disabled={disabled} onChange={(event) => setReviewed(event.target.checked)} />I checked the Malayalam draft I will apply against the English meaning</label>
    {replacing && <label className="performanceToggle"><input type="checkbox" checked={replace} disabled={disabled} onChange={(event) => setReplace(event.target.checked)} />Replace previously edited or approved text</label>}
    {evidence.alternatives.some((option) => option.findings.length || option.warnings.length) && <label className="performanceToggle"><input type="checkbox" checked={issues} disabled={disabled} onChange={(event) => setIssues(event.target.checked)} />I reviewed the terminology, number and script warnings</label>}
    <p>Applying changes text only, clears the old selected voice take and requires approval again. It does not change timing.</p>
    <details><summary>Model notes and provenance</summary><p>Unverified model note: {evidence.model_notes || "none"}</p>
      <p>{evidence.prompt_tokens} prompt tokens · {(evidence.latency_ms / 1000).toFixed(1)}s generation</p><p>Prompt SHA256: {evidence.prompt_sha256}</p></details>
  </article>;
}

export function DialogueAdaptationPanel({ project, available, disabled, unsaved, onRun, onSaved, onPlayRange, canPlay }: Props) {
  const [choice, setChoice] = useState("");
  const [timingCandidate, setTimingCandidate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<DialogueAdaptationReport | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const reports = project.artifacts.filter((item) => item.kind === "dialogue_adaptation_report" && item.metadata_json.revision_id === project.active_revision_id);
  const candidates = project.artifacts.filter((item) => choice && item.kind === "dialogue_candidate"
    && item.metadata_json.segment_id === choice && item.metadata_json.revision_id === project.active_revision_id && !item.access_blocked_reason);
  const stale = report?.stale_reason || (report && !currentContext(report, project) ? "Saved brief or dialogue context changed; generate alternatives again" : null);
  async function inspect(id: string) {
    try { setBusy(true); setError(null); setReport(await api.dialogueAdaptationReport(id)); setReportId(id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load dialogue alternatives"); }
    finally { setBusy(false); }
  }
  async function apply(line: DialogueAdaptationLine, kind: "faithful" | "concise", reviewed: boolean, replace: boolean, issues: boolean) {
    const saved = project.segments.find((item) => item.id === line.segment_id);
    if (!saved || !reportId) return;
    try {
      setBusy(true); setError(null);
      await api.applyDialogueAdaptation(reportId, { segment_id: saved.id, kind, expected_version: saved.version,
        language_reviewed: reviewed, replace_reviewed_text: replace, issues_reviewed: issues });
      await onSaved(); setReport(await api.dialogueAdaptationReport(reportId));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not apply dialogue draft"); }
    finally { setBusy(false); }
  }
  return <details className="dubPreview dialogueAdaptationPanel" aria-label="Model dialogue alternatives">
    <summary>Model dialogue alternatives · {reports.length} saved reports</summary>
    <p>Use the saved scene brief, character direction, preferred terms and surrounding dialogue to generate faithful and concise Malayalam drafts. Experimental local CPU model; generation never replaces your saved text.</p>
    <p className="lineWarning">These drafts need Malayalam language review. Shorter text does not prove timing fit, natural acting or emotion preservation.</p>
    <label className="fieldLabel">Lines to adapt<select aria-label="Lines to adapt" value={choice} disabled={disabled || busy} onChange={(event) => { setChoice(event.target.value); setTimingCandidate(""); }}>
      <option value="">All saved lines</option>{project.segments.map((line) => <option value={line.id} key={line.id}>Line {line.index + 1} · {line.source_text.slice(0, 60)}</option>)}</select></label>
    <label className="fieldLabel">Measured timing feedback<select aria-label="Measured timing feedback" value={timingCandidate} disabled={disabled || busy || !choice} onChange={(event) => setTimingCandidate(event.target.value)}>
      <option value="">No synthesized take feedback</option>{candidates.map((item) => <option value={item.id} key={item.id}>
        {item.metadata_json.demo ? "DEMO · " : ""}{String(item.metadata_json.fit_status)} · {(Number(item.metadata_json.raw_duration_ms) / 1000).toFixed(3)}s raw · {item.id.slice(0, 8)}
      </option>)}</select></label>
    <p>Optional: choose one saved line and a synthesized take. The server verifies raw duration, current dialogue, selected voice and consent before using it. Stale takes are refused; no take is selected automatically.</p>
    <button className="smallButton" disabled={disabled || busy || unsaved || !available || !project.segments.length} onClick={() => onRun({ stage: "adapt_dialogue", revision_id: project.active_revision_id!, ...(choice ? { segment_ids: [choice] } : {}), ...(choice && timingCandidate ? { candidate_ids: [timingCandidate] } : {}) })}>Generate dialogue alternatives</button>
    {!available && <p className="lineWarning">Install the optional local-dialogue model/runtime first. Plain translation and manual brief checks remain available independently.</p>}
    {unsaved && <p className="lineWarning">Save dialogue and brief drafts before generating or applying alternatives.</p>}
    {reports.map((artifact, index) => <div className="alignmentReportChoice" key={artifact.id}>
      <button className="smallButton" disabled={busy} onClick={() => inspect(artifact.id)}>Inspect alternatives {reports.length - index}</button>
      <a className="smallButton" href={`${API_URL}${artifact.download_url}`}>Download dialogue alternatives JSON</a></div>)}
    {error && <p className="inlineError" role="alert">{error}</p>}
    {report && <section aria-label="Model dialogue results"><p>{report.model} · {report.prompt_version} · brief version {report.brief.version}</p>
      <p>Native peak memory: {String(report.runtime.peak_rss_mib)} MiB · {String(report.runtime.threads)} CPU threads · no API charge</p>
      {stale && <p className="lineWarning">{stale}</p>}
      {report.lines.map((line) => {
        const current = project.segments.find((item) => item.id === line.segment_id);
        return <Alternatives key={`${line.segment_id}:${current?.version}`} evidence={line} current={current} disabled={disabled || busy || unsaved || !!stale}
          onApply={(kind, reviewed, replace, issues) => apply(line, kind, reviewed, replace, issues)} onPlayRange={onPlayRange} canPlay={canPlay} />;
      })}
      {report.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
    </section>}
  </details>;
}
