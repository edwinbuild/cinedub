"use client";

import type { HardwareStatus, ProjectDetail } from "@cinedub/contracts";
import { DemoBadge } from "@/components/demo-badge";
import { API_URL } from "@/lib/api";
import { errorAction } from "@/lib/review-queue";

/** Review progress, budget, revisions, speakers, jobs (with progress and next steps) and downloads. */
export function ProjectRail({ project, hardware, locked, hasRevision, onChangeBudget, onActivate, onAddSpeaker, onRename, onResume }: {
  project: ProjectDetail; hardware: HardwareStatus | null; locked: boolean; hasRevision: boolean;
  onChangeBudget: (value: number) => void; onActivate: (revisionId: string) => void; onAddSpeaker: () => void;
  onRename: (speakerId: string, name: string) => void; onResume: (jobId: string) => void;
}) {
  return <aside className="rightRail"><div className="metricCard"><div><span>Review</span><strong>{project.segments.filter((line) => line.status === "approved").length}/{project.segments.length} approved</strong></div></div>
    <div className="metricCard"><div><span>Estimated processing budget</span><strong>₹{project.spent_estimate_inr.toFixed(2)} / ₹{project.budget_inr.toFixed(2)}</strong>
      <small>₹{project.reserved_inr.toFixed(2)} reserved · provider bill may differ</small>
      <button className="smallButton" onClick={() => { const value = window.prompt("Project processing budget in INR (estimate, not provider billing)", String(project.budget_inr));
        if (value !== null && Number.isFinite(Number(value)) && Number(value) > 0) onChangeBudget(Number(value));
      }}>Change budget</button></div></div>
    <div className="metricCard hardwareCard"><div><span>Local hardware</span><strong>{hardware?.cuda_ready ? "Driver detected" : "GPU inference unavailable"}</strong>
      <small>v0.2 works without local AI models</small></div></div>
    <div className="inspectorSection"><p className="eyebrow">Timeline revisions</p>{project.revisions.map((revision, index) => <div className="revisionItem" key={revision.id}>
      <strong>{revision.provider === "fake" ? "Demo" : "Transcript"} · {project.revisions.length-index}</strong>
      <small>{new Date(revision.created_at).toLocaleString()}</small>
      <button className="smallButton" disabled={locked || revision.id === project.active_revision_id} onClick={() => onActivate(revision.id)}>
        {revision.id === project.active_revision_id ? "Active timeline" : "Use this timeline"}</button></div>)}</div>
    <div className="inspectorSection"><p className="eyebrow">Speakers</p>{hasRevision && <button className="smallButton" disabled={locked} onClick={onAddSpeaker}>Add speaker</button>}{project.speakers.map((speaker) => <button className="speakerRename" key={speaker.id}
      onClick={() => onRename(speaker.id, speaker.display_name)} title="Rename speaker">{speaker.display_name}<small>Rename</small></button>)}</div>
    <div className="inspectorSection"><p className="eyebrow">Jobs</p>{project.jobs.slice(0, 8).map((job) => <div className="revisionItem" key={job.id}>
      <strong>{job.provider === "fake" && <DemoBadge />}{job.stage} · {job.status}</strong><small>{job.provider} · {job.phase}</small>
      {["queued", "running"].includes(job.status) && <progress className="jobMeter" aria-label={`${job.stage} progress`} max={1} value={job.progress} />}
      {job.error_message && <p className="inlineError">{job.error_message}</p>}
      {job.status === "failed" && errorAction(job.error_code) && <small>{errorAction(job.error_code)}</small>}
      {job.warnings_json.map((warning) => <small key={warning}>{warning}</small>)}
      {job.status === "failed" && job.retryable && <button className="smallButton" disabled={locked}
        onClick={() => onResume(job.id)}>{job.provider === "sarvam" ? "Resume existing remote job" : "Resume saved local job"}</button>}</div>)}</div>
    <ArtifactDownloads project={project} />
  </aside>;
}

/** Saved deliverables are available beside export controls and in project history. */
export function ArtifactDownloads({ project }: { project: ProjectDetail }) {
  return <div className="inspectorSection"><p className="eyebrow">Downloads</p>{project.artifacts.filter((item) => ["subtitle", "raw_transcript", "translation_candidates", "dub_preview", "dialogue_mix"].includes(item.kind)).map((item) =>
      item.access_blocked_reason ? <div className="artifact" key={item.id}><strong>{item.filename}</strong><small>{item.access_blocked_reason}</small></div>
        : <a className="artifact" href={`${API_URL}${item.download_url}`} key={item.id}><span><strong>{item.filename}</strong><small>{item.kind.replaceAll("_", " ")} · {item.metadata_json.revision_id === project.active_revision_id ? "active timeline" : "other timeline"}</small></span></a>)}</div>;
}
