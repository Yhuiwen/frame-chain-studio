import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.entities import (
    AssetStatus,
    AssetType,
    CharacterReferenceType,
    GenerationKind,
    GenerationMode,
    GenerationTaskStatus,
    GenerationTaskType,
    HumanVisualStatus,
    LocationReferenceType,
    BudgetPeriodType,
    ProviderAdapterType,
    ProviderModelGenerationType,
    PricingReviewStatus,
    ProviderVerificationStatus,
    ProviderVerificationType,
    ToApisVerificationStage,
    ProjectRenderStatus,
    QualityCheckSeverity,
    ReliableTaskStatus,
    ScriptBlockType,
    ScriptDocumentStatus,
    ScriptSourceType,
    ShotCharacterRole,
    ShotDraftStatus,
    ShotStatus,
    StartFrameSourceType,
    StoryboardDraftStatus,
    UnknownCostPolicy,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
    WorkerStatus,
    WorkerType,
    VisualAnalysisStatus,
    ProductionGateStatus,
    VisualReviewDecision,
)

PROVIDER_ID_MAX_LENGTH = 80
MODEL_MAX_LENGTH = 120
ASPECT_RATIO_PATTERN = re.compile(r"^[1-9][0-9]{0,2}:[1-9][0-9]{0,2}$")
SEED_MIN = 0
SEED_MAX = 2_147_483_647
DECIMAL_STRING_PATTERN = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]{1,8})?$")


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


class ProviderProfileBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    provider_key: str = Field(min_length=1, max_length=120)
    adapter_type: ProviderAdapterType = ProviderAdapterType.MAPPED_ASYNC_HTTP
    display_name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=4000)
    base_url: str = Field(default="", max_length=1000)
    secret_env_var: str = Field(default="", max_length=160)
    enabled: bool = True
    config: dict[str, object] = Field(default_factory=dict)


class ProviderProfileCreate(ProviderProfileBase):
    pass


class ProviderProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    display_name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    base_url: str | None = Field(default=None, max_length=1000)
    secret_env_var: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    config: dict[str, object] | None = None


class ProviderProfileRead(ProviderProfileBase):
    id: int
    config_revision: int
    secret_configured: bool = False
    configuration_valid: bool = False
    contract_verified: bool = False
    live_verified: bool = False
    live_orchestration_enabled: bool = False
    live_enabled_at: datetime | None = None
    contract_reviewed_at: datetime | None = None
    contract_reference: str | None = None
    preflight_checked_at: datetime | None = None
    preflight_image_model_accessible: bool = False
    preflight_video_model_accessible: bool = False
    preflight_response_schema_valid: bool = False
    account_balance_reviewed_at: datetime | None = None
    account_balance_sufficient: bool = False
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProviderModelProfileBase(BaseModel):
    model_key: str = Field(min_length=1, max_length=160)
    remote_model: str = Field(default="", max_length=160)
    display_name: str = Field(default="", max_length=160)
    generation_type: ProviderModelGenerationType
    enabled: bool = True
    capabilities: dict[str, object] = Field(default_factory=dict)
    limits: dict[str, object] = Field(default_factory=dict)
    pricing: dict[str, object] = Field(default_factory=dict)
    billing_unit: str = Field(default="USD", min_length=3, max_length=40)
    pricing_version: str = Field(default="", max_length=120)
    pricing_source: str = Field(default="", max_length=500)
    pricing_review_status: PricingReviewStatus = PricingReviewStatus.PENDING
    currency: str = Field(default="USD", min_length=3, max_length=12)


class ProviderModelProfileCreate(ProviderModelProfileBase):
    pass


class ProviderModelProfileUpdate(BaseModel):
    remote_model: str | None = Field(default=None, max_length=160)
    display_name: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    capabilities: dict[str, object] | None = None
    limits: dict[str, object] | None = None
    pricing: dict[str, object] | None = None
    billing_unit: str | None = Field(default=None, min_length=3, max_length=40)
    pricing_version: str | None = Field(default=None, max_length=120)
    pricing_source: str | None = Field(default=None, max_length=500)
    currency: str | None = Field(default=None, min_length=3, max_length=12)


class ProviderModelProfileRead(ProviderModelProfileBase):
    id: int
    provider_profile_id: int
    pricing_effective_at: datetime | None = None
    pricing_reviewed_at: datetime | None = None
    pricing_reviewed_by: str | None = None
    pricing_snapshot_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProviderValidationRead(BaseModel):
    provider_profile_id: int
    configuration_valid: bool
    secret_configured: bool
    contract_verified: bool
    live_verified: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GenerationUsageRecordRead(BaseModel):
    id: int
    project_id: int
    shot_id: int | None
    generation_request_id: int | None
    generation_task_id: int | None
    provider_profile_id: int | None
    provider_model_profile_id: int | None
    attempt_number: int
    record_type: UsageRecordType
    status: UsageRecordStatus
    currency: str
    billing_unit: str = "USD"
    estimated_units: dict[str, object]
    actual_units: dict[str, object]
    estimated_cost: str | None
    actual_cost: str | None
    cost_source: UsageCostSource
    provider_usage: dict[str, object]
    created_at: datetime
    updated_at: datetime


class UsageSummaryRead(BaseModel):
    currencies: list[dict[str, object]]
    unknown_cost_count: int
    pending_estimate_total: dict[str, str]
    request_count: int
    image_request_count: int
    video_request_count: int
    failed_request_count: int
    cancelled_request_count: int
    provider_breakdown: list[dict[str, object]]
    model_breakdown: list[dict[str, object]]
    period_start: datetime | None = None
    period_end: datetime | None = None


class ProjectBudgetPolicyRead(BaseModel):
    id: int | None = None
    project_id: int
    currency: str = "USD"
    billing_unit: str = "USD"
    warning_limit: str | None = None
    hard_limit: str | None = None
    per_request_limit: str | None = None
    period_type: BudgetPeriodType = BudgetPeriodType.PROJECT_TOTAL
    unknown_cost_policy: UnknownCostPolicy = UnknownCostPolicy.ALLOW_WITH_WARNING
    enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectBudgetPolicyUpdate(BaseModel):
    currency: str = Field(default="USD", min_length=3, max_length=12)
    billing_unit: str = Field(default="USD", min_length=3, max_length=40)
    warning_limit: str | None = None
    hard_limit: str | None = None
    per_request_limit: str | None = None
    period_type: BudgetPeriodType = BudgetPeriodType.PROJECT_TOTAL
    unknown_cost_policy: UnknownCostPolicy = UnknownCostPolicy.ALLOW_WITH_WARNING
    enabled: bool = False

    @field_validator("warning_limit", "hard_limit", "per_request_limit")
    @classmethod
    def validate_decimal_string(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not DECIMAL_STRING_PATTERN.fullmatch(value):
            raise ValueError("Use a non-negative decimal string with at most 8 decimal places.")
        return value


class ProviderVerificationRunRead(BaseModel):
    id: int
    provider_profile_id: int
    model_profile_id: int | None
    verification_type: ProviderVerificationType
    status: ProviderVerificationStatus
    started_at: datetime | None
    completed_at: datetime | None
    max_cost: str | None
    actual_cost: str | None
    workflow_version: str
    current_stage: str
    verification_project_id: int | None
    shot_1_id: int | None
    shot_2_id: int | None
    initial_anchor_asset_id: int | None
    end_frame_asset_id: int | None
    tail_frame_asset_id: int | None
    shot_1_keyframe_request_id: int | None
    shot_1_video_request_id: int | None
    shot_2_keyframe_request_id: int | None
    shot_2_video_request_id: int | None
    render_id: int | None
    final_render_asset_id: int | None
    pricing_snapshot_hash: str | None
    billing_unit: str | None
    estimated_billing_units: str | None
    reserved_billing_units: str | None
    auto_approve_for_verification: bool
    canary_image_only: bool
    failure_stage: str | None
    failure_code: str | None
    state_version: int
    recovery_of_run_id: int | None = None
    lineage_root_run_id: int | None = None
    normalized_start_asset_id: int | None = None
    normalized_end_asset_id: int | None = None
    reused_keyframe_asset_id: int | None = None
    historical_image_submits: int = 0
    historical_video_submits: int = 0
    remaining_image_submit_limit: int | None = None
    remaining_video_submit_limit: int | None = None
    historical_billing_units: str | None = None
    estimated_remaining_billing_units: str | None = None
    estimated_lineage_billing_units: str | None = None
    maximum_lineage_billing_units: str | None = None
    recovery_plan_hash: str | None = None
    summary: dict[str, object]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    technical_status: str | None = None
    lineage_status: str | None = None
    automated_visual_status: str | None = None
    human_visual_status: str | None = None
    production_status: str | None = None
    production_ready: bool | None = None
    production_blockers: list[str] = Field(default_factory=list)
    selected_review_asset: dict[str, object] | None = None
    current_visual_review: dict[str, object] | None = None
    legacy_review_evidence: bool = False
    workflow_approval_only: bool = False


class LiveVerificationRequest(BaseModel):
    confirm_live: bool = False
    execute_paid: bool = False
    model_profile_id: int | None = None
    max_cost: str | None = None
    billing_unit: str | None = Field(default=None, max_length=40)
    max_billing_units: str | None = None
    pricing_snapshot_hash: str | None = Field(default=None, min_length=64, max_length=64)
    auto_approve_for_verification: bool = False
    canary_image_only: bool = False
    canary_video_first_last: bool = False


class ProviderVerificationAdvanceRead(BaseModel):
    run_id: int
    status: ProviderVerificationStatus
    stage: ToApisVerificationStage
    waiting_for: str | None = None
    project_id: int | None = None
    shot_ids: list[int] = Field(default_factory=list)
    request_ids: dict[str, int] = Field(default_factory=dict)
    render_id: int | None = None
    final_render_asset_id: int | None = None
    image_requests_created: int = 0
    video_requests_created: int = 0
    estimated_billing_units: str | None = None
    actual_billing_units: str | None = None
    can_advance: bool = False
    terminal: bool = False


class ToApisPricingReviewRequest(BaseModel):
    pricing_version: str
    image_price: Decimal = Field(gt=0)
    image_unit: str
    video_price: Decimal = Field(gt=0)
    video_unit: str
    billing_unit: str
    image_model: str
    video_model: str
    pricing_source_kind: str
    contract_reference: str = Field(min_length=1, max_length=500)
    acknowledged: bool = False


class ToApisLiveEnableRequest(BaseModel):
    acknowledged: bool = False
    pricing_snapshot_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class ToApisAccountBalanceRequest(BaseModel):
    acknowledged: bool = False
    sufficient: bool = False
    note: str = Field(default="", max_length=500)
    evidence_type: str = Field(default="", max_length=80)
    pricing_snapshot_hash: str | None = Field(default=None, min_length=64, max_length=64)
    confirmed_billing_units: str | None = Field(default=None, max_length=80)


class ToApisCanaryRecoveryRequest(BaseModel):
    existing_remote_task_id: str = Field(min_length=1, max_length=160)
    existing_result_url: str = Field(min_length=10, max_length=4000)
    acknowledge_existing_task_recovery: bool = False


class ToApisVideoCanaryConsoleReviewRequest(BaseModel):
    acknowledged: bool = False
    existing_remote_task_id: str = Field(min_length=1, max_length=160)
    actual_billing_units: Decimal = Field(gt=0)
    billing_unit: str = Field(max_length=40)
    evidence_type: str = Field(max_length=80)


class ToApisFailedRunRecoveryRequest(BaseModel):
    acknowledged: bool = False
    recovery_plan_hash: str = Field(min_length=64, max_length=64)
    billing_unit: str = Field(max_length=40)
    estimated_remaining_billing_units: Decimal = Field(gt=0)
    maximum_lineage_billing_units: Decimal = Field(gt=0)
    authorization_reference: str = Field(min_length=1, max_length=200)


class VisualContinuityAnalyzeRequest(BaseModel):
    video_asset_id: int
    start_anchor_asset_id: int | None = None
    target_keyframe_asset_id: int | None = None
    tail_frame_asset_id: int | None = None
    analysis_version: str = Field(default="visual-continuity-v1", max_length=80)


class VisualContinuityHumanReviewRequest(BaseModel):
    status: HumanVisualStatus
    rejection_reasons: list[str] = Field(default_factory=list, max_length=32)
    comment: str = Field(default="", max_length=2000)
    reviewer: str = Field(default="local-operator", min_length=1, max_length=160)
    expected_report_hash: str = Field(min_length=64, max_length=64)
    expected_updated_at: datetime


class VisualContinuityReportRead(BaseModel):
    id: int
    project_id: int
    shot_id: int | None
    video_asset_id: int
    start_anchor_asset_id: int | None
    target_keyframe_asset_id: int | None
    tail_frame_asset_id: int | None
    analysis_version: str
    config_hash: str
    report_hash: str
    technical_status: VisualAnalysisStatus
    automatic_visual_status: VisualAnalysisStatus
    human_visual_status: HumanVisualStatus
    overall_visual_status: VisualAnalysisStatus
    scene_cut_status: VisualAnalysisStatus
    anchor_match_status: VisualAnalysisStatus
    target_match_status: VisualAnalysisStatus
    camera_stability_status: VisualAnalysisStatus
    composition_drift_status: VisualAnalysisStatus
    subject_scale_drift_status: VisualAnalysisStatus
    style_drift_status: VisualAnalysisStatus
    cross_shot_seam_status: VisualAnalysisStatus
    production_gate_status: ProductionGateStatus
    metrics: dict[str, object]
    rejection_reasons: list[object]
    created_at: datetime
    updated_at: datetime


class VisualContinuityReviewEventRead(BaseModel):
    id: int
    report_id: int
    reviewer: str
    review_source: str
    status: HumanVisualStatus
    rejection_reasons: list[object]
    comment: str
    previous_production_gate_status: ProductionGateStatus
    resulting_production_gate_status: ProductionGateStatus
    report_hash: str
    reviewed_at: datetime


class ProviderVisualReviewCreateRequest(BaseModel):
    asset_id: int = Field(gt=0)
    decision: VisualReviewDecision
    reason_codes: list[str] = Field(default_factory=list, max_length=32)
    notes: str = Field(default="", max_length=2000)


class ProviderVisualReviewRead(BaseModel):
    id: int
    project_id: int
    provider_verification_run_id: int
    asset_id: int
    asset_sha256: str
    asset_url: str
    review_scope: str
    decision: VisualReviewDecision
    reason_codes: list[object]
    notes: str
    reviewer_source: str
    reviewer_reference: str | None
    reviewed_at: datetime
    created_at: datetime
    idempotency_key: str | None


class ProviderVisualReviewHistoryRead(BaseModel):
    current: ProviderVisualReviewRead | None
    history: list[ProviderVisualReviewRead]


class VisualRegenerationPlanRequest(BaseModel):
    project_id: int
    source_run_id: int
    strategy: str = Field(max_length=80)
    maximum_billing_units: Decimal = Field(default=Decimal("190"), gt=0)
    save_draft: bool = False
    ready_for_paid_execution: bool = False
    actual_billing_units: Decimal | None = None


class VisualRegenerationReviewRequest(BaseModel):
    decision: str = Field(max_length=20)
    expected_plan_hash: str = Field(min_length=64, max_length=64)
    review_comment: str = Field(default="", max_length=2000)
    acknowledged_visual_failures: bool
    acknowledged_estimated_cost: bool
    acknowledged_no_execution: bool


class VisualExperimentPlanRequest(BaseModel):
    project_id: int
    source_run_id: int
    candidate: str = Field(max_length=80)
    selected_baseline_asset_id: int | None = None
    save_draft: bool = False


class VisualBaselineDraftRequest(BaseModel):
    project_id: int
    source_asset_id: int
    source_run_id: int = 6


class VisualBaselineReviewRequest(BaseModel):
    expected_baseline_hash: str = Field(min_length=64, max_length=64)
    decision: str = Field(max_length=20)
    comment: str = Field(default="", max_length=2000)
    acknowledge_baseline_review: bool = False


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


class ScriptImportRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    text: str | None = Field(default=None, max_length=2_000_000)
    source_type: ScriptSourceType = ScriptSourceType.PASTED
    language: str = Field(default="", max_length=40)
    create_new_version: bool = False
    parent_document_id: int | None = None


class ScriptDocumentRead(BaseModel):
    id: int
    project_id: int
    title: str
    source_type: ScriptSourceType
    original_filename: str
    mime_type: str
    content_sha256: str
    language: str
    status: ScriptDocumentStatus
    version: int
    parent_document_id: int | None
    parse_revision: int
    block_count: int = 0
    storyboard_count: int = 0
    duplicate_of_id: int | None = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ScriptContentRead(BaseModel):
    id: int
    title: str
    raw_text: str
    content_sha256: str
    version: int


class ScriptParseRead(BaseModel):
    script: ScriptDocumentRead
    parser_version: str
    block_count: int
    warnings: list[str] = Field(default_factory=list)
    statistics: dict[str, object] = Field(default_factory=dict)


class ScriptBlockRead(BaseModel):
    id: int
    script_document_id: int
    parse_revision: int
    block_type: ScriptBlockType
    user_block_type: ScriptBlockType | None
    effective_block_type: ScriptBlockType
    sort_order: int
    source_start: int
    source_end: int
    source_text: str
    normalized_text: str
    user_normalized_text: str | None
    effective_text: str
    speaker: str
    metadata: dict[str, object] = Field(default_factory=dict)
    parse_confidence: float
    parse_warnings: list[str] = Field(default_factory=list)
    warnings_confirmed: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ScriptBlockUpdate(BaseModel):
    user_block_type: ScriptBlockType | None = None
    user_normalized_text: str | None = Field(default=None, max_length=4000)
    warnings_confirmed: bool | None = None


class StoryboardCreate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    default_style_profile_id: int | None = None


class StoryboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: StoryboardDraftStatus | None = None
    default_style_profile_id: int | None = None


class StoryboardRead(BaseModel):
    id: int
    project_id: int
    script_document_id: int
    name: str
    parser_version: str
    builder_version: str
    status: StoryboardDraftStatus
    default_style_profile_id: int | None
    shot_draft_count: int = 0
    applied_shot_count: int = 0
    created_at: datetime
    updated_at: datetime
    applied_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class ShotDraftCharacterInput(BaseModel):
    character_id: int | None = None
    character_name: str = Field(default="", max_length=160)
    role: ShotCharacterRole = ShotCharacterRole.SECONDARY
    action: str = Field(default="", max_length=2000)
    expression: str = Field(default="", max_length=1000)
    clothing: str = Field(default="", max_length=2000)
    position: str = Field(default="", max_length=1000)
    props: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)
    sort_order: int = 0


class ShotDraftRead(BaseModel):
    id: int
    storyboard_draft_id: int
    sort_order: int
    source_block_start_id: int | None
    source_block_end_id: int | None
    title: str
    summary: str
    action: str
    dialogue: str
    suggested_duration_seconds: float
    location_id: int | None
    location_name: str
    style_profile_id: int | None
    time_of_day: str
    weather: str
    shot_size: str
    camera_angle: str
    camera_movement: str
    composition: str
    lighting: str
    emotion: str
    props: list[str] = Field(default_factory=list)
    continuity_notes: str
    free_prompt: str
    negative_prompt: str
    status: ShotDraftStatus
    applied_shot_id: int | None
    characters: list[ShotDraftCharacterInput] = Field(default_factory=list)
    source_text: str = ""
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShotDraftUpdate(BaseModel):
    sort_order: int | None = None
    source_block_start_id: int | None = None
    source_block_end_id: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    summary: str | None = Field(default=None, max_length=4000)
    action: str | None = Field(default=None, max_length=4000)
    dialogue: str | None = Field(default=None, max_length=4000)
    suggested_duration_seconds: float | None = Field(default=None, ge=0.1, le=60)
    location_id: int | None = None
    location_name: str | None = Field(default=None, max_length=160)
    style_profile_id: int | None = None
    time_of_day: str | None = Field(default=None, max_length=120)
    weather: str | None = Field(default=None, max_length=120)
    shot_size: str | None = Field(default=None, max_length=120)
    camera_angle: str | None = Field(default=None, max_length=240)
    camera_movement: str | None = Field(default=None, max_length=1000)
    composition: str | None = Field(default=None, max_length=2000)
    lighting: str | None = Field(default=None, max_length=2000)
    emotion: str | None = Field(default=None, max_length=1000)
    props: list[str] | None = None
    continuity_notes: str | None = Field(default=None, max_length=4000)
    free_prompt: str | None = Field(default=None, max_length=4000)
    negative_prompt: str | None = Field(default=None, max_length=2000)
    status: ShotDraftStatus | None = None
    characters: list[ShotDraftCharacterInput] | None = None


class ShotDraftSplitRequest(BaseModel):
    split_after_block_id: int | None = None
    text_split_offset: int | None = None


class ShotDraftApplyRequest(BaseModel):
    insert_after_shot_id: int | None = None
    idempotency_key: str | None = Field(default=None, max_length=120)


class StoryboardApplyRequest(BaseModel):
    shot_draft_ids: list[int]
    insert_after_shot_id: int | None = None


class StoryboardApplyRead(BaseModel):
    storyboard: StoryboardRead
    applied_shot_ids: list[int]


class ShotDraftPreviewRead(BaseModel):
    shot_spec: dict[str, object]
    compiled_prompt: str
    compiled_negative_prompt: str
    structured_payload: dict[str, object]
    compiler_version: str
    reference_asset_ids: list[int]
    validation_warnings: list[str] = Field(default_factory=list)


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
