// What needs an editor's attention, and what each job failure means. Pure; unit-tested.
import type { JobErrorCode, ProjectDetail } from "@cinedub/contracts";

export type AttentionKind = "unapproved" | "untranslated" | "no_speaker" | "no_take" | "take_overrun"
  | "demo" | "line_warning" | "stale_take";

export interface AttentionItem {
  key: string; kind: AttentionKind; lineId: string | null; start_ms: number | null; end_ms: number | null;
  message: string;
}

const ORDER: AttentionKind[] = ["untranslated", "no_speaker", "unapproved", "stale_take", "take_overrun",
  "no_take", "line_warning", "demo"];

export function attentionItems(project: ProjectDetail): AttentionItem[] {
  const items: AttentionItem[] = [];
  const artifacts = new Map(project.artifacts.map((artifact) => [artifact.id, artifact]));
  const anyTakes = project.artifacts.some((artifact) => artifact.kind === "dialogue_candidate");
  for (const line of project.segments) {
    if (line.retired) continue;
    const at = { lineId: line.id, start_ms: line.start_ms, end_ms: line.end_ms };
    const name = `Line ${line.index + 1}`;
    const add = (kind: AttentionKind, message: string) =>
      items.push({ key: `${kind}:${line.id}`, kind, ...at, message: `${name}: ${message}` });
    if (!line.translated_text.trim()) add("untranslated", "no Malayalam translation yet");
    if (!line.speaker_id) add("no_speaker", "no speaker assigned");
    if (line.status !== "approved") add("unapproved", "not approved");
    const take = line.selected_candidate_id ? artifacts.get(line.selected_candidate_id) : undefined;
    if (line.selected_candidate_id && !take) add("stale_take", "selected take is no longer available");
    if (take && take.metadata_json.fit_status && take.metadata_json.fit_status !== "ready")
      add("take_overrun", "selected take does not fit its timing window");
    if (!line.selected_candidate_id && anyTakes && line.status === "approved") add("no_take", "no take selected");
    for (const warning of line.warnings_json) add("line_warning", warning);
  }
  const demo = project.artifacts.filter((artifact) => artifact.metadata_json.demo === true).length;
  if (demo) items.push({
    key: "demo", kind: "demo", lineId: null, start_ms: null, end_ms: null,
    message: `${demo} DEMO fixture outputs: not quality evidence; replace before delivery`,
  });
  return items.sort((left, right) => ORDER.indexOf(left.kind) - ORDER.indexOf(right.kind)
    || (left.start_ms ?? Infinity) - (right.start_ms ?? Infinity));
}

const ACTIONS: Record<JobErrorCode, string> = {
  input_invalid: "Saved inputs no longer match this step. Start the step again to create a fresh request.",
  output_invalid: "The step produced an invalid result, so nothing was recorded. Start it again; report it if it repeats.",
  stale_input: "The scene, timeline, voice or model changed after scheduling. Start the step again on the current state.",
  invalid_request: "The step refused its inputs. Read the message, fix the cause, then start it again.",
  budget_exceeded: "The reserved estimate ran out. Raise the project budget, then start a new request.",
  provider_timeout: "The provider did not answer in time. Resume if offered; otherwise check provider usage before a new request.",
  provider_transport: "The connection to the provider failed. Resume if offered; check provider usage before a new request.",
  provider_rejected: "The provider rejected the request. Check credentials, credit and settings.",
  deadline_exceeded: "Local processing hit its time limit and stopped. Resume to continue from saved progress.",
  media_invalid: "The media could not be processed. Check the source file, then resume or import it again.",
  io_error: "A file could not be read or written. Check disk space and permissions, then resume.",
  process_failed: "A local process failed. Resume to try again from saved progress.",
  storage_full: "Storage is full. Free disk space, restart the workspace, then resume.",
  cancelled: "Cancelled. Completed work is kept; start the step again when ready.",
  uncertain_submission: "A provider request may have been submitted (and billed) before an interruption. Check provider usage before retrying explicitly.",
  uncertain_registration: "A voice upload may have reached the provider. Check provider voices and usage before retrying explicitly.",
  restored_job_hold: "Held after workspace recovery. Review the restored state, then resume deliberately.",
  internal: "Unexpected failure. Start the step again; report it if it repeats.",
};

export function errorAction(code: string | null | undefined): string | null {
  if (!code) return null;
  return code in ACTIONS ? ACTIONS[code as JobErrorCode] : ACTIONS.internal;
}
