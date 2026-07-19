from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.providers.exceptions import ProviderUnsupportedCapabilityError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def default_status_aliases() -> dict[str, list[str | int]]:
    return {
        "queued": ["queued", "pending", "created", 0],
        "running": ["running", "processing", "generating", 1],
        "succeeded": ["succeeded", "completed", "success", 2],
        "failed": ["failed", "error", 3],
        "cancelled": ["cancelled", "canceled", 4],
    }


class RemoteJobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class ProviderCapabilities(BaseModel):
    provider_id: str
    display_name: str
    text_to_image: bool = False
    image_to_image: bool = False
    image_to_video: bool = False
    first_last_frame_video: bool = False
    video_extension: bool = False
    supports_seed: bool = False
    supports_cancel: bool = False
    supports_negative_prompt: bool = False
    max_reference_images: int = Field(default=0, ge=0)
    max_duration_seconds: float | None = Field(default=None, gt=0)
    supported_aspect_ratios: list[str] = Field(default_factory=list)
    supported_output_types: list[str] = Field(default_factory=list)


AssetRole = Literal["reference", "start_frame", "end_frame", "character", "scene", "style"]


class AssetReference(BaseModel):
    asset_id: int | None = None
    url: str
    mime_type: str | None = None
    role: AssetRole = "reference"


class ImageGenerationRequest(BaseModel):
    provider_id: str
    model: str = ""
    prompt: str
    negative_prompt: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    aspect_ratio: str | None = None
    seed: int | None = None
    reference_asset_ids: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_request_id: str | None = None


class VideoGenerationRequest(BaseModel):
    provider_id: str
    model: str = ""
    prompt: str
    negative_prompt: str | None = None
    duration_seconds: float = Field(gt=0)
    fps: float = Field(gt=0)
    aspect_ratio: str | None = None
    seed: int | None = None
    start_frame: AssetReference | None = None
    end_frame: AssetReference | None = None
    reference_assets: list[AssetReference] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_request_id: str | None = None


class ProviderResultUrl(BaseModel):
    url: str
    mime_type: str | None = None
    output_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderSubmitResult(BaseModel):
    remote_job_id: str
    remote_status: RemoteJobStatus
    accepted: bool = True
    raw_response_summary: str = ""
    submitted_at: datetime = Field(default_factory=utcnow)


class ProviderJobResult(BaseModel):
    remote_job_id: str
    remote_status: str | int | None = None
    normalized_status: RemoteJobStatus
    progress: float | None = Field(default=None, ge=0, le=1)
    result_urls: list[ProviderResultUrl] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    raw_response_summary: str = ""
    polled_at: datetime = Field(default_factory=utcnow)


class ProviderCancelResult(BaseModel):
    remote_job_id: str
    accepted: bool
    remote_status: RemoteJobStatus = RemoteJobStatus.UNKNOWN
    message: str = ""
    raw_response_summary: str = ""


class ProviderDefaults(BaseModel):
    image_model: str | None = None
    video_model: str | None = None
    aspect_ratio: str | None = "16:9"
    duration_seconds: float | None = None


class ProviderInfo(BaseModel):
    provider_id: str
    display_name: str
    capabilities: ProviderCapabilities
    configured: bool = True
    configuration_error: str | None = None
    defaults: ProviderDefaults = Field(default_factory=ProviderDefaults)


class ResponseMappingConfig(BaseModel):
    remote_job_id_path: str
    status_path: str
    progress_path: str | None = None
    result_urls_path: str | list[str] | None = None
    error_code_path: str | None = None
    error_message_path: str | None = None
    result_url_item_paths: list[str] = Field(default_factory=lambda: ["url", "download_url", "file.url"])
    status_aliases: dict[str, list[str | int]] = Field(default_factory=default_status_aliases)


class RequestFieldMapping(BaseModel):
    fields: dict[str, str] = Field(default_factory=dict)
    fixed_fields: dict[str, Any] = Field(default_factory=dict)
    skip_none: bool = True


class ProviderMappingConfig(BaseModel):
    submit_response: ResponseMappingConfig
    job_response: ResponseMappingConfig
    cancel_response: ResponseMappingConfig | None = None
    image_request: RequestFieldMapping = Field(default_factory=RequestFieldMapping)
    video_request: RequestFieldMapping = Field(default_factory=RequestFieldMapping)


class MappedHttpProviderConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider_id: str
    display_name: str
    base_url: str
    api_key: SecretStr | None = Field(default=None, repr=False)
    auth_header_name: str = "Authorization"
    auth_prefix: str = "Bearer "
    idempotency_header_name: str | None = "Idempotency-Key"
    image_submit_path: str = "/fake/v1/images/generations"
    video_submit_path: str = "/fake/v1/videos/generations"
    job_status_path_template: str = "/fake/v1/jobs/{remote_job_id}"
    job_cancel_path_template: str = "/fake/v1/jobs/{remote_job_id}/cancel"
    upload_endpoint: str | None = None
    upload_method: str = "POST"
    upload_file_field: str = "file"
    upload_response_url_path: str | None = None
    upload_response_file_id_path: str | None = None
    upload_extra_fields: dict[str, str] = Field(default_factory=dict)
    upload_timeout_seconds: float | None = Field(default=None, gt=0)
    upload_expiry_seconds: int | None = Field(default=None, gt=0)
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    verify_tls: bool = True
    default_image_model: str | None = None
    default_video_model: str | None = None
    default_aspect_ratio: str | None = "16:9"
    default_duration_seconds: float | None = None
    capabilities: ProviderCapabilities
    mapping: ProviderMappingConfig

    @model_validator(mode="after")
    def ensure_capability_identity(self) -> "MappedHttpProviderConfig":
        self.capabilities.provider_id = self.provider_id
        self.capabilities.display_name = self.display_name
        return self


def validate_request_capabilities(
    request: ImageGenerationRequest | VideoGenerationRequest,
    capabilities: ProviderCapabilities,
) -> None:
    if isinstance(request, ImageGenerationRequest):
        if not capabilities.text_to_image:
            raise ProviderUnsupportedCapabilityError("Provider does not support text-to-image.")
        if request.seed is not None and not capabilities.supports_seed:
            raise ProviderUnsupportedCapabilityError("Provider does not support seed control.")
        if request.aspect_ratio and capabilities.supported_aspect_ratios:
            if request.aspect_ratio not in capabilities.supported_aspect_ratios:
                raise ProviderUnsupportedCapabilityError("Requested aspect ratio is not supported.")
        if len(request.reference_asset_ids) > capabilities.max_reference_images:
            raise ProviderUnsupportedCapabilityError("Too many reference images for provider capability.")
        return
    if not capabilities.image_to_video:
        raise ProviderUnsupportedCapabilityError("Provider does not support image-to-video.")
    reference_count = len(request.reference_assets)
    if request.start_frame is not None:
        reference_count += 1
    if request.end_frame is not None:
        reference_count += 1
    if reference_count > capabilities.max_reference_images:
        raise ProviderUnsupportedCapabilityError("Too many reference images for provider capability.")
    if request.start_frame is not None and request.end_frame is not None and not capabilities.first_last_frame_video:
        raise ProviderUnsupportedCapabilityError("Provider does not support first-last-frame video.")
    if request.seed is not None and not capabilities.supports_seed:
        raise ProviderUnsupportedCapabilityError("Provider does not support seed control.")
    if request.aspect_ratio and capabilities.supported_aspect_ratios:
        if request.aspect_ratio not in capabilities.supported_aspect_ratios:
            raise ProviderUnsupportedCapabilityError("Requested aspect ratio is not supported.")
    if capabilities.max_duration_seconds is not None and request.duration_seconds > capabilities.max_duration_seconds:
        raise ProviderUnsupportedCapabilityError("Requested duration exceeds provider capability.")
