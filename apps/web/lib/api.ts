import type {
  CapabilityStatus,
  HardwareStatus,
  Job,
  ProjectDetail,
  ProjectSummary,
  Segment,
  SegmentBatchUpdate,
  SegmentBatchResult,
  EditGroupSummary,
  EditGroupHistory,
  EditGroupRestore,
  SegmentHistory,
  SegmentHistoryAction,
  SegmentSplit,
  SegmentMerge,
  TimelineStructureEdit,
  TimelineStructureRestore,
  JobRequest,
  JobEstimate,
  Speaker,
  SpeakerReuse,
  SpeakerReuseApply,
  SpeakerReusePreview,
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
  DialogueAdaptationReport,
  DialogueAdaptationApply,
  SpeechEmotionReport,
  SpeechEmotionReview,
  SpeechEmotionReviewRead,
  ArtifactLineage,
  Pipeline,
  PipelineContinue,
  PipelineCreate,
  PipelinePlan,
  ProjectDeletion,
  StorageUsage,
} from "@cinedub/contracts";

export const API_URL = process.env.NEXT_PUBLIC_CINEDUB_API_URL ?? "http://127.0.0.1:8000";

/** An HTTP failure with its status, so callers can tell conflicts from validation errors. */
export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); this.name = "ApiError"; }
}

/** A key per user action: a retried POST replays the first response instead of repeating work. */
function once(): HeadersInit {
  return { "Idempotency-Key": crypto.randomUUID() };
}

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
      message = typeof payload.detail === "string" ? payload.detail : message;
    } catch {
      // Keep the HTTP status when the body is not JSON.
    }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  editGroups: (projectId: string, revisionId: string) =>
    request<EditGroupSummary[]>(`/projects/${projectId}/edit-groups?revision_id=${encodeURIComponent(revisionId)}`),
  editGroup: (projectId: string, groupId: string) =>
    request<EditGroupHistory>(`/projects/${projectId}/edit-groups/${groupId}`),
  restoreEditGroup: (projectId: string, groupId: string, payload: EditGroupRestore) =>
    request<SegmentBatchResult>(`/projects/${projectId}/edit-groups/${groupId}/restore`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  updateSegments: (projectId: string, payload: SegmentBatchUpdate) =>
    request<SegmentBatchResult>(`/projects/${projectId}/segments`, {
      method: "PATCH", body: JSON.stringify(payload),
    }),
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
    return request(`/projects/${projectId}/assets`, { method: "POST", body, headers: once() });
  },
  startJob: (projectId: string, payload: JobRequest) =>
    request<Job>(`/projects/${projectId}/jobs`, {
      method: "POST",
      body: JSON.stringify(payload),
      headers: once(),
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
  earlierSpeakers: (id: string) => request<Speaker[]>(`/projects/${id}/earlier-speakers`),
  speakerReusePreview: (target: string, source: string, copy: boolean) => request<SpeakerReusePreview>(`/speakers/${target}/reuse/${source}?copy_stock_voice=${copy}`),
  reuseSpeaker: (target: string, payload: SpeakerReuseApply) => request<SpeakerReuse>(`/speakers/${target}/reuse`, { method: "POST", body: JSON.stringify(payload) }),
  speakerReuseHistory: (target: string) => request<SpeakerReuse[]>(`/speakers/${target}/reuse-history`),
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
  segmentHistory: (id: string) => request<SegmentHistory>(`/segments/${id}/history`),
  splitSegment: (id: string, payload: SegmentSplit) => request<TimelineStructureEdit>(`/segments/${id}/split`, { method: "POST", body: JSON.stringify(payload) }),
  mergeSegment: (id: string, payload: SegmentMerge) => request<TimelineStructureEdit>(`/segments/${id}/merge`, { method: "POST", body: JSON.stringify(payload) }),
  structureHistory: (projectId: string, revisionId: string) => request<TimelineStructureEdit[]>(`/projects/${projectId}/revisions/${revisionId}/structure-edits`),
  restoreStructure: (id: string, payload: TimelineStructureRestore) => request<TimelineStructureEdit>(`/timeline-structure-edits/${id}/restore`, { method: "POST", body: JSON.stringify(payload) }),
  restoreSegmentHistory: (id: string, payload: SegmentHistoryAction) => request<Segment>(`/segments/${id}/history`, { method: "POST", body: JSON.stringify(payload) }),
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
  speechEmotionReport: (id: string) => request<SpeechEmotionReport>(`/speech-emotion-reports/${id}`),
  reviewSpeechEmotion: (id: string, payload: SpeechEmotionReview) => request<SpeechEmotionReviewRead>(`/speech-emotion-reports/${id}/review`, { method: "POST", body: JSON.stringify(payload) }),
  saveDialogueBrief: (projectId: string, revisionId: string, payload: DialogueBriefUpdate) =>
    request<DialogueBrief>(`/projects/${projectId}/revisions/${revisionId}/dialogue-brief`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  dialogueReviewReport: (id: string) => request<DialogueReviewReport>(`/dialogue-review-reports/${id}`),
  dialogueAdaptationReport: (id: string) => request<DialogueAdaptationReport>(`/dialogue-adaptation-reports/${id}`),
  applyDialogueAdaptation: (id: string, payload: DialogueAdaptationApply) =>
    request<Segment>(`/dialogue-adaptation-reports/${id}/apply`, { method: "POST", body: JSON.stringify(payload) }),
  applyAlignment: (id: string, payload: AlignmentApply) => request<Segment>(`/alignment-reports/${id}/apply`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  reviewStems: (id: string, payload: StemReview) => request<StemSet>(`/stem-sets/${id}/review`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  reviewMix: (id: string, payload: MixReview) => request<MixRender>(`/mixes/${id}/review`, {
    method: "POST", body: JSON.stringify(payload), headers: once(),
  }),
  pipelinePlan: (projectId: string, payload: PipelineCreate) =>
    request<PipelinePlan>(`/projects/${projectId}/pipelines/plan`, { method: "POST", body: JSON.stringify(payload) }),
  startPipeline: (projectId: string, payload: PipelineCreate) =>
    request<Pipeline>(`/projects/${projectId}/pipelines`, { method: "POST", body: JSON.stringify(payload), headers: once() }),
  continuePipeline: (id: string, payload: PipelineContinue) =>
    request<Pipeline>(`/pipelines/${id}/continue`, { method: "POST", body: JSON.stringify(payload) }),
  cancelPipeline: (id: string) => request<Pipeline>(`/pipelines/${id}/cancel`, { method: "POST" }),
  lineage: (artifactId: string) => request<ArtifactLineage>(`/artifacts/${artifactId}/lineage`),
  deleteProject: (id: string, confirm: string) =>
    request<ProjectDeletion>(`/projects/${id}?confirm=${encodeURIComponent(confirm)}`, { method: "DELETE" }),
  storageUsage: () => request<StorageUsage>("/diagnostics/storage"),
};
