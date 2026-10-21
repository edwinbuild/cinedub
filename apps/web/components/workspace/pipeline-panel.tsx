"use client";

import type { CapabilityStatus, Pipeline, PipelineStep, ProjectDetail } from "@cinedub/contracts";
import { CheckCircle2, Circle, CircleAlert, LoaderCircle, PauseCircle } from "lucide-react";
import { useState } from "react";
import { DemoBadge } from "@/components/demo-badge";
import { api } from "@/lib/api";
import { errorAction } from "@/lib/review-queue";
import type { WorkspaceTool } from "./tool-navigation";

const STEP_LABELS: Record<string, string> = {
  ingest: "Prepare media",
  separate: "Separate dialogue & background",
  stems_approved: "Review: approve stems",
  transcribe: "Transcribe",
  speakers_assigned: "Review: speakers & transcript",
  translate: "Translate",
  review_translation: "Editorial checks",
  adapt_dialogue: "Dialogue alternatives",
  lines_approved: "Review: approve every line",
  voices_assigned: "Review: assign voices",
  synthesize: "Generate voice takes",
  takes_selected: "Review: select takes",
  align: "Align source words",
  analyze_takes: "Compare takes",
  analyze_emotion: "Emotion hints",
  render_mix: "Render mix",
  mix_accepted: "Review: accept mix & export",
};

function StepIcon({ step }: { step: PipelineStep }) {
  if (step.status === "completed") return <CheckCircle2 size={14} aria-hidden="true" />;
  if (step.status === "running") return <LoaderCircle size={14} className="spin" aria-hidden="true" />;
  if (step.status === "awaiting") return <PauseCircle size={14} aria-hidden="true" />;
  if (step.status === "failed" || step.status === "cancelled") return <CircleAlert size={14} aria-hidden="true" />;
  return <Circle size={14} aria-hidden="true" />;
}

/** Runs the whole workflow as one pipeline that stops at every human review gate. */
export function PipelinePanel({ project, sourceId, capabilities, locked, onChanged, onOpenTool }: {
  project: ProjectDetail; sourceId: string | null; capabilities: CapabilityStatus[]; locked: boolean;
  onChanged: () => Promise<void>;
  onOpenTool?: (tool: WorkspaceTool) => void;
}) {
  const [options, setOptions] = useState({ separate_dialogue: false, adapt_dialogue: false, analyze_performance: false });
  const [budget, setBudget] = useState("0");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pipeline: Pipeline | null | undefined = project.latest_pipeline;
  const active = pipeline && ["running", "awaiting_review"].includes(pipeline.status);
  const demo = capabilities.length > 0 && capabilities.every((item) =>
    ["media_exporter", "translation_reviewer"].includes(item.capability) || item.selected_provider === "fake");
  const current = active ? pipeline.steps_json[pipeline.current_step] : undefined;
  const job = current?.job_id ? project.jobs.find((item) => item.id === current.job_id) : undefined;
  const failedJob = pipeline?.status === "failed"
    ? project.jobs.find((item) => item.id === pipeline.steps_json[pipeline.current_step]?.job_id) : undefined;
  const budgetPause = pipeline?.status === "awaiting_review" && current?.kind === "job";

  async function act(action: () => Promise<unknown>) {
    try { setBusy(true); setError(null); await action(); await onChanged(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Workflow action failed"); await onChanged(); }
    finally { setBusy(false); }
  }
  const confirmedBudget = Number(budget);

  return <section className="pipelinePanel" aria-label="Dubbing workflow">
    <h2>{demo && <DemoBadge title="Every stage uses deterministic DEMO providers" />}Dubbing workflow</h2>
    {!active && <>
      <p>Runs every stage in order and stops at each review step. Nothing is approved for you.</p>
      <fieldset className="pipelineOptions" disabled={busy || locked}>
        <legend className="visuallyHidden">Workflow options</legend>
        <label><input type="checkbox" checked={options.separate_dialogue} onChange={(event) => setOptions({ ...options, separate_dialogue: event.target.checked })} />Separate dialogue first</label>
        <label><input type="checkbox" checked={options.adapt_dialogue} onChange={(event) => setOptions({ ...options, adapt_dialogue: event.target.checked })} />Generate dialogue alternatives</label>
        <label><input type="checkbox" checked={options.analyze_performance} onChange={(event) => setOptions({ ...options, analyze_performance: event.target.checked })} />Analyze timing &amp; performance</label>
        <label className="fieldLabel">Paid-provider budget (₹)<input aria-label="Workflow budget in rupees" type="number" min="0" step="1" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>
      </fieldset>
      <button className="pipelineButton" disabled={busy || locked || !sourceId || !Number.isFinite(confirmedBudget) || confirmedBudget < 0}
        onClick={() => act(() => api.startPipeline(project.id, { source_asset_id: sourceId!, ...options, confirmed_budget_inr: confirmedBudget }))}>
        <span><strong>Run dubbing workflow</strong><small>{demo ? "DEMO providers · fixtures only" : "Pauses before exceeding the budget"}</small></span></button>
    </>}
    {pipeline && <ol className="pipelineSteps" aria-label="Workflow steps">
      {pipeline.steps_json.map((step, index) => {
        const stepJob = step.job_id ? project.jobs.find((item) => item.id === step.job_id) : undefined;
        return <li key={step.key} className={`pipelineStep ${step.status} ${index === pipeline.current_step && active ? "current" : ""}`}
          aria-current={index === pipeline.current_step && active ? "step" : undefined}>
          <StepIcon step={step} /><span>{STEP_LABELS[step.key] ?? step.key}</span>
          <small>{step.status === "awaiting" ? "waiting for you" : step.status}</small>
          {step.status === "running" && stepJob && <progress aria-label={`${STEP_LABELS[step.key] ?? step.key} progress`} max={1} value={stepJob.progress} />}
        </li>;
      })}
    </ol>}
    {pipeline && <p className={pipeline.status === "failed" ? "inlineError" : "lineWarning"} role="status">
      {pipeline.status === "completed" ? "Workflow complete: the accepted export bundle is ready."
        : pipeline.status === "cancelled" ? "Workflow cancelled. Completed work is kept."
        : pipeline.gate_reason ?? (job ? `${job.stage.replaceAll("_", " ")} · ${job.phase.replaceAll("_", " ")}` : "Working…")}
    </p>}
    {failedJob?.error_code && <p className="lineWarning">{errorAction(failedJob.error_code)}</p>}
    {active && pipeline.status === "awaiting_review" && <div className="pipelineActions">
      {onOpenTool && current?.key === "voices_assigned" && <button className="smallButton" onClick={() => onOpenTool("voices")}>Choose voices</button>}
      {onOpenTool && current?.key === "mix_accepted" && <button className="smallButton" onClick={() => onOpenTool("export")}>Review mix and export</button>}
      {budgetPause && <label className="fieldLabel">New workflow budget (₹)<input aria-label="Raise workflow budget in rupees" type="number" min={pipeline.budget_confirmed_inr} step="1" value={budget} onChange={(event) => setBudget(event.target.value)} /></label>}
      <button className="smallButton" disabled={busy || locked}
        onClick={() => act(() => api.continuePipeline(pipeline.id, budgetPause ? { confirmed_budget_inr: confirmedBudget } : {}))}>
        {budgetPause ? "Confirm budget and continue" : "Continue after review"}</button>
    </div>}
    {active && <button className="smallButton" disabled={busy} onClick={() => {
      if (window.confirm("Cancel the workflow? The running step stops; completed work and reviews are kept.")) void act(() => api.cancelPipeline(pipeline.id));
    }}>Cancel workflow</button>}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </section>;
}
