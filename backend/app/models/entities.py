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


class ProjectBase(SQLModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


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
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    sort_order: int = Field(default=0, index=True)
    status: ShotStatus = Field(default=ShotStatus.DRAFT, index=True)
    start_frame_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    project: Project | None = Relationship(back_populates="shots")


class Asset(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    type: AssetType = Field(index=True)
    path: str
    mime_type: str
    source_asset_id: int | None = Field(default=None, foreign_key="asset.id")
    created_at: datetime = Field(default_factory=utcnow)


class GenerationRequest(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int = Field(foreign_key="shot.id", index=True)
    kind: GenerationKind = Field(index=True)
    provider_name: str
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
    submitted_at: datetime | None = None
    last_polled_at: datetime | None = Field(default=None, index=True)
    next_poll_at: datetime | None = Field(default=None, index=True)
    poll_count: int = Field(default=0)
    attempt_number: int = Field(default=1)
    max_attempts: int = Field(default=3)
    retry_count: int = Field(default=0)
    next_retry_at: datetime | None = Field(default=None, index=True)
    last_retry_delay_seconds: float | None = None
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
