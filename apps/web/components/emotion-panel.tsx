"use client";

import type { JobRequest, ProjectDetail, SpeechEmotionLine, SpeechEmotionReport, SpeechEmotionReview } from "@cinedub/contracts";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, api } from "@/lib/api";

type Props = {
  project: ProjectDetail; sourceId: string | null; available: boolean; disabled: boolean; unsaved: boolean;
  transcriptionInput: "original" | "dialogue_stem"; canPlay: boolean;
  onRun: (payload: JobRequest) => Promise<void>;
  onPlayRange: (start: number, end: number) => Promise<void>;
  onDirty: (id: string, dirty: boolean) => void;
};

function EmotionLine({ line, draftId, disabled, canPlay, onPlayRange, onReview, onDirty }: {
  line: SpeechEmotionLine; disabled: boolean; canPlay: boolean;
  draftId: string; onDirty: Props["onDirty"];
  onPlayRange: Props["onPlayRange"]; onReview: (payload: SpeechEmotionReview) => Promise<boolean>;
}) {
  const [listened, setListened] = useState(false);
  const [author, setAuthor] = useState("");
  const [label, setLabel] = useState<NonNullable<SpeechEmotionReview["label"]>>("neutral");
  const [direction, setDirection] = useState("");
  const latest = line.review_history.at(-1);
  const [baseVersion, setBaseVersion] = useState(latest?.version ?? 0);
  const dirty = !!(listened || author || direction || label !== "neutral");
  const conflict = dirty && baseVersion !== (latest?.version ?? 0);
  useEffect(() => { onDirty(draftId, dirty); }, [draftId, dirty, onDirty]);
  useEffect(() => () => onDirty(draftId, false), [draftId, onDirty]);
  function startEdit() { if (!dirty) setBaseVersion(latest?.version ?? 0); }
  function reset() { setAuthor(""); setLabel("neutral"); setDirection(""); setListened(false); }
  async function review(status: SpeechEmotionReview["status"]) {
    if (conflict) return;
    const saved = await onReview({ segment_id: line.segment_id, expected_review_version: baseVersion,
      status, label: status === "corrected" ? label : null, direction, reviewed_by: author,
      listening_confirmed: listened });
    if (saved) reset();
  }
  return <article className="alignmentLine" aria-label={`Speech emotion window ${line.segment_id}`}>
    <h3>{(line.start_ms / 1000).toFixed(2)}–{(line.end_ms / 1000).toFixed(2)}s · {line.status.replaceAll("_", " ")}</h3>
    <p>Saved transcript (not a model input): {line.source_text}</p>
    <button className="smallButton" disabled={!canPlay} onClick={() => onPlayRange(line.start_ms, line.end_ms)}>Listen to original source window</button>
    <p>Model suggestion: {line.suggested_label ?? "none"}. Speech detector: {line.speech_ms} ms.</p>
    {line.scores.length > 0 && <div className="comparisonTable"><table><caption>Normalized model scores, not confidence or acting-quality scores</caption>
      <thead><tr><th>Training label</th><th>Score</th></tr></thead><tbody>{line.scores.map((score) => <tr key={score.label}><th>{score.label}</th><td>{score.score.toFixed(3)}</td></tr>)}</tbody></table></div>}
    {line.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
    {line.stale_reason && <p className="lineWarning">{line.stale_reason}</p>}
    <fieldset disabled={disabled || !!line.stale_reason}><legend>Human performance review</legend>
      <label className="fieldLabel">Emotion reviewer<input aria-label="Emotion reviewer" value={author} maxLength={120} onChange={(event) => { startEdit(); setAuthor(event.target.value); }} /></label>
      <label className="fieldLabel">Human emotion label<select aria-label="Human emotion label" value={label} onChange={(event) => { startEdit(); setLabel(event.target.value as typeof label); }}>
        {["neutral", "happy", "angry", "sad", "fearful", "surprised", "disgusted", "other"].map((value) => <option key={value}>{value}</option>)}</select></label>
      <label className="fieldLabel">Performance direction<textarea aria-label="Performance direction" value={direction} maxLength={1000} onChange={(event) => { startEdit(); setDirection(event.target.value); }} /></label>
      <label className="performanceToggle"><input type="checkbox" checked={listened} onChange={(event) => { startEdit(); setListened(event.target.checked); }} />I listened to the source window before reviewing its performance</label>
      <button className="smallButton" disabled={conflict || !listened || !author.trim() || !line.suggested_label} onClick={() => review("accepted")}>Accept model hint</button>
      <button className="smallButton" disabled={conflict || !listened || !author.trim()} onClick={() => review("corrected")}>Save human correction</button>
      <button className="smallButton" disabled={conflict || !listened || !author.trim()} onClick={() => review("rejected")}>Reject model hint</button>
    </fieldset>
    {dirty && <><p className="lineWarning" role="status">Unsaved emotion review. Fields stay in this open page only; no performance decision has been saved.</p>
      <button className="smallButton" disabled={disabled} onClick={() => {
        if (window.confirm("Discard this unsaved emotion review? Saved review history will not change.")) reset();
      }}>Discard emotion review draft</button></>}
    {conflict && <p className="lineWarning" role="alert">A newer review was saved. Your draft is preserved; copy it before discarding and starting a fresh review.</p>}
    <p>Review history: {line.review_history.length} saved reviews. No dialogue, voice, timing or approval is changed.</p>
    {line.review_history.map((review) => <p key={review.id}>Version {review.version}: {review.status} · {review.label ?? "no label"} · {review.reviewed_by}{review.direction && ` · ${review.direction}`}</p>)}
  </article>;
}

export function EmotionPanel({ project, sourceId, available, disabled, unsaved, transcriptionInput, canPlay, onRun, onPlayRange, onDirty }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<SpeechEmotionReport | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const drafts = useRef(new Set<string>());
  const reportDirty = useCallback((id: string, dirty: boolean) => {
    if (dirty) drafts.current.add(id); else drafts.current.delete(id);
    onDirty(id, dirty);
  }, [onDirty]);
  const reports = project.artifacts.filter((item) => item.kind === "speech_emotion_report" && item.metadata_json.revision_id === project.active_revision_id);
  const sourceMatches = project.revisions.find((item) => item.id === project.active_revision_id)?.source_asset_id === sourceId;
  async function inspect(id: string) {
    if (id !== reportId && drafts.current.size && !window.confirm("Discard unsaved emotion reviews and inspect a different report? Saved reviews will not change.")) return;
    try { setBusy(true); setError(null); setReport(await api.speechEmotionReport(id)); setReportId(id); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load emotion evidence"); }
    finally { setBusy(false); }
  }
  async function review(payload: SpeechEmotionReview) {
    if (!reportId) return false;
    try { setBusy(true); setError(null); await api.reviewSpeechEmotion(reportId, payload); setReport(await api.speechEmotionReport(reportId)); return true; }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save performance review"); return false; }
    finally { setBusy(false); }
  }
  return <details className="dubPreview emotionPanel" aria-label="Speech-emotion hints">
    <summary>Speech-emotion hints · {reports.length} saved reports</summary>
    <p>Optional English audio-only model: neutral, happy, angry and sad. It does not read text, infer an actor’s mental state, or prove emotion preservation in Malayalam.</p>
    <p className="lineWarning">Experimental, uncalibrated scores. Silence, overlapping speech and unsupported window lengths are skipped. Film and language-expert quality evaluation is still required.</p>
    <p>Analysis input: {transcriptionInput === "dialogue_stem" ? "reviewed dialogue stem" : "original source audio"}. The listen button plays the original source for comparison.</p>
    <button className="smallButton" disabled={disabled || busy || unsaved || !available || !sourceMatches || !project.segments.length} onClick={() => onRun({
      stage: "analyze_emotion", revision_id: project.active_revision_id!, source_asset_id: sourceId!, transcription_input: transcriptionInput,
    })}>Analyze source speech emotion</button>
    {!available && <p className="lineWarning">Install the optional local-emotion dependencies and models first. Other workflows do not require them.</p>}
    {unsaved && <p className="lineWarning">Save drafts before analysis or review.</p>}
    {reports.map((artifact, index) => <div className="alignmentReportChoice" key={artifact.id}>
      <button className="smallButton" disabled={busy} onClick={() => inspect(artifact.id)}>Inspect emotion report {reports.length - index}</button>
      <a className="smallButton" href={`${API_URL}${artifact.download_url}`}>Download immutable emotion evidence</a></div>)}
    {error && <p className="inlineError" role="alert">{error}</p>}
    {report && <section aria-label="Speech-emotion results"><p>{report.model}</p>
      <p>Native peak memory: {String(report.metadata.peak_rss_mib)} MiB · no API charge</p>
      <p>Saved analysis input: {report.stem_set_id ? "reviewed dialogue stem" : "original source audio"}</p>
      {report.stale_reason && <p className="lineWarning">{report.stale_reason}</p>}
      {report.lines.map((line) => {
        const current = project.segments.find((item) => item.id === line.segment_id);
        const materialChanged = !current || current.start_ms !== line.start_ms || current.end_ms !== line.end_ms || current.speaker_id !== line.speaker_id;
        return <EmotionLine key={`${reportId}:${line.segment_id}`} draftId={`emotion-review:${reportId}:${line.segment_id}`} line={line}
          disabled={disabled || busy || unsaved || !!report.stale_reason || materialChanged} canPlay={canPlay && sourceMatches}
          onPlayRange={onPlayRange} onReview={review} onDirty={reportDirty} />;
      })}
      {report.warnings.map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
    </section>}
  </details>;
}
