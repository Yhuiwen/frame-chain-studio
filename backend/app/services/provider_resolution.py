from dataclasses import dataclass

from sqlmodel import Session

from app.core.errors import AppError
from app.models.entities import AssetType, GenerationKind, GenerationMode, Project, Shot
from app.models.schemas import GenerationStartRequest
from app.providers.exceptions import ProviderUnsupportedCapabilityError
from app.providers.models import (
    AssetReference,
    ImageGenerationRequest,
    ProviderCapabilities,
    ProviderInfo,
    VideoGenerationRequest,
    validate_request_capabilities,
)
from app.providers.registry import ProviderRegistry
from app.services import studio


MOCK_PROVIDER_ID = "mock"


@dataclass(frozen=True)
class ResolvedGeneration:
    provider_id: str
    model: str | None
    generation_mode: GenerationMode
    aspect_ratio: str | None
    seed: int | None
    duration_seconds: float | None
    allow_capability_fallback: bool
    input_asset_ids: list[int]
    provider_info: ProviderInfo | None

    def request_payload(self, shot: Shot) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "prompt": shot.prompt,
            "negative_prompt": shot.negative_prompt,
            "input_asset_ids": self.input_asset_ids,
            "generation_mode": self.generation_mode.value,
            "aspect_ratio": self.aspect_ratio,
            "seed": self.seed,
            "duration_seconds": self.duration_seconds,
            "allow_capability_fallback": self.allow_capability_fallback,
        }


def list_public_providers(registry: ProviderRegistry) -> list[ProviderInfo]:
    infos = registry.list_capabilities()
    if not any(info.provider_id == MOCK_PROVIDER_ID for info in infos):
        infos.append(
            ProviderInfo(
                provider_id=MOCK_PROVIDER_ID,
                display_name="Local Mock Provider",
                capabilities=ProviderCapabilities(
                    provider_id=MOCK_PROVIDER_ID,
                    display_name="Local Mock Provider",
                    text_to_image=True,
                    image_to_video=True,
                    first_last_frame_video=True,
                    supports_seed=True,
                    supports_negative_prompt=True,
                    max_reference_images=2,
                    max_duration_seconds=60,
                    supported_aspect_ratios=["16:9", "9:16", "1:1"],
                    supported_output_types=["image/png", "video/mp4"],
                ),
                configured=True,
            )
        )
    return sorted(infos, key=lambda item: (not item.configured, item.provider_id))


def resolve_generation(
    session: Session,
    *,
    project: Project,
    shot: Shot,
    kind: GenerationKind,
    payload: GenerationStartRequest | None,
    registry: ProviderRegistry,
    system_default_provider_id: str | None = None,
) -> ResolvedGeneration:
    payload = payload or GenerationStartRequest()
    provider_id = _choose_provider_id(project, kind, payload.provider_id, system_default_provider_id)
    providers = {info.provider_id: info for info in list_public_providers(registry)}
    info = providers.get(provider_id)
    if info is None:
        raise AppError("PROVIDER_NOT_FOUND", f"Provider '{provider_id}' was not found.", 400)
    if not info.configured:
        raise AppError("PROVIDER_NOT_CONFIGURED", f"Provider '{provider_id}' is not configured.", 400)

    model = payload.model or _project_model(project, kind) or _provider_model(info, kind)
    aspect_ratio = payload.aspect_ratio or project.default_aspect_ratio or info.defaults.aspect_ratio
    seed = payload.seed if payload.seed is not None else project.default_seed
    duration = _duration_seconds(project, shot, kind, payload, info)
    input_asset_ids = _input_asset_ids(session, shot, kind)
    mode = _generation_mode(input_asset_ids, kind, info.capabilities, payload.allow_capability_fallback)
    _validate_snapshot(
        kind=kind,
        provider_id=provider_id,
        model=model,
        shot=shot,
        mode=mode,
        capabilities=info.capabilities,
        aspect_ratio=aspect_ratio,
        seed=seed,
        duration_seconds=duration,
        input_asset_ids=input_asset_ids,
    )
    return ResolvedGeneration(
        provider_id=provider_id,
        model=model,
        generation_mode=mode,
        aspect_ratio=aspect_ratio,
        seed=seed,
        duration_seconds=duration,
        allow_capability_fallback=payload.allow_capability_fallback,
        input_asset_ids=input_asset_ids,
        provider_info=info,
    )


def _choose_provider_id(
    project: Project,
    kind: GenerationKind,
    explicit_provider_id: str | None,
    system_default_provider_id: str | None,
) -> str:
    if explicit_provider_id:
        return explicit_provider_id
    project_default = project.image_provider_id if kind == GenerationKind.KEYFRAME else project.video_provider_id
    if project_default:
        return project_default
    if system_default_provider_id:
        return system_default_provider_id
    return MOCK_PROVIDER_ID


def _project_model(project: Project, kind: GenerationKind) -> str | None:
    return project.image_model if kind == GenerationKind.KEYFRAME else project.video_model


def _provider_model(info: ProviderInfo, kind: GenerationKind) -> str | None:
    return info.defaults.image_model if kind == GenerationKind.KEYFRAME else info.defaults.video_model


def _duration_seconds(
    project: Project,
    shot: Shot,
    kind: GenerationKind,
    payload: GenerationStartRequest,
    info: ProviderInfo,
) -> float | None:
    if kind != GenerationKind.VIDEO:
        return None
    return payload.duration_seconds or project.default_video_duration_seconds or info.defaults.duration_seconds or shot.duration_seconds


def _input_asset_ids(session: Session, shot: Shot, kind: GenerationKind) -> list[int]:
    if kind == GenerationKind.KEYFRAME:
        return []
    assets: list[int] = []
    if shot.start_frame_asset_id:
        assets.append(shot.start_frame_asset_id)
    keyframe = studio.latest_asset(session, shot.id or 0, AssetType.KEYFRAME)
    if keyframe and keyframe.id:
        assets.append(keyframe.id)
    return assets


def _generation_mode(
    input_asset_ids: list[int],
    kind: GenerationKind,
    capabilities: ProviderCapabilities,
    allow_fallback: bool,
) -> GenerationMode:
    if kind == GenerationKind.KEYFRAME:
        return GenerationMode.TEXT_TO_IMAGE
    if len(input_asset_ids) >= 2:
        if capabilities.first_last_frame_video:
            return GenerationMode.FIRST_LAST_FRAME
        if not allow_fallback:
            raise AppError(
                "PROVIDER_CAPABILITY_UNSUPPORTED",
                "Provider does not support first-last-frame video for this shot.",
                400,
            )
    return GenerationMode.START_FRAME_ONLY


def _validate_snapshot(
    *,
    kind: GenerationKind,
    provider_id: str,
    model: str | None,
    shot: Shot,
    mode: GenerationMode,
    capabilities: ProviderCapabilities,
    aspect_ratio: str | None,
    seed: int | None,
    duration_seconds: float | None,
    input_asset_ids: list[int],
) -> None:
    try:
        if kind == GenerationKind.KEYFRAME:
            validate_request_capabilities(
                ImageGenerationRequest(
                    provider_id=provider_id,
                    model=model or "",
                    prompt=shot.prompt,
                    negative_prompt=shot.negative_prompt or None,
                    width=1024,
                    height=576,
                    aspect_ratio=aspect_ratio,
                    seed=seed,
                    reference_asset_ids=[],
                ),
                capabilities,
            )
            return
        validate_request_capabilities(
            VideoGenerationRequest(
                provider_id=provider_id,
                model=model or "",
                prompt=shot.prompt,
                negative_prompt=shot.negative_prompt or None,
                duration_seconds=duration_seconds or shot.duration_seconds,
                fps=24,
                aspect_ratio=aspect_ratio,
                seed=seed,
                start_frame=_asset_ref(input_asset_ids[0]) if input_asset_ids else None,
                end_frame=_asset_ref(input_asset_ids[1]) if mode == GenerationMode.FIRST_LAST_FRAME and len(input_asset_ids) > 1 else None,
            ),
            capabilities,
        )
    except ProviderUnsupportedCapabilityError as exc:
        raise AppError("PROVIDER_CAPABILITY_UNSUPPORTED", exc.message, 400) from exc


def _asset_ref(asset_id: int) -> AssetReference:
    return AssetReference(asset_id=asset_id, url=f"asset://{asset_id}", mime_type=None, role="reference")
