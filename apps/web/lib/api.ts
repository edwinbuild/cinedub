import type {
  CapabilityStatus,
  HardwareStatus,
  Job,
  ProjectDetail,
  ProjectSummary,
  Segment,
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
  startJob: (projectId: string, stage: string, provider?: string) =>
    request<Job>(`/projects/${projectId}/jobs`, {
      method: "POST",
      body: JSON.stringify({ stage, provider }),
    }),
  cancelJob: (jobId: string) => request<Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  updateSegment: (
    segment: Segment,
    changes: Partial<Pick<Segment, "translated_text" | "emotion_label" | "energy" | "pace" | "status">>,
  ) =>
    request<Segment>(`/segments/${segment.id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...changes, expected_version: segment.version }),
    }),
  capabilities: () => request<CapabilityStatus[]>("/capabilities"),
  diagnostics: () => request<HardwareStatus>("/diagnostics"),
};
