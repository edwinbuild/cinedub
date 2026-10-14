"use client";

import type { JobRequest, MixRender, MixSettings, ProjectDetail } from "@cinedub/contracts";
import { useState } from "react";
import { API_URL, api } from "@/lib/api";

function RenderReview({ mix, project, disabled, onSaved }: {
  mix: MixRender; project: ProjectDetail; disabled: boolean; onSaved: () => Promise<void>;
}) {
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [listened, setListened] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const artifacts = project.artifacts.filter((item) => Object.values(mix.artifacts_json).includes(item.id));
  const video = artifacts.find((item) => item.kind === "mix_video");
  const preview = video ?? artifacts.find((item) => item.kind === "mix_listening_copy");
  const acceptance = mix.reviews.at(-1);
  const bundle = acceptance?.bundle_artifact_id ? project.artifacts.find((item) => item.id === acceptance.bundle_artifact_id) : undefined;
  async function review(status: "approved" | "rejected") {
    try {
      setSaving(true); setError(null);
      await api.reviewMix(mix.id, { status, expected_version: mix.version, reviewed_by: reviewer,
        note, listening_confirmed: listened });
      setListened(false); await onSaved();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save mix review"); }
    finally { setSaving(false); }
  }
  const measured = mix.quality_json.audio_master as Record<string, unknown> | undefined;
  return <article className="mixCard" aria-label={`Mix render ${mix.id}`}>
    <header><strong>{preview?.metadata_json.demo ? "DEMO TONES · " : ""}{mix.status.replaceAll("_", " ")}</strong>
      <small>{new Date(mix.created_at).toLocaleString()} · review v{mix.version}</small></header>
    {mix.stale_reason && <p className="lineWarning">Historical render: {mix.stale_reason}</p>}
    <p>48 kHz stereo · {String(measured?.integrated_lufs)} LUFS · {String(measured?.true_peak_dbfs)} dBTP. Technical checks passed; {mix.status === "approved" ? "see saved listening acceptance below." : "listening acceptance is pending."}</p>
    {preview?.access_blocked_reason ? <p className="lineWarning">{preview.access_blocked_reason}</p>
      : preview && (video ? <video aria-label="Retained-background video preview" controls preload="metadata" src={`${API_URL}${preview.content_url}`} />
        : <audio aria-label="Retained-background audio preview" controls preload="metadata" src={`${API_URL}${preview.content_url}`} />)}
    <div className="mixDownloads">{artifacts.map((item) => item.access_blocked_reason ? <span key={item.id}>{item.filename}: {item.access_blocked_reason}</span>
      : <a key={item.id} href={`${API_URL}${item.download_url}`}>{item.kind === "mix_master" ? "Download 24-bit WAV master" : item.kind === "mix_manifest" ? "Download render manifest" : item.kind === "mix_subtitles" ? "Download matching SRT" : item.kind === "mix_video" ? "Download full-resolution review MP4" : "Download listening WAV"}</a>)}</div>
    <details><summary>Technical report and render settings</summary><pre>{JSON.stringify({ settings: mix.settings_json, quality: mix.quality_json }, null, 2)}</pre></details>
    <label className="fieldLabel">Mix reviewed by<input aria-label="Mix reviewer" value={reviewer} maxLength={120} disabled={disabled || saving} onChange={(event) => setReviewer(event.target.value)} /></label>
    <label className="fieldLabel">Mix review notes<input aria-label="Mix review notes" value={note} maxLength={1000} disabled={disabled || saving} onChange={(event) => setNote(event.target.value)} /></label>
    <label className="stemAttestation"><input type="checkbox" checked={listened} disabled={disabled || saving} onChange={(event) => setListened(event.target.checked)} />I reviewed dialogue, background leakage, effects, levels and timing against the scene.</label>
    <div className="stemActions"><button className="smallButton" disabled={disabled || saving || !reviewer.trim() || !listened || !!mix.stale_reason || !!preview?.access_blocked_reason}
      onClick={() => review("approved")}>Approve mix and export bundle</button>
      <button className="smallButton" disabled={disabled || saving || !reviewer.trim()} onClick={() => review("rejected")}>Reject mix</button></div>
    {bundle && (bundle.access_blocked_reason ? <p className="lineWarning">{bundle.access_blocked_reason}</p>
      : <a className="smallButton acceptedBundle" href={`${API_URL}${bundle.download_url}`}>{mix.stale_reason || mix.status !== "approved" ? "Download historical accepted bundle" : "Download accepted export bundle"}</a>)}
    {mix.status === "approved" && !bundle && <p>Acceptance saved. The worker will verify and package the export; check job errors if no bundle appears.</p>}
    {mix.reviews.length > 0 && <details><summary>Mix review history ({mix.reviews.length})</summary>{mix.reviews.map((item) => <p key={item.id}>v{item.version} · {item.status} · {item.reviewed_by} · {new Date(item.created_at).toLocaleString()}<br />{item.note || "No note recorded"}</p>)}</details>}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </article>;
}

export function MixPanel({ project, disabled, unsaved, onSaved, onRun }: {
  project: ProjectDetail; disabled: boolean; unsaved: boolean; onSaved: () => Promise<void>;
  onRun: (payload: JobRequest) => Promise<void>;
}) {
  const [settings, setSettings] = useState<MixSettings>({ profile: "stereo-review-v1", dialogue_gain_db: 0,
    music_gain_db: 0, effects_gain_db: 0, music_muted: false, effects_muted: false, target_lufs: -23,
    true_peak_dbfs: -2, allow_dynamic_normalization: false });
  const revision = project.revisions.find((item) => item.id === project.active_revision_id);
  const source = project.assets.find((item) => item.id === revision?.source_asset_id);
  const stems = project.stem_sets.find((item) => item.id === source?.active_stem_set_id && item.status === "approved");
  const ready = !!stems && project.segments.length > 0 && project.segments.every((line) => line.status === "approved" && !!line.selected_candidate_id);
  const controls = [ ["dialogue_gain_db", "Dialogue gain (dB)", -24, 12], ["music_gain_db", "Music gain (dB)", -60, 12],
    ["effects_gain_db", "Effects gain (dB)", -60, 12], ["target_lufs", "Target loudness (LUFS)", -30, -14],
    ["true_peak_dbfs", "Maximum true peak (dBTP)", -6, -2] ] as const;
  const valid = controls.every(([key, , min, max]) => { const value = settings[key]; return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max; });
  const renders = project.mixes.filter((item) => item.revision_id === project.active_revision_id);
  return <section className="mixPanel" aria-label="Retained-background mix and export"><details open={renders.length > 0 || undefined}><summary>Mix & export · reviewed stereo delivery</summary>
    <p>Selected dubbed takes + approved music/effects. Original dialogue is excluded. Estimated stems can still contain speech leakage: listen before accepting. This stereo SDR review profile is not theatrical, surround or HDR mastering.</p>
    <p>Active timeline source: {source?.filename ?? "No source timeline selected"}.</p>
    {!ready && <p className="lineWarning">Approve source stems, approve every translated line and select a timing-ready take for each line.</p>}
    <div className="mixControls">{controls.map(([key, label, min, max]) => <label key={key} className="fieldLabel">{label}
      <input type="number" aria-label={label} min={min} max={max} step={0.5} value={settings[key] ?? ""} disabled={disabled}
        onChange={(event) => setSettings({ ...settings, [key]: event.target.value === "" ? undefined : Number(event.target.value) })} /></label>)}</div>
    <div className="mixOptions">{([ ["music_muted", "Mute music"], ["effects_muted", "Mute effects"],
      ["allow_dynamic_normalization", "Allow dynamics processing if required to meet loudness/peak targets"] ] as const).map(([key, label]) =>
      <label key={key} className="stemAttestation"><input type="checkbox" checked={settings[key] ?? false} disabled={disabled} onChange={(event) => setSettings({ ...settings, [key]: event.target.checked })} />{label}</label>)}</div>
    <p>Default: -23 LUFS, -2 dBTP, 48 kHz stereo. Linear gain preserves dynamics when feasible; dynamics processing is off unless you enable it. The downloaded report records actual measurements and tolerances.</p>
    <button className="smallButton" disabled={disabled || unsaved || !ready || !valid} onClick={() => onRun({ stage: "render_mix", revision_id: project.active_revision_id,
      mix_settings: settings, force_new: renders.length > 0 })}>Render retained-background mix</button>
    {unsaved && <p className="lineWarning">Save dialogue drafts before rendering.</p>}
    {renders.map((mix) => <RenderReview key={mix.id} mix={mix} project={project} disabled={disabled} onSaved={onSaved} />)}
  </details></section>;
}
