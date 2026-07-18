from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Response
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db import engine, get_session
from app.models.entities import Asset, GenerationKind, GenerationRequest, Project, Shot, ShotStatus, TaskCommandType
from app.models.schemas import (
    GenerationStartRequest,
    GenerationRequestRead,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
    ReorderShot,
    ShotCreate,
    ShotRead,
    ShotUpdate,
    TaskCancelRequest,
    TaskRetryRequest,
    GenerationTaskRead,
    WorkersStatusRead,
)
from app.providers.config_loader import load_registry_from_env
from app.providers.exceptions import ProviderError
from app.providers.models import ProviderCapabilities, ProviderInfo
from app.providers.mock import MockGenerationProvider
from app.services import provider_resolution, studio, task_service, worker_status

router = APIRouter()
provider = MockGenerationProvider()


def run_request_in_background(request_id: int) -> None:
    with Session(engine) as session:
        studio.run_generation_request(session, request_id, provider)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/providers", response_model=list[ProviderInfo])
def list_providers() -> list[ProviderInfo]:
    try:
        return provider_resolution.list_public_providers(load_registry_from_env())
    except ProviderError as exc:
        return [
            ProviderInfo(
                provider_id="configured-provider",
                display_name="Configured Provider",
                capabilities=ProviderCapabilities(
                    provider_id="configured-provider",
                    display_name="Configured Provider",
                ),
                configured=False,
                configuration_error=exc.message,
            )
        ]


@router.get("/workers/status", response_model=WorkersStatusRead)
def workers_status(session: Session = Depends(get_session)) -> dict[str, object]:
    settings = get_settings()
    return worker_status.status_summary(session, stale_after_seconds=settings.worker_stale_after_seconds)


@router.post("/tasks/{task_id}/cancel", response_model=GenerationTaskRead)
def cancel_task(
    task_id: int,
    payload: TaskCancelRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    task_service.create_or_get_command(
        session,
        task_id=task_id,
        command_type=TaskCommandType.CANCEL,
        idempotency_key=idempotency_key or f"cancel:{task_id}",
        reason=payload.reason if payload else "",
    )
    task = task_service.request_task_cancel(
        session,
        task_id,
        reason=payload.reason if payload else "",
        cancellation_timeout_seconds=120,
    )
    return studio.task_payload(session, task)


@router.post("/tasks/{task_id}/retry", response_model=GenerationTaskRead)
def retry_task(
    task_id: int,
    payload: TaskRetryRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    retry = task_service.manual_retry_task(
        session,
        task_id,
        idempotency_key=idempotency_key or f"retry:{task_id}:{datetime.now().timestamp()}",
        reason=payload.reason if payload else "",
    )
    return studio.task_payload(session, retry)


@router.get("/media/{asset_id}")
def read_asset(asset_id: int, session: Session = Depends(get_session)) -> FileResponse:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise AppError("ASSET_NOT_FOUND", f"Asset {asset_id} was not found.", 404)
    settings = get_settings()
    storage_root = settings.storage_dir.resolve()
    asset_path = Path(asset.path).resolve()
    if storage_root not in asset_path.parents and asset_path != storage_root:
        raise AppError("ASSET_ACCESS_DENIED", "Asset file is outside the configured storage directory.", 403)
    if not asset_path.exists() or not asset_path.is_file():
        raise AppError("ASSET_FILE_NOT_FOUND", f"Asset file for {asset_id} was not found.", 404)
    return FileResponse(asset_path, media_type=asset.mime_type)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return studio.list_projects(session)


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> Project:
    return studio.create_project(session, payload)


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def project_detail(project_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    project, shots, assets, requests, tasks, logs = studio.project_detail(session, project_id)
    return {
        **ProjectRead.model_validate(project).model_dump(),
        "shots": shots,
        "assets": assets,
        "requests": requests,
        "tasks": tasks,
        "logs": logs,
    }


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, session: Session = Depends(get_session)) -> Project:
    return studio.update_project(session, project_id, payload)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)) -> Response:
    studio.delete_project(session, project_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/shots", response_model=list[ShotRead])
def list_shots(project_id: int, session: Session = Depends(get_session)) -> list[dict[str, object]]:
    return [studio.shot_payload(session, shot) for shot in studio.list_project_shots(session, project_id)]


@router.post("/projects/{project_id}/shots", response_model=ShotRead, status_code=201)
def create_shot(project_id: int, payload: ShotCreate, session: Session = Depends(get_session)) -> Shot:
    return studio.create_shot(session, project_id, payload)


@router.patch("/shots/{shot_id}", response_model=ShotRead)
def update_shot(shot_id: int, payload: ShotUpdate, session: Session = Depends(get_session)) -> Shot:
    return studio.update_shot(session, shot_id, payload)


@router.delete("/shots/{shot_id}", status_code=204)
def delete_shot(shot_id: int, session: Session = Depends(get_session)) -> Response:
    studio.delete_shot(session, shot_id)
    return Response(status_code=204)


@router.post("/projects/{project_id}/shots/reorder", response_model=list[ShotRead])
def reorder_shots(
    project_id: int,
    payload: list[ReorderShot],
    session: Session = Depends(get_session),
) -> list[Shot]:
    return studio.reorder_shots(session, project_id, payload)


@router.post("/shots/{shot_id}/keyframe/generate", response_model=GenerationRequestRead)
def generate_keyframe(
    shot_id: int,
    background_tasks: BackgroundTasks,
    payload: GenerationStartRequest | None = None,
    session: Session = Depends(get_session),
) -> GenerationRequest:
    shot = studio.get_shot_or_404(session, shot_id)
    project = studio.get_project_or_404(session, shot.project_id)
    settings = get_settings()
    resolved = provider_resolution.resolve_generation(
        session,
        project=project,
        shot=shot,
        kind=GenerationKind.KEYFRAME,
        payload=payload,
        registry=load_registry_from_env(),
        system_default_provider_id=settings.default_image_provider_id,
    )
    studio.transition_shot(session, shot, ShotStatus.KEYFRAME_GENERATING, "keyframe_generation_started")
    request = studio.create_generation_request(
        session,
        shot,
        GenerationKind.KEYFRAME,
        input_asset_ids=resolved.input_asset_ids,
        provider_id=resolved.provider_id,
        model=resolved.model,
        generation_mode=resolved.generation_mode.value,
        aspect_ratio=resolved.aspect_ratio,
        seed=resolved.seed,
        duration_seconds=resolved.duration_seconds,
        allow_capability_fallback=resolved.allow_capability_fallback,
        request_payload=resolved.request_payload(shot),
        provider_config_snapshot={
            "provider_id": resolved.provider_id,
            "configured": resolved.provider_info.configured if resolved.provider_info else True,
        },
    )
    if resolved.provider_id == provider_resolution.MOCK_PROVIDER_ID:
        background_tasks.add_task(run_request_in_background, request.id or 0)
    return request


@router.post("/shots/{shot_id}/keyframe/approve", response_model=ShotRead)
def approve_keyframe(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.approve_keyframe(session, shot_id)


@router.post("/shots/{shot_id}/keyframe/reject", response_model=ShotRead)
def reject_keyframe(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.reject_keyframe(session, shot_id)


@router.post("/shots/{shot_id}/video/generate", response_model=GenerationRequestRead)
def generate_video(
    shot_id: int,
    background_tasks: BackgroundTasks,
    payload: GenerationStartRequest | None = None,
    session: Session = Depends(get_session),
) -> GenerationRequest:
    shot = studio.get_shot_or_404(session, shot_id)
    if shot.status != ShotStatus.KEYFRAME_APPROVED:
        raise AppError("KEYFRAME_NOT_APPROVED", "Video generation requires an approved keyframe.", 409)
    project = studio.get_project_or_404(session, shot.project_id)
    settings = get_settings()
    resolved = provider_resolution.resolve_generation(
        session,
        project=project,
        shot=shot,
        kind=GenerationKind.VIDEO,
        payload=payload,
        registry=load_registry_from_env(),
        system_default_provider_id=settings.default_video_provider_id,
    )
    studio.transition_shot(session, shot, ShotStatus.VIDEO_GENERATING, "video_generation_started")
    request = studio.create_generation_request(
        session,
        shot,
        GenerationKind.VIDEO,
        input_asset_ids=resolved.input_asset_ids,
        provider_id=resolved.provider_id,
        model=resolved.model,
        generation_mode=resolved.generation_mode.value,
        aspect_ratio=resolved.aspect_ratio,
        seed=resolved.seed,
        duration_seconds=resolved.duration_seconds,
        allow_capability_fallback=resolved.allow_capability_fallback,
        request_payload=resolved.request_payload(shot),
        provider_config_snapshot={
            "provider_id": resolved.provider_id,
            "configured": resolved.provider_info.configured if resolved.provider_info else True,
        },
    )
    if resolved.provider_id == provider_resolution.MOCK_PROVIDER_ID:
        background_tasks.add_task(run_request_in_background, request.id or 0)
    return request


@router.post("/shots/{shot_id}/video/approve", response_model=ShotRead)
def approve_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.approve_video(session, shot_id)


@router.post("/shots/{shot_id}/video/reject", response_model=ShotRead)
def reject_video(shot_id: int, session: Session = Depends(get_session)) -> Shot:
    return studio.reject_video(session, shot_id)
