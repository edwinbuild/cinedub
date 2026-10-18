"use client";

import type { ProjectDetail, StemSet } from "@cinedub/contracts";
import { useState } from "react";
import { DemoBadge } from "@/components/demo-badge";
import { API_URL, api } from "@/lib/api";

function StemReviewCard({ stems, project, disabled, onSaved }: {
  stems: StemSet; project: ProjectDetail; disabled: boolean; onSaved: () => Promise<void>;
}) {
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [listened, setListened] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const source = project.assets.find((asset) => asset.id === stems.source_asset_id);
  const active = source?.active_stem_set_id === stems.id;
  async function review(status: "approved" | "rejected") {
    try {
      setSaving(true); setError(null);
      await api.reviewStems(stems.id, { status, expected_version: stems.version,
        expected_active_stem_set_id: source?.active_stem_set_id ?? null, reviewed_by: reviewer, note });
      setListened(false); await onSaved();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save stem review"); }
    finally { setSaving(false); }
  }
  const previews = project.artifacts.filter((artifact) => artifact.kind === "stem_preview"
    && artifact.metadata_json.stem_set_id === stems.id);
  return <article className="stemCard" aria-label={`Stem set ${stems.id}`}>
    <header><strong>{stems.provider === "fake" && <DemoBadge label="DEMO STEMS" title="No separation was performed: dialogue is the original mix and music/effects are synthetic tones" />}{active ? "Approved · active source stems" : stems.status.replaceAll("_", " ")}</strong>
      <small>{new Date(stems.created_at).toLocaleString()} · review v{stems.version}</small></header>
    <p className="lineWarning">Estimated dialogue, music and effects. Listen for speech leaking into background, missing effects and stereo changes. These players audition independently of the scene timeline.</p>
    <div className="stemPlayers">{previews.map((artifact) => <div key={artifact.id}>
      <strong>{String(artifact.metadata_json.stem)}</strong>
      <audio aria-label={`${String(artifact.metadata_json.stem)} stem preview`} controls preload="metadata" src={`${API_URL}${artifact.content_url}`} />
      <a href={`${API_URL}${artifact.download_url}`}>Download listening copy</a>
    </div>)}</div>
    <details><summary>Model and measurement provenance</summary><p>{stems.model}</p>
      <p>{String(stems.metadata_json.device)} · {String(stems.metadata_json.latency_ms)} ms · {String(stems.metadata_json.peak_rss_mib)} MiB peak process memory</p>
      <p>Reconstruction SNR: {String(stems.metadata_json.reconstruction_snr_db)} dB. This is not a score for dialogue isolation.</p></details>
    {stems.reviews.length > 0 && <details><summary>Saved review history ({stems.reviews.length})</summary>
      {stems.reviews.map((review) => <p key={review.id}>v{review.version} · {review.status} · {review.reviewed_by} · {new Date(review.created_at).toLocaleString()}<br />{review.note || "No note recorded"}</p>)}</details>}
    <label className="fieldLabel">Reviewed by<input aria-label="Stem reviewer" value={reviewer} maxLength={120} disabled={disabled || saving} onChange={(event) => setReviewer(event.target.value)} /></label>
    <label className="fieldLabel">Review notes<input aria-label="Stem review notes" value={note} maxLength={1000} disabled={disabled || saving} onChange={(event) => setNote(event.target.value)} /></label>
    <label className="stemAttestation"><input type="checkbox" checked={listened} disabled={disabled || saving} onChange={(event) => setListened(event.target.checked)} />I listened to all three stems and checked leakage, effects and stereo.</label>
    <div className="stemActions"><button className="smallButton" disabled={disabled || saving || !reviewer.trim() || !listened} onClick={() => review("approved")}>Approve and use stems</button>
      <button className="smallButton" disabled={disabled || saving || !reviewer.trim()} onClick={() => review("rejected")}>Reject stems</button></div>
    {error && <p role="alert" className="inlineError">{error}</p>}
  </article>;
}

export function StemPanel({ project, sourceId, disabled, onSaved }: {
  project: ProjectDetail; sourceId: string | null; disabled: boolean; onSaved: () => Promise<void>;
}) {
  const sets = project.stem_sets.filter((stems) => stems.source_asset_id === sourceId);
  if (!sets.length) return null;
  return <section className="stemPanel" aria-label="Separated audio review"><h2>Review separated audio</h2>
    <p>Original media is unchanged. New runs do not replace an approved choice. Approval enables dialogue-stem transcription and music/effects mixing for this source.</p>
    {sets.map((stems) => <StemReviewCard key={stems.id} stems={stems} project={project} disabled={disabled} onSaved={onSaved} />)}
  </section>;
}
