from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.entities import (
    AssetType,
    GenerationKind,
    GenerationTaskStatus,
    GenerationTaskType,
    ReliableTaskStatus,
    ShotStatus,
)


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


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


class ShotRead(ShotCreate):
    id: int
    project_id: int
    sort_order: int
    status: ShotStatus
    start_frame_asset_id: int | None
    start_frame: ShotAssetSummary | None = None
    target_keyframe: ShotAssetSummary | None = None
    locked_tail_frame: ShotAssetSummary | None = None
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
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class GenerationRequestRead(BaseModel):
    id: int
    project_id: int
    shot_id: int
    kind: GenerationKind
    provider_name: str
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
    attempt_number: int
    retry_count: int
    max_attempts: int
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


class TaskLogRead(BaseModel):
    id: int
    request_id: int | None
    task_id: int | None
    shot_id: int | None
    level: str
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectDetail(ProjectRead):
    shots: list[ShotRead]
    assets: list[AssetRead]
    requests: list[GenerationRequestRead]
    tasks: list[GenerationTaskRead]
    logs: list[TaskLogRead]
