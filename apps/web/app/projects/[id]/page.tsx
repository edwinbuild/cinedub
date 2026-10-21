"use client";

import type { CapabilityStatus, HardwareStatus, JobRequest, ProjectDetail, Segment } from "@cinedub/contracts";
import { ArrowLeft, ArrowRight, Download, Film, LoaderCircle, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, RefreshCw, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { DialogueLine, type GroupedDraft } from "@/components/dialogue-line";
import { DialogueTimeline } from "@/components/dialogue-timeline";
import { StructurePanel } from "@/components/structure-panel";
import { GroupHistoryPanel } from "@/components/group-history-panel";
import { ScenePlayer } from "@/components/scene-player";
import { VoicePanel } from "@/components/voice-panel";
import { SpeakerReusePanel } from "@/components/speaker-reuse-panel";
import { ClonePanel } from "@/components/clone-panel";
import { StemPanel } from "@/components/stem-panel";
import { MixPanel } from "@/components/mix-panel";
import { AlignmentPanel } from "@/components/alignment-panel";
import { PerformancePanel } from "@/components/performance-panel";
import { EmotionPanel } from "@/components/emotion-panel";
import { DialogueBriefPanel } from "@/components/dialogue-brief-panel";
import { DialogueAdaptationPanel } from "@/components/dialogue-adaptation-panel";
import { DemoBadge } from "@/components/demo-badge";
import { PipelinePanel } from "@/components/workspace/pipeline-panel";
import { ArtifactDownloads, ProjectRail } from "@/components/workspace/project-rail";
import { ReviewQueue } from "@/components/workspace/review-queue";
import { TimelineView, type TimingEditor } from "@/components/workspace/timeline-view";
import { ToolNavigation, WORKSPACE_TOOLS, type WorkspaceTool } from "@/components/workspace/tool-navigation";
import { MediaImport } from "@/components/workspace/media-import";
import { WorkspaceLayout } from "@/components/workspace/workspace-layout";
import { API_URL, api } from "@/lib/api";
import { useProjectEvents } from "@/lib/project-events";
import type { Range } from "@/lib/timeline";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityStatus[]>([]);
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [speakerCount, setSpeakerCount] = useState("");
  const [preferDialogue, setPreferDialogue] = useState(false);
  const [filter, setFilter] = useState("all");
  const [activeTool, setActiveTool] = useState<WorkspaceTool>("media");
  const [toolsOpen, setToolsOpen] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [timelineOpen, setTimelineOpen] = useState(true);
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);
  const structureEditor = useRef<{ open: (lineId: string | null) => void }>(null);
  const toolPanel = useRef<HTMLElement>(null);
  function changeTool(tool: WorkspaceTool) {
    setActiveTool(tool);
    setToolsOpen(true);
    toolPanel.current?.scrollTo({ top: 0 });
  }
  const [time, setTime] = useState(0);
  const [stopAt, setStopAt] = useState<number | null>(null);
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(() => new Set());
  const [structureDirty, setStructureDirty] = useState(false);
  const [referenceDirty, setReferenceDirty] = useState(false);
  const [panelDraftIds, setPanelDraftIds] = useState<Set<string>>(() => new Set());
  const panelDraftRef = useRef<Set<string>>(new Set());
  const displayedRevision = useRef<string | null | undefined>(undefined);
  const [remoteTimelineChanged, setRemoteTimelineChanged] = useState(false);
  const onPanelDirty = useCallback((key: string, dirty: boolean) => {
    const previous = panelDraftRef.current;
    if (previous.has(key) === dirty) return;
    const next = new Set(previous); if (dirty) next.add(key); else next.delete(key);
    panelDraftRef.current = next; setPanelDraftIds(next);
  }, []);
  const [preservedDrafts, setPreservedDrafts] = useState<Segment[]>([]);
  const dirtyRef = useRef<Set<string>>(new Set());
  const groupedDrafts = useRef(new Map<string, GroupedDraft>());
  const groupedFocus = useRef<HTMLElement | null>(null);
  const timelineHeading = useRef<HTMLHeadingElement>(null);
  useLayoutEffect(() => {
    if (busy || !groupedFocus.current) return;
    const target = groupedFocus.current; groupedFocus.current = null;
    if (document.activeElement !== document.body) return;
    if (target.isConnected && !target.matches(":disabled") && !target.closest("[hidden]")) target.focus();
    else timelineHeading.current?.focus();
  }, [busy]);
  const onGroupedDraft = useCallback((lineId: string, value: GroupedDraft | null) => {
    if (value) groupedDrafts.current.set(lineId, value); else groupedDrafts.current.delete(lineId);
  }, []);
  const lineCache = useRef<Map<string, Segment>>(new Map());
  const timingEditors = useRef(new Map<string, TimingEditor>());
  const [timingDrafts, setTimingDrafts] = useState<Record<string, Range>>({});
  const onTimingEditor = useCallback((lineId: string, apply: TimingEditor | null) => {
    if (apply) timingEditors.current.set(lineId, apply); else timingEditors.current.delete(lineId);
  }, []);
  const onTimingDraft = useCallback((lineId: string, range: Range | null) => {
    setTimingDrafts((current) => {
      const existing = current[lineId];
      if (!range) { if (!existing) return current; const next = { ...current }; delete next[lineId]; return next; }
      if (existing && existing.start_ms === range.start_ms && existing.end_ms === range.end_ms) return current;
      return { ...current, [lineId]: range };
    });
  }, []);
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const loadSequence = useRef(0);
  const load = useCallback(async (discardPanelDrafts = false) => {
    const sequence = ++loadSequence.current;
    try { const detail = await api.project(id);
      if (sequence === loadSequence.current) {
        if (displayedRevision.current !== undefined && displayedRevision.current !== detail.active_revision_id
          && panelDraftRef.current.size && !discardPanelDrafts) {
          mediaRef.current?.pause(); setStopAt(null);
          setRemoteTimelineChanged(true); setError(null); return;
        }
        if (displayedRevision.current !== undefined && displayedRevision.current !== detail.active_revision_id) {
          setSelectedSource(null); setStructureDirty(false); mediaRef.current?.pause(); setStopAt(null);
        }
        displayedRevision.current = detail.active_revision_id;
        setRemoteTimelineChanged(false);
        const current = new Map(detail.segments.map((line) => [line.id, line]));
        const displaced = Array.from(dirtyRef.current).flatMap((lineId) => {
          const previous = lineCache.current.get(lineId);
          return !current.has(lineId) && previous ? [{ ...previous, retired: true }] : [];
        });
        lineCache.current = new Map([...current, ...displaced.map((line) => [line.id, line] as const)]);
        setPreservedDrafts(displaced); setProject(detail); setError(null);
      } }
    catch (cause) { if (sequence === loadSequence.current)
      setError(cause instanceof Error ? cause.message : "Could not load project"); }
  }, [id]);
  const loadDiagnostics = useCallback(async () => {
    const results = await Promise.allSettled([api.capabilities(), api.diagnostics()]);
    if (results[0].status === "fulfilled") setCapabilities(results[0].value);
    if (results[1].status === "fulfilled") setHardware(results[1].value);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => { void load(); void loadDiagnostics(); }, 0);
    return () => window.clearTimeout(timer);
  }, [load, loadDiagnostics]);
  // Live server events replace polling: job/pipeline updates patch state in place, while
  // timeline or artifact changes refetch through load(), which protects unsaved drafts.
  useProjectEvents(id, {
    onJob: (job) => {
      setProject((current) => current && ({
        ...current, jobs: [job, ...current.jobs.filter((item) => item.id !== job.id)]
          .sort((left, right) => right.created_at.localeCompare(left.created_at)),
      }));
      // A finished job may have changed anything (voices, stems, mixes, reviews): refetch.
      if (!["queued", "running"].includes(job.status)) void load();
    },
    onPipeline: (pipeline) => setProject((current) => current && (
      !current.latest_pipeline || current.latest_pipeline.id === pipeline.id
        || pipeline.created_at >= current.latest_pipeline.created_at
        ? { ...current, latest_pipeline: pipeline } : current)),
    onStatus: (status) => setProject((current) => current && ({ ...current, status })),
    onStale: () => void load(),
  });
  useEffect(() => {
    if (!dirtyIds.size && !structureDirty && !referenceDirty && !panelDraftIds.size) return;
    function warn(event: BeforeUnloadEvent) { event.preventDefault(); event.returnValue = ""; }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyIds.size, structureDirty, referenceDirty, panelDraftIds.size]);
  const onDirty = useCallback((lineId: string, dirty: boolean) => {
    const next = new Set(dirtyRef.current); if (dirty) next.add(lineId); else next.delete(lineId);
    dirtyRef.current = next; setDirtyIds(next);
    if (!dirty) setPreservedDrafts((lines) => lines.filter((line) => line.id !== lineId));
  }, []);
  const onTime = useCallback((value: number) => setTime(value), []);
  const onStop = useCallback(() => setStopAt(null), []);

  const activeRevision = project?.revisions.find((item) => item.id === project.active_revision_id);
  const sourceId = selectedSource ?? activeRevision?.source_asset_id ?? project?.assets.at(-1)?.id ?? null;
  const sourceReady = project?.artifacts.some((item) => item.kind === "recognition_audio" && item.metadata_json.source_asset_id === sourceId);
  const timelineMatches = !activeRevision?.source_asset_id || activeRevision.source_asset_id === sourceId;
  const transcriber = capabilities.find((item) => item.capability === "transcriber");
  const translator = capabilities.find((item) => item.capability === "translator");
  const voiceCapability = capabilities.find((item) => item.capability === "voice_synthesizer");
  const cloneCapability = capabilities.find((item) => item.capability === "voice_cloner");
  const separator = capabilities.find((item) => item.capability === "stem_separator");
  const aligner = capabilities.find((item) => item.capability === "timing_aligner");
  const targetAligner = capabilities.find((item) => item.capability === "target_timing_aligner");
  const performanceAnalyzer = capabilities.find((item) => item.capability === "performance_analyzer");
  const dialogueAdapter = capabilities.find((item) => item.capability === "dialogue_adapter");
  const activeStems = project?.stem_sets.find((stems) => stems.id === project.assets.find((asset) => asset.id === sourceId)?.active_stem_set_id && stems.status === "approved");
  const transcriptionInput = preferDialogue && activeStems ? "dialogue_stem" : "original";

  async function run(payload: JobRequest) {
    try {
      setBusy(payload.stage); setError(null); setNotice(null);
      const estimate = await api.estimateJob(id, payload);
      if (estimate.estimated_cost_inr > 0 && !window.confirm(
        `Reserve up to ₹${estimate.estimated_cost_inr.toFixed(2)} for this operation? Remaining estimated budget: ₹${estimate.remaining_inr.toFixed(2)}. Estimates are not the provider bill.`
      )) return;
      const job = await api.startJob(id, payload);
      if (estimate.cached_job_id) setNotice(`Reused existing ${job.status} result. Choose Retranscribe to create a fresh revision.`);
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start processing"); }
    finally { setBusy(null); }
  }
  async function upload(file: File) {
    if (busy || remoteTimelineChanged || project?.jobs.some((job) => ["queued", "running"].includes(job.status))) return;
    try { setBusy("upload"); setError(null); const result = await api.upload(id, file) as { id: string };
      setSelectedSource(result.id); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Upload failed"); }
    finally { setBusy(null); }
  }
  async function activate(revisionId: string) {
    if (!project) return;
    if ((dirtyIds.size || structureDirty || panelDraftIds.size) && !window.confirm("Discard unsaved drafts and switch timeline? Saved revisions are preserved.")) return;
    try { setBusy("revision"); const detail = await api.activateRevision(id, revisionId, project.active_revision_id);
      displayedRevision.current = detail.active_revision_id; setProject(detail); setRemoteTimelineChanged(false);
      dirtyRef.current = new Set(); lineCache.current.clear(); setPreservedDrafts([]);
      setDirtyIds(new Set()); panelDraftRef.current = new Set(); setPanelDraftIds(new Set()); setStructureDirty(false); setSelectedSource(null); mediaRef.current?.pause(); setStopAt(null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not switch timeline"); }
    finally { setBusy(null); }
  }
  async function jobAction(action: () => Promise<unknown>) {
    try { setBusy("job"); await action(); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Job action failed"); }
    finally { setBusy(null); }
  }
  async function structureAction(action: () => Promise<unknown>) {
    setBusy("structure");
    try { await action(); await load(); }
    finally { setBusy(null); }
  }
  async function saveGroupedDrafts() {
    if (!project?.active_revision_id || busy) return;
    const drafts = Array.from(dirtyRef.current).map((lineId) => groupedDrafts.current.get(lineId));
    if (!drafts.length || drafts.length > 100 || drafts.some((value) => !value || value.blocked)) {
      setError("Grouped save is unavailable: resolve stale or removed lines and wait for individual saves. Save at most 100 dialogue drafts together."); return;
    }
    const ready = drafts as GroupedDraft[];
    if (!window.confirm(`Save all ${ready.length} dialogue drafts together, including filtered-out lines? One invalid or changed line prevents the entire save. Dialogue/timing changes require review again. Other review forms are not saved.`)) return;
    groupedFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setBusy("group-save"); setError(null); setNotice(null);
    try {
      const result = await api.updateSegments(id, { revision_id: project.active_revision_id, lines: ready.map((value) => value.item) });
      const saved = new Map(result.lines.map((line) => [line.id, line]));
      if (saved.size !== ready.length || ready.some((value) => !saved.has(value.item.segment_id))) throw new Error("Grouped save response was incomplete; refresh to inspect saved versions.");
      ready.forEach((value) => value.accept(saved.get(value.item.segment_id)!));
      setNotice(`${result.lines.length} dialogue drafts saved together. Changed content requires review again.`);
      await load();
    } catch (cause) {
      setError(`${cause instanceof Error ? cause.message : "Grouped save failed"}. Drafts are preserved. Refresh to inspect saved versions before retrying if the connection failed.`);
    } finally { setBusy(null); }
  }
  function goToLine(lineId: string, startMs: number) {
    setFilter("all"); setInspectorOpen(true); setSelectedLineId(lineId);
    // Wait for the filter change to reveal the line before scrolling/focusing it.
    requestAnimationFrame(() => {
      const target = document.getElementById(`line-${lineId}`);
      target?.scrollIntoView({ block: "center" }); target?.focus();
    });
    const player = mediaRef.current; if (player) player.currentTime = startMs / 1000;
  }
  function seek(ms: number) {
    const player = mediaRef.current; if (player) player.currentTime = ms / 1000;
  }
  function openStructure() {
    setInspectorOpen(true);
    requestAnimationFrame(() => structureEditor.current?.open(selectedLineId));
  }
  async function playLine(line: Segment) {
    await playRange(line.start_ms, line.end_ms);
  }
  async function playRange(start: number, end: number) {
    const player = mediaRef.current; if (!player) return;
    try { player.currentTime = start / 1000;
      await player.play(); setStopAt(end); }
    catch { setError("Playback could not start. Use the media player's play control first."); }
  }
  async function rename(speakerId: string, oldName: string) {
    const name = window.prompt("Speaker name", oldName); if (!name?.trim() || name === oldName) return;
    await jobAction(() => api.renameSpeaker(speakerId, name));
  }
  async function addSpeaker() {
    if (!project?.active_revision_id) return;
    const name = window.prompt("New speaker name"); if (!name?.trim()) return;
    await jobAction(() => api.createSpeaker(id, project.active_revision_id!, name));
  }
  if (!project) return <main className="loadingScreen"><LoaderCircle className="spin" />{error ?? "Opening scene…"}</main>;
  const activeJob = project.jobs.find((job) => ["running", "queued"].includes(job.status));
  const locked = !!busy || !!activeJob || remoteTimelineChanged;
  const missing = project.segments.some((line) => !line.translated_text.trim());
  const revisionId = project.active_revision_id ?? undefined;
  const allApproved = project.segments.length > 0 && project.segments.every((line) => line.status === "approved");
  const allSelected = allApproved && project.segments.every((line) => line.selected_candidate_id !== null);
  const voicePreview = project.artifacts.find((item) => ["dub_preview", "dialogue_mix"].includes(item.kind)
    && item.metadata_json.revision_id === project.active_revision_id);
  const selectedTakes = voicePreview?.metadata_json.candidates as Record<string, string> | undefined;
  const previewStale = !!voicePreview && (!allSelected || project.segments.some((line) => selectedTakes?.[line.id] !== line.selected_candidate_id));
  function hidden(line: Segment) {
    return filter === "untranslated" ? !!line.translated_text.trim() : filter === "edited" ? !line.human_edited
      : filter === "approved" ? line.status !== "approved" : filter === "warnings" ? !line.warnings_json.length : false;
  }

  return <main className="studioShell">
    <a className="skipLink" href="#dialogue-editor">Skip to dialogue editor</a>
    <header className="studioTopbar"><div className="studioIdentity">
      <Link href="/" className="iconButton" aria-label="Projects" onClick={(event) => {
        if ((dirtyIds.size || structureDirty || referenceDirty || panelDraftIds.size) && !window.confirm("Leave this scene and discard unsaved drafts?")) event.preventDefault();
      }}><ArrowLeft size={17} /></Link><span className="brandMark"><Film size={17} /></span>
      <div><strong>{project.name}</strong><span>English → Malayalam</span></div></div>
      <div className="workspaceContext"><span className="statusDot active" /> Editing workspace</div>
      <div className="studioStatus">{(dirtyIds.size > 0 || structureDirty || referenceDirty || panelDraftIds.size > 0) && <span>{dirtyIds.size + Number(structureDirty) + Number(referenceDirty) + panelDraftIds.size} unsaved</span>}
        {activeJob ? activeJob.phase.replaceAll("_", " ") : project.status}
        <button className="iconButton" aria-label={toolsOpen ? "Hide tools panel" : "Show tools panel"} aria-expanded={toolsOpen} aria-controls="scene-tools" onClick={() => setToolsOpen(!toolsOpen)}>
          {toolsOpen ? <PanelLeftClose size={16} /> : <PanelLeftOpen size={16} />}</button>
        <button className="iconButton" aria-label={inspectorOpen ? "Hide dialogue inspector" : "Show dialogue inspector"} aria-expanded={inspectorOpen} aria-controls="dialogue-inspector" onClick={() => setInspectorOpen(!inspectorOpen)}>
          {inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}</button>
        <button className="iconButton" aria-label="Refresh project" onClick={() => void load()}><RefreshCw size={15} /></button>
        <button className="primaryButton headerExport" onClick={() => changeTool("export")}><Download size={14} /> Export</button></div></header>
    {error && <div className="errorBanner studioError" role="alert">{error}</div>}
    {notice && <div className="noticeBanner" role="status">{notice}</div>}
    {remoteTimelineChanged && <div className="noticeBanner" role="alert">
      Another tab changed the active timeline. Your unsaved mix settings and emotion/mix review fields are still visible below.
      Copy any needed values before continuing. Actions on this old timeline are paused.
      <button className="smallButton" disabled={!!busy} onClick={() => {
        if (window.confirm("Discard unsaved mix settings, emotion/mix review fields and other timeline-specific forms and load the current server timeline? Displaced dialogue drafts remain available to copy. Saved renders and review history will not change.")) void load(true);
      }}>Discard review drafts and load current timeline</button>
    </div>}
    <WorkspaceLayout toolsOpen={toolsOpen} inspectorOpen={inspectorOpen} timelineOpen={timelineOpen}>
      <ToolNavigation active={activeTool} onChange={changeTool} />
      <aside id="scene-tools" className="toolPanel" aria-label="Scene tools" ref={toolPanel} hidden={!toolsOpen}>
        <div className="toolPanelHeading"><h2>{WORKSPACE_TOOLS.find((tool) => tool.id === activeTool)?.label}</h2><button className="iconButton" aria-label="Close tools panel" onClick={() => setToolsOpen(false)}><X size={14} /></button>
          <p>{WORKSPACE_TOOLS.find((tool) => tool.id === activeTool)?.description}</p></div>
        {/* Hidden panels stay mounted: switching tools must never discard a draft. */}
        <section id="tool-media" className="toolBody" aria-label="Media tools" hidden={activeTool !== "media"}>
          <MediaImport disabled={locked} uploading={busy === "upload"} onFile={upload} />
        <label className="fieldLabel">Source<select aria-label="Scene source" value={sourceId ?? ""} disabled={locked}
          onChange={(event) => { mediaRef.current?.pause(); setStopAt(null); setSelectedSource(event.target.value); }}>
          <option value="" disabled>Select a scene</option>{project.assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select></label>
          <div className="mediaBin" aria-label="Imported media">{project.assets.map((asset) => <button key={asset.id} className={`mediaBinItem ${sourceId === asset.id ? "selected" : ""}`}
            disabled={locked} aria-pressed={sourceId === asset.id} onClick={() => { mediaRef.current?.pause(); setStopAt(null); setSelectedSource(asset.id); }}>
            <Film size={22} aria-hidden="true" /><span><strong>{asset.filename}</strong><small>{sourceId === asset.id ? "Active source" : "Use this source"}</small></span></button>)}
            {!project.assets.length && <p className="toolHint">Your imported clips will appear here.</p>}</div>
          <button className="primaryButton toolPrimary" disabled={!sourceId} onClick={() => changeTool("workflow")}>Open dubbing workflow <ArrowRight size={15} /></button>
        <div className="railSection"><p className="eyebrow">Development demo</p><button className="pipelineButton" disabled={locked || !!project.revisions.length}
          onClick={() => run({ stage: "demo_pipeline", provider: "fake" })}><span><strong>Build demo timeline</strong><small>Four fixture lines; no AI calls</small></span></button></div>
        </section>
        <section id="tool-workflow" className="toolBody" aria-label="Workflow tools" hidden={activeTool !== "workflow"}>
        <PipelinePanel project={project} sourceId={sourceId} capabilities={capabilities}
          locked={!!busy || remoteTimelineChanged || (!!activeJob && !["running", "awaiting_review"].includes(project.latest_pipeline?.status ?? ""))}
          onChanged={load} onOpenTool={changeTool} />
        <div className="railSection"><p className="eyebrow">Process scene</p>
          <button className="pipelineButton" aria-label="Separate dialogue and background" disabled={locked || !sourceId || !separator?.available}
            onClick={() => run({ stage: "separate", source_asset_id: sourceId!, force_new: project.stem_sets.some((stems) => stems.source_asset_id === sourceId) })}>
            <span><strong>Separate dialogue & background</strong><small>{separator?.selected_provider === "fake" ? "DEMO fixture stems · no separation" : "Local CPU · three stems · review required"}</small></span></button>
          <label className="fieldLabel">Transcription audio<select aria-label="Transcription audio" value={transcriptionInput} disabled={locked}
            onChange={(event) => setPreferDialogue(event.target.value === "dialogue_stem")}>
            <option value="original">Original source audio</option><option value="dialogue_stem" disabled={!activeStems}>Reviewed dialogue stem</option></select></label>
          {transcriber?.selected_provider !== "local" && <label className="fieldLabel">Expected speakers<select value={speakerCount} onChange={(event) => setSpeakerCount(event.target.value)}>
            <option value="">Detect automatically</option>{Array.from({ length: 20 }, (_, index) => <option key={index} value={index + 1}>{index + 1}</option>)}</select></label>
          }
          {transcriber?.selected_provider === "local" && <p className="lineWarning">Offline English transcription. Add speakers and assign each line manually; this model does not identify speakers.</p>}
          {sourceId && !sourceReady && !activeJob && <button className="pipelineButton" disabled={locked}
            onClick={() => run({ stage: "ingest", source_asset_id: sourceId })}><span><strong>Prepare media</strong><small>Create audio, waveform and preview</small></span></button>}
          <button className="pipelineButton" aria-label="Transcribe scene" disabled={locked || !sourceReady || !transcriber?.available}
            onClick={() => run({ stage: "transcribe", source_asset_id: sourceId!, transcription_input: transcriptionInput, num_speakers: transcriber?.selected_provider !== "local" && speakerCount ? Number(speakerCount) : undefined })}>
            <span><strong>Transcribe scene</strong><small>{transcriber?.selected_provider === "fake" ? "Demo fixture transcription" : transcriber?.selected_provider === "local" ? "Local English ASR · manual speakers" : "Real dialogue and speakers"}</small></span></button>
          {activeRevision && <button className="pipelineButton" aria-label="Retranscribe into new revision" disabled={locked || !sourceReady || !transcriber?.available}
            onClick={() => run({ stage: "transcribe", source_asset_id: sourceId!, transcription_input: transcriptionInput, force_new: true, num_speakers: transcriber?.selected_provider !== "local" && speakerCount ? Number(speakerCount) : undefined })}>
            <span><strong>Retranscribe into new revision</strong><small>Current edits remain saved</small></span></button>}
          <button className="pipelineButton" aria-label="Translate dialogue" disabled={locked || !project.segments.length || !translator?.available || dirtyIds.size > 0}
            onClick={() => run({ stage: "translate", revision_id: revisionId })}><span><strong>Translate dialogue</strong><small>Preserve human edits and approved lines</small></span></button>
        </div>
        <StemPanel project={project} sourceId={sourceId} disabled={locked} onSaved={load} />
        </section>
        <section id="tool-voices" className="toolBody" aria-label="Voice tools" hidden={activeTool !== "voices"}>
        {voiceCapability && ["sarvam", "fake"].includes(voiceCapability.selected_provider) && <VoicePanel speakers={project.speakers}
          profiles={project.voice_profiles} provider={voiceCapability.selected_provider as "sarvam" | "fake"} disabled={locked} onSaved={load} />}
          <button className="pipelineButton" aria-label="Generate voice candidates" disabled={locked || !allApproved || !voiceCapability?.available || dirtyIds.size > 0}
            onClick={() => run({ stage: "synthesize", revision_id: revisionId })}><span><strong>Generate voice candidates</strong><small>{voiceCapability?.selected_provider === "fake" ? "Demo tones for approved lines" : "Selected voices · approved lines"}</small></span></button>
        {project.active_revision_id && <SpeakerReusePanel key={`reuse:${project.active_revision_id}`} project={project}
          disabled={locked} unsaved={dirtyIds.size > 0 || structureDirty || referenceDirty || panelDraftIds.size > 0} onSaved={load} />}
        {cloneCapability && ["fake", "sarvam"].includes(cloneCapability.selected_provider) && <ClonePanel project={project}
          provider={cloneCapability.selected_provider as "fake" | "sarvam"} available={cloneCapability.available}
          disabled={locked} onSaved={load} onRun={run} onDirty={setReferenceDirty} />}
        </section>
        <section id="tool-analysis" className="toolBody" aria-label="Analysis tools" hidden={activeTool !== "analysis"}>
          <p className="toolHint">Optional tools. Review suggestions before applying them to your dialogue.</p>
        {project.active_revision_id && <DialogueBriefPanel key={`brief:${project.active_revision_id}`} project={project}
          disabled={locked} unsaved={dirtyIds.size > 0} onRun={run} onSaved={load} onDirty={onDirty}
          onPlayRange={playRange} canPlay={!!sourceReady && timelineMatches} />}
        {project.active_revision_id && <DialogueAdaptationPanel key={`adaptation:${project.active_revision_id}`} project={project}
          available={!!dialogueAdapter?.available} disabled={locked} unsaved={dirtyIds.size > 0} onRun={run} onSaved={load}
          onPlayRange={playRange} canPlay={!!sourceReady && timelineMatches} />}
        <AlignmentPanel project={project} disabled={locked} unsaved={dirtyIds.size > 0}
          available={!!aligner?.available} sourceId={sourceId} transcriptionInput={transcriptionInput}
          onRun={run} onSaved={load} onPlayRange={playRange} />
        <PerformancePanel key={project.active_revision_id ?? "none"} project={project} sourceId={sourceId} disabled={locked} unsaved={dirtyIds.size > 0}
          available={!!performanceAnalyzer?.available} targetAlignmentAvailable={!!targetAligner?.available}
          transcriptionInput={transcriptionInput} onRun={run} onPlayRange={playRange} />
        {project.active_revision_id && <EmotionPanel key={`emotion:${project.active_revision_id}`} project={project} sourceId={sourceId}
          disabled={locked} unsaved={dirtyIds.size > 0} available={!!capabilities.find((item) => item.capability === "emotion_analyzer")?.available}
          transcriptionInput={transcriptionInput} onRun={run} onPlayRange={playRange} canPlay={!!sourceReady && timelineMatches} onDirty={onPanelDirty} />}
        </section>
        <section id="tool-export" className="toolBody" aria-label="Export tools" hidden={activeTool !== "export"}>
          <button className="pipelineButton" aria-label="Export Malayalam subtitles" disabled={locked || !project.segments.length || dirtyIds.size > 0}
            onClick={() => { if (missing && !window.confirm("Some lines have no Malayalam translation. Export using English for those lines?")) return;
              void run({ stage: "export", revision_id: revisionId, allow_incomplete: missing }); }}>
            <span><strong>Export Malayalam subtitles</strong><small>Current saved timeline · SRT</small></span></button>
          <button className="pipelineButton" aria-label="Render dialogue preview" disabled={locked || !allSelected || dirtyIds.size > 0}
            onClick={() => run({ stage: "render_preview", revision_id: revisionId })}><span><strong>Render dialogue preview</strong><small>Selected takes · no original music/effects</small></span></button>
        <MixPanel key={`mix:${project.active_revision_id ?? "none"}`} project={project} disabled={locked || !timelineMatches} unsaved={dirtyIds.size > 0} onSaved={load} onRun={run} onDirty={onPanelDirty} />
        {voicePreview && <section className="dubPreview" aria-label="Dialogue-only preview"><h2>{voicePreview.metadata_json.demo ? "Demo-tone preview" : "Dialogue-only preview"}</h2>
          <p className="lineWarning">{previewStale ? "Saved preview uses earlier takes. Render again after selecting current audio." : "Original dialogue, music and effects are excluded from this preview."}</p>
          {voicePreview.access_blocked_reason ? <p className="lineWarning">{voicePreview.access_blocked_reason}</p>
            : <>{voicePreview.kind === "dub_preview" ? <video controls preload="metadata" src={`${API_URL}${voicePreview.content_url}`} />
              : <audio controls preload="metadata" src={`${API_URL}${voicePreview.content_url}`} />}
              <a className="smallButton" href={`${API_URL}${voicePreview.download_url}`}>Download dialogue preview</a></>}</section>}
          <ArtifactDownloads project={project} />
        </section>
        <section id="tool-project" className="toolBody" aria-label="Project tools" hidden={activeTool !== "project"}>
      <ProjectRail project={project} hardware={hardware} locked={locked} hasRevision={!!activeRevision}
        onChangeBudget={(value) => void jobAction(() => api.changeBudget(id, value))} onActivate={activate}
        onAddSpeaker={addSpeaker} onRename={rename} onResume={(jobId) => void jobAction(() => api.resumeJob(jobId))} />
          <details className="providerDetails"><summary>Provider status</summary>
        <div className="railSection"><p className="eyebrow">Providers</p>{capabilities.map((item) =>
          <div className="capability" key={item.capability}><span className={item.available ? "ready" : "missing"} />
            <div><strong>{item.selected_provider === "fake" && <DemoBadge />}{item.capability.replaceAll("_", " ")}</strong><small>{item.selected_provider} · {item.verified ? "Verified job" : item.available ? "Adapter available" : "Unavailable"}</small>
              {item.reason && <small>{item.reason}</small>}</div></div>)}</div>
          </details>
        </section>
      </aside>
      <section className="viewerPanel" aria-label="Source monitor">
        <div className="monitorHeading"><span>Source monitor</span><span>{project.assets.find((asset) => asset.id === sourceId)?.filename ?? "No source selected"}</span></div>
        <ScenePlayer artifacts={project.artifacts} sourceId={sourceId} mediaRef={mediaRef} onTime={onTime} stopAt={stopAt} onStop={onStop} />
        <div className="viewerFootnote"><span>English <ArrowRight size={12} /> Malayalam</span><span>Review before you render</span></div>
      </section>
      <section id="dialogue-inspector" className="dialogueInspector" aria-label="Dialogue inspector" hidden={!inspectorOpen}>
        <div className="inspectorHeading"><span>Dialogue inspector</span><button className="iconButton" aria-label="Close dialogue inspector" onClick={() => setInspectorOpen(false)}><X size={14} /></button></div>
        {!timelineMatches && <p className="lineWarning">The displayed timeline belongs to another source. Select its source or activate a matching revision to play individual lines.</p>}
        <div className="timelineHeader"><div><p className="eyebrow">Dialogue timeline</p><h1 ref={timelineHeading} tabIndex={-1}>{project.segments.length} reviewable lines</h1></div>
          <span className="provenanceTag">{activeRevision ? activeRevision.provider === "fake" ? "DEMO FIXTURE" : `${activeRevision.provider} · ${activeRevision.model}` : "No transcript yet"}</span></div>
        {activeJob && <div className="jobProgress"><LoaderCircle className="spin" /><strong>{activeJob.stage} · {activeJob.phase} · {Math.round(activeJob.progress * 100)}%</strong>
          <button className="smallButton" onClick={() => jobAction(() => api.cancelJob(activeJob.id))}>Cancel</button></div>}
        {activeRevision?.warnings_json.filter((warning) => warning !== "Some lines have no speaker assignment"
          || project.segments.some((line) => !line.speaker_id)).map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
        <ReviewQueue project={project} onGoTo={goToLine} />
        <div className="reviewFilters" role="group" aria-label="Filter dialogue">{["all", "untranslated", "edited", "approved", "warnings"].map((value) =>
          <button key={value} className={`smallButton ${filter === value ? "selected" : ""}`} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value}</button>)}</div>
        {dirtyIds.size > 1 && <div className="lineWarning" aria-label="Grouped dialogue save">
          <button className="smallButton" disabled={locked || dirtyIds.size > 100 || preservedDrafts.length > 0} onClick={saveGroupedDrafts}>Save all dialogue drafts together</button>
          <p>{dirtyIds.size} dialogue drafts, including filtered-out lines. All save or none save; other review forms are excluded. Limit: 100 lines.</p>
          {preservedDrafts.length > 0 && <p>Copy or discard removed-line drafts before grouped saving.</p>}
        </div>}
        <DialogueTimeline>{[...project.segments, ...preservedDrafts].map((line) => <DialogueLine key={line.id} segment={line} speakers={project.speakers} artifacts={project.artifacts}
          structureLocked={busy === "structure" || busy === "group-save" || remoteTimelineChanged}
          disabled={locked} onGenerate={(lineId) => run({ stage: "synthesize", revision_id: revisionId, segment_ids: [lineId], force_new: true })}
          active={!line.retired && timelineMatches && time >= line.start_ms && time < line.end_ms} hidden={!line.retired && hidden(line)} canPlay={!line.retired && !!sourceReady && timelineMatches}
          onPlay={playLine} onSaved={load} onDirty={onDirty} onGroupedDraft={onGroupedDraft}
          onTimingEditor={onTimingEditor} onTimingDraft={onTimingDraft} onRegenerate={(lineId) => {
            if (window.confirm("Generate a new translation for this saved line? It will need review again."))
              void run({ stage: "translate", revision_id: revisionId, segment_ids: [lineId], regenerate: true });
          }} />)}
          {!project.segments.length && <div className="timelineEmpty"><strong>{activeRevision ? "No speech detected" : "Your dialogue will appear here"}</strong>
            <span>{activeRevision ? "Try a clearer source or retranscribe into a new revision." : "Import a scene, wait for preparation, then transcribe it."}</span></div>}</DialogueTimeline>
        {project.active_revision_id && <GroupHistoryPanel key={`group-history:${project.active_revision_id}`} project={project}
          disabled={locked} unsaved={dirtyIds.size > 0 || structureDirty || panelDraftIds.size > 0 || referenceDirty}
          onApply={structureAction} />}
        {project.active_revision_id && <StructurePanel key={`structure:${project.active_revision_id}`} project={project}
          disabled={locked} unsaved={dirtyIds.size > 0} onApply={structureAction} onDirty={setStructureDirty}
          onPlayRange={playRange} canPlay={!!sourceReady && timelineMatches} editorRef={structureEditor} />}
      </section>
      <section id="timeline-workspace" className="timelineDock" aria-label="Timeline workspace">
        {timelineMatches && <TimelineView project={project} sourceId={sourceId} mediaRef={mediaRef}
          drafts={timingDrafts} editors={timingEditors} disabled={locked} onSeek={seek} onSelectLine={goToLine}
          selectedLineId={selectedLineId} onSplit={openStructure} collapsed={!timelineOpen} onToggle={() => setTimelineOpen(!timelineOpen)} />}
      </section>
    </WorkspaceLayout>
  </main>;
}
