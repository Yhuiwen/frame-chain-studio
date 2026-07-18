from datetime import datetime, timezone
from enum import Enum

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
    shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    level: str = Field(default="INFO", max_length=16)
    message: str
    created_at: datetime = Field(default_factory=utcnow)
