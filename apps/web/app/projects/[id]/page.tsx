"use client";

import type { CapabilityStatus, HardwareStatus, ProjectDetail, Segment } from "@cinedub/contracts";
import {
  Activity, ArrowLeft, AudioWaveform, Check, ChevronRight, CircleAlert, CloudCog, Download,
  Film, Gauge, Languages, LoaderCircle, Mic2, Play, RefreshCw, Save, Upload,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ChangeEvent, useCallback, useEffect, useMemo, useState } from "react";
import { API_URL, api } from "@/lib/api";

function milliseconds(value: number) {
  const seconds = value / 1000;
  return `${Math.floor(seconds / 60).toString().padStart(2, "0")}:${(seconds % 60).toFixed(1).padStart(4, "0")}`;
}

function SegmentRow({ segment, speaker, onSaved }: { segment: Segment; speaker: string; onSaved: () => void }) {
  const [text, setText] = useState(segment.translated_text);
  const [status, setStatus] = useState(segment.status);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await api.updateSegment(segment, { translated_text: text, status });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="segmentRow">
      <div className="segmentMeta"><span className="segmentIndex">{String(segment.index + 1).padStart(2, "0")}</span><span>{milliseconds(segment.start_ms)} — {milliseconds(segment.end_ms)}</span></div>
      <div className="speakerChip"><Mic2 size={13} /> {speaker}</div>
      <div className="sourceLine">{segment.source_text}</div>
      <textarea value={text} onChange={(event) => setText(event.target.value)} aria-label={`Malayalam translation for segment ${segment.index + 1}`} />
      <div className="performance"><span>{segment.emotion_label ?? "unrated"}</span><span>Energy {Math.round((segment.energy ?? 0) * 100)}</span><span>Pace {(segment.pace ?? 1).toFixed(2)}×</span></div>
      <div className="segmentActions">
        <select value={status} onChange={(event) => setStatus(event.target.value as Segment["status"])} aria-label="Review state">
          <option value="translated">Translated</option><option value="needs_review">Needs review</option><option value="approved">Approved</option><option value="voiced">Voiced</option>
        </select>
        <button className="smallButton" onClick={save} disabled={saving || (text === segment.translated_text && status === segment.status)}>{saving ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />} Save</button>
      </div>
    </article>
  );
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityStatus[]>([]);
  const [hardware, setHardware] = useState<HardwareStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [detail, capabilityList, hardwareStatus] = await Promise.all([
        api.project(id),
        api.capabilities(),
        api.diagnostics(),
      ]);
      setProject(detail); setCapabilities(capabilityList); setHardware(hardwareStatus); setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not load project"); }
  }, [id]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    if (!project?.jobs.some((job) => job.status === "queued" || job.status === "running")) return;
    const timer = window.setInterval(load, 1200); return () => window.clearInterval(timer);
  }, [project?.jobs, load]);

  const speakers = useMemo(() => Object.fromEntries((project?.speakers ?? []).map((speaker) => [speaker.id, speaker.display_name])), [project?.speakers]);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    try { setBusy("upload"); await api.upload(id, file); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Upload failed"); }
    finally { setBusy(null); event.target.value = ""; }
  }

  async function run(stage: string, provider?: string) {
    try { setBusy(stage); await api.startJob(id, stage, provider); await load(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start job"); }
    finally { setBusy(null); }
  }

  if (!project) return <main className="loadingScreen"><LoaderCircle className="spin" />{error ?? "Opening dubbing room…"}</main>;
  const activeJob = project.jobs.find((job) => job.status === "running" || job.status === "queued");

  return (
    <main className="studioShell">
      <header className="studioTopbar">
        <div className="studioIdentity"><Link href="/" className="iconButton"><ArrowLeft size={17} /></Link><span className="brandMark"><Film size={17} /></span><div><strong>{project.name}</strong><span>English <ChevronRight size={10} /> Malayalam</span></div></div>
        <div className="studioStatus"><span className={`statusDot ${activeJob ? "active" : ""}`} />{activeJob ? `${activeJob.stage} ${Math.round(activeJob.progress * 100)}%` : project.status}<button className="iconButton" onClick={load}><RefreshCw size={15} /></button></div>
      </header>

      {error && <div className="errorBanner studioError"><CircleAlert size={16} />{error}</div>}
      <section className="studioGrid">
        <aside className="leftRail">
          <div className="panelTitle"><span>Scene media</span><label className="uploadButton"><Upload size={14} />{busy === "upload" ? "Uploading…" : "Import"}<input type="file" accept="video/*,audio/*" onChange={upload} disabled={busy === "upload"} /></label></div>
          <div className="previewStage">{project.assets.length ? <><Film size={34} /><strong>{project.assets[0].filename}</strong><span>{project.assets[0].duration_ms ? milliseconds(project.assets[0].duration_ms) : "Duration unavailable"}</span></> : <><Upload size={30} /><strong>No source imported</strong><span>You can still run the deterministic demo.</span></>}</div>
          <div className="railSection"><p className="eyebrow">Pipeline</p>
            <button className="pipelineButton" onClick={() => run("demo_pipeline", "fake")} disabled={!!busy}><Play size={15} /><span><strong>Build demo timeline</strong><small>Safe, deterministic fixture</small></span></button>
            <button className="pipelineButton" onClick={() => run("translate")} disabled={!project.segments.length || !!busy}><Languages size={15} /><span><strong>Translate dialogue</strong><small>Selected provider route</small></span></button>
            <button className="pipelineButton" onClick={() => run("synthesize", "fake")} disabled={!project.segments.length || !!busy}><AudioWaveform size={15} /><span><strong>Generate candidates</strong><small>Fake tones until voice consent</small></span></button>
            <button className="pipelineButton" onClick={() => run("export")} disabled={!project.segments.length || !!busy}><Download size={15} /><span><strong>Validate export</strong><small>SRT and reference artifact</small></span></button>
          </div>
          <div className="railSection"><p className="eyebrow">Providers</p>{capabilities.map((capability) => <div className="capability" key={capability.capability}><span className={capability.available ? "ready" : "missing"} /><div><strong>{capability.capability.replaceAll("_", " ")}</strong><small>{capability.selected_provider}{capability.reason ? ` · ${capability.reason}` : ""}</small></div></div>)}</div>
        </aside>

        <section className="timelinePanel">
          <div className="timelineHeader"><div><p className="eyebrow">Dialogue timeline</p><h1>{project.segments.length} reviewable lines</h1></div><div className="legend"><span><i className="source" /> Source</span><span><i className="target" /> Malayalam</span></div></div>
          {activeJob && <div className="jobProgress"><LoaderCircle className="spin" size={15} /><div><strong>{activeJob.stage.replaceAll("_", " ")}</strong><span style={{ width: `${Math.max(4, activeJob.progress * 100)}%` }} /></div><em>{Math.round(activeJob.progress * 100)}%</em></div>}
          <div className="waveformMock" aria-hidden="true">{Array.from({ length: 80 }, (_, index) => <i key={index} style={{ height: `${16 + ((index * 17) % 46)}%` }} />)}</div>
          <div className="segments">{project.segments.length ? project.segments.map((segment) => <SegmentRow key={segment.id} segment={segment} speaker={speakers[segment.speaker_id ?? ""] ?? "Unassigned"} onSaved={load} />) : <div className="timelineEmpty"><Activity size={30} /><strong>No timeline yet</strong><span>Import media, then connect a transcriber—or build the deterministic demo to inspect the workflow now.</span><button className="primaryButton" onClick={() => run("demo_pipeline", "fake")}>Build demo timeline <ChevronRight size={15} /></button></div>}</div>
        </section>

        <aside className="rightRail">
          <div className="metricCard"><Gauge size={18} /><div><span>Review status</span><strong>{project.segments.filter((segment) => segment.status === "approved").length}/{project.segments.length} approved</strong></div></div>
          <div className="metricCard hardwareCard"><CloudCog size={18} /><div><span>Local inference</span><strong>{hardware?.cuda_ready ? "GPU ready" : hardware?.gpu_detected ? "GPU driver blocked" : "CPU only"}</strong><small>{hardware?.gpu_name ?? "No NVIDIA GPU detected"}</small></div></div>
          <div className="inspectorSection"><p className="eyebrow">Speakers</p>{project.speakers.length ? project.speakers.map((speaker) => <div className="speakerItem" key={speaker.id}><span>{speaker.display_name.slice(0, 1)}</span><div><strong>{speaker.display_name}</strong><small>{speaker.label}</small></div></div>) : <p className="muted">Speakers appear after diarization.</p>}</div>
          <div className="inspectorSection"><p className="eyebrow">Jobs</p>{project.jobs.slice(0, 6).map((job) => <div className="jobItem" key={job.id}><span className={`jobIcon ${job.status}`}>{job.status === "completed" ? <Check size={12} /> : job.status === "failed" ? <CircleAlert size={12} /> : <LoaderCircle size={12} />}</span><div><strong>{job.stage.replaceAll("_", " ")}</strong><small>{job.provider} · {job.status}{job.error_message ? ` · ${job.error_message}` : ""}</small></div></div>)}</div>
          <div className="inspectorSection"><p className="eyebrow">Artifacts</p>{project.artifacts.length ? project.artifacts.map((artifact) => <a className="artifact" href={`${API_URL}${artifact.download_url}`} key={artifact.id}><CloudCog size={14} /><span><strong>{artifact.filename}</strong><small>{artifact.kind.replaceAll("_", " ")}</small></span><Download size={13} /></a>) : <p className="muted">Exports and generated dialogue appear here.</p>}</div>
        </aside>
      </section>
    </main>
  );
}
