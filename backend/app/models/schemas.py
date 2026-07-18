from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.entities import (
    AssetType,
    GenerationKind,
    GenerationMode,
    ProjectRenderStatus,
    GenerationTaskStatus,
    GenerationTaskType,
    ReliableTaskStatus,
    ShotStatus,
    WorkerStatus,
    WorkerType,
)


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    image_provider_id: str | None = None
    video_provider_id: str | None = None
    image_model: str | None = None
    video_model: str | None = None
    default_aspect_ratio: str | None = "16:9"
    default_video_duration_seconds: float | None = None
    default_seed: int | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    image_provider_id: str | None = None
    video_provider_id: str | None = None
    image_model: str | None = None
    video_model: str | None = None
    default_aspect_ratio: str | None = None
    default_video_duration_seconds: float | None = None
    default_seed: int | None = None


class ProjectRead(ProjectCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShotCreate(BaseModel):
    title: str
    description: str = ""
    duration_seconds: float = 4.0
    prompt: str = ""
    negative_prompt: str = ""


class ShotUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_seconds: float | None = None
    prompt: str | None = None
    negative_prompt: str | None = None


class ShotAssetSummary(BaseModel):
    asset_id: int
    url: str
    source_type: str
    source_shot_id: int | None = None
    source_shot_title: str | None = None
    file_name: str
    created_at: datetime


class ShotActionState(BaseModel):
    can_generate_keyframe: bool
    can_generate_video: bool
    reasons: list[str] = []


class ShotRead(ShotCreate):
    id: int
    project_id: int
    sort_order: int
    status: ShotStatus
    start_frame_asset_id: int | None
    start_frame: ShotAssetSummary | None = None
    target_keyframe: ShotAssetSummary | None = None
    locked_tail_frame: ShotAssetSummary | None = None
    actions: ShotActionState | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ReorderShot(BaseModel):
    id: int
    sort_order: int


class AssetRead(BaseModel):
    id: int
    project_id: int
    shot_id: int | None
    type: AssetType
    url: str
    file_name: str
    mime_type: str
    source_asset_id: int | None
    sha256: str | None = None
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectCompletionRead(BaseModel):
    total_shots: int
    completed_shots: int
    missing_shot_ids: list[int]
    estimated_duration_seconds: float
    can_render: bool
    render_disabled_reason: str | None = None


class GenerationRequestRead(BaseModel):
    id: int
    project_id: int
    shot_id: int
    kind: GenerationKind
    provider_name: str
    effective_provider_id: str | None
    model: str | None
    generation_mode: GenerationMode | None
    aspect_ratio: str | None
    seed: int | None
    duration_seconds: float | None
    allow_capability_fallback: bool
    status: GenerationTaskStatus
    prompt_snapshot: str
    negative_prompt_snapshot: str
    input_asset_ids: str
    output_asset_ids: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GenerationTaskRead(BaseModel):
    id: int
    generation_request_id: int
    project_id: int
    shot_id: int
    task_type: GenerationTaskType
    provider_id: str
    status: ReliableTaskStatus
    remote_job_id: str | None
    remote_status: str | None
    remote_progress: float | None = None
    processing_stage: str | None = None
    processing_progress: float | None = None
    attempt_number: int
    retry_count: int
    max_attempts: int
    result_count: int = 0
    result_hosts: list[str] = []
    processing_status: str | None = None
    can_cancel: bool = False
    can_retry: bool = False
    retry_of_task_id: int | None = None
    root_task_id: int | None = None
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    submission_deadline_at: datetime | None = None
    job_deadline_at: datetime | None = None
    cancellation_deadline_at: datetime | None = None
    last_retry_delay_seconds: float | None = None
    result_retry_count: int = 0
    max_result_attempts: int = 3
    next_result_retry_at: datetime | None = None
    last_result_retry_delay_seconds: float | None = None
    next_retry_at: datetime | None
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    locked_by: str | None
    locked_until: datetime | None
    error_code: str | None
    error_message: str | None
    result_asset_id: int | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class GenerationStartRequest(BaseModel):
    provider_id: str | None = None
    model: str | None = None
    seed: int | None = None
    duration_seconds: float | None = None
    aspect_ratio: str | None = None
    allow_capability_fallback: bool = False


class WorkerHeartbeatRead(BaseModel):
    worker_id: str
    worker_type: WorkerType
    status: WorkerStatus
    online: bool
    started_at: datetime
    last_seen_at: datetime
    current_task_id: int | None
    processed_count: int
    last_error_code: str | None
    last_error_message: str | None


class WorkerTypeStatus(BaseModel):
    worker_type: WorkerType
    online_count: int
    total_count: int
    stale_after_seconds: int
    workers: list[WorkerHeartbeatRead]


class WorkersStatusRead(BaseModel):
    stale_after_seconds: int
    generation: WorkerTypeStatus
    result: WorkerTypeStatus
    render: WorkerTypeStatus


class TaskLogRead(BaseModel):
    id: int
    request_id: int | None
    task_id: int | None
    shot_id: int | None
    level: str
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TaskCancelRequest(BaseModel):
    reason: str = ""


class TaskRetryRequest(BaseModel):
    reason: str = ""


class ProjectRenderCreate(BaseModel):
    allow_partial_render: bool = False


class ProjectRenderRead(BaseModel):
    id: int
    project_id: int
    status: ProjectRenderStatus
    render_version: int
    requested_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    progress: float
    current_stage: str
    output_asset_id: int | None
    output_url: str | None = None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectDetail(ProjectRead):
    shots: list[ShotRead]
    assets: list[AssetRead]
    requests: list[GenerationRequestRead]
    tasks: list[GenerationTaskRead]
    renders: list[ProjectRenderRead] = []
    completion: ProjectCompletionRead
    logs: list[TaskLogRead]
