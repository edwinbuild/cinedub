"use client";

import type { Artifact } from "@cinedub/contracts";
import { AudioLines, Clapperboard } from "lucide-react";
import { useEffect, useState, type RefObject } from "react";
import { API_URL } from "@/lib/api";

interface Waveform { duration_ms: number; peaks: number[] }

export function ScenePlayer({ artifacts, sourceId, mediaRef, onTime, stopAt, onStop }: {
  artifacts: Artifact[]; sourceId: string | null; mediaRef: RefObject<HTMLMediaElement | null>;
  onTime: (time: number) => void; stopAt: number | null; onStop: () => void;
}) {
  const [wave, setWave] = useState<Waveform | null>(null);
  const [time, setTime] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const relevant = artifacts.filter((item) => item.metadata_json.source_asset_id === sourceId);
  const video = relevant.find((item) => item.kind === "preview_proxy");
  const audio = relevant.find((item) => item.kind === "source_audio");
  const waveform = relevant.find((item) => item.kind === "waveform");
  const waveformUrl = waveform ? `${API_URL}${waveform.content_url}` : null;
  const media = video ?? audio;

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => { setWave(null); setTime(0); setError(null); onTime(0); }, 0);
    if (waveformUrl) fetch(waveformUrl, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error("Waveform unavailable"); return response.json(); })
      .then((value: Waveform) => setWave(value))
      .catch((cause: Error) => { if (cause.name !== "AbortError") setError(cause.message); });
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [waveformUrl, onTime]);

  function updateTime(element: HTMLMediaElement) {
    const milliseconds = Math.round(element.currentTime * 1000);
    setTime(milliseconds); onTime(milliseconds);
    if (stopAt !== null && milliseconds >= stopAt) { element.pause(); onStop(); }
  }

  const bins = wave ? Array.from({ length: Math.min(200, wave.peaks.length) }, (_, index) => {
    const first = Math.floor(index * wave.peaks.length / Math.min(200, wave.peaks.length));
    const last = Math.ceil((index + 1) * wave.peaks.length / Math.min(200, wave.peaks.length));
    return Math.max(...wave.peaks.slice(first, last));
  }) : [];

  return <div className="scenePlayer">
    {media ? video ? <video key={media.id} controls preload="metadata" src={`${API_URL}${media.content_url}`}
      ref={(element) => { mediaRef.current = element; }} onTimeUpdate={(event) => updateTime(event.currentTarget)}
      onSeeking={onStop} onError={() => setError("Video could not load. Check media preparation and the local API.")} />
      : <><div className="previewStage"><AudioLines size={44} aria-hidden="true" /><strong>Audio source</strong><span>Listen to your scene and follow the dialogue on the timeline.</span></div><audio key={media.id} controls preload="metadata" src={`${API_URL}${media.content_url}`}
        ref={(element) => { mediaRef.current = element; }} onTimeUpdate={(event) => updateTime(event.currentTarget)}
        onSeeking={onStop} onError={() => setError("Audio could not load. Check the local API.")} /></>
      : <div className="previewStage"><Clapperboard size={40} aria-hidden="true" /><strong>{sourceId ? "Preparing scene media…" : "Your scene takes centre stage"}</strong>
        <span>{sourceId ? "Audio, waveform and video proxy appear after preparation." : "Import a video or audio file from the Media panel to get started."}</span></div>}
    {wave && <div className="realWaveform">
      <svg viewBox="0 0 800 70" preserveAspectRatio="none" aria-hidden="true">
        {bins.map((peak, index) => <rect key={index} x={index * 800 / bins.length} y={35 - Math.max(1, peak * 33)}
          width={Math.max(1, 800 / bins.length - 1)} height={Math.max(2, peak * 66)} />)}
        <line x1={time / wave.duration_ms * 800} x2={time / wave.duration_ms * 800} y1="0" y2="70" />
      </svg>
      <input aria-label="Seek scene" type="range" min="0" max={wave.duration_ms} step="10" value={Math.min(time, wave.duration_ms)}
        onChange={(event) => { const value = Number(event.target.value); onStop();
          if (mediaRef.current) mediaRef.current.currentTime = value / 1000;
          setTime(value); onTime(value); }} />
      <small>{(time / 1000).toFixed(1)}s / {(wave.duration_ms / 1000).toFixed(1)}s</small>
    </div>}
    {error && <p className="inlineError" role="alert">{error}</p>}
  </div>;
}
