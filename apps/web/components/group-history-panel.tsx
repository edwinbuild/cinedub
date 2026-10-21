"use client";

import type { EditGroupHistory, EditGroupSummary, ProjectDetail } from "@cinedub/contracts";
import { useLayoutEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export function GroupHistoryPanel({ project, disabled, unsaved, onApply }: {
  project: ProjectDetail; disabled: boolean; unsaved: boolean;
  onApply: (action: () => Promise<unknown>) => Promise<void>;
}) {
  const [groups, setGroups] = useState<EditGroupSummary[] | null>(null);
  const [view, setView] = useState<EditGroupHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const root = useRef<HTMLDetailsElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (busy || !restoreFocus.current) return;
    const target = restoreFocus.current; restoreFocus.current = null;
    if (document.activeElement !== document.body) return;
    if (target.isConnected && !target.matches(":disabled")) target.focus(); else root.current?.focus();
  }, [busy]);
  const versions = new Map(project.segments.map((segment) => [segment.id, segment.version]));
  const current = !!view && view.revision_id === project.active_revision_id && view.lines.every((line) =>
    versions.get(line.segment_id) === line.expected_version);
  async function inspect(groupId: string) {
    setBusy(true); setConfirmed(false); setError(null); setNotice("");
    try { setView(await api.editGroup(project.id, groupId)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not inspect grouped history"); }
    finally { setBusy(false); }
  }
  async function load() {
    if (!project.active_revision_id) return;
    setBusy(true); setConfirmed(false); setError(null);
    try {
      const result = await api.editGroups(project.id, project.active_revision_id); setGroups(result);
      const groupId = result.some((group) => group.group_id === view?.group_id) ? view!.group_id : result[0]?.group_id;
      setView(groupId ? await api.editGroup(project.id, groupId) : null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not refresh grouped history"); }
    finally { setBusy(false); }
  }
  async function restore(action: "undo" | "redo") {
    if (!view || !current || disabled || unsaved || busy || !confirmed || !view[`can_${action}`]) return;
    if (!window.confirm(`${action === "undo" ? "Undo" : "Redo"} content on all ${view.lines.length} material group members? Selected takes will be cleared and review is required again. Approval-only changes are excluded.`)) return;
    restoreFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setBusy(true); setError(null); setNotice("");
    try {
      await onApply(() => api.restoreEditGroup(project.id, view.group_id, {
        revision_id: view.revision_id, action, restoration_confirmed: confirmed,
        lines: view.lines.map(({ segment_id, expected_version, expected_edit_id }) => ({ segment_id, expected_version, expected_edit_id })),
      }));
      setConfirmed(false); setNotice(`Grouped ${action} saved. All restored content requires review again.`);
      await load();
    } catch (cause) { setError(`${cause instanceof Error ? cause.message : "Grouped restoration failed"}. Refresh project and history before retrying; no local draft is replaced.`); }
    finally { setBusy(false); }
  }
  return <details ref={root} tabIndex={-1} className="dubPreview" aria-label="Grouped edit history" onToggle={(event) => {
    if (event.currentTarget.open && groups === null && !busy) void load();
  }}>
    <summary>Grouped edit history · undo/redo content together</summary>
    <p>Restore saved text, speakers and timing as one transaction. Later or independently restored content on any material member prevents partial restoration. Approval, voice selection, consent and other review forms are never restored.</p>
    <button className="smallButton" disabled={busy} onClick={load}>Refresh grouped history</button>
    {groups && groups.length > 0 && <label className="fieldLabel">Saved dialogue group<select aria-label="Saved dialogue group" disabled={busy} value={view?.group_id ?? ""} onChange={(event) => void inspect(event.target.value)}>
      {!view && <option value="">Choose a group</option>}
      {groups.map((group) => <option key={group.group_id} value={group.group_id}>{new Date(group.created_at).toLocaleString()} · {group.line_count} saved lines · {group.group_id.slice(0, 8)}</option>)}
    </select></label>}
    {groups?.length === 0 && <p>No grouped dialogue saves in this timeline. Showing at most the latest 20 groups.</p>}
    {view && <section aria-label="Grouped content restoration">
      <p>{view.lines.length} content-changing members. {view.excluded_nonmaterial_count} approval/status-only members excluded.</p>
      {!current && <p className="lineWarning">Project versions differ from this inspection. Refresh project and grouped history before restoring.</p>}
      {view.unavailable_reason && <p className="lineWarning">{view.unavailable_reason}</p>}
      {unsaved && <p className="lineWarning">Save or discard dialogue and other review drafts before restoring grouped content.</p>}
      <label className="performanceToggle"><input type="checkbox" checked={confirmed} disabled={disabled || busy || unsaved || !current} onChange={(event) => setConfirmed(event.target.checked)} />Grouped restoration clears selected takes and requires approval again</label>
      <button className="smallButton" disabled={disabled || busy || unsaved || !current || !confirmed || !view.can_undo} onClick={() => void restore("undo")}>Undo grouped content</button>
      <button className="smallButton" disabled={disabled || busy || unsaved || !current || !confirmed || !view.can_redo} onClick={() => void restore("redo")}>Redo grouped content</button>
      {view.lines.map((line) => <details key={line.segment_id}><summary>Line {line.index + 1} · inspected version {line.expected_version}</summary>
        <h4>Before grouped save</h4><p>{line.before.source_text}</p><p lang="ml">{line.before.translated_text || "No translation"}</p>
        <p>{line.before.start_ms}–{line.before.end_ms} ms · speaker {line.before.speaker_id ?? "unassigned"}</p>
        <h4>After grouped save</h4><p>{line.after.source_text}</p><p lang="ml">{line.after.translated_text || "No translation"}</p>
        <p>{line.after.start_ms}–{line.after.end_ms} ms · speaker {line.after.speaker_id ?? "unassigned"}</p>
      </details>)}
    </section>}
    <p role="status" aria-atomic="true">{notice}</p>
    {error && <p className="inlineError" role="alert">{error}</p>}
  </details>;
}
