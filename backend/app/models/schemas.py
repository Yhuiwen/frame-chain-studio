import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.entities import (
    AssetStatus,
    AssetType,
    CharacterReferenceType,
    GenerationKind,
    GenerationMode,
    GenerationTaskStatus,
    GenerationTaskType,
    LocationReferenceType,
    ProjectRenderStatus,
    QualityCheckSeverity,
    ReliableTaskStatus,
    ShotCharacterRole,
    ShotStatus,
    StartFrameSourceType,
    WorkerStatus,
    WorkerType,
)

PROVIDER_ID_MAX_LENGTH = 80
MODEL_MAX_LENGTH = 120
ASPECT_RATIO_PATTERN = re.compile(r"^[1-9][0-9]{0,2}:[1-9][0-9]{0,2}$")
SEED_MIN = 0
SEED_MAX = 2_147_483_647


class ProjectSettingsValidationMixin(BaseModel):
    image_provider_id: str | None = Field(default=None, max_length=PROVIDER_ID_MAX_LENGTH)
    video_provider_id: str | None = Field(default=None, max_length=PROVIDER_ID_MAX_LENGTH)
    image_model: str | None = Field(default=None, max_length=MODEL_MAX_LENGTH)
    video_model: str | None = Field(default=None, max_length=MODEL_MAX_LENGTH)
    default_aspect_ratio: str | None = "16:9"
    default_video_duration_seconds: float | None = Field(default=None, gt=0, le=60)
    default_seed: int | None = Field(default=None, ge=SEED_MIN, le=SEED_MAX)

    @field_validator("default_aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not ASPECT_RATIO_PATTERN.fullmatch(value):
            raise ValueError("Aspect ratio must use WIDTH:HEIGHT, such as 16:9.")
        width, height = [int(part) for part in value.split(":", 1)]
        ratio = width / height
        if ratio < 0.1 or ratio > 10:
            raise ValueError("Aspect ratio is outside the supported range.")
        return value

class ProjectCreate(ProjectSettingsValidationMixin):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class ProjectUpdate(ProjectSettingsValidationMixin):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    default_aspect_ratio: str | None = None


class ProjectRead(ProjectCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class CharacterBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    appearance: str = Field(default="", max_length=4000)
    personality: str = Field(default="", max_length=2000)
    default_clothing: str = Field(default="", max_length=2000)
    default_props: list[str] = Field(default_factory=list)
    continuity_notes: str = Field(default="", max_length=4000)


class CharacterCreate(CharacterBase):
    pass


class CharacterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    appearance: str | None = Field(default=None, max_length=4000)
    personality: str | None = Field(default=None, max_length=2000)
    default_clothing: str | None = Field(default=None, max_length=2000)
    default_props: list[str] | None = None
    continuity_notes: str | None = Field(default=None, max_length=4000)


class CharacterRead(CharacterBase):
    id: int
    project_id: int
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0
    reference_count: int = 0
    primary_reference_asset_id: int | None = None
    model_config = ConfigDict(from_attributes=True)


class LocationBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    environment: str = Field(default="", max_length=2000)
    architecture: str = Field(default="", max_length=2000)
    time_of_day: str = Field(default="", max_length=120)
    weather: str = Field(default="", max_length=120)
    lighting: str = Field(default="", max_length=2000)
    continuity_notes: str = Field(default="", max_length=4000)


class LocationCreate(LocationBase):
    pass


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    environment: str | None = Field(default=None, max_length=2000)
    architecture: str | None = Field(default=None, max_length=2000)
    time_of_day: str | None = Field(default=None, max_length=120)
    weather: str | None = Field(default=None, max_length=120)
    lighting: str | None = Field(default=None, max_length=2000)
    continuity_notes: str | None = Field(default=None, max_length=4000)


class LocationRead(LocationBase):
    id: int
    project_id: int
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0
    reference_count: int = 0
    primary_reference_asset_id: int | None = None
    model_config = ConfigDict(from_attributes=True)


class StyleProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    positive_prompt: str = Field(default="", max_length=4000)
    negative_prompt: str = Field(default="", max_length=4000)
    color_palette: list[str] = Field(default_factory=list)
    rendering_style: str = Field(default="", max_length=1000)
    camera_language: str = Field(default="", max_length=1000)
    aspect_ratio: str | None = None
    fps: float | None = Field(default=None, gt=0)
    default_provider_options: dict[str, object] = Field(default_factory=dict)


class StyleProfileCreate(StyleProfileBase):
    pass


class StyleProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    positive_prompt: str | None = Field(default=None, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=4000)
    color_palette: list[str] | None = None
    rendering_style: str | None = Field(default=None, max_length=1000)
    camera_language: str | None = Field(default=None, max_length=1000)
    aspect_ratio: str | None = None
    fps: float | None = Field(default=None, gt=0)
    default_provider_options: dict[str, object] | None = None


class StyleProfileRead(StyleProfileBase):
    id: int
    project_id: int
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0
    model_config = ConfigDict(from_attributes=True)


class ReferenceCreate(BaseModel):
    asset_id: int
    reference_type: CharacterReferenceType | LocationReferenceType
    label: str = Field(default="", max_length=160)
    is_primary: bool = False
    sort_order: int = 0


class CharacterReferenceCreate(BaseModel):
    asset_id: int
    reference_type: CharacterReferenceType = CharacterReferenceType.OTHER
    label: str = Field(default="", max_length=160)
    is_primary: bool = False
    sort_order: int = 0


class CharacterReferenceRead(BaseModel):
    id: int
    character_id: int
    asset_id: int
    reference_type: CharacterReferenceType
    label: str
    is_primary: bool
    sort_order: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LocationReferenceCreate(BaseModel):
    asset_id: int
    reference_type: LocationReferenceType = LocationReferenceType.OTHER
    label: str = Field(default="", max_length=160)
    is_primary: bool = False
    sort_order: int = 0


class LocationReferenceRead(BaseModel):
    id: int
    location_id: int
    asset_id: int
    reference_type: LocationReferenceType
    label: str
    is_primary: bool
    sort_order: int
    created_at: datetime
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


class ShotRevisionRequest(BaseModel):
    reason: str = ""
    changes: dict[str, object] = Field(default_factory=dict)


class ShotRevisionRead(BaseModel):
    shot_id: int
    old_spec_revision: int
    new_spec_revision: int
    old_state: ShotStatus
    new_state: ShotStatus
    invalidated_asset_ids: list[int]
    affected_downstream_shot_ids: list[int]


class ShotStartFrameRequest(BaseModel):
    action: str
    asset_id: int | None = None


class ShotTargetKeyframeRequest(BaseModel):
    asset_id: int


class ShotCharacterInput(BaseModel):
    character_id: int
    role: ShotCharacterRole = ShotCharacterRole.SECONDARY
    sort_order: int = 0
    appearance_override: str = Field(default="", max_length=4000)
    clothing_override: str = Field(default="", max_length=2000)
    expression: str = Field(default="", max_length=1000)
    action: str = Field(default="", max_length=2000)
    position: str = Field(default="", max_length=1000)
    props: list[str] = Field(default_factory=list)
    continuity_notes: str = Field(default="", max_length=4000)
    reference_asset_ids: list[int] = Field(default_factory=list)


class ShotCharacterRead(ShotCharacterInput):
    id: int | None = None
    shot_spec_id: int | None = None
    name_snapshot: str = ""
    model_config = ConfigDict(from_attributes=True)


class ShotSpecBase(BaseModel):
    location_id: int | None = None
    style_profile_id: int | None = None
    summary: str = Field(default="", max_length=4000)
    action: str = Field(default="", max_length=4000)
    emotion: str = Field(default="", max_length=1000)
    composition: str = Field(default="", max_length=2000)
    shot_size: str = Field(default="", max_length=120)
    camera_angle: str = Field(default="", max_length=240)
    camera_movement: str = Field(default="", max_length=1000)
    lighting: str = Field(default="", max_length=2000)
    time_of_day: str = Field(default="", max_length=120)
    weather: str = Field(default="", max_length=120)
    dialogue: str = Field(default="", max_length=4000)
    continuity_notes: str = Field(default="", max_length=4000)
    props: list[str] = Field(default_factory=list)
    provider_overrides: dict[str, object] = Field(default_factory=dict)


class ShotSpecRevisionRequest(BaseModel):
    reason: str = ""
    changes: dict[str, object] = Field(default_factory=dict)
    characters: list[ShotCharacterInput] | None = None


class ShotSpecSyncRequest(BaseModel):
    sync_character_defaults: bool = True
    sync_location_defaults: bool = True
    sync_style_profile: bool = True
    reason: str = ""


class ShotSpecRead(ShotSpecBase):
    id: int
    shot_id: int
    revision: int
    compiled_prompt: str
    compiled_negative_prompt: str
    structured_payload_json: str
    structured_payload: dict[str, object] = Field(default_factory=dict)
    compiler_version: str
    created_at: datetime
    characters: list[ShotCharacterRead] = Field(default_factory=list)
    reference_asset_ids: list[int] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


class ShotAssetSummary(BaseModel):
    asset_id: int
    url: str
    source_type: str
    source_shot_id: int | None = None
    source_shot_title: str | None = None
    file_name: str
    status: AssetStatus | None = None
    revision: int | None = None
    created_at: datetime


class ShotActionState(BaseModel):
    can_generate_keyframe: bool
    can_generate_video: bool
    reasons: list[str] = Field(default_factory=list)


class ShotRead(ShotCreate):
    id: int
    project_id: int
    sort_order: int
    status: ShotStatus
    start_frame_asset_id: int | None
    spec_revision: int
    approved_keyframe_asset_id: int | None = None
    approved_video_asset_id: int | None = None
    locked_tail_frame_asset_id: int | None = None
    start_frame_source_type: StartFrameSourceType
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
    status: AssetStatus
    revision: int
    superseded_by_asset_id: int | None = None
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
    shot_spec_revision: int
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
    structured_payload_json: str
    compiler_version: str
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


class QualityCheckResultRead(BaseModel):
    id: int
    project_id: int
    shot_id: int | None
    asset_id: int | None
    reference_asset_id: int | None = None
    check_type: str
    severity: QualityCheckSeverity
    score: float | None
    threshold: float | None
    message: str
    details_json: str
    details: dict[str, object] = {}
    algorithm_version: str = "quality-v1"
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
    quality_checks: list[QualityCheckResultRead] = []
    completion: ProjectCompletionRead
    logs: list[TaskLogRead]
