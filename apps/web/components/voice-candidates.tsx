"use client";

import type { Artifact, Segment } from "@cinedub/contracts";
import { useState } from "react";
import { API_URL, api } from "@/lib/api";

export function VoiceCandidates({ segment, artifacts, disabled, onSaved }: {
  segment: Segment; artifacts: Artifact[]; disabled: boolean; onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const candidates = artifacts.filter((item) => item.kind === "dialogue_candidate" && item.metadata_json.segment_id === segment.id);
  if (!candidates.length) return null;
  async function select(id: string) {
    try { setBusy(true); setError(null); await api.selectCandidate(segment, id); await onSaved(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Candidate selection failed"); }
    finally { setBusy(false); }
  }
  return <div className="candidateList" aria-label={`Audio candidates for line ${segment.index + 1}`}>
    {candidates.map((candidate, index) => <div key={candidate.id} className="candidateItem">
      <strong>{candidate.metadata_json.demo ? "Demo tone" : candidate.metadata_json.evaluation_fixture ? "Synthetic speech fixture" : "Voice candidate"} {candidates.length-index}</strong>
      {!candidate.access_blocked_reason && <audio controls preload="none" src={`${API_URL}${candidate.content_url}`} aria-label={`Candidate ${candidates.length-index} for line ${segment.index + 1}`} />}
      {candidate.access_blocked_reason && <p className="lineWarning">{candidate.access_blocked_reason}</p>}
      <small>{candidate.metadata_json.fit_status === "ready" ? `Fits ${Number(candidate.metadata_json.target_duration_ms) / 1000}s window` : String(candidate.metadata_json.warning ?? "Timing needs review")}</small>
      <button className="smallButton" disabled={disabled || busy || !!candidate.access_blocked_reason || candidate.metadata_json.fit_status !== "ready" || segment.selected_candidate_id === candidate.id}
        onClick={() => select(candidate.id)}>{segment.selected_candidate_id === candidate.id ? "Selected take" : "Use this take"}</button>
    </div>)}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </div>;
}
