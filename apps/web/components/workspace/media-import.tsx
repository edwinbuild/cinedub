"use client";

import { Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

/** Picker and file drop share the same validated upload path. */
export function MediaImport({ disabled, uploading, onFile }: {
  disabled: boolean; uploading: boolean; onFile: (file: File) => Promise<void>;
}) {
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const depth = useRef(0);
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault(); depth.current = 0; setOver(false);
    if (disabled) return;
    const files = Array.from(event.dataTransfer.files);
    if (files.length !== 1) { setError("Import one scene at a time."); return; }
    setError(null); void onFile(files[0]);
  }
  return <div className={`mediaDropZone ${over && !disabled ? "dragOver" : ""}`} aria-label="Scene file drop zone"
    onDragEnter={(event) => { event.preventDefault(); depth.current++; if (!disabled) setOver(true); }}
    onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = disabled ? "none" : "copy"; }}
    onDragLeave={() => { depth.current--; if (depth.current <= 0) { depth.current = 0; setOver(false); } }} onDrop={drop}>
    <label className="mediaImport"><Upload size={24} aria-hidden="true" /><strong>{uploading ? "Importing scene…" : "Import media"}</strong>
      <span>Drop a video or audio file here</span><span className="importBrowse">or browse files</span><small>Up to 2 minutes per scene</small>
      <input aria-label="Import scene" type="file" accept=".mp4,.mov,.mkv,.webm,.wav,.mp3,.flac,.m4a" disabled={disabled}
        onChange={(event) => { const file = event.target.files?.[0]; event.target.value = "";
          if (file) { setError(null); void onFile(file); } }} />
    </label>
    {error && <p className="inlineError" role="alert">{error}</p>}
  </div>;
}
