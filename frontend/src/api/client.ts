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
  archived_at?: string | null;
  archived_by_source?: string | null;
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
  spec_revision?: number;
  approved_keyframe_asset_id?: number | null;
  approved_video_asset_id?: number | null;
  locked_tail_frame_asset_id?: number | null;
  start_frame_source_type?: "NONE" | "MANUAL" | "INHERITED";
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
  source_type: "inherited" | "manual" | "generated" | "none";
  source_shot_id: number | null;
  source_shot_title: string | null;
  file_name: string;
  status?: Asset["status"] | null;
  revision?: number | null;
  created_at: string;
}

export interface Asset {
  id: number;
  project_id: number;
  shot_id: number | null;
  type: "KEYFRAME" | "VIDEO" | "TAIL_FRAME" | "START_FRAME" | "PROJECT_RENDER";
  status?: "ACTIVE" | "APPROVED" | "REJECTED" | "STALE" | "SUPERSEDED";
  revision?: number;
  superseded_by_asset_id?: number | null;
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

export type VisualStatus = "PENDING" | "PASSED" | "FAILED" | "INCONCLUSIVE";
export type HumanVisualStatus = "PENDING" | "APPROVED" | "REJECTED";

export interface VisualContinuityReport {
  id: number;
  project_id: number;
  shot_id: number | null;
  video_asset_id: number;
  start_anchor_asset_id: number | null;
  target_keyframe_asset_id: number | null;
  tail_frame_asset_id: number | null;
  analysis_version: string;
  config_hash: string;
  report_hash: string;
  technical_status: VisualStatus;
  automatic_visual_status: VisualStatus;
  human_visual_status: HumanVisualStatus;
  overall_visual_status: VisualStatus;
  scene_cut_status: VisualStatus;
  anchor_match_status: VisualStatus;
  target_match_status: VisualStatus;
  camera_stability_status: VisualStatus;
  composition_drift_status: VisualStatus;
  subject_scale_drift_status: VisualStatus;
  style_drift_status: VisualStatus;
  cross_shot_seam_status: VisualStatus;
  production_gate_status: "BLOCKED" | "ALLOWED";
  metrics: Record<string, unknown>;
  rejection_reasons: string[];
  created_at: string;
  updated_at: string;
}

export interface VisualComparisonPair {
  kind: string;
  leftSource: string;
  rightSource: string;
  leftAssetId: number | null;
  rightAssetId: number | null;
  leftTimestamp: number | null;
  rightTimestamp: number | null;
  metrics: Record<string, unknown>;
  status: string;
  reasonCodes: string[];
}

export interface VisualPreviewManifest {
  reportId: number;
  projectId: number;
  shotId: number | null;
  videoAssetId: number;
  sceneCutCandidates: Array<Record<string, unknown>>;
  comparisonPairs: VisualComparisonPair[];
  analysisVersion: string;
  configHash: string;
  reportHash: string;
  promptContract: Record<string, unknown> | null;
  promptContractWarning: string | null;
  crossShotSeam?: Record<string, unknown> | null;
}

export interface VisualRegenerationPlanOnly {
  strategy: string; status: "BLOCKED" | "READY_FOR_REVIEW"; scope: string;
  regenerationPlanHash: string; promptContractHash: string; targetShotIds: number[];
  reusedAssets: number[]; reasonCodes: string[]; blockedReasons: string[];
  promptContract: Record<string, Record<string, unknown>>;
  compiledImagePrompt: Record<string, string>; compiledVideoPrompt: Record<string, string>;
  keyframeDeltaStatus: string; splitSuggestion: Record<string, unknown>;
  imageRequests: number; videoRequests: number; totalVideoSeconds: string;
  estimatedBillingUnits: string; maximumBillingUnits: string; billingUnit: string;
  pricingReviewed: boolean; pricingFresh: boolean; crossShotSeamStatus: string;
  readyForHumanReview: boolean; readyForPaidExecution: false; recommendationReason: string;
}

export interface VisualExperimentPlanOnly {
  candidateType: string; experimentPlanHash: string; selectedRegenerationPlanHash: string;
  selectedBaselineAssetId: number | null; baselineHash: string | null; baselineCandidates: Array<{assetId:number; automaticScore:number; styleAssessment:string; exclusionReasons:string[]}>;
  baselineHumanReviewStatus: string; planHumanReviewStatus: string; authorizationStatus: string;
  recommendedCandidate: string; promptContractHash: string; compiledImagePromptHashes: string[]; compiledVideoPromptHashes: string[];
  promptContracts: Record<string, Record<string, Record<string, unknown>>>; compiledPrompts: Array<{image:{prompt:string;promptHash:string};video:{prompt:string;promptHash:string}}>;
  imageRequests:number; videoRequests:number; videoDurationSecondsEach:number; totalVideoSeconds:number;
  estimatedBillingUnits:string; maximumBillingUnits:string; billingUnit:string;
  readyForExplicitAuthorization:boolean; readyForPaidExecution:boolean;
}

export interface GenerationRequest {
  id: number;
  project_id: number;
  shot_id: number;
  shot_spec_revision?: number;
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

export type CharacterReferenceType = "FACE" | "FULL_BODY" | "CLOTHING" | "POSE" | "EXPRESSION" | "OTHER";
export type LocationReferenceType = "WIDE" | "INTERIOR" | "EXTERIOR" | "DETAIL" | "LIGHTING" | "OTHER";
export type ShotCharacterRole = "PRIMARY" | "SECONDARY" | "BACKGROUND";

export interface Character {
  id: number;
  project_id: number;
  name: string;
  description: string;
  appearance: string;
  personality: string;
  default_clothing: string;
  default_props: string[];
  continuity_notes: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  usage_count: number;
  reference_count: number;
  primary_reference_asset_id: number | null;
}

export interface Location {
  id: number;
  project_id: number;
  name: string;
  description: string;
  environment: string;
  architecture: string;
  time_of_day: string;
  weather: string;
  lighting: string;
  continuity_notes: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  usage_count: number;
  reference_count: number;
  primary_reference_asset_id: number | null;
}

export interface StyleProfile {
  id: number;
  project_id: number;
  name: string;
  description: string;
  positive_prompt: string;
  negative_prompt: string;
  color_palette: string[];
  rendering_style: string;
  camera_language: string;
  aspect_ratio: string | null;
  fps: number | null;
  default_provider_options: Record<string, unknown>;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  usage_count: number;
}

export interface ShotCharacterSpec {
  id?: number;
  shot_spec_id?: number;
  character_id: number;
  role: ShotCharacterRole;
  sort_order: number;
  appearance_override: string;
  clothing_override: string;
  expression: string;
  action: string;
  position: string;
  props: string[];
  continuity_notes: string;
  reference_asset_ids: number[];
}

export interface ShotSpec {
  id: number;
  shot_id: number;
  revision: number;
  location_id: number | null;
  style_profile_id: number | null;
  summary: string;
  action: string;
  emotion: string;
  composition: string;
  shot_size: string;
  camera_angle: string;
  camera_movement: string;
  lighting: string;
  time_of_day: string;
  weather: string;
  dialogue: string;
  continuity_notes: string;
  props: string[];
  provider_overrides: Record<string, unknown>;
  compiled_prompt: string;
  compiled_negative_prompt: string;
  structured_payload_json: string;
  structured_payload: Record<string, unknown>;
  compiler_version: string;
  created_at: string;
  characters: ShotCharacterSpec[];
  reference_asset_ids: number[];
}

export type ScriptSourceType = "PLAIN_TEXT" | "MARKDOWN" | "FOUNTAIN" | "DOCX" | "PASTED";
export type ScriptDocumentStatus = "IMPORTED" | "PARSED" | "PARSE_WARNING" | "ARCHIVED";
export type ScriptBlockType =
  | "SCENE_HEADING"
  | "ACTION"
  | "DIALOGUE"
  | "CHARACTER_CUE"
  | "PARENTHETICAL"
  | "TRANSITION"
  | "COMMENT"
  | "UNKNOWN";
export type StoryboardDraftStatus = "DRAFT" | "REVIEWED" | "PARTIALLY_APPLIED" | "APPLIED" | "ARCHIVED";
export type ShotDraftStatus = "DRAFT" | "READY" | "SKIPPED" | "APPLIED";

export interface ScriptDocument {
  id: number;
  project_id: number;
  title: string;
  source_type: ScriptSourceType;
  original_filename: string;
  mime_type: string;
  content_sha256: string;
  language: string;
  status: ScriptDocumentStatus;
  version: number;
  parent_document_id: number | null;
  parse_revision: number;
  block_count: number;
  storyboard_count: number;
  duplicate_of_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ScriptContent {
  id: number;
  title: string;
  raw_text: string;
  content_sha256: string;
  version: number;
}

export interface ScriptBlock {
  id: number;
  script_document_id: number;
  parse_revision: number;
  block_type: ScriptBlockType;
  user_block_type: ScriptBlockType | null;
  effective_block_type: ScriptBlockType;
  sort_order: number;
  source_start: number;
  source_end: number;
  source_text: string;
  normalized_text: string;
  user_normalized_text: string | null;
  effective_text: string;
  speaker: string;
  metadata: Record<string, unknown>;
  parse_confidence: number;
  parse_warnings: string[];
  warnings_confirmed: boolean;
  created_at: string;
}

export interface StoryboardDraft {
  id: number;
  project_id: number;
  script_document_id: number;
  name: string;
  parser_version: string;
  builder_version: string;
  status: StoryboardDraftStatus;
  default_style_profile_id: number | null;
  shot_draft_count: number;
  applied_shot_count: number;
  created_at: string;
  updated_at: string;
  applied_at: string | null;
}

export interface ShotDraftCharacter {
  character_id: number | null;
  character_name: string;
  role: ShotCharacterRole;
  action: string;
  expression: string;
  clothing: string;
  position: string;
  props: string[];
  notes: string;
  sort_order: number;
}

export interface ShotDraft {
  id: number;
  storyboard_draft_id: number;
  sort_order: number;
  source_block_start_id: number | null;
  source_block_end_id: number | null;
  title: string;
  summary: string;
  action: string;
  dialogue: string;
  suggested_duration_seconds: number;
  location_id: number | null;
  location_name: string;
  style_profile_id: number | null;
  time_of_day: string;
  weather: string;
  shot_size: string;
  camera_angle: string;
  camera_movement: string;
  composition: string;
  lighting: string;
  emotion: string;
  props: string[];
  continuity_notes: string;
  free_prompt: string;
  negative_prompt: string;
  status: ShotDraftStatus;
  applied_shot_id: number | null;
  characters: ShotDraftCharacter[];
  source_text: string;
  created_at: string;
  updated_at: string;
}

export interface ShotDraftPreview {
  shot_spec: Record<string, unknown>;
  compiled_prompt: string;
  compiled_negative_prompt: string;
  structured_payload: Record<string, unknown>;
  compiler_version: string;
  reference_asset_ids: number[];
  validation_warnings: string[];
}

export type ShotSpecPatch = Partial<
  Pick<
    ShotSpec,
    | "location_id"
    | "style_profile_id"
    | "summary"
    | "action"
    | "emotion"
    | "composition"
    | "shot_size"
    | "camera_angle"
    | "camera_movement"
    | "lighting"
    | "time_of_day"
    | "weather"
    | "dialogue"
    | "continuity_notes"
    | "props"
    | "provider_overrides"
  >
>;

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

export interface QualityCheckResult {
  id: number;
  project_id: number;
  shot_id: number | null;
  asset_id: number | null;
  reference_asset_id: number | null;
  check_type: string;
  severity: "INFO" | "WARNING" | "ERROR";
  score: number | null;
  threshold: number | null;
  message: string;
  details_json: string;
  details: Record<string, unknown>;
  algorithm_version: string;
  created_at: string;
}

export interface ProjectDetail extends Project {
  shots: Shot[];
  assets: Asset[];
  requests: GenerationRequest[];
  tasks: GenerationTask[];
  renders: ProjectRender[];
  quality_checks?: QualityCheckResult[];
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

export type ProviderAdapterType = "FAKE" | "MAPPED_ASYNC_HTTP" | "TOAPIS";
export type ProviderModelGenerationType = "IMAGE" | "VIDEO";
export type UsageRecordType = "ESTIMATE" | "PROVIDER_REPORTED" | "MANUAL_ADJUSTMENT";
export type UsageRecordStatus = "ESTIMATED" | "ACTUAL" | "UNKNOWN" | "WAIVED";
export type UsageCostSource = "PRICING_RULE" | "PROVIDER_RESPONSE" | "MANUAL" | "FAKE_PROVIDER" | "UNKNOWN";
export type UnknownCostPolicy = "ALLOW_WITH_WARNING" | "BLOCK";

export interface ProviderProfile {
  id: number;
  name: string;
  provider_key: string;
  adapter_type: ProviderAdapterType;
  display_name: string;
  description: string;
  base_url: string;
  secret_env_var: string;
  enabled: boolean;
  config: Record<string, unknown>;
  config_revision: number;
  secret_configured: boolean;
  configuration_valid: boolean;
  contract_verified: boolean;
  live_verified: boolean;
  live_orchestration_enabled: boolean;
  live_enabled_at: string | null;
  contract_reviewed_at: string | null;
  contract_reference: string | null;
  preflight_checked_at: string | null;
  preflight_image_model_accessible: boolean;
  preflight_video_model_accessible: boolean;
  preflight_response_schema_valid: boolean;
  account_balance_reviewed_at: string | null;
  account_balance_sufficient: boolean;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderModelProfile {
  id: number;
  provider_profile_id: number;
  model_key: string;
  remote_model: string;
  display_name: string;
  generation_type: ProviderModelGenerationType;
  enabled: boolean;
  capabilities: Record<string, unknown>;
  limits: Record<string, unknown>;
  pricing: Record<string, unknown>;
  billing_unit: string;
  pricing_version: string;
  pricing_source: string;
  pricing_review_status: "PENDING" | "REVIEWED" | "REJECTED" | "STALE";
  pricing_reviewed_at: string | null;
  pricing_snapshot_hash: string | null;
  currency: string;
  created_at: string;
  updated_at: string;
}

export interface ProviderValidation {
  provider_profile_id: number;
  configuration_valid: boolean;
  secret_configured: boolean;
  contract_verified: boolean;
  live_verified: boolean;
  warnings: string[];
  errors: string[];
}

export interface ToApisGateState {
  pricing_version: string;
  billing_unit: string;
  pricing_snapshot_hash: string | null;
  pricing_reviewed: boolean;
  live_orchestration_enabled: boolean;
  contract_reviewed_at: string | null;
  account_balance_sufficient: boolean;
  estimated_two_shot_billing_units: string;
  recommended_test_ceiling: string;
  image: Record<string, unknown>;
  video: Record<string, unknown>;
  preflight: { checked_at: string | null; image_model_accessible: boolean; video_model_accessible: boolean; response_schema_valid: boolean; balance_check: string };
}

export interface ProviderVerificationRun {
  id: number;
  provider_profile_id: number;
  model_profile_id: number | null;
  verification_type: "CONTRACT" | "LIVE_IMAGE" | "LIVE_VIDEO" | "LIVE_CHAIN";
  status: "PENDING" | "RUNNING" | "PASSED" | "FAILED" | "BLOCKED" | "CANCELLED";
  started_at: string | null;
  completed_at: string | null;
  max_cost: string | null;
  actual_cost: string | null;
  summary: Record<string, unknown>;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ProviderVisualReview {
  id: number;
  project_id: number;
  provider_verification_run_id: number;
  asset_id: number;
  asset_sha256: string;
  asset_url: string;
  review_scope: "PROVIDER_VERIFICATION";
  decision: "APPROVED" | "REJECTED";
  reason_codes: string[];
  notes: string;
  reviewer_source: "HUMAN_OPERATOR" | "SYSTEM_MIGRATION" | "TEST_FIXTURE";
  reviewer_reference: string | null;
  reviewed_at: string;
  created_at: string;
  idempotency_key: string | null;
}

export interface ProviderRunReadiness extends ProviderVerificationRun {
  run_id: number;
  technical_status: "PENDING" | "RUNNING" | "PASSED" | "FAILED" | "BLOCKED" | "CANCELLED";
  lineage_status: "PENDING" | "PASSED" | "FAILED" | "BLOCKED";
  automated_visual_status: "NOT_RUN" | "PENDING" | "PASSED" | "WARNING" | "FAILED";
  human_visual_status: HumanVisualStatus;
  production_status: "BLOCKED" | "READY";
  production_ready: boolean;
  production_blockers: string[];
  selected_review_asset: {
    id: number;
    type: Asset["type"];
    sha256: string;
    created_at: string;
    url: string;
  } | null;
  current_visual_review: ProviderVisualReview | null;
  legacy_review_evidence: boolean;
  legacy_review_report_ids: number[];
  legacy_reason_codes: string[];
  workflow_approval_only: boolean;
  scene_cut_check: {
    status: "NOT_RUN" | "PASSED" | "WARNING" | "FAILED";
    asset_ids: number[];
    algorithm_version: string;
    hard_cut_count: number;
    review_candidate_count: number;
    events: Array<{
      asset_id: number;
      timestamp_seconds: string;
      previous_timestamp_seconds: string;
      pixel_delta: string;
      histogram_delta: string;
      classification: "REVIEW_CANDIDATE" | "HARD_CUT";
      blocking: boolean;
    }>;
    missing_asset_ids: number[];
    calibration_scope: "SYNTHETIC_FIXTURES_ONLY";
  };
}

export interface GenerationUsageRecord {
  id: number;
  project_id: number;
  shot_id: number | null;
  generation_request_id: number | null;
  generation_task_id: number | null;
  provider_profile_id: number | null;
  provider_model_profile_id: number | null;
  attempt_number: number;
  record_type: UsageRecordType;
  status: UsageRecordStatus;
  currency: string;
  estimated_units: Record<string, unknown>;
  actual_units: Record<string, unknown>;
  estimated_cost: string | null;
  actual_cost: string | null;
  cost_source: UsageCostSource;
  provider_usage: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface UsageSummary {
  currencies: Array<{ currency: string; estimated_total: string; actual_total: string }>;
  unknown_cost_count: number;
  pending_estimate_total: Record<string, string>;
  request_count: number;
  image_request_count: number;
  video_request_count: number;
  failed_request_count: number;
  cancelled_request_count: number;
  provider_breakdown: Array<{ key: string; record_count: number }>;
  model_breakdown: Array<{ key: string; record_count: number }>;
  period_start: string | null;
  period_end: string | null;
}

export interface ProjectBudgetPolicy {
  id: number | null;
  project_id: number;
  currency: string;
  warning_limit: string | null;
  hard_limit: string | null;
  per_request_limit: string | null;
  period_type: "PROJECT_TOTAL" | "MONTHLY";
  unknown_cost_policy: UnknownCostPolicy;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
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

export class ApiError extends Error {
  status: number;
  code: string | null;
  requestId: string | null;

  constructor(
    message: string,
    options: { status: number; code?: string | null; requestId?: string | null },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? null;
    this.requestId = options.requestId ?? null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers =
    init?.body instanceof FormData
      ? { ...(init?.headers ?? {}) }
      : { "Content-Type": "application/json", ...(init?.headers ?? {}) };
  const response = await fetch(`${API_BASE}${path}`, {
    headers,
    ...init,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string; request_id?: string };
      error_code?: string; message?: string; request_id?: string; field_errors?: Record<string, string>;
    } | null;
    const requestId = payload?.request_id ?? payload?.error?.request_id ?? response.headers.get("X-Request-ID");
    const message = payload?.message ?? payload?.error?.message ?? `请求失败：${response.status}`;
    const suffix = requestId ? ` (request id: ${requestId})` : "";
    throw new ApiError(`${message}${suffix}`, {
      status: response.status,
      code: payload?.error_code ?? payload?.error?.code ?? null,
      requestId,
    });
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  listProjectProviderVerificationRuns: (projectId: number) =>
    request<ProviderRunReadiness[]>(`/api/projects/${projectId}/provider-verification-runs`),
  getProviderVerificationRun: (runId: number) =>
    request<ProviderRunReadiness>(`/api/provider-verification-runs/${runId}`),
  getProviderVisualReviews: (runId: number) =>
    request<{ current: ProviderVisualReview | null; history: ProviderVisualReview[] }>(
      `/api/provider-verification-runs/${runId}/visual-reviews`,
    ),
  createProviderVisualReview: (
    runId: number,
    body: { asset_id: number; decision: "APPROVED" | "REJECTED"; reason_codes: string[]; notes: string },
    idempotencyKey: string,
  ) => request<ProviderVisualReview>(`/api/provider-verification-runs/${runId}/visual-reviews`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(body),
  }),
  planVisualExperiment: (body: {project_id:number;source_run_id:number;candidate:string;selected_baseline_asset_id?:number|null;save_draft?:boolean}) =>
    request<VisualExperimentPlanOnly>("/api/visual-experiments/plan-only", {method:"POST",body:JSON.stringify(body)}),
  planVisualRegeneration: (body: { project_id: number; source_run_id: number; strategy: string; maximum_billing_units: string; save_draft?: boolean }) =>
    request<VisualRegenerationPlanOnly>("/api/visual-regeneration/plan-only", { method: "POST", body: JSON.stringify(body) }),
  mediaUrl: (assetId: number) => `${API_BASE}/api/media/${assetId}`,
  visualFrameUrl: (reportId: number, timestamp: number) =>
    `${API_BASE}/api/visual-continuity/reports/${reportId}/frames/${timestamp}`,
  listVisualReports: (projectId?: number) =>
    request<VisualContinuityReport[]>(`/api/visual-continuity/reports${projectId ? `?project_id=${projectId}` : ""}`),
  getVisualReport: (reportId: number) =>
    request<VisualContinuityReport>(`/api/visual-continuity/reports/${reportId}`),
  getVisualManifest: (reportId: number) =>
    request<VisualPreviewManifest>(`/api/visual-continuity/reports/${reportId}/preview-manifest`),
  getVisualReviewHistory: (reportId: number) =>
    request<Array<Record<string, unknown>>>(`/api/visual-continuity/reports/${reportId}/history`),
  reviewVisualReport: (reportId: number, body: {
    status: "APPROVED" | "REJECTED";
    rejection_reasons: string[];
    comment: string;
    reviewer: string;
    expected_report_hash: string;
    expected_updated_at: string;
  }) => request<VisualContinuityReport>(`/api/visual-continuity/reports/${reportId}/human-review`, {
    method: "POST", body: JSON.stringify(body),
  }),
  analyzeVisualReport: (body: {
    video_asset_id: number;
    start_anchor_asset_id: number | null;
    target_keyframe_asset_id: number | null;
    tail_frame_asset_id: number | null;
    analysis_version: string;
  }) => request<VisualContinuityReport>("/api/visual-continuity/reports/analyze", {
    method: "POST", body: JSON.stringify(body),
  }),
  usageCsvUrl: (projectId: number) => `${API_BASE}/api/projects/${projectId}/usage/export.csv`,
  listProviders: () => request<ProviderInfo[]>("/api/providers"),
  listProviderProfiles: (includeArchived = false) =>
    request<ProviderProfile[]>(`/api/provider-profiles?include_archived=${includeArchived ? "true" : "false"}`),
  createProviderProfile: (body: Partial<ProviderProfile>) =>
    request<ProviderProfile>("/api/provider-profiles", { method: "POST", body: JSON.stringify(body) }),
  updateProviderProfile: (providerId: number, body: Partial<ProviderProfile>) =>
    request<ProviderProfile>(`/api/provider-profiles/${providerId}`, { method: "PATCH", body: JSON.stringify(body) }),
  archiveProviderProfile: (providerId: number) =>
    request<ProviderProfile>(`/api/provider-profiles/${providerId}/archive`, { method: "POST" }),
  validateProviderProfile: (providerId: number) =>
    request<ProviderValidation>(`/api/provider-profiles/${providerId}/validate`, { method: "POST" }),
  verifyProviderContract: (providerId: number) =>
    request<ProviderVerificationRun>(`/api/provider-profiles/${providerId}/verify-contract`, { method: "POST" }),
  verifyProviderLive: (providerId: number, body: { confirm_live?: boolean; model_profile_id?: number | null; max_cost?: string | null }) =>
    request<ProviderVerificationRun>(`/api/provider-profiles/${providerId}/verify-live`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getToApisGate: () => request<ToApisGateState>("/api/provider-profiles/toapis/pricing-review"),
  reviewToApisPricing: () => request<ToApisGateState>("/api/provider-profiles/toapis/pricing-review", { method: "POST", body: JSON.stringify({ pricing_version: "toapis-public-2026-07", image_price: "6.3", image_unit: "IMAGE_REQUEST", video_price: "20", video_unit: "VIDEO_SECOND", billing_unit: "TOAPIS_CREDIT", contract_reference: "TOAPIS public pricing reviewed by local operator", acknowledged: true }) }),
  preflightToApis: () => request<Record<string, unknown>>("/api/provider-profiles/toapis/preflight", { method: "POST" }),
  confirmToApisBalance: () => request<ToApisGateState>("/api/provider-profiles/toapis/account-balance-review", { method: "POST", body: JSON.stringify({ acknowledged: true, sufficient: true, note: "Confirmed sufficient in TOAPIS console by local operator." }) }),
  enableToApisLive: (pricingSnapshotHash: string) => request<ToApisGateState>("/api/provider-profiles/toapis/live-enable", { method: "POST", body: JSON.stringify({ acknowledged: true, pricing_snapshot_hash: pricingSnapshotHash, reason: "Enable isolated two-shot TOAPIS verification" }) }),
  disableToApisLive: () => request<ToApisGateState>("/api/provider-profiles/toapis/live-disable", { method: "POST" }),
  listProviderModels: (providerId: number) =>
    request<ProviderModelProfile[]>(`/api/provider-profiles/${providerId}/models`),
  createProviderModel: (providerId: number, body: Partial<ProviderModelProfile>) =>
    request<ProviderModelProfile>(`/api/provider-profiles/${providerId}/models`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateProviderModel: (modelId: number, body: Partial<ProviderModelProfile>) =>
    request<ProviderModelProfile>(`/api/provider-models/${modelId}`, { method: "PATCH", body: JSON.stringify(body) }),
  archiveProviderModel: (modelId: number) =>
    request<ProviderModelProfile>(`/api/provider-models/${modelId}/archive`, { method: "POST" }),
  getProjectUsageSummary: (projectId: number) => request<UsageSummary>(`/api/projects/${projectId}/usage/summary`),
  listProjectUsageRecords: (projectId: number) =>
    request<GenerationUsageRecord[]>(`/api/projects/${projectId}/usage/records`),
  getProjectBudget: (projectId: number) => request<ProjectBudgetPolicy>(`/api/projects/${projectId}/budget`),
  updateProjectBudget: (projectId: number, body: Partial<ProjectBudgetPolicy>) =>
    request<ProjectBudgetPolicy>(`/api/projects/${projectId}/budget`, { method: "PUT", body: JSON.stringify(body) }),
  getWorkerStatus: () => request<WorkersStatus>("/api/workers/status"),
  listTasks: () => request<GenerationTask[]>("/api/tasks"),
  listProjects: (archived = false) => request<Project[]>(`/api/projects?archived=${archived}`),
  createProject: (body: { name: string; description: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  getProject: (id: number) => request<ProjectDetail>(`/api/projects/${id}`),
  updateProject: (id: number, body: Partial<Project>) =>
    request<Project>(`/api/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  archiveProject: (id: number) => request<Project>(`/api/projects/${id}/archive`, { method: "POST" }),
  restoreProject: (id: number) => request<Project>(`/api/projects/${id}/restore`, { method: "POST" }),
  permanentlyDeleteProject: (id: number, confirmationName: string) => request<void>(`/api/projects/${id}`, {
    method: "DELETE", body: JSON.stringify({ confirmation_name: confirmationName, irreversible_acknowledged: true }),
  }),
  importProviderConfig: (body: Record<string, unknown>) => request<ProviderProfile>("/api/provider-configs/import", { method: "POST", body: JSON.stringify(body) }),
  createCharacterFromImage: (projectId: number, file: File, fields: { name: string; description: string; appearance: string }) => {
    const body = new FormData(); body.append("file", file); body.append("name", fields.name); body.append("description", fields.description); body.append("appearance", fields.appearance);
    return request<{ character: Character; asset: Asset }>(`/api/projects/${projectId}/characters/from-image`, { method: "POST", body });
  },
  createShot: (projectId: number, body: Partial<Shot>) =>
    request<Shot>(`/api/projects/${projectId}/shots`, { method: "POST", body: JSON.stringify(body) }),
  updateShot: (shotId: number, body: Partial<Shot>) =>
    request<Shot>(`/api/shots/${shotId}`, { method: "PATCH", body: JSON.stringify(body) }),
  reviseShot: (shotId: number, body: { reason?: string; changes: Record<string, unknown> }) =>
    request<{
      shot_id: number;
      old_spec_revision: number;
      new_spec_revision: number;
      old_state: ShotStatus;
      new_state: ShotStatus;
      invalidated_asset_ids: number[];
      affected_downstream_shot_ids: number[];
    }>(`/api/shots/${shotId}/revisions`, { method: "POST", body: JSON.stringify(body) }),
  uploadProjectImage: (projectId: number, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Asset>(`/api/projects/${projectId}/assets/images`, { method: "POST", body });
  },
  listScripts: (projectId: number) => request<ScriptDocument[]>(`/api/projects/${projectId}/scripts`),
  importScriptText: (projectId: number, body: { title?: string; text: string; source_type?: ScriptSourceType; language?: string; create_new_version?: boolean; parent_document_id?: number | null }) =>
    request<ScriptDocument>(`/api/projects/${projectId}/scripts/import`, { method: "POST", body: JSON.stringify(body) }),
  importScriptFile: (projectId: number, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<ScriptDocument>(`/api/projects/${projectId}/scripts/import`, { method: "POST", body });
  },
  getScript: (scriptId: number) => request<ScriptDocument>(`/api/scripts/${scriptId}`),
  getScriptContent: (scriptId: number) => request<ScriptContent>(`/api/scripts/${scriptId}/content`),
  parseScript: (scriptId: number) =>
    request<{ script: ScriptDocument; parser_version: string; block_count: number; warnings: string[]; statistics: Record<string, unknown> }>(
      `/api/scripts/${scriptId}/parse`,
      { method: "POST" },
    ),
  listScriptBlocks: (scriptId: number) => request<ScriptBlock[]>(`/api/scripts/${scriptId}/blocks`),
  updateScriptBlock: (blockId: number, body: { user_block_type?: ScriptBlockType | null; user_normalized_text?: string | null; warnings_confirmed?: boolean | null }) =>
    request<ScriptBlock>(`/api/script-blocks/${blockId}`, { method: "PATCH", body: JSON.stringify(body) }),
  archiveScript: (scriptId: number) => request<ScriptDocument>(`/api/scripts/${scriptId}/archive`, { method: "POST" }),
  listStoryboards: (scriptId: number) => request<StoryboardDraft[]>(`/api/scripts/${scriptId}/storyboards`),
  createStoryboard: (scriptId: number, body: { name?: string | null; default_style_profile_id?: number | null }) =>
    request<StoryboardDraft>(`/api/scripts/${scriptId}/storyboards`, { method: "POST", body: JSON.stringify(body) }),
  getStoryboard: (storyboardId: number) => request<StoryboardDraft>(`/api/storyboards/${storyboardId}`),
  updateStoryboard: (storyboardId: number, body: Partial<StoryboardDraft>) =>
    request<StoryboardDraft>(`/api/storyboards/${storyboardId}`, { method: "PATCH", body: JSON.stringify(body) }),
  applyStoryboard: (storyboardId: number, body: { shot_draft_ids: number[]; insert_after_shot_id?: number | null }) =>
    request<{ storyboard: StoryboardDraft; applied_shot_ids: number[] }>(`/api/storyboards/${storyboardId}/apply`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listShotDrafts: (storyboardId: number) => request<ShotDraft[]>(`/api/storyboards/${storyboardId}/shot-drafts`),
  updateShotDraft: (shotDraftId: number, body: Partial<ShotDraft>) =>
    request<ShotDraft>(`/api/shot-drafts/${shotDraftId}`, { method: "PATCH", body: JSON.stringify(body) }),
  splitShotDraft: (shotDraftId: number, body: { split_after_block_id?: number | null; text_split_offset?: number | null }) =>
    request<ShotDraft[]>(`/api/shot-drafts/${shotDraftId}/split`, { method: "POST", body: JSON.stringify(body) }),
  mergeShotDraftNext: (shotDraftId: number) => request<ShotDraft>(`/api/shot-drafts/${shotDraftId}/merge-next`, { method: "POST" }),
  skipShotDraft: (shotDraftId: number) => request<ShotDraft>(`/api/shot-drafts/${shotDraftId}/skip`, { method: "POST" }),
  restoreShotDraft: (shotDraftId: number) => request<ShotDraft>(`/api/shot-drafts/${shotDraftId}/restore`, { method: "POST" }),
  previewShotDraft: (shotDraftId: number) => request<ShotDraftPreview>(`/api/shot-drafts/${shotDraftId}/preview-spec`, { method: "POST" }),
  applyShotDraft: (shotDraftId: number, body: { insert_after_shot_id?: number | null } = {}) =>
    request<ShotDraft>(`/api/shot-drafts/${shotDraftId}/apply`, { method: "POST", body: JSON.stringify(body) }),
  setStartFrame: (shotId: number, body: { action: "SELECT" | "CLEAR" | "RESTORE_INHERITED"; asset_id?: number | null }) =>
    request<Shot>(`/api/shots/${shotId}/start-frame`, { method: "POST", body: JSON.stringify(body) }),
  setTargetKeyframe: (shotId: number, body: { asset_id: number }) =>
    request<Shot>(`/api/shots/${shotId}/target-keyframe`, { method: "POST", body: JSON.stringify(body) }),
  listQualityChecks: (shotId: number) => request<QualityCheckResult[]>(`/api/shots/${shotId}/quality-checks`),
  runQualityChecks: (shotId: number) =>
    request<QualityCheckResult[]>(`/api/shots/${shotId}/quality-checks/run`, { method: "POST" }),
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
  listCharacters: (projectId: number) => request<Character[]>(`/api/projects/${projectId}/characters`),
  createCharacter: (projectId: number, body: Partial<Character>) =>
    request<Character>(`/api/projects/${projectId}/characters`, { method: "POST", body: JSON.stringify(body) }),
  updateCharacter: (characterId: number, body: Partial<Character>) =>
    request<Character>(`/api/characters/${characterId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCharacter: (characterId: number) => request<void>(`/api/characters/${characterId}`, { method: "DELETE" }),
  addCharacterReference: (
    characterId: number,
    body: { asset_id: number; reference_type?: CharacterReferenceType; label?: string; is_primary?: boolean; sort_order?: number },
  ) =>
    request<void>(`/api/characters/${characterId}/references`, { method: "POST", body: JSON.stringify(body) }),
  listLocations: (projectId: number) => request<Location[]>(`/api/projects/${projectId}/locations`),
  createLocation: (projectId: number, body: Partial<Location>) =>
    request<Location>(`/api/projects/${projectId}/locations`, { method: "POST", body: JSON.stringify(body) }),
  updateLocation: (locationId: number, body: Partial<Location>) =>
    request<Location>(`/api/locations/${locationId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteLocation: (locationId: number) => request<void>(`/api/locations/${locationId}`, { method: "DELETE" }),
  addLocationReference: (
    locationId: number,
    body: { asset_id: number; reference_type?: LocationReferenceType; label?: string; is_primary?: boolean; sort_order?: number },
  ) =>
    request<void>(`/api/locations/${locationId}/references`, { method: "POST", body: JSON.stringify(body) }),
  listStyleProfiles: (projectId: number) => request<StyleProfile[]>(`/api/projects/${projectId}/style-profiles`),
  createStyleProfile: (projectId: number, body: Partial<StyleProfile>) =>
    request<StyleProfile>(`/api/projects/${projectId}/style-profiles`, { method: "POST", body: JSON.stringify(body) }),
  updateStyleProfile: (styleProfileId: number, body: Partial<StyleProfile>) =>
    request<StyleProfile>(`/api/style-profiles/${styleProfileId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteStyleProfile: (styleProfileId: number) => request<void>(`/api/style-profiles/${styleProfileId}`, { method: "DELETE" }),
  getShotSpec: (shotId: number) => request<ShotSpec>(`/api/shots/${shotId}/spec`),
  listShotSpecHistory: (shotId: number) => request<ShotSpec[]>(`/api/shots/${shotId}/spec/history`),
  reviseShotSpec: (shotId: number, body: { reason?: string; changes: ShotSpecPatch; characters?: ShotCharacterSpec[] | null }) =>
    request<{
      shot_id: number;
      old_spec_revision: number;
      new_spec_revision: number;
      old_state: ShotStatus;
      new_state: ShotStatus;
      invalidated_asset_ids: number[];
      affected_downstream_shot_ids: number[];
    }>(`/api/shots/${shotId}/spec/revisions`, { method: "POST", body: JSON.stringify(body) }),
  syncShotSpec: (
    shotId: number,
    body: { reason?: string; sync_character_defaults?: boolean; sync_location_defaults?: boolean; sync_style_profile?: boolean },
  ) =>
    request<{
      shot_id: number;
      old_spec_revision: number;
      new_spec_revision: number;
      old_state: ShotStatus;
      new_state: ShotStatus;
      invalidated_asset_ids: number[];
      affected_downstream_shot_ids: number[];
    }>(`/api/shots/${shotId}/spec/sync`, { method: "POST", body: JSON.stringify(body) }),
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
