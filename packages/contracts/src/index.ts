export type LanguageCode = "en-IN" | "ml-IN";

export type ProjectStatus = "draft" | "processing" | "review" | "ready" | "failed";
export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type SegmentStatus = "draft" | "translated" | "voiced" | "approved" | "needs_review";

export interface ProjectSummary {
  id: string;
  name: string;
  source_language: LanguageCode;
  target_language: LanguageCode;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
}

export interface MediaAsset {
  id: string;
  project_id: string;
  kind: string;
  filename: string;
  media_type: string;
  duration_ms: number | null;
  created_at: string;
}

export interface Speaker {
  id: string;
  project_id: string;
  label: string;
  display_name: string;
}

export interface Segment {
  id: string;
  project_id: string;
  speaker_id: string | null;
  index: number;
  start_ms: number;
  end_ms: number;
  source_text: string;
  translated_text: string;
  status: SegmentStatus;
  emotion_label: string | null;
  emotion_confidence: number | null;
  energy: number | null;
  pace: number | null;
  version: number;
  updated_at: string;
}

export interface Job {
  id: string;
  project_id: string;
  stage: string;
  status: JobStatus;
  progress: number;
  provider: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: string;
  project_id: string;
  job_id: string | null;
  kind: string;
  filename: string;
  media_type: string;
  download_url: string;
  created_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  assets: MediaAsset[];
  speakers: Speaker[];
  segments: Segment[];
  jobs: Job[];
  artifacts: Artifact[];
}

export interface CapabilityStatus {
  capability: string;
  selected_provider: string;
  available: boolean;
  reason: string | null;
}

export interface HardwareStatus {
  gpu_detected: boolean;
  gpu_name: string | null;
  cuda_ready: boolean;
  gpu_error: string | null;
  memory_total_gib: number | null;
  memory_available_gib: number | null;
  storage_free_gib: number;
  ffmpeg_ready: boolean;
}
