"use client";

import type { AcousticPerformance, Artifact, JobRequest, ProjectDetail, TakePerformanceLine, TakePerformanceReport } from "@cinedub/contracts";
import { useRef, useState } from "react";
import { API_URL, api } from "@/lib/api";

type Props = {
  project: ProjectDetail;
  sourceId: string | null;
  disabled: boolean;
  unsaved: boolean;
  available: boolean;
  targetAlignmentAvailable: boolean;
  transcriptionInput: "original" | "dialogue_stem";
  onRun: (payload: JobRequest) => Promise<void>;
  onPlayRange: (start: number, end: number) => Promise<void>;
};

function SignalChart({ source, target, start, end, kind }: {
  source: AcousticPerformance; target: AcousticPerformance; start: number; end: number;
  kind: "pitch_hz" | "rms_dbfs";
}) {
  const title = kind === "pitch_hz" ? "Pitch estimate" : "RMS energy";
  const low = kind === "pitch_hz" ? 70 : -60, high = kind === "pitch_hz" ? 500 : 0;
  function path(performance: AcousticPerformance) {
    const step = Math.max(1, Math.ceil(performance.frames.length / 240));
    let drawing = false;
    return performance.frames.filter((_, index) => index % step === 0).map((frame) => {
      const value = frame[kind];
      if (value === null) { drawing = false; return ""; }
      const x = (frame.time_ms - start) / (end - start) * 600;
      const y = 100 - (Math.max(low, Math.min(high, value)) - low) / (high - low) * 100;
      const prefix = drawing ? "L" : "M"; drawing = true;
      return `${prefix}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
  }
  return <figure className="signalChart"><figcaption>{title} · {low}–{high} {kind === "pitch_hz" ? "Hz" : "dBFS"}</figcaption>
    <svg viewBox="0 0 600 104" role="img" aria-label={`${title}: source in cyan, take in green; same saved time window`}>
      <path d={path(source)} fill="none" stroke="var(--cyan)" strokeWidth="1.5" />
      <path d={path(target)} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
    </svg>
    <small>Source: cyan · Take: green · missing pitch is not drawn · {(start / 1000).toFixed(2)}–{(end / 1000).toFixed(2)}s</small>
  </figure>;
}

function TakeResult({ evidence, artifact, current, sourceMatches, onPlayRange }: {
  evidence: TakePerformanceLine; artifact?: Artifact; current: boolean; sourceMatches: boolean;
  onPlayRange: Props["onPlayRange"];
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const [error, setError] = useState<string | null>(null);
  const comparison = evidence.comparison;
  const stale = evidence.stale_reason || (!current ? "Saved dialogue, timing or voice changed; analyze a current take" : null);
  async function playWord(start: number) {
    if (!audio.current) return;
    try { audio.current.currentTime = (start - evidence.start_ms) / 1000; await audio.current.play(); }
    catch { setError("Use the take player's play control first, then choose a word."); }
  }
  return <article className="alignmentLine" aria-label={`Take analysis ${evidence.candidate_id}`}>
    <h3>{evidence.demo ? "DEMO TONE · " : evidence.evaluation_fixture ? "SYNTHETIC SPEECH FIXTURE · " : ""}{evidence.translated_text}</h3>
    <p>{evidence.source_text}</p>
    {stale && <p className="lineWarning">{stale}</p>}
    <button className="smallButton" disabled={!sourceMatches} onClick={() => onPlayRange(evidence.start_ms, evidence.end_ms)}>Listen to source range</button>
    {artifact && !artifact.access_blocked_reason && <audio ref={audio} controls preload="none" src={`${API_URL}${artifact.content_url}`} aria-label="Analyzed voice take" />}
    <div className="comparisonTable"><table><caption>Measured differences, not quality scores</caption><thead><tr><th>Signal</th><th>Source</th><th>Take</th></tr></thead>
      <tbody><tr><th>Median pitch</th><td>{evidence.source_performance.pitch_median_hz ?? "—"} Hz</td><td>{evidence.target_performance.pitch_median_hz ?? "—"} Hz</td></tr>
        <tr><th>RMS level</th><td>{evidence.source_performance.rms_dbfs ?? "Silent"}</td><td>{evidence.target_performance.rms_dbfs ?? "Silent"} dBFS</td></tr>
        <tr><th>Energy-active span</th><td>{comparison.source_active_span_ms} ms</td><td>{comparison.target_active_span_ms} ms</td></tr>
        <tr><th>Internal low-energy pauses</th><td>{comparison.source_internal_pause_ms} ms</td><td>{comparison.target_internal_pause_ms} ms</td></tr>
        <tr><th>Text pace</th><td>{evidence.source_performance.words_per_minute} words/min</td><td>{evidence.target_performance.words_per_minute} words/min</td></tr></tbody></table></div>
    <p>Fitting added approximately {comparison.fitted_padding_ms} ms of padding. Pitch shift: {comparison.pitch_shift_semitones ?? "not measurable"} semitones; a different voice may naturally have a different pitch.</p>
    <SignalChart source={evidence.source_performance} target={evidence.target_performance} start={evidence.start_ms} end={evidence.end_ms} kind="pitch_hz" />
    <SignalChart source={evidence.source_performance} target={evidence.target_performance} start={evidence.start_ms} end={evidence.end_ms} kind="rms_dbfs" />
    <p>Malayalam word suggestions: {evidence.target_alignment.status.replaceAll("_", " ")}</p>
    <div className="alignmentWords" role="group" aria-label="Malayalam word suggestions">{evidence.target_alignment.words.map((word, index) =>
      <button className="smallButton" disabled={!artifact || !!artifact.access_blocked_reason} key={`${index}-${word.text}`} onClick={() => playWord(word.start_ms)} title="Play from this estimated word; not calibrated confidence">
        {word.text}<small>{(word.start_ms / 1000).toFixed(2)}–{(word.end_ms / 1000).toFixed(2)}s</small></button>)}</div>
    {[...evidence.warnings, ...evidence.target_alignment.warnings].map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </article>;
}

export function PerformancePanel({ project, sourceId, disabled, unsaved, available,
  targetAlignmentAvailable, transcriptionInput, onRun, onPlayRange }: Props) {
  const [choice, setChoice] = useState("");
  const [words, setWords] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<TakePerformanceReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reports = project.artifacts.filter((item) => item.kind === "take_performance_report" && item.metadata_json.revision_id === project.active_revision_id);
  const candidates = project.artifacts.filter((item) => item.kind === "dialogue_candidate" && item.metadata_json.revision_id === project.active_revision_id && item.metadata_json.fit_status === "ready" && !item.access_blocked_reason);
  const sourceMatches = project.revisions.find((item) => item.id === project.active_revision_id)?.source_asset_id === sourceId;
  const hasSelection = project.segments.some((line) => line.selected_candidate_id);
  const reportStale = report?.stale_reason || (report?.stem_set_id && project.assets.find((item) => item.id === report.source_asset_id)?.active_stem_set_id !== report.stem_set_id ? "Reviewed dialogue stem changed; analyze again" : null);
  async function inspect(id: string) {
    try { setBusy(true); setError(null); setReport(await api.takeAnalysisReport(id)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load comparison"); }
    finally { setBusy(false); }
  }
  return <details className="dubPreview performancePanel" aria-label="Source versus voice performance">
    <summary>Source versus voice · {reports.length} saved comparisons</summary>
    <p>Compare source and fitted takes before choosing a voice. Signals help listening review; they are not emotion, identity or naturalness scores. Saved dialogue and takes are never changed.</p>
    <label className="fieldLabel">Take to analyze<select aria-label="Take to analyze" value={choice} disabled={disabled || busy} onChange={(event) => setChoice(event.target.value)}>
      <option value="">Selected takes</option>{candidates.map((candidate, index) => <option value={candidate.id} key={candidate.id}>Line {1 + project.segments.findIndex((line) => line.id === candidate.metadata_json.segment_id)} · take {candidates.length - index}{candidate.metadata_json.demo ? " · demo tone" : ""}</option>)}</select></label>
    <label className="performanceToggle"><input type="checkbox" checked={words} disabled={disabled || !targetAlignmentAvailable} onChange={(event) => setWords(event.target.checked)} />Include experimental Malayalam word suggestions</label>
    <p className="lineWarning">Analysis input: {transcriptionInput === "dialogue_stem" ? "reviewed dialogue stem" : "original source audio"}. Voice/gain/background differences affect the measurements. Word suggestions need listening and language review.</p>
    <button className="smallButton" disabled={disabled || busy || unsaved || !available || !sourceMatches || (!choice && !hasSelection)} onClick={() => onRun({
      stage: "analyze_takes", revision_id: project.active_revision_id!, source_asset_id: sourceId!,
      candidate_ids: choice ? [choice] : project.segments.flatMap((line) => line.selected_candidate_id ? [line.selected_candidate_id] : []),
      include_target_alignment: words, transcription_input: transcriptionInput,
    })}>Analyze take performance</button>
    {unsaved && <p className="lineWarning">Save drafts before analyzing takes.</p>}
    {!available && <p className="lineWarning">Install the optional local-alignment dependencies for measurements.</p>}
    {!targetAlignmentAvailable && <p className="lineWarning">Malayalam suggestions need the separately installed experimental model; measurements can run without it.</p>}
    {reports.map((artifact, index) => <div className="alignmentReportChoice" key={artifact.id}>
      {artifact.access_blocked_reason ? <p className="lineWarning">{artifact.access_blocked_reason}</p> : <><button className="smallButton" disabled={busy} onClick={() => inspect(artifact.id)}>Inspect comparison {reports.length - index}</button>
        <a className="smallButton" href={`${API_URL}${artifact.download_url}`}>Download comparison JSON</a></>}
    </div>)}
    {error && <p className="inlineError" role="alert">{error}</p>}
    {report && report.revision_id === project.active_revision_id && <section aria-label="Take performance results">
      {reportStale && <p className="lineWarning">{reportStale}</p>}
      {report.lines.map((evidence) => {
        const artifact = project.artifacts.find((item) => item.id === evidence.candidate_id);
        const line = project.segments.find((item) => item.id === evidence.segment_id);
        const speaker = project.speakers.find((item) => item.id === line?.speaker_id);
        const profile = project.voice_profiles.find((item) => item.id === evidence.voice.profile_id);
        const current = !!line && line.speaker_id === evidence.speaker_id && line.source_text === evidence.source_text && line.translated_text === evidence.translated_text
          && line.start_ms === evidence.start_ms && line.end_ms === evidence.end_ms
          && speaker?.voice_profile_id === profile?.id && profile?.version === evidence.voice.profile_version;
        if (artifact?.access_blocked_reason) return <p className="lineWarning" key={evidence.candidate_id}>{artifact.access_blocked_reason}</p>;
        return <TakeResult key={evidence.candidate_id} evidence={evidence} artifact={artifact} current={current} sourceMatches={sourceMatches} onPlayRange={onPlayRange} />;
      })}
    </section>}
  </details>;
}
