import type {
  CapabilityStatus,
  HardwareStatus,
  Job,
  ProjectDetail,
  ProjectSummary,
  Segment,
  JobRequest,
  JobEstimate,
  Speaker,
  VoiceChoice,
  StockVoiceAssignment,
  VoiceProfile,
  VoiceProfileCreate,
  ConsentRecord,
  StemSet,
  StemReview,
  MixRender,
  MixReview,
  AlignmentReport,
  AlignmentApply,
  TakePerformanceReport,
  DialogueBrief,
  DialogueBriefUpdate,
  DialogueReviewReport,
} from "@cinedub/contracts";

export const API_URL = process.env.NEXT_PUBLIC_CINEDUB_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: init?.body instanceof FormData
      ? init.headers
      : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
    } catch {
      // Keep the HTTP status when the body is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  projects: () => request<ProjectSummary[]>("/projects"),
  project: (id: string) => request<ProjectDetail>(`/projects/${id}`),
  createProject: (name: string) =>
    request<ProjectSummary>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, source_language: "en-IN", target_language: "ml-IN" }),
    }),
  upload: (projectId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request(`/projects/${projectId}/assets`, { method: "POST", body });
  },
  startJob: (projectId: string, payload: JobRequest) =>
    request<Job>(`/projects/${projectId}/jobs`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  estimateJob: (projectId: string, payload: JobRequest) =>
    request<JobEstimate>(`/projects/${projectId}/jobs/estimate`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  activateRevision: (projectId: string, revisionId: string, activeId: string | null) =>
    request<ProjectDetail>(`/projects/${projectId}/revisions/${revisionId}/activate`, {
      method: "POST", body: JSON.stringify({ expected_active_revision_id: activeId }),
    }),
  renameSpeaker: (id: string, displayName: string) =>
    request<Speaker>(`/speakers/${id}`, {
      method: "PATCH", body: JSON.stringify({ display_name: displayName }),
    }),
  createSpeaker: (projectId: string, revisionId: string, displayName: string) =>
    request<Speaker>(`/projects/${projectId}/speakers`, {
      method: "POST", body: JSON.stringify({ revision_id: revisionId, display_name: displayName }),
    }),
  resumeJob: (id: string) => request<Job>(`/jobs/${id}/resume`, { method: "POST" }),
  changeBudget: (id: string, budget: number) => request<ProjectDetail>(`/projects/${id}/budget`, {
    method: "PATCH", body: JSON.stringify({ budget_inr: budget }),
  }),
  stockVoices: (provider: "fake" | "sarvam") => request<VoiceChoice[]>(`/voices/stock?provider=${provider}`),
  assignStockVoice: (id: string, payload: StockVoiceAssignment) => request<VoiceProfile>(`/speakers/${id}/stock-voice`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  createVoiceProfile: (id: string, payload: VoiceProfileCreate) => request<VoiceProfile>(`/projects/${id}/voice-profiles`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  selectVoiceProfile: (speaker: Speaker, profileId: string) => request<Speaker>(`/speakers/${speaker.id}/voice-profile`, {
    method: "POST", body: JSON.stringify({ profile_id: profileId, expected_profile_id: speaker.voice_profile_id }),
  }),
  revokeVoiceProfile: (id: string, attestedBy: string) => request<VoiceProfile>(`/voice-profiles/${id}/revoke`, {
    method: "POST", body: JSON.stringify({ attested_by: attestedBy, note: "Revoked through the local editor" }),
  }),
  voiceConsentHistory: (id: string) => request<ConsentRecord[]>(`/voice-profiles/${id}/consent`),
  selectCandidate: (line: Segment, artifactId: string) => request<Segment>(`/segments/${line.id}/candidate`, {
    method: "POST", body: JSON.stringify({ artifact_id: artifactId, expected_version: line.version }),
  }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  updateSegment: (
    segment: Segment,
    changes: Partial<Pick<Segment, "source_text" | "translated_text" | "start_ms" | "end_ms" | "speaker_id" | "status">>,
  ) =>
    request<Segment>(`/segments/${segment.id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...changes, expected_version: segment.version }),
    }),
  capabilities: () => request<CapabilityStatus[]>("/capabilities"),
  diagnostics: () => request<HardwareStatus>("/diagnostics"),
  alignmentReport: (id: string) => request<AlignmentReport>(`/alignment-reports/${id}`),
  takeAnalysisReport: (id: string) => request<TakePerformanceReport>(`/take-analysis-reports/${id}`),
  saveDialogueBrief: (projectId: string, revisionId: string, payload: DialogueBriefUpdate) =>
    request<DialogueBrief>(`/projects/${projectId}/revisions/${revisionId}/dialogue-brief`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  dialogueReviewReport: (id: string) => request<DialogueReviewReport>(`/dialogue-review-reports/${id}`),
  applyAlignment: (id: string, payload: AlignmentApply) => request<Segment>(`/alignment-reports/${id}/apply`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  reviewStems: (id: string, payload: StemReview) => request<StemSet>(`/stem-sets/${id}/review`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  reviewMix: (id: string, payload: MixReview) => request<MixRender>(`/mixes/${id}/review`, {
    method: "POST", body: JSON.stringify(payload),
  }),
};
