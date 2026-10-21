"use client";

import type { AlignmentReport, JobRequest, ProjectDetail } from "@cinedub/contracts";
import { useState } from "react";
import { DemoBadge } from "@/components/demo-badge";
import { API_URL, api } from "@/lib/api";

type Props = {
  project: ProjectDetail;
  disabled: boolean;
  unsaved: boolean;
  available: boolean;
  sourceId: string | null;
  transcriptionInput: "original" | "dialogue_stem";
  onRun: (request: JobRequest) => Promise<void>;
  onSaved: () => Promise<void>;
  onPlayRange: (start: number, end: number) => Promise<void>;
};

export function AlignmentPanel({ project, disabled, unsaved, available, sourceId,
  transcriptionInput, onRun, onSaved, onPlayRange }: Props) {
  const [report, setReport] = useState<AlignmentReport | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const artifacts = project.artifacts.filter((item) => item.kind === "alignment_report"
    && item.metadata_json.revision_id === project.active_revision_id);
  const revision = project.revisions.find((item) => item.id === project.active_revision_id);
  const sourceMatches = revision?.source_asset_id === sourceId;
  const locked = disabled || unsaved || busy || !sourceMatches;

  async function openReport(id: string) {
    try {
      setBusy(true); setError(null);
      const value = await api.alignmentReport(id);
      setReport(value); setReportId(id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load alignment"); }
    finally { setBusy(false); }
  }
  async function apply(segmentId: string) {
    if (!reportId) return;
    const line = project.segments.find((item) => item.id === segmentId);
    if (!line || !window.confirm(
      "Have you listened to the suggested timing? Applying it replaces saved line timing, clears the selected voice take, and requires dialogue approval again. Previously edited timing will also be replaced."
    )) return;
    try {
      setBusy(true); setError(null);
      await api.applyAlignment(reportId, {
        segment_id: segmentId, expected_version: line.version, replace_reviewed_timing: true,
        listening_confirmed: true,
      });
      await onSaved();
      setReport(await api.alignmentReport(reportId));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not apply timing"); }
    finally { setBusy(false); }
  }

  return <details className="dubPreview alignmentPanel" aria-label="Source timing and performance">
    <summary>Source timing & performance · {artifacts.length} saved reports</summary>
    <p>English source-word alignment and measured pitch, energy and pauses. These are not emotion labels or Malayalam voice alignment.</p>
    <p className="lineWarning">Uses the selected transcription audio ({transcriptionInput === "dialogue_stem" ? "reviewed dialogue stem" : "original audio"}). Noise, music and overlapping voices can distort measurements. Saved timings never change automatically.</p>
    <button className="smallButton" disabled={locked || !available || !project.segments.length}
      onClick={() => onRun({ stage: "align", revision_id: project.active_revision_id!,
        source_asset_id: sourceId!, transcription_input: transcriptionInput, force_new: artifacts.length > 0 })}>
      Align source words</button>
    {unsaved && <p className="lineWarning">Save dialogue drafts before alignment or timing application.</p>}
    {!available && <p className="lineWarning">Install the optional local alignment model to enable analysis.</p>}
    {error && <p className="inlineError" role="alert">{error}</p>}
    {artifacts.map((item, index) => <div className="alignmentReportChoice" key={item.id}>
      <button className="smallButton" disabled={busy} onClick={() => openReport(item.id)}>
        Inspect alignment report {artifacts.length - index}</button>
      <a className="smallButton" href={`${API_URL}${item.download_url}`}>Download evidence JSON</a>
    </div>)}
    {report && report.revision_id === project.active_revision_id && <section aria-label="Alignment results">
      {report.provider === "fake" && <p><DemoBadge /> Placeholder word slots spread evenly across each line. No forced alignment or acoustic measurement ran.</p>}
      <p>Saved analysis input: {report.stem_set_id ? "reviewed dialogue stem" : "original source audio"}.</p>
      {report.stale_reason && <p className="lineWarning">{report.stale_reason}</p>}
      <p className="lineWarning">Acoustic scores are not calibrated confidence. Listen before accepting any suggestion.</p>
      {report.lines.map((evidence, index) => {
        const current = project.segments.find((item) => item.id === evidence.segment_id);
        const stale = evidence.stale_reason || (current?.version !== evidence.segment_version ? "Saved line changed; align again" : null);
        const first = evidence.words.at(0), last = evidence.words.at(-1);
        const performance = evidence.performance;
        return <article className="alignmentLine" key={evidence.segment_id} aria-label={`Alignment line ${index + 1}`}>
          <h3>{evidence.source_text}</h3>
          <p>{evidence.status.replaceAll("_", " ")} · {evidence.words.length} words</p>
          {stale && <p className="lineWarning">{stale}</p>}
          {evidence.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
          <dl className="alignmentMetrics">
            <div><dt>RMS level</dt><dd>{performance.rms_dbfs === null ? "Silent" : `${performance.rms_dbfs} dBFS`}</dd></div>
            <div><dt>Median pitch</dt><dd>{performance.pitch_median_hz === null ? "Not measurable" : `${performance.pitch_median_hz} Hz`}</dd></div>
            <div><dt>Text pace</dt><dd>{performance.words_per_minute} words/min</dd></div>
            <div><dt>Low-energy pauses</dt><dd>{performance.pauses.length} · not speech detection</dd></div>
          </dl>
          {!!evidence.words.length && <div className="alignmentWords" role="group" aria-label="Aligned words">
            {evidence.words.map((word, position) => <button className="smallButton" key={`${position}-${word.text}`}
              disabled={!sourceMatches} onClick={() => onPlayRange(word.start_ms, word.end_ms)}
              title={`Acoustic score ${word.acoustic_score}; not calibrated confidence`}>
              {word.text} <small>{(word.start_ms / 1000).toFixed(2)}–{(word.end_ms / 1000).toFixed(2)}s</small>
            </button>)}
          </div>}
          {first && last && <button className="smallButton" disabled={locked || !!stale || !!report.stale_reason || evidence.status !== "aligned"}
            onClick={() => apply(evidence.segment_id)}>Apply suggested timing ({(first.start_ms / 1000).toFixed(2)}–{(last.end_ms / 1000).toFixed(2)}s)</button>}
        </article>;
      })}
    </section>}
  </details>;
}
