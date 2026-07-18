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
  image_provider_id: string | null;
  video_provider_id: string | null;
  image_model: string | null;
  video_model: string | null;
  default_aspect_ratio: string | null;
  default_video_duration_seconds: number | null;
  default_seed: number | null;
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
  actions: ShotActionState | null;
}

export interface ShotActionState {
  can_generate_keyframe: boolean;
  can_generate_video: boolean;
  reasons: string[];
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
  type: "KEYFRAME" | "VIDEO" | "TAIL_FRAME" | "START_FRAME" | "PROJECT_RENDER";
  url: string;
  file_name: string;
  mime_type: string;
  source_asset_id: number | null;
  sha256: string | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  fps: number | null;
}

export interface GenerationRequest {
  id: number;
  project_id: number;
  shot_id: number;
  kind: "KEYFRAME" | "VIDEO" | "TAIL_FRAME";
  provider_name: string;
  effective_provider_id: string | null;
  model: string | null;
  generation_mode: "TEXT_TO_IMAGE" | "START_FRAME_ONLY" | "FIRST_LAST_FRAME" | null;
  aspect_ratio: string | null;
  seed: number | null;
  duration_seconds: number | null;
  allow_capability_fallback: boolean;
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
    | "PROCESSING_RESULT"
    | "SUCCEEDED"
    | "FAILED"
    | "CANCELLING"
    | "CANCELLED";
  remote_job_id: string | null;
  remote_status: string | null;
  remote_progress: number | null;
  processing_stage: string | null;
  processing_progress: number | null;
  attempt_number: number;
  retry_count: number;
  max_attempts: number;
  can_cancel: boolean;
  can_retry: boolean;
  retry_of_task_id: number | null;
  root_task_id: number | null;
  result_count: number;
  result_hosts: string[];
  processing_status: string | null;
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
  result_retry_count: number;
  max_result_attempts: number;
  next_result_retry_at: string | null;
  last_result_retry_delay_seconds: number | null;
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
  renders: ProjectRender[];
  completion: ProjectCompletion;
  logs: TaskLog[];
}

export interface ProjectCompletion {
  total_shots: number;
  completed_shots: number;
  missing_shot_ids: number[];
  estimated_duration_seconds: number;
  can_render: boolean;
  render_disabled_reason: string | null;
}

export interface ProjectRender {
  id: number;
  project_id: number;
  status: "QUEUED" | "PREPARING" | "NORMALIZING" | "CONCATENATING" | "VALIDATING" | "FINALIZING" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  render_version: number;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: number;
  current_stage: string;
  output_asset_id: number | null;
  output_url: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderCapabilities {
  provider_id: string;
  display_name: string;
  text_to_image: boolean;
  image_to_image: boolean;
  image_to_video: boolean;
  first_last_frame_video: boolean;
  video_extension: boolean;
  supports_seed: boolean;
  supports_cancel: boolean;
  supports_negative_prompt: boolean;
  max_reference_images: number;
  max_duration_seconds: number | null;
  supported_aspect_ratios: string[];
  supported_output_types: string[];
}

export interface ProviderDefaults {
  image_model: string | null;
  video_model: string | null;
  aspect_ratio: string | null;
  duration_seconds: number | null;
}

export interface ProviderInfo {
  provider_id: string;
  display_name: string;
  capabilities: ProviderCapabilities;
  configured: boolean;
  configuration_error: string | null;
  defaults: ProviderDefaults;
}

export interface GenerationStartOptions {
  provider_id?: string | null;
  model?: string | null;
  seed?: number | null;
  duration_seconds?: number | null;
  aspect_ratio?: string | null;
  allow_capability_fallback?: boolean;
}

export interface WorkerHeartbeat {
  worker_id: string;
  worker_type: "GENERATION" | "RESULT" | "RENDER";
  status: "STARTING" | "IDLE" | "BUSY" | "STOPPING" | "STOPPED" | "ERROR";
  online: boolean;
  started_at: string;
  last_seen_at: string;
  current_task_id: number | null;
  processed_count: number;
  last_error_code: string | null;
  last_error_message: string | null;
}

export interface WorkerTypeStatus {
  worker_type: "GENERATION" | "RESULT" | "RENDER";
  online_count: number;
  total_count: number;
  stale_after_seconds: number;
  workers: WorkerHeartbeat[];
}

export interface WorkersStatus {
  stale_after_seconds: number;
  generation: WorkerTypeStatus;
  result: WorkerTypeStatus;
  render: WorkerTypeStatus;
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
  listProviders: () => request<ProviderInfo[]>("/api/providers"),
  getWorkerStatus: () => request<WorkersStatus>("/api/workers/status"),
  listProjects: () => request<Project[]>("/api/projects"),
  createProject: (body: { name: string; description: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: number) => request<ProjectDetail>(`/api/projects/${id}`),
  updateProject: (id: number, body: Partial<Project>) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
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
  generateKeyframe: (shotId: number, body: GenerationStartOptions = {}) =>
    request<GenerationRequest>(`/api/shots/${shotId}/keyframe/generate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  approveKeyframe: (shotId: number) =>
    request<Shot>(`/api/shots/${shotId}/keyframe/approve`, { method: "POST" }),
  rejectKeyframe: (shotId: number) =>
    request<Shot>(`/api/shots/${shotId}/keyframe/reject`, { method: "POST" }),
  generateVideo: (shotId: number, body: GenerationStartOptions = {}) =>
    request<GenerationRequest>(`/api/shots/${shotId}/video/generate`, { method: "POST", body: JSON.stringify(body) }),
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
  createProjectRender: (projectId: number, idempotencyKey: string, body: { allow_partial_render?: boolean } = {}) =>
    request<ProjectRender>(`/api/projects/${projectId}/renders`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(body),
    }),
};
