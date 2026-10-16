"use client";

import type { CapabilityStatus, HardwareStatus, JobRequest, ProjectDetail, Segment } from "@cinedub/contracts";
import { ArrowLeft, Film, LoaderCircle, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { DialogueLine } from "@/components/dialogue-line";
import { DialogueTimeline } from "@/components/dialogue-timeline";
import { ScenePlayer } from "@/components/scene-player";
import { VoicePanel } from "@/components/voice-panel";
import { ClonePanel } from "@/components/clone-panel";
import { StemPanel } from "@/components/stem-panel";
import { MixPanel } from "@/components/mix-panel";
import { AlignmentPanel } from "@/components/alignment-panel";
import { PerformancePanel } from "@/components/performance-panel";
import { EmotionPanel } from "@/components/emotion-panel";
import { DialogueBriefPanel } from "@/components/dialogue-brief-panel";
import { DialogueAdaptationPanel } from "@/components/dialogue-adaptation-panel";
import { API_URL, api } from "@/lib/api";

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
  const [time, setTime] = useState(0);
  const [stopAt, setStopAt] = useState<number | null>(null);
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(() => new Set());
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const loadSequence = useRef(0);
  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    try { const detail = await api.project(id);
      if (sequence === loadSequence.current) { setProject(detail); setError(null); } }
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
  const hasJobs = project?.jobs.some((job) => ["queued", "running"].includes(job.status));
  useEffect(() => {
    if (!hasJobs) return;
    const timer = window.setInterval(load, 1500); return () => window.clearInterval(timer);
  }, [hasJobs, load]);
  useEffect(() => {
    if (!dirtyIds.size) return;
    function warn(event: BeforeUnloadEvent) { event.preventDefault(); event.returnValue = ""; }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyIds.size]);
  const onDirty = useCallback((lineId: string, dirty: boolean) => {
    setDirtyIds((ids) => { const next = new Set(ids); if (dirty) next.add(lineId); else next.delete(lineId); return next; });
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
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    try { setBusy("upload"); const result = await api.upload(id, file) as { id: string };
      setSelectedSource(result.id); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Upload failed"); }
    finally { setBusy(null); event.target.value = ""; }
  }
  async function activate(revisionId: string) {
    if (!project) return;
    if (dirtyIds.size && !window.confirm("Discard unsaved drafts and switch timeline? Saved revisions are preserved.")) return;
    try { setBusy("revision"); setProject(await api.activateRevision(id, revisionId, project.active_revision_id));
      setDirtyIds(new Set()); setSelectedSource(null); mediaRef.current?.pause(); setStopAt(null); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not switch timeline"); }
    finally { setBusy(null); }
  }
  async function jobAction(action: () => Promise<unknown>) {
    try { setBusy("job"); await action(); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Job action failed"); }
    finally { setBusy(null); }
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
  const locked = !!busy || !!activeJob;
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
    <header className="studioTopbar"><div className="studioIdentity">
      <Link href="/" className="iconButton" aria-label="Projects" onClick={(event) => {
        if (dirtyIds.size && !window.confirm("Leave this scene and discard unsaved drafts?")) event.preventDefault();
      }}><ArrowLeft size={17} /></Link><span className="brandMark"><Film size={17} /></span>
      <div><strong>{project.name}</strong><span>English → Malayalam · v0.2</span></div></div>
      <div className="studioStatus">{dirtyIds.size > 0 && <span>{dirtyIds.size} unsaved</span>}
        {activeJob ? activeJob.phase.replaceAll("_", " ") : project.status}
        <button className="iconButton" aria-label="Refresh project" onClick={load}><RefreshCw size={15} /></button></div></header>
    {error && <div className="errorBanner studioError" role="alert">{error}</div>}
    {notice && <div className="noticeBanner" role="status">{notice}</div>}
    <section className="studioGrid">
      <aside className="leftRail">
        <div className="panelTitle"><span>Scene media</span><label className="uploadButton"><Upload size={14} />
          {busy === "upload" ? "Uploading…" : "Import"}<input aria-label="Import scene" type="file" accept=".mp4,.mov,.mkv,.webm,.wav,.mp3,.flac,.m4a" onChange={upload} disabled={locked} /></label></div>
        <label className="fieldLabel">Source<select aria-label="Scene source" value={sourceId ?? ""} disabled={locked}
          onChange={(event) => { mediaRef.current?.pause(); setStopAt(null); setSelectedSource(event.target.value); }}>
          <option value="" disabled>Select a scene</option>{project.assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.filename}</option>)}</select></label>
        <div className="railSection"><p className="eyebrow">Process scene</p>
          <button className="pipelineButton" aria-label="Separate dialogue and background" disabled={locked || !sourceId || !separator?.available}
            onClick={() => run({ stage: "separate", source_asset_id: sourceId!, force_new: project.stem_sets.some((stems) => stems.source_asset_id === sourceId) })}>
            <span><strong>Separate dialogue & background</strong><small>Local CPU · three stems · review required</small></span></button>
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
          <button className="pipelineButton" aria-label="Export Malayalam subtitles" disabled={locked || !project.segments.length || dirtyIds.size > 0}
            onClick={() => { if (missing && !window.confirm("Some lines have no Malayalam translation. Export using English for those lines?")) return;
              void run({ stage: "export", revision_id: revisionId, allow_incomplete: missing }); }}>
            <span><strong>Export Malayalam subtitles</strong><small>Current saved timeline · SRT</small></span></button>
          <button className="pipelineButton" aria-label="Generate voice candidates" disabled={locked || !allApproved || !voiceCapability?.available || dirtyIds.size > 0}
            onClick={() => run({ stage: "synthesize", revision_id: revisionId })}><span><strong>Generate voice candidates</strong><small>{voiceCapability?.selected_provider === "fake" ? "Demo tones for approved lines" : "Selected voices · approved lines"}</small></span></button>
          <button className="pipelineButton" aria-label="Render dialogue preview" disabled={locked || !allSelected || dirtyIds.size > 0}
            onClick={() => run({ stage: "render_preview", revision_id: revisionId })}><span><strong>Render dialogue preview</strong><small>Selected takes · no original music/effects</small></span></button>
        </div>
        <div className="railSection"><p className="eyebrow">Providers</p>{capabilities.map((item) =>
          <div className="capability" key={item.capability}><span className={item.available ? "ready" : "missing"} />
            <div><strong>{item.capability.replaceAll("_", " ")}</strong><small>{item.selected_provider} · {item.verified ? "Verified job" : item.available ? "Adapter available" : "Unavailable"}</small>
              {item.reason && <small>{item.reason}</small>}</div></div>)}</div>
        <div className="railSection"><p className="eyebrow">Development demo</p><button className="pipelineButton" disabled={locked || !!project.revisions.length}
          onClick={() => run({ stage: "demo_pipeline", provider: "fake" })}><span><strong>Build demo timeline</strong><small>Four fixture lines; no AI calls</small></span></button></div>
        {voiceCapability && ["sarvam", "fake"].includes(voiceCapability.selected_provider) && <VoicePanel speakers={project.speakers}
          profiles={project.voice_profiles} provider={voiceCapability.selected_provider as "sarvam" | "fake"} disabled={locked} onSaved={load} />}
      </aside>
      <section className="timelinePanel">
        <ScenePlayer artifacts={project.artifacts} sourceId={sourceId} mediaRef={mediaRef} onTime={onTime} stopAt={stopAt} onStop={onStop} />
        <StemPanel project={project} sourceId={sourceId} disabled={locked} onSaved={load} />
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
          transcriptionInput={transcriptionInput} onRun={run} onPlayRange={playRange} canPlay={!!sourceReady && timelineMatches} />}
        <MixPanel project={project} disabled={locked || !timelineMatches} unsaved={dirtyIds.size > 0} onSaved={load} onRun={run} />
        {voicePreview && <section className="dubPreview" aria-label="Dialogue-only preview"><h2>{voicePreview.metadata_json.demo ? "Demo-tone preview" : "Dialogue-only preview"}</h2>
          <p className="lineWarning">{previewStale ? "Saved preview uses earlier takes. Render again after selecting current audio." : "Original dialogue, music and effects are excluded from this preview."}</p>
          {voicePreview.access_blocked_reason ? <p className="lineWarning">{voicePreview.access_blocked_reason}</p>
            : <>{voicePreview.kind === "dub_preview" ? <video controls preload="metadata" src={`${API_URL}${voicePreview.content_url}`} />
              : <audio controls preload="metadata" src={`${API_URL}${voicePreview.content_url}`} />}
              <a className="smallButton" href={`${API_URL}${voicePreview.download_url}`}>Download dialogue preview</a></>}</section>}
        {!timelineMatches && <p className="lineWarning">The displayed timeline belongs to another source. Select its source or activate a matching revision to play individual lines.</p>}
        <div className="timelineHeader"><div><p className="eyebrow">Dialogue timeline</p><h1>{project.segments.length} reviewable lines</h1></div>
          <span className="provenanceTag">{activeRevision ? activeRevision.provider === "fake" ? "DEMO FIXTURE" : `${activeRevision.provider} · ${activeRevision.model}` : "No transcript yet"}</span></div>
        {activeJob && <div className="jobProgress"><LoaderCircle className="spin" /><strong>{activeJob.stage} · {activeJob.phase}</strong>
          <button className="smallButton" onClick={() => jobAction(() => api.cancelJob(activeJob.id))}>Cancel</button></div>}
        {activeRevision?.warnings_json.filter((warning) => warning !== "Some lines have no speaker assignment"
          || project.segments.some((line) => !line.speaker_id)).map((warning) => <p className="lineWarning" key={warning}>{warning}</p>)}
        {cloneCapability && ["fake", "sarvam"].includes(cloneCapability.selected_provider) && <ClonePanel project={project}
          provider={cloneCapability.selected_provider as "fake" | "sarvam"} available={cloneCapability.available}
          disabled={locked} onSaved={load} onRun={run} />}
        <div className="reviewFilters" role="group" aria-label="Filter dialogue">{["all", "untranslated", "edited", "approved", "warnings"].map((value) =>
          <button key={value} className={`smallButton ${filter === value ? "selected" : ""}`} aria-pressed={filter === value} onClick={() => setFilter(value)}>{value}</button>)}</div>
        <DialogueTimeline>{project.segments.map((line) => <DialogueLine key={line.id} segment={line} speakers={project.speakers} artifacts={project.artifacts}
          disabled={locked} onGenerate={(lineId) => run({ stage: "synthesize", revision_id: revisionId, segment_ids: [lineId], force_new: true })}
          active={timelineMatches && time >= line.start_ms && time < line.end_ms} hidden={hidden(line)} canPlay={!!sourceReady && timelineMatches}
          onPlay={playLine} onSaved={load} onDirty={onDirty} onRegenerate={(lineId) => {
            if (window.confirm("Generate a new translation for this saved line? It will need review again."))
              void run({ stage: "translate", revision_id: revisionId, segment_ids: [lineId], regenerate: true });
          }} />)}
          {!project.segments.length && <div className="timelineEmpty"><strong>{activeRevision ? "No speech detected" : "Your dialogue will appear here"}</strong>
            <span>{activeRevision ? "Try a clearer source or retranscribe into a new revision." : "Import a scene, wait for preparation, then transcribe it."}</span></div>}</DialogueTimeline>
      </section>
      <aside className="rightRail"><div className="metricCard"><div><span>Review</span><strong>{project.segments.filter((line) => line.status === "approved").length}/{project.segments.length} approved</strong></div></div>
        <div className="metricCard"><div><span>Estimated processing budget</span><strong>₹{project.spent_estimate_inr.toFixed(2)} / ₹{project.budget_inr.toFixed(2)}</strong>
          <small>₹{project.reserved_inr.toFixed(2)} reserved · provider bill may differ</small>
          <button className="smallButton" onClick={() => { const value = window.prompt("Project processing budget in INR (estimate, not provider billing)", String(project.budget_inr));
            if (value !== null && Number.isFinite(Number(value)) && Number(value) > 0) void jobAction(() => api.changeBudget(id, Number(value)));
          }}>Change budget</button></div></div>
        <div className="metricCard hardwareCard"><div><span>Local hardware</span><strong>{hardware?.cuda_ready ? "Driver detected" : "GPU inference unavailable"}</strong>
          <small>v0.2 works without local AI models</small></div></div>
        <div className="inspectorSection"><p className="eyebrow">Timeline revisions</p>{project.revisions.map((revision, index) => <div className="revisionItem" key={revision.id}>
          <strong>{revision.provider === "fake" ? "Demo" : "Transcript"} · {project.revisions.length-index}</strong>
          <small>{new Date(revision.created_at).toLocaleString()}</small>
          <button className="smallButton" disabled={locked || revision.id === project.active_revision_id} onClick={() => activate(revision.id)}>
            {revision.id === project.active_revision_id ? "Active timeline" : "Use this timeline"}</button></div>)}</div>
        <div className="inspectorSection"><p className="eyebrow">Speakers</p>{activeRevision && <button className="smallButton" disabled={locked} onClick={addSpeaker}>Add speaker</button>}{project.speakers.map((speaker) => <button className="speakerRename" key={speaker.id}
          onClick={() => rename(speaker.id, speaker.display_name)} title="Rename speaker">{speaker.display_name}<small>Rename</small></button>)}</div>
        <div className="inspectorSection"><p className="eyebrow">Jobs</p>{project.jobs.slice(0, 8).map((job) => <div className="revisionItem" key={job.id}>
          <strong>{job.stage} · {job.status}</strong><small>{job.provider} · {job.phase}</small>
          {job.error_message && <p className="inlineError">{job.error_message}</p>}
          {job.warnings_json.map((warning) => <small key={warning}>{warning}</small>)}
          {job.status === "failed" && job.retryable && <button className="smallButton" disabled={locked}
            onClick={() => jobAction(() => api.resumeJob(job.id))}>Resume existing remote job</button>}</div>)}</div>
        <div className="inspectorSection"><p className="eyebrow">Downloads</p>{project.artifacts.filter((item) => ["subtitle", "raw_transcript", "translation_candidates", "dub_preview", "dialogue_mix"].includes(item.kind)).map((item) =>
          item.access_blocked_reason ? <div className="artifact" key={item.id}><strong>{item.filename}</strong><small>{item.access_blocked_reason}</small></div>
            : <a className="artifact" href={`${API_URL}${item.download_url}`} key={item.id}><span><strong>{item.filename}</strong><small>{item.kind.replaceAll("_", " ")} · {item.metadata_json.revision_id === project.active_revision_id ? "active timeline" : "other timeline"}</small></span></a>)}</div>
      </aside>
    </section>
  </main>;
}
