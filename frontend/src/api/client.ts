export type ShotStatus =
  | "DRAFT"
  | "KEYFRAME_GENERATING"
  | "KEYFRAME_REVIEW"
  | "KEYFRAME_APPROVED"
  | "VIDEO_GENERATING"
  | "VIDEO_REVIEW"
  | "VIDEO_APPROVED"
  | "TAIL_FRAME_LOCKED"
  | "COMPLETED";

export interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface Shot {
  id: number;
  project_id: number;
  sort_order: number;
  title: string;
  description: string;
  duration_seconds: number;
  prompt: string;
  negative_prompt: string;
  status: ShotStatus;
  start_frame_asset_id: number | null;
  start_frame: ShotAssetSummary | null;
  target_keyframe: ShotAssetSummary | null;
  locked_tail_frame: ShotAssetSummary | null;
}

export interface ShotAssetSummary {
  asset_id: number;
  url: string;
  source_type: "inherited" | "manual" | "generated";
  source_shot_id: number | null;
  source_shot_title: string | null;
  file_name: string;
  created_at: string;
}

export interface Asset {
  id: number;
  project_id: number;
  shot_id: number | null;
  type: "KEYFRAME" | "VIDEO" | "TAIL_FRAME" | "START_FRAME";
  url: string;
  file_name: string;
  mime_type: string;
  source_asset_id: number | null;
}

export interface GenerationRequest {
  id: number;
  project_id: number;
  shot_id: number;
  kind: "KEYFRAME" | "VIDEO" | "TAIL_FRAME";
  provider_name: string;
  status: "QUEUED" | "SUBMITTING" | "GENERATING" | "PENDING" | "RUNNING" | "PROCESSING" | "SUCCEEDED" | "FAILED";
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface GenerationTask {
  id: number;
  generation_request_id: number;
  project_id: number;
  shot_id: number;
  task_type: string;
  provider_id: string;
  status:
    | "QUEUED"
    | "SUBMITTING"
    | "RUNNING"
    | "RETRY_WAIT"
    | "RESULT_READY"
    | "SUCCEEDED"
    | "FAILED"
    | "CANCELLING"
    | "CANCELLED";
  remote_job_id: string | null;
  remote_status: string | null;
  attempt_number: number;
  retry_count: number;
  max_attempts: number;
  can_cancel: boolean;
  can_retry: boolean;
  retry_of_task_id: number | null;
  root_task_id: number | null;
  result_urls?: Array<Record<string, unknown>>;
  next_retry_at: string | null;
  last_polled_at: string | null;
  next_poll_at: string | null;
  submission_deadline_at: string | null;
  job_deadline_at: string | null;
  cancellation_deadline_at: string | null;
  cancel_requested_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  last_retry_delay_seconds: number | null;
  locked_by: string | null;
  locked_until: string | null;
  error_code: string | null;
  error_message: string | null;
  result_asset_id: number | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface TaskLog {
  id: number;
  request_id: number | null;
  task_id: number | null;
  shot_id: number | null;
  level: string;
  message: string;
  created_at: string;
}

export interface ProjectDetail extends Project {
  shots: Shot[];
  assets: Asset[];
  requests: GenerationRequest[];
  tasks: GenerationTask[];
  logs: TaskLog[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    throw new Error(payload?.error?.message ?? `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (body: { name: string; description: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: number) => request<ProjectDetail>(`/api/projects/${id}`),
  createShot: (projectId: number, body: Partial<Shot>) =>
    request<Shot>(`/api/projects/${projectId}/shots`, { method: "POST", body: JSON.stringify(body) }),
  updateShot: (shotId: number, body: Partial<Shot>) =>
    request<Shot>(`/api/shots/${shotId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteShot: (shotId: number) => request<void>(`/api/shots/${shotId}`, { method: "DELETE" }),
  reorderShots: (projectId: number, shots: Shot[]) =>
    request<Shot[]>(`/api/projects/${projectId}/shots/reorder`, {
      method: "POST",
      body: JSON.stringify(shots.map((shot, index) => ({ id: shot.id, sort_order: index }))),
    }),
  generateKeyframe: (shotId: number) =>
    request<GenerationRequest>(`/api/shots/${shotId}/keyframe/generate`, { method: "POST" }),
  approveKeyframe: (shotId: number) =>
    request<Shot>(`/api/shots/${shotId}/keyframe/approve`, { method: "POST" }),
  rejectKeyframe: (shotId: number) =>
    request<Shot>(`/api/shots/${shotId}/keyframe/reject`, { method: "POST" }),
  generateVideo: (shotId: number) =>
    request<GenerationRequest>(`/api/shots/${shotId}/video/generate`, { method: "POST" }),
  approveVideo: (shotId: number) => request<Shot>(`/api/shots/${shotId}/video/approve`, { method: "POST" }),
  rejectVideo: (shotId: number) => request<Shot>(`/api/shots/${shotId}/video/reject`, { method: "POST" }),
  cancelTask: (taskId: number, reason: string, idempotencyKey: string) =>
    request<GenerationTask>(`/api/tasks/${taskId}/cancel`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ reason }),
    }),
  retryTask: (taskId: number, reason: string, idempotencyKey: string) =>
    request<GenerationTask>(`/api/tasks/${taskId}/retry`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ reason }),
    }),
};
