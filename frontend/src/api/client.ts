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
}

export interface Asset {
  id: number;
  project_id: number;
  shot_id: number | null;
  type: "KEYFRAME" | "VIDEO" | "TAIL_FRAME" | "START_FRAME";
  path: string;
  mime_type: string;
  source_asset_id: number | null;
}

export interface GenerationRequest {
  id: number;
  project_id: number;
  shot_id: number;
  kind: "KEYFRAME" | "VIDEO" | "TAIL_FRAME";
  provider_name: string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskLog {
  id: number;
  request_id: number | null;
  shot_id: number | null;
  level: string;
  message: string;
  created_at: string;
}

export interface ProjectDetail extends Project {
  shots: Shot[];
  assets: Asset[];
  requests: GenerationRequest[];
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
};
