from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ShotStatus(str, Enum):
    DRAFT = "DRAFT"
    KEYFRAME_GENERATING = "KEYFRAME_GENERATING"
    KEYFRAME_REVIEW = "KEYFRAME_REVIEW"
    KEYFRAME_APPROVED = "KEYFRAME_APPROVED"
    VIDEO_GENERATING = "VIDEO_GENERATING"
    VIDEO_REVIEW = "VIDEO_REVIEW"
    VIDEO_APPROVED = "VIDEO_APPROVED"
    TAIL_FRAME_LOCKED = "TAIL_FRAME_LOCKED"
    COMPLETED = "COMPLETED"


class AssetType(str, Enum):
    KEYFRAME = "KEYFRAME"
    VIDEO = "VIDEO"
    TAIL_FRAME = "TAIL_FRAME"
    START_FRAME = "START_FRAME"
    PROJECT_RENDER = "PROJECT_RENDER"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class StartFrameSourceType(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    INHERITED = "INHERITED"


class QualityCheckSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class GenerationKind(str, Enum):
    KEYFRAME = "KEYFRAME"
    VIDEO = "VIDEO"
    TAIL_FRAME = "TAIL_FRAME"


class GenerationTaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ReliableTaskStatus(str, Enum):
    QUEUED = "QUEUED"
    SUBMITTING = "SUBMITTING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    RESULT_READY = "RESULT_READY"
    PROCESSING_RESULT = "PROCESSING_RESULT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"


class GenerationTaskType(str, Enum):
    KEYFRAME_GENERATION = "KEYFRAME_GENERATION"
    VIDEO_GENERATION = "VIDEO_GENERATION"
    VIDEO_EXTENSION = "VIDEO_EXTENSION"
    IMAGE_CORRECTION = "IMAGE_CORRECTION"
    VIDEO_CORRECTION = "VIDEO_CORRECTION"


class TaskErrorCode(str, Enum):
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    REMOTE_SERVER_ERROR = "REMOTE_SERVER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    JOB_TIMEOUT = "JOB_TIMEOUT"
    INVALID_REMOTE_RESPONSE = "INVALID_REMOTE_RESPONSE"
    DOWNLOAD_ERROR = "DOWNLOAD_ERROR"
    MEDIA_VALIDATION_ERROR = "MEDIA_VALIDATION_ERROR"
    CANCELLED = "CANCELLED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class TaskCommandType(str, Enum):
    CANCEL = "CANCEL"
    MANUAL_RETRY = "MANUAL_RETRY"


class TaskCommandStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ResultMediaKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class GenerationTaskResultStatus(str, Enum):
    PENDING = "PENDING"
    DOWNLOADING = "DOWNLOADING"
    DOWNLOADED = "DOWNLOADED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    RETRY_WAIT = "RETRY_WAIT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class GenerationMode(str, Enum):
    TEXT_TO_IMAGE = "TEXT_TO_IMAGE"
    START_FRAME_ONLY = "START_FRAME_ONLY"
    FIRST_LAST_FRAME = "FIRST_LAST_FRAME"


class WorkerType(str, Enum):
    GENERATION = "GENERATION"
    RESULT = "RESULT"
    RENDER = "RENDER"


class WorkerStatus(str, Enum):
    STARTING = "STARTING"
    IDLE = "IDLE"
    BUSY = "BUSY"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class ProjectRenderStatus(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    NORMALIZING = "NORMALIZING"
    CONCATENATING = "CONCATENATING"
    VALIDATING = "VALIDATING"
    FINALIZING = "FINALIZING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProjectBase(SQLModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    image_provider_id: str | None = None
    video_provider_id: str | None = None
    image_model: str | None = None
    video_model: str | None = None
    default_aspect_ratio: str | None = "16:9"
    default_video_duration_seconds: float | None = None
    default_seed: int | None = None


class Project(ProjectBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    shots: list["Shot"] = Relationship(back_populates="project")


class ShotBase(SQLModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    duration_seconds: float = Field(default=4.0, ge=0.1, le=60)
    prompt: str = ""
    negative_prompt: str = ""


class Shot(ShotBase, table=True):
    __table_args__ = (UniqueConstraint("project_id", "sort_order", name="uq_shot_project_sort_order"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    sort_order: int = Field(default=0, index=True)
    status: ShotStatus = Field(default=ShotStatus.DRAFT, index=True)
    start_frame_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    spec_revision: int = Field(default=1, index=True)
    approved_keyframe_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    approved_video_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    locked_tail_frame_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    start_frame_source_type: StartFrameSourceType = Field(default=StartFrameSourceType.NONE, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    project: Project | None = Relationship(back_populates="shots")


class Asset(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "shot_id",
            "type",
            "revision",
            "sha256",
            name="uq_asset_project_shot_type_revision_sha256",
        ),
        Index("ix_asset_project_shot_type_revision_sha256", "project_id", "shot_id", "type", "revision", "sha256"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    type: AssetType = Field(index=True)
    status: AssetStatus = Field(default=AssetStatus.ACTIVE, index=True)
    revision: int = Field(default=1, index=True)
    superseded_by_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    path: str
    mime_type: str
    source_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    sha256: str | None = Field(default=None, index=True)
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    frame_count: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class GenerationRequest(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int = Field(foreign_key="shot.id", index=True)
    shot_spec_revision: int = Field(default=1, index=True)
    kind: GenerationKind = Field(index=True)
    provider_name: str
    effective_provider_id: str | None = Field(default=None, index=True)
    model: str | None = None
    generation_mode: GenerationMode | None = Field(default=None, index=True)
    aspect_ratio: str | None = None
    seed: int | None = None
    duration_seconds: float | None = None
    allow_capability_fallback: bool = Field(default=False)
    status: GenerationTaskStatus = Field(default=GenerationTaskStatus.PENDING, index=True)
    prompt_snapshot: str = ""
    negative_prompt_snapshot: str = ""
    input_asset_ids: str = ""
    output_asset_ids: str = ""
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class GenerationTask(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_generationtask_idempotency_key"),
        UniqueConstraint("provider_id", "remote_job_id", name="uq_generationtask_provider_remote_job"),
        CheckConstraint("attempt_number >= 1", name="ck_generationtask_attempt_number"),
        CheckConstraint("retry_count >= 0", name="ck_generationtask_retry_count"),
        CheckConstraint("max_attempts >= 1", name="ck_generationtask_max_attempts"),
        CheckConstraint(
            "retry_of_task_id IS NULL OR retry_of_task_id != id",
            name="ck_generationtask_no_self_retry",
        ),
        Index("ix_generationtask_status_next_retry", "status", "next_retry_at"),
        Index("ix_generationtask_status_next_poll", "status", "next_poll_at"),
        Index("ix_generationtask_status_locked_until", "status", "locked_until"),
        Index("ix_generationtask_status_submission_deadline", "status", "submission_deadline_at"),
        Index("ix_generationtask_status_job_deadline", "status", "job_deadline_at"),
        Index("ix_generationtask_status_cancellation_deadline", "status", "cancellation_deadline_at"),
        Index("ix_generationtask_project_created", "project_id", "created_at"),
        Index("ix_generationtask_shot_type_created", "shot_id", "task_type", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    generation_request_id: int = Field(foreign_key="generationrequest.id", index=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int = Field(foreign_key="shot.id", index=True)
    task_type: GenerationTaskType = Field(index=True)
    provider_id: str = Field(default="mock", index=True)
    status: ReliableTaskStatus = Field(default=ReliableTaskStatus.QUEUED, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    remote_job_id: str | None = Field(default=None, index=True)
    remote_status: str | None = None
    remote_progress: float | None = None
    processing_stage: str | None = None
    processing_progress: float | None = None
    submitted_at: datetime | None = None
    last_polled_at: datetime | None = Field(default=None, index=True)
    next_poll_at: datetime | None = Field(default=None, index=True)
    poll_count: int = Field(default=0)
    attempt_number: int = Field(default=1)
    max_attempts: int = Field(default=3)
    retry_count: int = Field(default=0)
    next_retry_at: datetime | None = Field(default=None, index=True)
    last_retry_delay_seconds: float | None = None
    result_retry_count: int = Field(default=0)
    max_result_attempts: int = Field(default=3)
    next_result_retry_at: datetime | None = Field(default=None, index=True)
    last_result_retry_delay_seconds: float | None = None
    submission_deadline_at: datetime | None = Field(default=None, index=True)
    job_deadline_at: datetime | None = Field(default=None, index=True)
    cancellation_deadline_at: datetime | None = Field(default=None, index=True)
    cancel_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    cancel_requested_by: str | None = None
    retry_of_task_id: int | None = Field(default=None, foreign_key="generationtask.id")
    root_task_id: int | None = Field(default=None, foreign_key="generationtask.id")
    request_payload_json: str = Field(default="{}")
    response_summary_json: str = Field(default="{}")
    result_urls_json: str = Field(default="[]")
    raw_result_urls_json: str = Field(default="[]")
    provider_config_snapshot_json: str = Field(default="{}")
    error_code: str | None = None
    error_message: str | None = None
    error_details_json: str = Field(default="{}")
    last_error_at: datetime | None = None
    locked_by: str | None = Field(default=None, index=True)
    locked_until: datetime | None = Field(default=None, index=True)
    lock_acquired_at: datetime | None = None
    lock_version: int = Field(default=0)
    idempotency_key: str = Field(index=True)
    result_asset_id: int | None = Field(default=None, foreign_key="asset.id")


class WorkerHeartbeat(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("worker_type", "worker_id", name="uq_workerheartbeat_type_id"),
        Index("ix_workerheartbeat_type_last_seen", "worker_type", "last_seen_at"),
        Index("ix_workerheartbeat_status_last_seen", "status", "last_seen_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    worker_id: str = Field(index=True)
    worker_type: WorkerType = Field(index=True)
    status: WorkerStatus = Field(default=WorkerStatus.STARTING, index=True)
    started_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow, index=True)
    current_task_id: int | None = Field(default=None, foreign_key="generationtask.id", index=True)
    processed_count: int = Field(default=0)
    last_error_code: str | None = None
    last_error_message: str | None = None
    metadata_json: str = Field(default="{}")


class ProviderAssetCache(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("provider_id", "asset_id", "asset_sha256", name="uq_providerassetcache_provider_asset_sha"),
        Index("ix_providerassetcache_provider_asset", "provider_id", "asset_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    provider_id: str = Field(index=True)
    asset_id: int = Field(foreign_key="asset.id", index=True)
    asset_sha256: str = Field(index=True)
    reference_kind: str
    reference_value: str = Field(repr=False)
    expires_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectRender(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_projectrender_idempotency_key"),
        Index("ix_projectrender_project_status", "project_id", "status"),
        Index("ix_projectrender_status_locked_until", "status", "locked_until"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    status: ProjectRenderStatus = Field(default=ProjectRenderStatus.QUEUED, index=True)
    render_version: int = Field(default=1, index=True)
    idempotency_key: str = Field(index=True)
    requested_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    locked_by: str | None = Field(default=None, index=True)
    locked_until: datetime | None = Field(default=None, index=True)
    lock_version: int = Field(default=0)
    input_manifest_json: str = Field(default="[]")
    settings_json: str = Field(default="{}")
    progress: float = Field(default=0)
    current_stage: str = ""
    output_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    temporary_relative_path: str | None = None
    final_relative_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_details_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class GenerationTaskResult(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("generation_task_id", "result_index", name="uq_taskresult_task_index"),
        UniqueConstraint("generation_task_id", "source_url_hash", name="uq_taskresult_task_url_hash"),
        Index("ix_taskresult_task_status", "generation_task_id", "status"),
        Index("ix_taskresult_status_next_retry", "status", "next_retry_at"),
        Index("ix_taskresult_source_url_hash", "source_url_hash"),
        Index("ix_taskresult_asset_id", "asset_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    generation_task_id: int = Field(foreign_key="generationtask.id", index=True)
    result_index: int
    source_url: str
    source_url_hash: str = Field(index=True)
    status: GenerationTaskResultStatus = Field(default=GenerationTaskResultStatus.PENDING, index=True)
    media_kind: ResultMediaKind | None = Field(default=None, index=True)
    expected_media_kind: ResultMediaKind = Field(index=True)
    is_primary: bool = Field(default=False, index=True)
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=3)
    next_retry_at: datetime | None = Field(default=None, index=True)
    download_started_at: datetime | None = None
    download_completed_at: datetime | None = None
    validation_completed_at: datetime | None = None
    finalized_at: datetime | None = None
    temporary_relative_path: str | None = None
    final_relative_path: str | None = None
    sha256: str | None = Field(default=None, index=True)
    file_size: int | None = None
    mime_type: str | None = None
    file_name: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    fps: float | None = None
    frame_count: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    asset_id: int | None = Field(default=None, foreign_key="asset.id", index=True)
    error_code: str | None = None
    error_message: str | None = None
    error_details_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QualityCheckResult(SQLModel, table=True):
    __table_args__ = (
        Index("ix_qualitycheck_project_shot_created", "project_id", "shot_id", "created_at"),
        Index("ix_qualitycheck_asset_type_created", "asset_id", "check_type", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    asset_id: int | None = Field(default=None, foreign_key="asset.id", index=True)
    reference_asset_id: int | None = Field(default=None, foreign_key="asset.id", index=True)
    check_type: str = Field(index=True)
    severity: QualityCheckSeverity = Field(default=QualityCheckSeverity.INFO, index=True)
    score: float | None = None
    threshold: float | None = None
    message: str
    details_json: str = Field(default="{}")
    algorithm_version: str = Field(default="quality-v1", index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class TaskCommand(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("command_type", "idempotency_key", name="uq_taskcommand_type_idempotency"),
        Index("ix_taskcommand_task_type_created", "task_id", "command_type", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="generationtask.id", index=True)
    command_type: TaskCommandType = Field(index=True)
    idempotency_key: str = Field(index=True)
    status: TaskCommandStatus = Field(default=TaskCommandStatus.PENDING, index=True)
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    result_task_id: int | None = Field(default=None, foreign_key="generationtask.id")
    error_code: str | None = None
    error_message: str | None = None


class TaskStateChange(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="generationtask.id", index=True)
    from_status: ReliableTaskStatus | None = None
    to_status: ReliableTaskStatus
    reason_code: str | None = None
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ShotStateChange(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    shot_id: int = Field(foreign_key="shot.id", index=True)
    from_status: ShotStatus | None = Field(default=None)
    to_status: ShotStatus
    reason: str
    created_at: datetime = Field(default_factory=utcnow)


class TaskLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    request_id: int | None = Field(default=None, foreign_key="generationrequest.id", index=True)
    task_id: int | None = Field(default=None, foreign_key="generationtask.id", index=True)
    shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    level: str = Field(default="INFO", max_length=16)
    message: str
    created_at: datetime = Field(default_factory=utcnow)
