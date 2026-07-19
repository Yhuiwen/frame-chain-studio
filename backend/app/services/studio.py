import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.domain.state_machine import ensure_transition_allowed
from app.media.ffmpeg import extract_tail_frame
from app.models.entities import (
    Asset,
    AssetType,
    GenerationKind,
    GenerationRequest,
    GenerationTaskStatus,
    GenerationTask,
    GenerationTaskResult,
    Project,
    ProjectRender,
    ProviderAssetCache,
    ReliableTaskStatus,
    Shot,
    ShotStateChange,
    ShotStatus,
    TaskCommand,
    TaskLog,
    TaskStateChange,
    WorkerHeartbeat,
    utcnow,
)
from app.models.schemas import ProjectCreate, ProjectUpdate, ReorderShot, ShotCreate, ShotUpdate
from app.providers.base import GenerationProvider
from app.services import task_service

ACTIVE_GENERATION_STATUSES = task_service.ACTIVE_TASK_STATUSES
ACTIVE_RENDER_STATUSES = {
    "QUEUED",
    "PREPARING",
    "NORMALIZING",
    "CONCATENATING",
    "VALIDATING",
    "FINALIZING",
}

logger = logging.getLogger(__name__)


def get_project_or_404(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("PROJECT_NOT_FOUND", f"Project {project_id} was not found.", 404)
    return project


def get_shot_or_404(session: Session, shot_id: int) -> Shot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise AppError("SHOT_NOT_FOUND", f"Shot {shot_id} was not found.", 404)
    return shot


def create_project(session: Session, payload: ProjectCreate) -> Project:
    if hasattr(payload, "model_dump"):
        data = payload.model_dump()
    else:
        data = {
            "name": getattr(payload, "name"),
            "description": getattr(payload, "description", ""),
        }
    project = Project(**data)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def update_project(session: Session, project_id: int, payload: ProjectUpdate) -> Project:
    project = get_project_or_404(session, project_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(project, key, value)
    project.updated_at = utcnow()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def delete_project(session: Session, project_id: int) -> None:
    project = get_project_or_404(session, project_id)
    _ensure_project_deletable(session, project_id)
    paths = _asset_paths_for_project(session, project_id)
    try:
        task_ids = [
            task.id or 0
            for task in session.exec(select(GenerationTask).where(GenerationTask.project_id == project_id)).all()
        ]
        _delete_task_records(session, task_ids)
        for log in session.exec(select(TaskLog).where(col(TaskLog.shot_id).in_(_shot_ids(session, project_id)))).all():
            session.delete(log)
        for change in session.exec(
            select(ShotStateChange).where(col(ShotStateChange.shot_id).in_(_shot_ids(session, project_id)))
        ).all():
            session.delete(change)
        for render in session.exec(select(ProjectRender).where(ProjectRender.project_id == project_id)).all():
            session.delete(render)
        for request in session.exec(select(GenerationRequest).where(GenerationRequest.project_id == project_id)).all():
            session.delete(request)
        for shot in session.exec(select(Shot).where(Shot.project_id == project_id)).all():
            shot.start_frame_asset_id = None
            session.add(shot)
        session.flush()
        for asset in session.exec(select(Asset).where(Asset.project_id == project_id)).all():
            asset.source_asset_id = None
            session.add(asset)
        session.flush()
        assets_to_delete = list(session.exec(select(Asset).where(Asset.project_id == project_id)).all())
        _delete_provider_asset_caches(session, [asset.id for asset in assets_to_delete if asset.id is not None])
        for asset in assets_to_delete:
            session.delete(asset)
        for shot in session.exec(select(Shot).where(Shot.project_id == project_id)).all():
            session.delete(shot)
        session.delete(project)
        session.commit()
    except Exception:
        session.rollback()
        raise
    _cleanup_unreferenced_paths(session, paths)


def list_projects(session: Session) -> list[Project]:
    return list(session.exec(select(Project).order_by(col(Project.created_at))).all())


def create_shot(session: Session, project_id: int, payload: ShotCreate) -> Shot:
    get_project_or_404(session, project_id)
    max_order = session.exec(
        select(Shot.sort_order).where(Shot.project_id == project_id).order_by(col(Shot.sort_order).desc())
    ).first()
    shot = Shot(
        project_id=project_id,
        sort_order=(max_order + 1) if max_order is not None else 0,
        **payload.model_dump(),
    )
    session.add(shot)
    session.commit()
    session.refresh(shot)
    log_state(session, shot, None, shot.status, "shot_created")
    return shot


def update_shot(session: Session, shot_id: int, payload: ShotUpdate) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(shot, key, value)
    shot.updated_at = utcnow()
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


def delete_shot(session: Session, shot_id: int) -> None:
    shot = get_shot_or_404(session, shot_id)
    project_id = shot.project_id
    _ensure_shot_deletable(session, shot)
    deleted_order = shot.sort_order
    next_shot = session.exec(
        select(Shot)
        .where(Shot.project_id == project_id, Shot.sort_order > deleted_order)
        .order_by(col(Shot.sort_order))
    ).first()
    previous_shot = session.exec(
        select(Shot)
        .where(Shot.project_id == project_id, Shot.sort_order < deleted_order)
        .order_by(col(Shot.sort_order).desc())
    ).first()
    paths = _asset_paths_for_shot(session, shot_id)
    try:
        if next_shot is not None:
            relink_start_frame_after_delete(session, previous_shot, next_shot)

        task_ids = [
            task.id or 0 for task in session.exec(select(GenerationTask).where(GenerationTask.shot_id == shot_id)).all()
        ]
        _delete_task_records(session, task_ids)
        for state_change in session.exec(select(ShotStateChange).where(ShotStateChange.shot_id == shot_id)).all():
            session.delete(state_change)
        for log in session.exec(select(TaskLog).where(TaskLog.shot_id == shot_id)).all():
            session.delete(log)
        for request in session.exec(select(GenerationRequest).where(GenerationRequest.shot_id == shot_id)).all():
            session.delete(request)
        assets_to_delete = list(session.exec(select(Asset).where(Asset.shot_id == shot_id)).all())
        asset_ids_to_delete = {asset.id for asset in assets_to_delete if asset.id is not None}
        for other_shot in session.exec(select(Shot).where(col(Shot.start_frame_asset_id).in_(asset_ids_to_delete))).all():
            other_shot.start_frame_asset_id = None
            other_shot.updated_at = utcnow()
            session.add(other_shot)
        for task in session.exec(select(GenerationTask).where(col(GenerationTask.result_asset_id).in_(asset_ids_to_delete))).all():
            task.result_asset_id = None
            session.add(task)
        for result in session.exec(select(GenerationTaskResult).where(col(GenerationTaskResult.asset_id).in_(asset_ids_to_delete))).all():
            result.asset_id = None
            session.add(result)
        _delete_provider_asset_caches(session, list(asset_ids_to_delete))
        session.flush()
        for asset in assets_to_delete:
            references = session.exec(select(Asset).where(Asset.source_asset_id == asset.id)).all()
            external_references = [reference for reference in references if reference.id not in asset_ids_to_delete]
            if not external_references:
                session.delete(asset)
            else:
                asset.shot_id = None
                session.add(asset)

        session.delete(shot)
        remaining = list(
            session.exec(select(Shot).where(Shot.project_id == project_id).order_by(col(Shot.sort_order))).all()
        )
        for index, remaining_shot in enumerate(remaining):
            remaining_shot.sort_order = index
            remaining_shot.updated_at = utcnow()
            session.add(remaining_shot)
        session.commit()
    except Exception:
        session.rollback()
        raise
    _cleanup_unreferenced_paths(session, paths)


def _shot_ids(session: Session, project_id: int) -> list[int]:
    return [
        shot_id
        for shot_id in session.exec(select(Shot.id).where(Shot.project_id == project_id)).all()
        if shot_id is not None
    ]


def _ensure_shot_deletable(session: Session, shot: Shot) -> None:
    active = session.exec(
        select(GenerationTask).where(
            GenerationTask.shot_id == shot.id,
            col(GenerationTask.status).in_([status.value for status in ACTIVE_GENERATION_STATUSES]),
        )
    ).first()
    if active:
        raise AppError("SHOT_HAS_ACTIVE_TASKS", "Shot has active generation tasks.", 409)
    active_render = session.exec(
        select(ProjectRender).where(
            ProjectRender.project_id == shot.project_id,
            col(ProjectRender.status).in_(list(ACTIVE_RENDER_STATUSES)),
        )
    ).first()
    if active_render:
        raise AppError("PROJECT_HAS_ACTIVE_RENDER", "Project has an active render.", 409)


def _ensure_project_deletable(session: Session, project_id: int) -> None:
    active = session.exec(
        select(GenerationTask).where(
            GenerationTask.project_id == project_id,
            col(GenerationTask.status).in_([status.value for status in ACTIVE_GENERATION_STATUSES]),
        )
    ).first()
    if active:
        raise AppError("PROJECT_HAS_ACTIVE_TASKS", "Project has active generation tasks.", 409)
    active_render = session.exec(
        select(ProjectRender).where(
            ProjectRender.project_id == project_id,
            col(ProjectRender.status).in_(list(ACTIVE_RENDER_STATUSES)),
        )
    ).first()
    if active_render:
        raise AppError("PROJECT_HAS_ACTIVE_RENDER", "Project has an active render.", 409)


def _delete_task_records(session: Session, task_ids: list[int]) -> None:
    if not task_ids:
        return
    for heartbeat in session.exec(select(WorkerHeartbeat).where(col(WorkerHeartbeat.current_task_id).in_(task_ids))).all():
        heartbeat.current_task_id = None
        session.add(heartbeat)
    for change in session.exec(select(TaskStateChange).where(col(TaskStateChange.task_id).in_(task_ids))).all():
        session.delete(change)
    for command in session.exec(
        select(TaskCommand).where(
            col(TaskCommand.task_id).in_(task_ids) | col(TaskCommand.result_task_id).in_(task_ids)
        )
    ).all():
        session.delete(command)
    for result in session.exec(select(GenerationTaskResult).where(col(GenerationTaskResult.generation_task_id).in_(task_ids))).all():
        session.delete(result)
    for log in session.exec(select(TaskLog).where(col(TaskLog.task_id).in_(task_ids))).all():
        session.delete(log)
    for task in session.exec(select(GenerationTask).where(col(GenerationTask.id).in_(task_ids))).all():
        session.delete(task)


def _delete_provider_asset_caches(session: Session, asset_ids: list[int]) -> None:
    if not asset_ids:
        return
    for cache in session.exec(select(ProviderAssetCache).where(col(ProviderAssetCache.asset_id).in_(asset_ids))).all():
        session.delete(cache)


def _asset_paths_for_shot(session: Session, shot_id: int) -> list[Path]:
    return [Path(asset.path) for asset in session.exec(select(Asset).where(Asset.shot_id == shot_id)).all()]


def _asset_paths_for_project(session: Session, project_id: int) -> list[Path]:
    return [Path(asset.path) for asset in session.exec(select(Asset).where(Asset.project_id == project_id)).all()]


def _cleanup_unreferenced_paths(session: Session, paths: list[Path]) -> None:
    settings = get_settings()
    storage_root = settings.storage_dir.resolve()
    remaining_paths = {str(Path(asset.path).resolve()) for asset in session.exec(select(Asset)).all()}
    remaining_raw_paths = {str(Path(asset.path).absolute()) for asset in session.exec(select(Asset)).all()}
    for path in paths:
        try:
            raw_path = Path(path)
            absolute_path = raw_path if raw_path.is_absolute() else settings.storage_dir / raw_path
            if absolute_path.is_symlink():
                if str(absolute_path.absolute()) in remaining_raw_paths:
                    continue
                parent = absolute_path.parent.resolve()
                if parent == storage_root or storage_root in parent.parents:
                    absolute_path.unlink(missing_ok=True)
                continue
            resolved = path.resolve()
            if resolved == storage_root or storage_root not in resolved.parents:
                continue
            if str(resolved) in remaining_paths:
                continue
            if resolved.is_file():
                resolved.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("failed to cleanup asset file path=%s error=%s", _safe_storage_path(path), exc.__class__.__name__)
            continue


def _safe_storage_path(path: Path) -> str:
    settings = get_settings()
    try:
        return Path(path).resolve().relative_to(settings.storage_dir.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def relink_start_frame_after_delete(
    session: Session,
    previous_shot: Shot | None,
    next_shot: Shot,
) -> None:
    for start_asset in session.exec(
        select(Asset).where(
            Asset.shot_id == next_shot.id,
            Asset.type == AssetType.START_FRAME,
            col(Asset.source_asset_id).is_not(None),
        )
    ).all():
        session.delete(start_asset)

    tail_asset = latest_asset(session, previous_shot.id or 0, AssetType.TAIL_FRAME) if previous_shot else None
    if tail_asset is None or tail_asset.id is None:
        next_shot.start_frame_asset_id = None
        next_shot.updated_at = utcnow()
        session.add(next_shot)
        return

    inherited = Asset(
        project_id=next_shot.project_id,
        shot_id=next_shot.id,
        type=AssetType.START_FRAME,
        path=tail_asset.path,
        mime_type=tail_asset.mime_type,
        source_asset_id=tail_asset.id,
    )
    session.add(inherited)
    session.flush()
    next_shot.start_frame_asset_id = inherited.id
    next_shot.updated_at = utcnow()
    session.add(next_shot)


def list_project_shots(session: Session, project_id: int) -> list[Shot]:
    get_project_or_404(session, project_id)
    return list(
        session.exec(select(Shot).where(Shot.project_id == project_id).order_by(col(Shot.sort_order))).all()
    )


def reorder_shots(session: Session, project_id: int, items: list[ReorderShot]) -> list[Shot]:
    shots = {shot.id: shot for shot in list_project_shots(session, project_id)}
    if len(items) != len(shots):
        raise AppError("INVALID_SHOT_ORDER", "Reorder payload must include every shot in the project.", 400)
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise AppError("INVALID_SHOT_ORDER", "Reorder payload contains duplicate shot IDs.", 400)
    requested_ids = set(ids)
    if requested_ids != set(shots):
        raise AppError("INVALID_SHOT_ORDER", "Reorder payload must include every shot in the project.", 400)
    orders = [item.sort_order for item in items]
    if len(set(orders)) != len(orders):
        raise AppError("INVALID_SHOT_ORDER", "Reorder payload contains duplicate sort orders.", 400)
    if sorted(orders) != list(range(len(shots))):
        raise AppError("INVALID_SHOT_ORDER", "Sort orders must be exactly 0..n-1.", 400)
    offset = len(shots) + 1000
    for item in items:
        shot = shots[item.id]
        shot.sort_order = item.sort_order + offset
        session.add(shot)
    session.flush()
    for item in items:
        shot = shots[item.id]
        shot.sort_order = item.sort_order
        shot.updated_at = utcnow()
        session.add(shot)
    session.commit()
    return list_project_shots(session, project_id)


def log_state(
    session: Session,
    shot: Shot,
    from_status: ShotStatus | None,
    to_status: ShotStatus,
    reason: str,
    commit: bool = True,
) -> None:
    session.add(ShotStateChange(shot_id=shot.id or 0, from_status=from_status, to_status=to_status, reason=reason))
    if commit:
        session.commit()
    else:
        session.flush()


def transition_shot(session: Session, shot: Shot, target: ShotStatus, reason: str, *, commit: bool = True) -> Shot:
    previous = shot.status
    ensure_transition_allowed(previous, target)
    shot.status = target
    shot.updated_at = utcnow()
    session.add(shot)
    if commit:
        session.commit()
        session.refresh(shot)
    else:
        session.flush()
    log_state(session, shot, previous, target, reason, commit=commit)
    return shot


def log_task(
    session: Session,
    request: GenerationRequest | None,
    shot: Shot | None,
    message: str,
    level: str = "INFO",
    task: GenerationTask | None = None,
    commit: bool = True,
) -> None:
    session.add(
        TaskLog(
            request_id=request.id if request else None,
            task_id=task.id if task else None,
            shot_id=shot.id if shot else None,
            level=level,
            message=message,
        )
    )
    if commit:
        session.commit()
    else:
        session.flush()


def create_generation_request(
    session: Session,
    shot: Shot,
    kind: GenerationKind,
    input_asset_ids: list[int] | None = None,
    provider_id: str = "mock",
    model: str | None = None,
    generation_mode: str | None = None,
    aspect_ratio: str | None = None,
    seed: int | None = None,
    duration_seconds: float | None = None,
    allow_capability_fallback: bool = False,
    request_payload: dict[str, object] | None = None,
    provider_config_snapshot: dict[str, object] | None = None,
    commit: bool = True,
) -> GenerationRequest:
    request = task_service.create_generation_request(
        session,
        project_id=shot.project_id,
        shot_id=shot.id or 0,
        kind=kind,
        provider_name=provider_id,
        effective_provider_id=provider_id,
        model=model,
        generation_mode=generation_mode,
        aspect_ratio=aspect_ratio,
        seed=seed,
        duration_seconds=duration_seconds,
        allow_capability_fallback=allow_capability_fallback,
        prompt_snapshot=shot.prompt,
        negative_prompt_snapshot=shot.negative_prompt,
        input_asset_ids=input_asset_ids or [],
        commit=commit,
    )
    task = task_service.create_task_attempt(
        session,
        generation_request=request,
        provider_id=provider_id,
        request_payload=request_payload
        or {
            "provider_id": provider_id,
            "model": model,
            "prompt": shot.prompt,
            "negative_prompt": shot.negative_prompt,
            "input_asset_ids": input_asset_ids or [],
            "generation_mode": generation_mode,
            "aspect_ratio": aspect_ratio,
            "seed": seed,
            "duration_seconds": duration_seconds,
            "allow_capability_fallback": allow_capability_fallback,
        },
        provider_config_snapshot=provider_config_snapshot or {"provider_id": provider_id, "mode": "local_fixture"},
        commit=commit,
    )
    log_task(session, request, shot, f"{kind.value.lower()} request created", task=task, commit=commit)
    return request


def active_task_for_shot(session: Session, shot_id: int) -> GenerationTask | None:
    return session.exec(
        select(GenerationTask)
        .where(
            GenerationTask.shot_id == shot_id,
            col(GenerationTask.status).in_([status.value for status in task_service.ACTIVE_TASK_STATUSES]),
        )
        .order_by(col(GenerationTask.created_at).desc())
    ).first()


def start_keyframe_generation_atomic(
    session: Session,
    *,
    shot: Shot,
    resolved: object,
    request_payload: dict[str, object],
) -> GenerationRequest:
    if shot.status != ShotStatus.DRAFT:
        raise AppError("INVALID_SHOT_STATE", "Keyframe generation requires a draft shot.", 409)
    if shot.id is None:
        raise AppError("SHOT_NOT_PERSISTED", "Shot must be persisted before generation.", 500)
    if active_task_for_shot(session, shot.id):
        raise AppError("SHOT_HAS_ACTIVE_TASKS", "Shot already has an active generation task.", 409)
    try:
        request = create_generation_request(
            session,
            shot,
            GenerationKind.KEYFRAME,
            input_asset_ids=getattr(resolved, "input_asset_ids"),
            provider_id=getattr(resolved, "provider_id"),
            model=getattr(resolved, "model"),
            generation_mode=getattr(resolved, "generation_mode").value,
            aspect_ratio=getattr(resolved, "aspect_ratio"),
            seed=getattr(resolved, "seed"),
            duration_seconds=getattr(resolved, "duration_seconds"),
            allow_capability_fallback=getattr(resolved, "allow_capability_fallback"),
            request_payload=request_payload,
            provider_config_snapshot={
                "provider_id": getattr(resolved, "provider_id"),
                "configured": getattr(getattr(resolved, "provider_info", None), "configured", True),
            },
            commit=False,
        )
        transition_shot(session, shot, ShotStatus.KEYFRAME_GENERATING, "keyframe_generation_started", commit=False)
        session.commit()
        session.refresh(request)
        return request
    except Exception:
        session.rollback()
        raise


def start_video_generation_atomic(
    session: Session,
    *,
    shot: Shot,
    resolved: object,
    request_payload: dict[str, object],
) -> GenerationRequest:
    if shot.status != ShotStatus.KEYFRAME_APPROVED:
        raise AppError("KEYFRAME_NOT_APPROVED", "Video generation requires an approved keyframe.", 409)
    if shot.id is None:
        raise AppError("SHOT_NOT_PERSISTED", "Shot must be persisted before generation.", 500)
    if active_task_for_shot(session, shot.id):
        raise AppError("SHOT_HAS_ACTIVE_TASKS", "Shot already has an active generation task.", 409)
    try:
        request = create_generation_request(
            session,
            shot,
            GenerationKind.VIDEO,
            input_asset_ids=getattr(resolved, "input_asset_ids"),
            provider_id=getattr(resolved, "provider_id"),
            model=getattr(resolved, "model"),
            generation_mode=getattr(resolved, "generation_mode").value,
            aspect_ratio=getattr(resolved, "aspect_ratio"),
            seed=getattr(resolved, "seed"),
            duration_seconds=getattr(resolved, "duration_seconds"),
            allow_capability_fallback=getattr(resolved, "allow_capability_fallback"),
            request_payload=request_payload,
            provider_config_snapshot={
                "provider_id": getattr(resolved, "provider_id"),
                "configured": getattr(getattr(resolved, "provider_info", None), "configured", True),
            },
            commit=False,
        )
        transition_shot(session, shot, ShotStatus.VIDEO_GENERATING, "video_generation_started", commit=False)
        session.commit()
        session.refresh(request)
        return request
    except Exception:
        session.rollback()
        raise


def start_keyframe_generation(session: Session, shot_id: int) -> GenerationRequest:
    shot = get_shot_or_404(session, shot_id)
    transition_shot(session, shot, ShotStatus.KEYFRAME_GENERATING, "keyframe_generation_started")
    return create_generation_request(session, shot, GenerationKind.KEYFRAME)


def start_video_generation(session: Session, shot_id: int) -> GenerationRequest:
    shot = get_shot_or_404(session, shot_id)
    if shot.status != ShotStatus.KEYFRAME_APPROVED:
        raise AppError("KEYFRAME_NOT_APPROVED", "Video generation requires an approved keyframe.", 409)
    keyframe = latest_asset(session, shot.id or 0, AssetType.KEYFRAME)
    transition_shot(session, shot, ShotStatus.VIDEO_GENERATING, "video_generation_started")
    return create_generation_request(
        session,
        shot,
        GenerationKind.VIDEO,
        input_asset_ids=[keyframe.id] if keyframe and keyframe.id else [],
    )


def latest_asset(session: Session, shot_id: int, asset_type: AssetType) -> Asset | None:
    return session.exec(
        select(Asset)
        .where(Asset.shot_id == shot_id, Asset.type == asset_type)
        .order_by(col(Asset.created_at).desc())
    ).first()


def run_generation_request(
    session: Session,
    request_id: int,
    provider: GenerationProvider,
) -> GenerationRequest:
    request = session.get(GenerationRequest, request_id)
    if request is None:
        raise AppError("REQUEST_NOT_FOUND", f"Generation request {request_id} was not found.", 404)
    shot = get_shot_or_404(session, request.shot_id)
    task = active_or_latest_task_for_request(session, request.id or 0)
    if task is None:
        task = task_service.create_task_attempt(session, generation_request=request, provider_id=provider.name)
    task_service.mark_task_running(session, task.id or 0)
    request.status = GenerationTaskStatus.RUNNING
    request.updated_at = utcnow()
    session.add(request)
    session.commit()
    try:
        if request.kind == GenerationKind.KEYFRAME:
            output_path = provider.generate_keyframe(session, request)
            asset_type = AssetType.KEYFRAME
            mime_type = "image/png"
            next_status = ShotStatus.KEYFRAME_REVIEW
        elif request.kind == GenerationKind.VIDEO:
            output_path = provider.generate_video(session, request)
            asset_type = AssetType.VIDEO
            mime_type = "video/mp4"
            next_status = ShotStatus.VIDEO_REVIEW
        else:
            raise AppError("UNSUPPORTED_GENERATION_KIND", f"Unsupported kind {request.kind.value}.", 400)
        asset = Asset(
            project_id=request.project_id,
            shot_id=request.shot_id,
            type=asset_type,
            path=str(output_path),
            mime_type=mime_type,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        request.status = GenerationTaskStatus.SUCCEEDED
        request.output_asset_ids = json.dumps([asset.id])
        request.updated_at = utcnow()
        session.add(request)
        session.commit()
        task_service.mark_task_succeeded(
            session,
            task.id or 0,
            result_asset_id=asset.id,
            response_summary={"asset_id": asset.id, "asset_type": asset_type.value},
        )
        transition_shot(session, shot, next_status, f"{request.kind.value.lower()}_generation_succeeded")
        log_task(session, request, shot, f"{request.kind.value.lower()} request succeeded", task=task)
    except Exception as exc:
        request.status = GenerationTaskStatus.FAILED
        request.error_code = exc.__class__.__name__
        request.error_message = str(exc)
        request.updated_at = utcnow()
        session.add(request)
        session.commit()
        task_service.mark_task_failed(
            session,
            task.id or 0,
            error_code=request.error_code or "UNKNOWN_ERROR",
            error_message=request.error_message or "",
        )
        fallback = ShotStatus.DRAFT if request.kind == GenerationKind.KEYFRAME else ShotStatus.KEYFRAME_APPROVED
        transition_shot(session, shot, fallback, f"{request.kind.value.lower()}_generation_failed")
        log_task(session, request, shot, str(exc), "ERROR", task=task)
    session.refresh(request)
    return request


def active_or_latest_task_for_request(session: Session, request_id: int) -> GenerationTask | None:
    active = session.exec(
        select(GenerationTask)
        .where(
            GenerationTask.generation_request_id == request_id,
            col(GenerationTask.status).in_(
                [
                    ReliableTaskStatus.QUEUED.value,
                    ReliableTaskStatus.SUBMITTING.value,
                    ReliableTaskStatus.RUNNING.value,
                    ReliableTaskStatus.RETRY_WAIT.value,
                    ReliableTaskStatus.RESULT_READY.value,
                    ReliableTaskStatus.PROCESSING_RESULT.value,
                    ReliableTaskStatus.CANCELLING.value,
                ]
            ),
        )
        .order_by(col(GenerationTask.created_at).desc())
    ).first()
    if active is not None:
        return active
    return session.exec(
        select(GenerationTask)
        .where(GenerationTask.generation_request_id == request_id)
        .order_by(col(GenerationTask.created_at).desc())
    ).first()


def approve_keyframe(session: Session, shot_id: int) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    if shot.status == ShotStatus.KEYFRAME_APPROVED:
        return shot
    return transition_shot(session, shot, ShotStatus.KEYFRAME_APPROVED, "keyframe_approved")


def reject_keyframe(session: Session, shot_id: int) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    return transition_shot(session, shot, ShotStatus.DRAFT, "keyframe_rejected")


def approve_video(session: Session, shot_id: int) -> Shot:
    settings = get_settings()
    shot = get_shot_or_404(session, shot_id)
    if shot.status == ShotStatus.COMPLETED:
        return shot
    if shot.status != ShotStatus.VIDEO_REVIEW:
        raise AppError("INVALID_SHOT_STATE", "Video approval requires VIDEO_REVIEW status.", 409)
    video = latest_asset(session, shot_id, AssetType.VIDEO)
    if video is None:
        raise AppError("VIDEO_ASSET_MISSING", "Cannot extract tail frame without a video asset.", 409)
    video_path = Path(video.path)
    if not video_path.exists():
        raise AppError("VIDEO_ASSET_FILE_MISSING", "Cannot extract tail frame because the video file is missing.", 409)
    temp_dir = settings.storage_dir / "temp" / "tails"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_tail_path = temp_dir / f"shot-{shot.id}-{uuid4().hex}.png"
    final_tail_path = settings.storage_dir / f"project-{shot.project_id}" / f"shot-{shot.id}" / f"tail-frame-shot-{shot.id}.png"
    try:
        extract_tail_frame(video_path, temp_tail_path)
        _validate_tail_frame_temp(temp_tail_path, settings.storage_dir)
    except Exception:
        temp_tail_path.unlink(missing_ok=True)
        raise
    final_moved = False
    try:
        final_tail_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp_tail_path, final_tail_path)
        final_moved = True
        try:
            tail_asset = session.exec(
                select(Asset).where(
                    Asset.shot_id == shot.id,
                    Asset.type == AssetType.TAIL_FRAME,
                    Asset.source_asset_id == video.id,
                )
            ).first()
            transition_shot(session, shot, ShotStatus.VIDEO_APPROVED, "video_approved", commit=False)
            if tail_asset is None:
                tail_asset = Asset(
                    project_id=shot.project_id,
                    shot_id=shot.id,
                    type=AssetType.TAIL_FRAME,
                    path=str(final_tail_path),
                    mime_type="image/png",
                    source_asset_id=video.id,
                )
                session.add(tail_asset)
                session.flush()
            else:
                tail_asset.path = str(final_tail_path)
                session.add(tail_asset)
                session.flush()
            transition_shot(session, shot, ShotStatus.TAIL_FRAME_LOCKED, "tail_frame_extracted", commit=False)
            next_shot = session.exec(
                select(Shot)
                .where(Shot.project_id == shot.project_id, Shot.sort_order > shot.sort_order)
                .order_by(col(Shot.sort_order))
            ).first()
            if next_shot and tail_asset.id:
                for existing_start in session.exec(
                    select(Asset).where(Asset.shot_id == next_shot.id, Asset.type == AssetType.START_FRAME)
                ).all():
                    session.delete(existing_start)
                start_asset = Asset(
                    project_id=shot.project_id,
                    shot_id=next_shot.id,
                    type=AssetType.START_FRAME,
                    path=tail_asset.path,
                    mime_type=tail_asset.mime_type,
                    source_asset_id=tail_asset.id,
                )
                session.add(start_asset)
                session.flush()
                next_shot.start_frame_asset_id = start_asset.id
                next_shot.updated_at = utcnow()
                session.add(next_shot)
            transition_shot(session, shot, ShotStatus.COMPLETED, "shot_completed", commit=False)
            session.commit()
        except Exception:
            session.rollback()
            raise
        session.refresh(shot)
        return shot
    except Exception:
        temp_tail_path.unlink(missing_ok=True)
        if final_moved:
            final_tail_path.unlink(missing_ok=True)
        raise


def reject_video(session: Session, shot_id: int) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    return transition_shot(session, shot, ShotStatus.KEYFRAME_APPROVED, "video_rejected")


def _validate_tail_frame_temp(path: Path, storage_dir: Path) -> None:
    resolved = path.resolve()
    storage_root = storage_dir.resolve()
    if resolved == storage_root or storage_root not in resolved.parents:
        raise AppError("TAIL_FRAME_INVALID", "Tail frame temporary file is outside storage.", 500)
    if not resolved.exists() or not resolved.is_file() or resolved.stat().st_size <= 0:
        raise AppError("TAIL_FRAME_INVALID", "Tail frame extraction produced an empty file.", 500)
    try:
        with Image.open(resolved) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise AppError("TAIL_FRAME_INVALID", "Tail frame extraction produced an invalid image.", 500) from exc


def project_detail(
    session: Session,
    project_id: int,
) -> tuple[
    Project,
    list[dict[str, object]],
    list[dict[str, object]],
    list[GenerationRequest],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
    list[TaskLog],
]:
    project = get_project_or_404(session, project_id)
    shots = list_project_shots(session, project_id)
    assets = list(
        session.exec(select(Asset).where(Asset.project_id == project_id).order_by(col(Asset.created_at))).all()
    )
    requests = list(
        session.exec(
            select(GenerationRequest)
            .where(GenerationRequest.project_id == project_id)
            .order_by(col(GenerationRequest.created_at))
        ).all()
    )
    tasks = [task_payload(session, task) for task in task_service.list_project_tasks(session, project_id)]
    renders = [render_payload(render) for render in list_project_renders(session, project_id)]
    shot_ids = [shot.id for shot in shots if shot.id is not None]
    logs = list(
        session.exec(
            select(TaskLog)
            .where(col(TaskLog.shot_id).in_(shot_ids))
            .order_by(col(TaskLog.created_at))
        ).all()
    )
    serialized_assets = [asset_payload(asset) for asset in assets]
    serialized_shots = [shot_payload(session, shot) for shot in shots]
    return project, serialized_shots, serialized_assets, requests, tasks, renders, project_completion(shots, assets), logs


def list_project_renders(session: Session, project_id: int) -> list[ProjectRender]:
    return list(
        session.exec(
            select(ProjectRender).where(ProjectRender.project_id == project_id).order_by(col(ProjectRender.created_at))
        ).all()
    )


def render_payload(render: ProjectRender) -> dict[str, object]:
    return {
        "id": render.id,
        "project_id": render.project_id,
        "status": render.status,
        "render_version": render.render_version,
        "requested_at": render.requested_at,
        "started_at": render.started_at,
        "completed_at": render.completed_at,
        "progress": render.progress,
        "current_stage": render.current_stage,
        "output_asset_id": render.output_asset_id,
        "output_url": asset_url(render.output_asset_id) if render.output_asset_id else None,
        "error_code": render.error_code,
        "error_message": render.error_message,
        "created_at": render.created_at,
        "updated_at": render.updated_at,
    }


def project_completion(shots: list[Shot], assets: list[Asset]) -> dict[str, object]:
    video_by_shot = {asset.shot_id: asset for asset in assets if asset.type == AssetType.VIDEO and asset.shot_id}
    missing = [shot.id or 0 for shot in shots if shot.status != ShotStatus.COMPLETED or shot.id not in video_by_shot]
    estimated = 0.0
    for shot in shots:
        if shot.id is None:
            continue
        video = video_by_shot.get(shot.id)
        if video is not None:
            estimated += video.duration_seconds or shot.duration_seconds
    reason = None
    if missing:
        reason = f"Missing approved video for Shot {missing[0]}"
    return {
        "total_shots": len(shots),
        "completed_shots": len(shots) - len(missing),
        "missing_shot_ids": missing,
        "estimated_duration_seconds": estimated,
        "can_render": len(shots) > 0 and not missing,
        "render_disabled_reason": reason,
    }


def task_payload(session: Session, task: GenerationTask) -> dict[str, object]:
    result_items = task_service.loads_json_list(task.result_urls_json)
    result_hosts = sorted(
        {
            str(item.get("host") or parsed.hostname)
            for item in result_items
            if isinstance(item, dict)
            for parsed in [urlsplit(str(item.get("url", "")))]
            if item.get("host") or parsed.hostname
        }
    )
    processing_status = task_service.primary_result_status(session, task.id or 0)
    return {
        "id": task.id,
        "generation_request_id": task.generation_request_id,
        "project_id": task.project_id,
        "shot_id": task.shot_id,
        "task_type": task.task_type,
        "provider_id": task.provider_id,
        "status": task.status,
        "remote_job_id": task.remote_job_id,
        "remote_status": task.remote_status,
        "remote_progress": task.remote_progress,
        "processing_stage": task.processing_stage,
        "processing_progress": task.processing_progress,
        "attempt_number": task.attempt_number,
        "retry_count": task.retry_count,
        "max_attempts": task.max_attempts,
        "result_count": len(result_items),
        "result_hosts": result_hosts,
        "processing_status": processing_status,
        "can_cancel": task.status
        in {
            ReliableTaskStatus.QUEUED,
            ReliableTaskStatus.SUBMITTING,
            ReliableTaskStatus.RUNNING,
            ReliableTaskStatus.RETRY_WAIT,
            ReliableTaskStatus.RESULT_READY,
            ReliableTaskStatus.CANCELLING,
        },
        "can_retry": task.status in {ReliableTaskStatus.FAILED, ReliableTaskStatus.CANCELLED},
        "retry_of_task_id": task.retry_of_task_id,
        "root_task_id": task.root_task_id,
        "cancel_requested_at": task.cancel_requested_at,
        "cancelled_at": task.cancelled_at,
        "cancel_reason": task.cancel_reason,
        "submission_deadline_at": task.submission_deadline_at,
        "job_deadline_at": task.job_deadline_at,
        "cancellation_deadline_at": task.cancellation_deadline_at,
        "last_retry_delay_seconds": task.last_retry_delay_seconds,
        "result_retry_count": task.result_retry_count,
        "max_result_attempts": task.max_result_attempts,
        "next_result_retry_at": task.next_result_retry_at,
        "last_result_retry_delay_seconds": task.last_result_retry_delay_seconds,
        "next_retry_at": task.next_retry_at,
        "last_polled_at": task.last_polled_at,
        "next_poll_at": task.next_poll_at,
        "locked_by": task.locked_by,
        "locked_until": task.locked_until,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "result_asset_id": task.result_asset_id,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
    }


def asset_url(asset_id: int) -> str:
    return f"/api/media/{asset_id}"


def asset_payload(asset: Asset) -> dict[str, object]:
    return {
        "id": asset.id,
        "project_id": asset.project_id,
        "shot_id": asset.shot_id,
        "type": asset.type,
        "url": asset_url(asset.id or 0),
        "file_name": Path(asset.path).name,
        "mime_type": asset.mime_type,
        "source_asset_id": asset.source_asset_id,
        "sha256": asset.sha256,
        "file_size": asset.file_size,
        "width": asset.width,
        "height": asset.height,
        "duration_seconds": asset.duration_seconds,
        "fps": asset.fps,
        "created_at": asset.created_at,
    }


def asset_summary(
    session: Session,
    asset: Asset | None,
    source_type: str,
) -> dict[str, object] | None:
    if asset is None or asset.id is None:
        return None
    source_shot_id: int | None = None
    source_shot_title: str | None = None
    if asset.source_asset_id is not None:
        source_asset = session.get(Asset, asset.source_asset_id)
        if source_asset and source_asset.shot_id:
            source_shot = session.get(Shot, source_asset.shot_id)
            if source_shot:
                source_shot_id = source_shot.id
                source_shot_title = source_shot.title
    return {
        "asset_id": asset.id,
        "url": asset_url(asset.id),
        "source_type": source_type,
        "source_shot_id": source_shot_id,
        "source_shot_title": source_shot_title,
        "file_name": Path(asset.path).name,
        "created_at": asset.created_at,
    }


def shot_payload(session: Session, shot: Shot) -> dict[str, object]:
    start_asset = session.get(Asset, shot.start_frame_asset_id) if shot.start_frame_asset_id else None
    start_source_type = "inherited" if start_asset and start_asset.source_asset_id else "manual"
    return {
        "id": shot.id,
        "project_id": shot.project_id,
        "sort_order": shot.sort_order,
        "title": shot.title,
        "description": shot.description,
        "duration_seconds": shot.duration_seconds,
        "prompt": shot.prompt,
        "negative_prompt": shot.negative_prompt,
        "status": shot.status,
        "start_frame_asset_id": shot.start_frame_asset_id,
        "start_frame": asset_summary(session, start_asset, start_source_type),
        "target_keyframe": asset_summary(session, latest_asset(session, shot.id or 0, AssetType.KEYFRAME), "generated"),
        "locked_tail_frame": asset_summary(
            session,
            latest_asset(session, shot.id or 0, AssetType.TAIL_FRAME),
            "generated",
        ),
        "actions": shot_actions(shot),
        "created_at": shot.created_at,
        "updated_at": shot.updated_at,
    }


def shot_actions(shot: Shot) -> dict[str, object]:
    reasons: list[str] = []
    can_generate_keyframe = shot.status == ShotStatus.DRAFT
    if not can_generate_keyframe:
        reasons.append("KEYFRAME_REQUIRES_DRAFT")
    can_generate_video = shot.status == ShotStatus.KEYFRAME_APPROVED
    if not can_generate_video:
        reasons.append("VIDEO_REQUIRES_KEYFRAME_APPROVED")
    return {
        "can_generate_keyframe": can_generate_keyframe,
        "can_generate_video": can_generate_video,
        "reasons": reasons,
    }
