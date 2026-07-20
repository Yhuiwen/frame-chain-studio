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


class CharacterReferenceType(str, Enum):
    FACE = "FACE"
    FULL_BODY = "FULL_BODY"
    CLOTHING = "CLOTHING"
    POSE = "POSE"
    EXPRESSION = "EXPRESSION"
    OTHER = "OTHER"


class LocationReferenceType(str, Enum):
    WIDE = "WIDE"
    INTERIOR = "INTERIOR"
    EXTERIOR = "EXTERIOR"
    DETAIL = "DETAIL"
    LIGHTING = "LIGHTING"
    OTHER = "OTHER"


class ShotCharacterRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    BACKGROUND = "BACKGROUND"


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


class ScriptSourceType(str, Enum):
    PLAIN_TEXT = "PLAIN_TEXT"
    MARKDOWN = "MARKDOWN"
    FOUNTAIN = "FOUNTAIN"
    DOCX = "DOCX"
    PASTED = "PASTED"


class ScriptDocumentStatus(str, Enum):
    IMPORTED = "IMPORTED"
    PARSED = "PARSED"
    PARSE_WARNING = "PARSE_WARNING"
    ARCHIVED = "ARCHIVED"


class ScriptBlockType(str, Enum):
    SCENE_HEADING = "SCENE_HEADING"
    ACTION = "ACTION"
    DIALOGUE = "DIALOGUE"
    CHARACTER_CUE = "CHARACTER_CUE"
    PARENTHETICAL = "PARENTHETICAL"
    TRANSITION = "TRANSITION"
    COMMENT = "COMMENT"
    UNKNOWN = "UNKNOWN"


class StoryboardDraftStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"
    ARCHIVED = "ARCHIVED"


class ShotDraftStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SKIPPED = "SKIPPED"
    APPLIED = "APPLIED"


class ProviderAdapterType(str, Enum):
    FAKE = "FAKE"
    MAPPED_ASYNC_HTTP = "MAPPED_ASYNC_HTTP"
    TOAPIS = "TOAPIS"


class ProviderModelGenerationType(str, Enum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class UsageRecordType(str, Enum):
    ESTIMATE = "ESTIMATE"
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class UsageRecordStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"
    UNKNOWN = "UNKNOWN"
    WAIVED = "WAIVED"


class UsageCostSource(str, Enum):
    PRICING_RULE = "PRICING_RULE"
    PROVIDER_RESPONSE = "PROVIDER_RESPONSE"
    MANUAL = "MANUAL"
    FAKE_PROVIDER = "FAKE_PROVIDER"
    UNKNOWN = "UNKNOWN"


class BudgetPeriodType(str, Enum):
    PROJECT_TOTAL = "PROJECT_TOTAL"
    MONTHLY = "MONTHLY"


class UnknownCostPolicy(str, Enum):
    ALLOW_WITH_WARNING = "ALLOW_WITH_WARNING"
    BLOCK = "BLOCK"


class ProviderVerificationType(str, Enum):
    CONTRACT = "CONTRACT"
    LIVE_IMAGE = "LIVE_IMAGE"
    LIVE_VIDEO = "LIVE_VIDEO"
    LIVE_CHAIN = "LIVE_CHAIN"


class ProviderVerificationStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
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


class Character(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_character_project_name"),
        Index("ix_character_project_archived", "project_id", "archived_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    appearance: str = Field(default="", max_length=4000)
    personality: str = Field(default="", max_length=2000)
    default_clothing: str = Field(default="", max_length=2000)
    default_props_json: str = Field(default="[]")
    continuity_notes: str = Field(default="", max_length=4000)
    archived_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CharacterReference(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("character_id", "asset_id", "reference_type", name="uq_characterreference_character_asset_type"),
        Index("ix_characterreference_character_sort", "character_id", "sort_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    character_id: int = Field(foreign_key="character.id", index=True)
    asset_id: int = Field(foreign_key="asset.id", index=True)
    reference_type: CharacterReferenceType = Field(default=CharacterReferenceType.OTHER, index=True)
    label: str = Field(default="", max_length=160)
    is_primary: bool = Field(default=False, index=True)
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Location(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_location_project_name"),
        Index("ix_location_project_archived", "project_id", "archived_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    environment: str = Field(default="", max_length=2000)
    architecture: str = Field(default="", max_length=2000)
    time_of_day: str = Field(default="", max_length=120)
    weather: str = Field(default="", max_length=120)
    lighting: str = Field(default="", max_length=2000)
    continuity_notes: str = Field(default="", max_length=4000)
    archived_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class LocationReference(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("location_id", "asset_id", "reference_type", name="uq_locationreference_location_asset_type"),
        Index("ix_locationreference_location_sort", "location_id", "sort_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    location_id: int = Field(foreign_key="location.id", index=True)
    asset_id: int = Field(foreign_key="asset.id", index=True)
    reference_type: LocationReferenceType = Field(default=LocationReferenceType.OTHER, index=True)
    label: str = Field(default="", max_length=160)
    is_primary: bool = Field(default=False, index=True)
    sort_order: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class StyleProfile(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_styleprofile_project_name"),
        Index("ix_styleprofile_project_archived", "project_id", "archived_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    positive_prompt: str = Field(default="", max_length=4000)
    negative_prompt: str = Field(default="", max_length=4000)
    color_palette_json: str = Field(default="[]")
    rendering_style: str = Field(default="", max_length=1000)
    camera_language: str = Field(default="", max_length=1000)
    aspect_ratio: str | None = None
    fps: float | None = None
    default_provider_options_json: str = Field(default="{}")
    archived_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ShotSpec(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("shot_id", "revision", name="uq_shotspec_shot_revision"),
        Index("ix_shotspec_location_revision", "location_id", "revision"),
        Index("ix_shotspec_style_revision", "style_profile_id", "revision"),
    )

    id: int | None = Field(default=None, primary_key=True)
    shot_id: int = Field(foreign_key="shot.id", index=True)
    revision: int = Field(index=True)
    location_id: int | None = Field(default=None, foreign_key="location.id", index=True)
    style_profile_id: int | None = Field(default=None, foreign_key="styleprofile.id", index=True)
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
    props_json: str = Field(default="[]")
    provider_overrides_json: str = Field(default="{}")
    compiled_prompt: str = Field(default="", max_length=12000)
    compiled_negative_prompt: str = Field(default="", max_length=6000)
    structured_payload_json: str = Field(default="{}")
    compiler_version: str = Field(default="structured-continuity-v1", max_length=80, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class ShotCharacter(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("shot_spec_id", "character_id", name="uq_shotcharacter_spec_character"),
        Index("ix_shotcharacter_spec_sort", "shot_spec_id", "sort_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    shot_spec_id: int = Field(foreign_key="shotspec.id", index=True)
    character_id: int = Field(foreign_key="character.id", index=True)
    role: ShotCharacterRole = Field(default=ShotCharacterRole.SECONDARY, index=True)
    sort_order: int = Field(default=0, index=True)
    appearance_override: str = Field(default="", max_length=4000)
    clothing_override: str = Field(default="", max_length=2000)
    expression: str = Field(default="", max_length=1000)
    action: str = Field(default="", max_length=2000)
    position: str = Field(default="", max_length=1000)
    props_json: str = Field(default="[]")
    continuity_notes: str = Field(default="", max_length=4000)
    reference_asset_ids_json: str = Field(default="[]")


class ScriptDocument(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("project_id", "content_sha256", "version", name="uq_scriptdocument_project_sha_version"),
        Index("ix_scriptdocument_project_status", "project_id", "status"),
        Index("ix_scriptdocument_project_sha", "project_id", "content_sha256"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    title: str = Field(min_length=1, max_length=160)
    source_type: ScriptSourceType = Field(index=True)
    original_filename: str = Field(default="", max_length=260)
    mime_type: str = Field(default="", max_length=160)
    content_sha256: str = Field(index=True, max_length=64)
    raw_text: str
    language: str = Field(default="", max_length=40)
    status: ScriptDocumentStatus = Field(default=ScriptDocumentStatus.IMPORTED, index=True)
    version: int = Field(default=1, index=True)
    parent_document_id: int | None = Field(default=None, foreign_key="scriptdocument.id", index=True)
    parse_revision: int = Field(default=0, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ScriptBlock(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("script_document_id", "parse_revision", "sort_order", name="uq_scriptblock_doc_rev_order"),
        Index("ix_scriptblock_doc_rev_order", "script_document_id", "parse_revision", "sort_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    script_document_id: int = Field(foreign_key="scriptdocument.id", index=True)
    parse_revision: int = Field(default=1, index=True)
    block_type: ScriptBlockType = Field(index=True)
    user_block_type: ScriptBlockType | None = Field(default=None, index=True)
    sort_order: int = Field(index=True)
    source_start: int = Field(index=True)
    source_end: int = Field(index=True)
    source_text: str
    normalized_text: str = ""
    user_normalized_text: str | None = None
    speaker: str = Field(default="", max_length=160)
    metadata_json: str = Field(default="{}")
    parse_confidence: float = Field(default=0.5, ge=0, le=1)
    parse_warnings_json: str = Field(default="[]")
    warnings_confirmed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)


class StoryboardDraft(SQLModel, table=True):
    __table_args__ = (Index("ix_storyboarddraft_project_script", "project_id", "script_document_id"),)

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    script_document_id: int = Field(foreign_key="scriptdocument.id", index=True)
    name: str = Field(min_length=1, max_length=160)
    parser_version: str = Field(default="", max_length=120)
    builder_version: str = Field(default="", max_length=120)
    status: StoryboardDraftStatus = Field(default=StoryboardDraftStatus.DRAFT, index=True)
    default_style_profile_id: int | None = Field(default=None, foreign_key="styleprofile.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    applied_at: datetime | None = None


class ShotDraft(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("storyboard_draft_id", "applied_shot_id", name="uq_shotdraft_storyboard_applied_shot"),
        Index("ix_shotdraft_storyboard_order", "storyboard_draft_id", "sort_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    storyboard_draft_id: int = Field(foreign_key="storyboarddraft.id", index=True)
    sort_order: int = Field(index=True)
    source_block_start_id: int | None = Field(default=None, foreign_key="scriptblock.id", index=True)
    source_block_end_id: int | None = Field(default=None, foreign_key="scriptblock.id", index=True)
    title: str = Field(default="", max_length=160)
    summary: str = Field(default="", max_length=4000)
    action: str = Field(default="", max_length=4000)
    dialogue: str = Field(default="", max_length=4000)
    suggested_duration_seconds: float = Field(default=4.0, ge=0.1, le=60)
    location_id: int | None = Field(default=None, foreign_key="location.id", index=True)
    location_name: str = Field(default="", max_length=160)
    style_profile_id: int | None = Field(default=None, foreign_key="styleprofile.id", index=True)
    time_of_day: str = Field(default="", max_length=120)
    weather: str = Field(default="", max_length=120)
    shot_size: str = Field(default="", max_length=120)
    camera_angle: str = Field(default="", max_length=240)
    camera_movement: str = Field(default="", max_length=1000)
    composition: str = Field(default="", max_length=2000)
    lighting: str = Field(default="", max_length=2000)
    emotion: str = Field(default="", max_length=1000)
    props_json: str = Field(default="[]")
    continuity_notes: str = Field(default="", max_length=4000)
    free_prompt: str = Field(default="", max_length=4000)
    negative_prompt: str = Field(default="", max_length=2000)
    status: ShotDraftStatus = Field(default=ShotDraftStatus.DRAFT, index=True)
    applied_shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ShotDraftCharacter(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("shot_draft_id", "character_id", "character_name", name="uq_shotdraftcharacter_identity"),
        Index("ix_shotdraftcharacter_draft_sort", "shot_draft_id", "sort_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    shot_draft_id: int = Field(foreign_key="shotdraft.id", index=True)
    character_id: int | None = Field(default=None, foreign_key="character.id", index=True)
    character_name: str = Field(default="", max_length=160)
    role: ShotCharacterRole = Field(default=ShotCharacterRole.SECONDARY, index=True)
    action: str = Field(default="", max_length=2000)
    expression: str = Field(default="", max_length=1000)
    clothing: str = Field(default="", max_length=2000)
    position: str = Field(default="", max_length=1000)
    props_json: str = Field(default="[]")
    notes: str = Field(default="", max_length=4000)
    sort_order: int = Field(default=0, index=True)


class ProviderProfile(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("provider_key", name="uq_providerprofile_provider_key"),
        Index("ix_providerprofile_enabled_archived", "enabled", "archived_at"),
    )

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1, max_length=160)
    provider_key: str = Field(min_length=1, max_length=120, index=True)
    adapter_type: ProviderAdapterType = Field(index=True)
    display_name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=4000)
    base_url: str = Field(default="", max_length=1000)
    secret_env_var: str = Field(default="", max_length=160)
    enabled: bool = Field(default=True, index=True)
    archived_at: datetime | None = Field(default=None, index=True)
    config_json: str = Field(default="{}")
    config_revision: int = Field(default=1, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProviderModelProfile(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("provider_profile_id", "model_key", name="uq_providermodel_profile_model"),
        Index("ix_providermodel_profile_type", "provider_profile_id", "generation_type"),
    )

    id: int | None = Field(default=None, primary_key=True)
    provider_profile_id: int = Field(foreign_key="providerprofile.id", index=True)
    model_key: str = Field(min_length=1, max_length=160, index=True)
    remote_model: str = Field(default="", max_length=160)
    display_name: str = Field(default="", max_length=160)
    generation_type: ProviderModelGenerationType = Field(index=True)
    enabled: bool = Field(default=True, index=True)
    capabilities_json: str = Field(default="{}")
    limits_json: str = Field(default="{}")
    pricing_json: str = Field(default="{}")
    currency: str = Field(default="USD", max_length=12, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class GenerationUsageRecord(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generation_task_id",
            "attempt_number",
            "record_type",
            name="uq_usagerecord_task_attempt_type",
        ),
        Index("ix_usagerecord_project_created", "project_id", "created_at"),
        Index("ix_usagerecord_request_type", "generation_request_id", "record_type"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    shot_id: int | None = Field(default=None, foreign_key="shot.id", index=True)
    generation_request_id: int | None = Field(default=None, foreign_key="generationrequest.id", index=True)
    generation_task_id: int | None = Field(default=None, foreign_key="generationtask.id", index=True)
    provider_profile_id: int | None = Field(default=None, foreign_key="providerprofile.id", index=True)
    provider_model_profile_id: int | None = Field(default=None, foreign_key="providermodelprofile.id", index=True)
    attempt_number: int = Field(default=1, index=True)
    record_type: UsageRecordType = Field(index=True)
    status: UsageRecordStatus = Field(index=True)
    currency: str = Field(default="USD", max_length=12, index=True)
    estimated_units_json: str = Field(default="{}")
    actual_units_json: str = Field(default="{}")
    estimated_cost: str | None = Field(default=None, max_length=80)
    actual_cost: str | None = Field(default=None, max_length=80)
    cost_source: UsageCostSource = Field(default=UsageCostSource.UNKNOWN, index=True)
    provider_usage_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class ProjectBudgetPolicy(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("project_id", "period_type", name="uq_projectbudget_project_period"),
        Index("ix_projectbudget_project_enabled", "project_id", "enabled"),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="project.id", index=True)
    currency: str = Field(default="USD", max_length=12, index=True)
    warning_limit: str | None = Field(default=None, max_length=80)
    hard_limit: str | None = Field(default=None, max_length=80)
    per_request_limit: str | None = Field(default=None, max_length=80)
    period_type: BudgetPeriodType = Field(default=BudgetPeriodType.PROJECT_TOTAL, index=True)
    unknown_cost_policy: UnknownCostPolicy = Field(default=UnknownCostPolicy.ALLOW_WITH_WARNING, index=True)
    enabled: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProviderVerificationRun(SQLModel, table=True):
    __table_args__ = (Index("ix_providerverification_provider_created", "provider_profile_id", "created_at"),)

    id: int | None = Field(default=None, primary_key=True)
    provider_profile_id: int = Field(foreign_key="providerprofile.id", index=True)
    model_profile_id: int | None = Field(default=None, foreign_key="providermodelprofile.id", index=True)
    verification_type: ProviderVerificationType = Field(index=True)
    status: ProviderVerificationStatus = Field(default=ProviderVerificationStatus.PENDING, index=True)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    max_cost: str | None = Field(default=None, max_length=80)
    actual_cost: str | None = Field(default=None, max_length=80)
    summary_json: str = Field(default="{}")
    error_code: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=utcnow, index=True)


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
    structured_payload_json: str = Field(default="{}")
    compiler_version: str = Field(default="legacy-v1", index=True)
    provider_key: str | None = Field(default=None, index=True)
    provider_model_key: str | None = Field(default=None, index=True)
    provider_config_revision: int | None = Field(default=None, index=True)
    provider_capability_snapshot_json: str = Field(default="{}")
    pricing_snapshot_json: str = Field(default="{}")
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
