import json
import logging
import os
import shutil
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.domain.continuity_invariants import (
    validate_project_continuity_invariants,
    validate_shot_invariants,
)
from app.domain.state_machine import ensure_transition_allowed
from app.media.ffmpeg import extract_tail_frame
from app.media.validation import MediaValidationError, validate_image
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    Character,
    CharacterReference,
    GenerationKind,
    GenerationRequest,
    GenerationTask,
    GenerationTaskStatus,
    GenerationTaskResult,
    Location,
    LocationReference,
    Project,
    ProjectRender,
    ProviderAssetCache,
    ReliableTaskStatus,
    Shot,
    ShotCharacter,
    ShotSpec,
    ShotStateChange,
    ShotStatus,
    StartFrameSourceType,
    StyleProfile,
    TaskCommand,
    TaskLog,
    TaskStateChange,
    WorkerHeartbeat,
    utcnow,
)
from app.models.schemas import (
    ProjectCreate,
    ProjectUpdate,
    ReorderShot,
    ShotCreate,
    ShotRevisionRequest,
    ShotSpecRevisionRequest,
    ShotSpecSyncRequest,
    ShotUpdate,
)
from app.providers.base import GenerationProvider
from app.services import quality_service, structured, task_service

ACTIVE_GENERATION_STATUSES = task_service.ACTIVE_TASK_STATUSES
ACTIVE_RENDER_STATUSES = {
    "QUEUED",
    "PREPARING",
    "NORMALIZING",
    "CONCATENATING",
    "VALIDATING",
    "FINALIZING",
}
GENERATION_SPEC_FIELDS = {"description", "prompt", "negative_prompt"}
VIDEO_SPEC_FIELDS = {"duration_seconds"}
DISPLAY_ONLY_FIELDS = {"title"}

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
        _delete_structured_project_records(session, project_id)
        for shot in session.exec(select(Shot).where(Shot.project_id == project_id)).all():
            shot.start_frame_asset_id = None
            shot.approved_keyframe_asset_id = None
            shot.approved_video_asset_id = None
            shot.locked_tail_frame_asset_id = None
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
    session.flush()
    structured.create_initial_shot_spec(session, shot, commit=False)
    session.commit()
    session.refresh(shot)
    log_state(session, shot, None, shot.status, "shot_created")
    return shot


def update_shot(session: Session, shot_id: int, payload: ShotUpdate) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    updates = payload.model_dump(exclude_unset=True)
    generation_updates = sorted(set(updates) - DISPLAY_ONLY_FIELDS)
    if generation_updates:
        raise AppError(
            "SHOT_REVISION_REQUIRED",
            f"Use the shot revision API to update generation fields: {generation_updates}.",
            409,
        )
    for key, value in updates.items():
        setattr(shot, key, value)
    shot.updated_at = utcnow()
    session.add(shot)
    session.commit()
    session.refresh(shot)
    return shot


def revise_shot_spec(session: Session, shot_id: int, payload: ShotRevisionRequest) -> dict[str, object]:
    shot = get_shot_or_404(session, shot_id)
    changes = payload.changes or {}
    unknown = sorted(set(changes) - (DISPLAY_ONLY_FIELDS | GENERATION_SPEC_FIELDS | VIDEO_SPEC_FIELDS))
    if unknown:
        raise AppError("INVALID_REVISION_FIELDS", f"Unsupported revision fields: {unknown}.", 400)
    old_revision = shot.spec_revision
    old_state = shot.status
    invalidated: list[int] = []
    affects_keyframe = any(field in changes for field in GENERATION_SPEC_FIELDS)
    affects_video_only = any(field in changes for field in VIDEO_SPEC_FIELDS) and not affects_keyframe
    for key, value in changes.items():
        setattr(shot, key, value)
    if affects_keyframe or affects_video_only:
        shot.spec_revision += 1
        if affects_keyframe:
            invalidated.extend(
                invalidate_shot_assets(
                    session,
                    shot,
                    asset_types={AssetType.KEYFRAME, AssetType.VIDEO, AssetType.TAIL_FRAME},
                    clear_keyframe=True,
                    clear_video=True,
                    clear_tail=True,
                )
            )
            new_state = ShotStatus.DRAFT
        else:
            keyframe = _copy_current_approved_keyframe_for_revision(session, shot)
            invalidated.extend(
                invalidate_shot_assets(
                    session,
                    shot,
                    asset_types={AssetType.VIDEO, AssetType.TAIL_FRAME},
                    clear_video=True,
                    clear_tail=True,
                )
            )
            if keyframe is not None:
                shot.approved_keyframe_asset_id = keyframe.id
                session.add(shot)
            new_state = ShotStatus.KEYFRAME_APPROVED if get_current_approved_keyframe(session, shot) else ShotStatus.DRAFT
        previous = shot.status
        shot.status = new_state
        session.add(ShotStateChange(shot_id=shot.id or 0, from_status=previous, to_status=new_state, reason="shot_revised"))
        structured.create_revised_shot_spec(
            session,
            shot,
            previous_revision=old_revision,
            payload=legacy_shot_revision_to_structured(payload),
        )
    shot.updated_at = utcnow()
    session.add(shot)
    affected = invalidate_downstream_shots(session, shot, reason=payload.reason or "shot_revised")
    rebuild_project_continuity_chain(session, shot.project_id, reason=payload.reason or "shot_revised")
    log_task(
        session,
        None,
        shot,
        f"Shot revised from spec {old_revision} to {shot.spec_revision}: {payload.reason}",
        commit=False,
    )
    validate_project_continuity_invariants(session, shot.project_id)
    session.commit()
    session.refresh(shot)
    return {
        "shot_id": shot.id,
        "old_spec_revision": old_revision,
        "new_spec_revision": shot.spec_revision,
        "old_state": old_state,
        "new_state": shot.status,
        "invalidated_asset_ids": sorted(set(invalidated)),
        "affected_downstream_shot_ids": sorted(set(affected)),
    }


def legacy_shot_revision_to_structured(payload: ShotRevisionRequest) -> ShotSpecRevisionRequest:
    changes: dict[str, object] = {}
    if "description" in payload.changes:
        changes["summary"] = payload.changes["description"]
    return ShotSpecRevisionRequest(reason=payload.reason, changes=changes)


def revise_structured_shot_spec(
    session: Session, shot_id: int, payload: ShotSpecRevisionRequest
) -> dict[str, object]:
    shot = get_shot_or_404(session, shot_id)
    old_revision = shot.spec_revision
    old_state = shot.status
    shot.spec_revision += 1
    invalidated = invalidate_shot_assets(
        session,
        shot,
        asset_types={AssetType.KEYFRAME, AssetType.VIDEO, AssetType.TAIL_FRAME},
        clear_keyframe=True,
        clear_video=True,
        clear_tail=True,
    )
    previous = shot.status
    shot.status = ShotStatus.DRAFT
    shot.updated_at = utcnow()
    session.add(shot)
    session.add(ShotStateChange(shot_id=shot.id or 0, from_status=previous, to_status=shot.status, reason="shot_spec_revised"))
    structured.create_revised_shot_spec(session, shot, previous_revision=old_revision, payload=payload)
    affected = invalidate_downstream_shots(session, shot, reason=payload.reason or "shot_spec_revised")
    rebuild_project_continuity_chain(session, shot.project_id, reason=payload.reason or "shot_spec_revised")
    log_task(
        session,
        None,
        shot,
        f"Structured ShotSpec revised from {old_revision} to {shot.spec_revision}: {payload.reason}",
        commit=False,
    )
    validate_project_continuity_invariants(session, shot.project_id)
    session.commit()
    session.refresh(shot)
    return {
        "shot_id": shot.id,
        "old_spec_revision": old_revision,
        "new_spec_revision": shot.spec_revision,
        "old_state": old_state,
        "new_state": shot.status,
        "invalidated_asset_ids": sorted(set(invalidated)),
        "affected_downstream_shot_ids": sorted(set(affected)),
    }


def sync_structured_shot_spec(
    session: Session, shot_id: int, payload: ShotSpecSyncRequest
) -> dict[str, object]:
    shot = get_shot_or_404(session, shot_id)
    old_revision = shot.spec_revision
    old_state = shot.status
    if structured.synced_spec_matches_current(
        session,
        shot,
        sync_character_defaults=payload.sync_character_defaults,
        sync_location_defaults=payload.sync_location_defaults,
        sync_style_profile=payload.sync_style_profile,
    ):
        return {
            "shot_id": shot.id,
            "old_spec_revision": old_revision,
            "new_spec_revision": old_revision,
            "old_state": old_state,
            "new_state": shot.status,
            "invalidated_asset_ids": [],
            "affected_downstream_shot_ids": [],
        }
    shot.spec_revision += 1
    invalidated = invalidate_shot_assets(
        session,
        shot,
        asset_types={AssetType.KEYFRAME, AssetType.VIDEO, AssetType.TAIL_FRAME},
        clear_keyframe=True,
        clear_video=True,
        clear_tail=True,
    )
    previous = shot.status
    shot.status = ShotStatus.DRAFT
    shot.updated_at = utcnow()
    session.add(shot)
    session.add(ShotStateChange(shot_id=shot.id or 0, from_status=previous, to_status=shot.status, reason="shot_spec_synced"))
    structured.sync_shot_spec(
        session,
        shot,
        previous_revision=old_revision,
        sync_character_defaults=payload.sync_character_defaults,
        sync_location_defaults=payload.sync_location_defaults,
        sync_style_profile=payload.sync_style_profile,
    )
    affected = invalidate_downstream_shots(session, shot, reason=payload.reason or "shot_spec_synced")
    rebuild_project_continuity_chain(session, shot.project_id, reason=payload.reason or "shot_spec_synced")
    log_task(
        session,
        None,
        shot,
        f"Structured ShotSpec synced from {old_revision} to {shot.spec_revision}: {payload.reason}",
        commit=False,
    )
    validate_project_continuity_invariants(session, shot.project_id)
    session.commit()
    session.refresh(shot)
    return {
        "shot_id": shot.id,
        "old_spec_revision": old_revision,
        "new_spec_revision": shot.spec_revision,
        "old_state": old_state,
        "new_state": shot.status,
        "invalidated_asset_ids": sorted(set(invalidated)),
        "affected_downstream_shot_ids": sorted(set(affected)),
    }


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
        _delete_structured_shot_records(session, shot_id)
        assets_to_delete = list(session.exec(select(Asset).where(Asset.shot_id == shot_id)).all())
        asset_ids_to_delete = {asset.id for asset in assets_to_delete if asset.id is not None}
        for other_shot in session.exec(select(Shot).where(col(Shot.start_frame_asset_id).in_(asset_ids_to_delete))).all():
            other_shot.start_frame_asset_id = None
            other_shot.updated_at = utcnow()
            session.add(other_shot)
        for other_shot in session.exec(select(Shot).where(col(Shot.approved_keyframe_asset_id).in_(asset_ids_to_delete))).all():
            other_shot.approved_keyframe_asset_id = None
            session.add(other_shot)
        for other_shot in session.exec(select(Shot).where(col(Shot.approved_video_asset_id).in_(asset_ids_to_delete))).all():
            other_shot.approved_video_asset_id = None
            session.add(other_shot)
        for other_shot in session.exec(select(Shot).where(col(Shot.locked_tail_frame_asset_id).in_(asset_ids_to_delete))).all():
            other_shot.locked_tail_frame_asset_id = None
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


def _delete_structured_project_records(session: Session, project_id: int) -> None:
    shot_ids = _shot_ids(session, project_id)
    if shot_ids:
        spec_ids = [
            spec_id
            for spec_id in session.exec(select(ShotSpec.id).where(col(ShotSpec.shot_id).in_(shot_ids))).all()
            if spec_id is not None
        ]
        if spec_ids:
            for item in session.exec(select(ShotCharacter).where(col(ShotCharacter.shot_spec_id).in_(spec_ids))).all():
                session.delete(item)
        for spec in session.exec(select(ShotSpec).where(col(ShotSpec.shot_id).in_(shot_ids))).all():
            session.delete(spec)
    character_ids = [
        character_id
        for character_id in session.exec(select(Character.id).where(Character.project_id == project_id)).all()
        if character_id is not None
    ]
    if character_ids:
        for character_reference in session.exec(
            select(CharacterReference).where(col(CharacterReference.character_id).in_(character_ids))
        ).all():
            session.delete(character_reference)
    location_ids = [
        location_id
        for location_id in session.exec(select(Location.id).where(Location.project_id == project_id)).all()
        if location_id is not None
    ]
    if location_ids:
        for location_reference in session.exec(
            select(LocationReference).where(col(LocationReference.location_id).in_(location_ids))
        ).all():
            session.delete(location_reference)
    for style in session.exec(select(StyleProfile).where(StyleProfile.project_id == project_id)).all():
        session.delete(style)
    for location in session.exec(select(Location).where(Location.project_id == project_id)).all():
        session.delete(location)
    for character in session.exec(select(Character).where(Character.project_id == project_id)).all():
        session.delete(character)


def _delete_structured_shot_records(session: Session, shot_id: int) -> None:
    spec_ids = [
        spec_id
        for spec_id in session.exec(select(ShotSpec.id).where(ShotSpec.shot_id == shot_id)).all()
        if spec_id is not None
    ]
    if spec_ids:
        for item in session.exec(select(ShotCharacter).where(col(ShotCharacter.shot_spec_id).in_(spec_ids))).all():
            session.delete(item)
    for spec in session.exec(select(ShotSpec).where(ShotSpec.shot_id == shot_id)).all():
        session.delete(spec)


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


def create_project_image_asset(
    session: Session,
    project_id: int,
    *,
    content: bytes,
    content_type: str | None,
) -> Asset:
    get_project_or_404(session, project_id)
    settings = get_settings()
    if not content:
        raise AppError("UPLOAD_EMPTY", "Uploaded image is empty.", 400)
    if len(content) > settings.upload_max_image_bytes:
        raise AppError("UPLOAD_TOO_LARGE", "Uploaded image exceeds the configured byte limit.", 413)
    digest = hashlib.sha256(content).hexdigest()
    existing = session.exec(
        select(Asset).where(Asset.project_id == project_id, col(Asset.shot_id).is_(None), Asset.sha256 == digest)
    ).first()
    if existing is not None:
        return existing
    temp_dir = settings.storage_dir / "temp" / "uploads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / f"{uuid4().hex}.upload"
    temp_path.write_bytes(content)
    try:
        try:
            metadata = validate_image(temp_path, max_pixels=settings.upload_max_image_pixels)
        except MediaValidationError as exc:
            raise AppError(exc.code, str(exc), 400) from exc
        if content_type and content_type not in {"application/octet-stream", metadata.mime_type}:
            raise AppError("UPLOAD_MIME_MISMATCH", "Uploaded image MIME type does not match its decoded format.", 400)
        extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[metadata.mime_type]
        final_path = settings.storage_dir / f"project-{project_id}" / "uploads" / f"image-{uuid4().hex}{extension}"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_path), final_path)
        asset = Asset(
            project_id=project_id,
            shot_id=None,
            type=AssetType.START_FRAME,
            status=AssetStatus.ACTIVE,
            revision=1,
            path=str(final_path),
            mime_type=metadata.mime_type,
            sha256=digest,
            file_size=len(content),
            width=metadata.width,
            height=metadata.height,
        )
        session.add(asset)
        session.commit()
        session.refresh(asset)
        return asset
    finally:
        temp_path.unlink(missing_ok=True)


def set_shot_start_frame(session: Session, shot_id: int, *, action: str, asset_id: int | None = None) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    normalized = action.upper()
    if normalized == "CLEAR":
        _clear_start_frame(session, shot)
    elif normalized == "RESTORE_INHERITED":
        shot.start_frame_source_type = StartFrameSourceType.INHERITED
        shot.updated_at = utcnow()
        session.add(shot)
        rebuild_project_continuity_chain(session, shot.project_id, reason="start_frame_restored")
    elif normalized == "SELECT":
        asset = _project_image_asset_or_404(session, shot.project_id, asset_id)
        shot.start_frame_asset_id = asset.id
        shot.start_frame_source_type = StartFrameSourceType.MANUAL
        shot.updated_at = utcnow()
        session.add(shot)
    else:
        raise AppError("INVALID_START_FRAME_ACTION", "Unsupported start frame action.", 400)
    _invalidate_after_start_frame_change(session, shot, "start_frame_changed")
    affected = invalidate_downstream_shots(session, shot, reason="start_frame_changed")
    if affected:
        rebuild_project_continuity_chain(session, shot.project_id, reason="start_frame_changed")
    validate_project_continuity_invariants(session, shot.project_id)
    session.commit()
    session.refresh(shot)
    return shot


def set_shot_target_keyframe(session: Session, shot_id: int, *, asset_id: int) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    source = _project_image_asset_or_404(session, shot.project_id, asset_id)
    invalidate_shot_assets(
        session,
        shot,
        asset_types={AssetType.KEYFRAME, AssetType.VIDEO, AssetType.TAIL_FRAME},
        clear_keyframe=True,
        clear_video=True,
        clear_tail=True,
    )
    keyframe = Asset(
        project_id=shot.project_id,
        shot_id=shot.id,
        type=AssetType.KEYFRAME,
        status=AssetStatus.ACTIVE,
        revision=shot.spec_revision,
        path=source.path,
        mime_type=source.mime_type,
        source_asset_id=source.id,
        sha256=source.sha256,
        file_size=source.file_size,
        width=source.width,
        height=source.height,
    )
    session.add(keyframe)
    session.flush()
    previous = shot.status
    shot.status = ShotStatus.KEYFRAME_REVIEW
    shot.updated_at = utcnow()
    session.add(shot)
    session.add(ShotStateChange(shot_id=shot.id or 0, from_status=previous, to_status=shot.status, reason="manual_keyframe_uploaded"))
    invalidate_downstream_shots(session, shot, reason="manual_keyframe_uploaded")
    validate_project_continuity_invariants(session, shot.project_id)
    session.commit()
    session.refresh(shot)
    return shot


def _project_image_asset_or_404(session: Session, project_id: int, asset_id: int | None) -> Asset:
    if asset_id is None:
        raise AppError("ASSET_REQUIRED", "An image asset id is required.", 400)
    asset = session.get(Asset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise AppError("ASSET_NOT_FOUND", f"Asset {asset_id} was not found in this project.", 404)
    if asset.mime_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise AppError("ASSET_NOT_IMAGE", "Selected asset is not an accepted image.", 400)
    return asset


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

    tail_asset = get_current_locked_tail_frame(session, previous_shot) if previous_shot else None
    if tail_asset is None or tail_asset.id is None:
        next_shot.start_frame_asset_id = None
        next_shot.start_frame_source_type = StartFrameSourceType.NONE
        next_shot.updated_at = utcnow()
        session.add(next_shot)
        return

    inherited = Asset(
        project_id=next_shot.project_id,
        shot_id=next_shot.id,
        type=AssetType.START_FRAME,
        status=AssetStatus.APPROVED,
        revision=next_shot.spec_revision,
        path=tail_asset.path,
        mime_type=tail_asset.mime_type,
        source_asset_id=tail_asset.id,
    )
    session.add(inherited)
    session.flush()
    next_shot.start_frame_asset_id = inherited.id
    next_shot.start_frame_source_type = StartFrameSourceType.INHERITED
    next_shot.updated_at = utcnow()
    session.add(next_shot)


def list_project_shots(session: Session, project_id: int) -> list[Shot]:
    get_project_or_404(session, project_id)
    return list(
        session.exec(select(Shot).where(Shot.project_id == project_id).order_by(col(Shot.sort_order))).all()
    )


def reorder_shots(session: Session, project_id: int, items: list[ReorderShot]) -> list[Shot]:
    _ensure_project_reorderable(session, project_id)
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
    rebuild_project_continuity_chain(session, project_id, reason="shots_reordered")
    validate_project_continuity_invariants(session, project_id)
    session.commit()
    return list_project_shots(session, project_id)


def _ensure_project_reorderable(session: Session, project_id: int) -> None:
    active = session.exec(
        select(GenerationTask).where(
            GenerationTask.project_id == project_id,
            col(GenerationTask.status).in_([status.value for status in ACTIVE_GENERATION_STATUSES]),
        )
    ).first()
    if active:
        raise AppError("PROJECT_HAS_ACTIVE_TASKS", f"Project has active generation task {active.id}.", 409)
    active_render = session.exec(
        select(ProjectRender).where(
            ProjectRender.project_id == project_id,
            col(ProjectRender.status).in_(list(ACTIVE_RENDER_STATUSES)),
        )
    ).first()
    if active_render:
        raise AppError("PROJECT_HAS_ACTIVE_RENDER", f"Project has active render {active_render.id}.", 409)


def rebuild_project_continuity_chain(session: Session, project_id: int, *, reason: str) -> list[int]:
    shots = list_project_shots(session, project_id)
    affected: list[int] = []
    previous_tail: Asset | None = None
    for index, shot in enumerate(shots):
        existing_start = session.get(Asset, shot.start_frame_asset_id) if shot.start_frame_asset_id else None
        if index == 0:
            if shot.start_frame_source_type == StartFrameSourceType.INHERITED:
                _clear_start_frame(session, shot)
                _invalidate_after_start_frame_change(session, shot, reason)
                affected.append(shot.id or 0)
            previous_tail = get_current_locked_tail_frame(session, shot)
            continue
        if shot.start_frame_source_type == StartFrameSourceType.MANUAL:
            previous_tail = get_current_locked_tail_frame(session, shot)
            continue
        if previous_tail is None:
            if shot.start_frame_asset_id is not None or shot.start_frame_source_type == StartFrameSourceType.INHERITED:
                _clear_start_frame(session, shot)
                _invalidate_after_start_frame_change(session, shot, reason)
                affected.append(shot.id or 0)
            previous_tail = get_current_locked_tail_frame(session, shot)
            continue
        if existing_start is None or existing_start.source_asset_id != previous_tail.id:
            inherited = _set_inherited_start_frame(session, shot, previous_tail)
            if inherited:
                _invalidate_after_start_frame_change(session, shot, reason)
                affected.append(shot.id or 0)
        previous_tail = get_current_locked_tail_frame(session, shot)
    return [item for item in affected if item]


def _clear_start_frame(session: Session, shot: Shot) -> None:
    existing = session.get(Asset, shot.start_frame_asset_id) if shot.start_frame_asset_id else None
    if (
        existing is not None
        and existing.shot_id == shot.id
        and existing.type == AssetType.START_FRAME
        and existing.source_asset_id is not None
        and existing.status in {AssetStatus.ACTIVE, AssetStatus.APPROVED}
    ):
        existing.status = AssetStatus.STALE
        session.add(existing)
    shot.start_frame_asset_id = None
    shot.start_frame_source_type = StartFrameSourceType.NONE
    shot.updated_at = utcnow()
    session.add(shot)


def _set_inherited_start_frame(session: Session, shot: Shot, tail_asset: Asset) -> Asset | None:
    if tail_asset.id is None:
        return None
    _clear_start_frame(session, shot)
    inherited = Asset(
        project_id=shot.project_id,
        shot_id=shot.id,
        type=AssetType.START_FRAME,
        status=AssetStatus.APPROVED,
        revision=shot.spec_revision,
        path=tail_asset.path,
        mime_type=tail_asset.mime_type,
        source_asset_id=tail_asset.id,
        sha256=tail_asset.sha256,
        file_size=tail_asset.file_size,
        width=tail_asset.width,
        height=tail_asset.height,
    )
    session.add(inherited)
    session.flush()
    shot.start_frame_asset_id = inherited.id
    shot.start_frame_source_type = StartFrameSourceType.INHERITED
    shot.updated_at = utcnow()
    session.add(shot)
    return inherited


def _invalidate_after_start_frame_change(session: Session, shot: Shot, reason: str) -> None:
    invalidate_shot_assets(
        session,
        shot,
        asset_types={AssetType.VIDEO, AssetType.TAIL_FRAME},
        clear_video=True,
        clear_tail=True,
    )
    previous = shot.status
    shot.status = ShotStatus.KEYFRAME_APPROVED if get_current_approved_keyframe(session, shot) else ShotStatus.DRAFT
    shot.updated_at = utcnow()
    session.add(shot)
    session.add(ShotStateChange(shot_id=shot.id or 0, from_status=previous, to_status=shot.status, reason=reason))


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
    provider_snapshot: dict[str, object] | None = None,
    commit: bool = True,
) -> GenerationRequest:
    spec = structured.create_initial_shot_spec(session, shot, commit=False)
    prompt_snapshot = spec.compiled_prompt or shot.prompt
    negative_snapshot = spec.compiled_negative_prompt or shot.negative_prompt
    structured_payload = structured.loads_dict(spec.structured_payload_json)
    provider_payload = dict(request_payload or {})
    provider_payload["prompt"] = prompt_snapshot
    provider_payload["negative_prompt"] = negative_snapshot
    provider_payload["structured_payload"] = structured_payload
    provider_payload["compiler_version"] = spec.compiler_version
    reference_asset_ids = [item for item in structured_payload.get("reference_asset_ids", []) if isinstance(item, int)]
    if reference_asset_ids:
        provider_payload["reference_asset_ids"] = reference_asset_ids
    snapshot = provider_snapshot or {}
    snapshot_model = snapshot.get("provider_model_key")
    snapshot_revision = snapshot.get("revision")
    provider_model_key = snapshot_model if isinstance(snapshot_model, str) else model
    provider_config_revision = snapshot_revision if isinstance(snapshot_revision, int) else None
    request = task_service.create_generation_request(
        session,
        project_id=shot.project_id,
        shot_id=shot.id or 0,
        shot_spec_revision=shot.spec_revision,
        kind=kind,
        provider_name=provider_id,
        effective_provider_id=provider_id,
        model=model,
        generation_mode=generation_mode,
        aspect_ratio=aspect_ratio,
        seed=seed,
        duration_seconds=duration_seconds,
        allow_capability_fallback=allow_capability_fallback,
        prompt_snapshot=prompt_snapshot,
        negative_prompt_snapshot=negative_snapshot,
        structured_payload_json=spec.structured_payload_json,
        compiler_version=spec.compiler_version,
        provider_key=str(snapshot.get("provider_key") or provider_id),
        provider_model_key=provider_model_key,
        provider_config_revision=provider_config_revision,
        provider_capability_snapshot_json=json.dumps(snapshot.get("capabilities") or {}, ensure_ascii=True, sort_keys=True),
        pricing_snapshot_json=json.dumps(snapshot, ensure_ascii=True, sort_keys=True),
        provider_live_enable_snapshot=bool(snapshot.get("provider_live_enable_snapshot")),
        pricing_snapshot_hash=str(snapshot["pricing_snapshot_hash"]) if snapshot.get("pricing_snapshot_hash") else None,
        billing_unit=str(snapshot["billing_unit"]) if snapshot.get("billing_unit") else None,
        contract_review_reference=str(snapshot["contract_review_reference"]) if snapshot.get("contract_review_reference") else None,
        preflight_checked_at=(datetime.fromisoformat(str(snapshot["preflight_checked_at"])) if snapshot.get("preflight_checked_at") else None),
        input_asset_ids=input_asset_ids or [],
        commit=commit,
    )
    task = task_service.create_task_attempt(
        session,
        generation_request=request,
        provider_id=provider_id,
        request_payload=provider_payload
        or {
            "provider_id": provider_id,
            "model": model,
            "prompt": prompt_snapshot,
            "negative_prompt": negative_snapshot,
            "input_asset_ids": input_asset_ids or [],
            "generation_mode": generation_mode,
            "aspect_ratio": aspect_ratio,
            "seed": seed,
            "duration_seconds": duration_seconds,
            "allow_capability_fallback": allow_capability_fallback,
            "structured_payload": structured_payload,
            "compiler_version": spec.compiler_version,
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
                "provider_config_revision": getattr(resolved, "provider_snapshot", {}).get("revision") if isinstance(getattr(resolved, "provider_snapshot", {}), dict) else None,
            },
            provider_snapshot=getattr(resolved, "provider_snapshot", {}),
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
                "provider_config_revision": getattr(resolved, "provider_snapshot", {}).get("revision") if isinstance(getattr(resolved, "provider_snapshot", {}), dict) else None,
            },
            provider_snapshot=getattr(resolved, "provider_snapshot", {}),
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
    keyframe = get_current_approved_keyframe(session, shot)
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


def current_asset_by_id(session: Session, asset_id: int | None, *, revision: int | None = None) -> Asset | None:
    if asset_id is None:
        return None
    asset = session.get(Asset, asset_id)
    if asset is None:
        return None
    if asset.status not in {AssetStatus.APPROVED, AssetStatus.ACTIVE}:
        return None
    if revision is not None and asset.revision != revision:
        return None
    return asset


def latest_current_revision_asset(session: Session, shot: Shot, asset_type: AssetType) -> Asset | None:
    return session.exec(
        select(Asset)
        .where(
            Asset.shot_id == shot.id,
            Asset.type == asset_type,
            Asset.revision == shot.spec_revision,
            col(Asset.status).in_([AssetStatus.ACTIVE.value, AssetStatus.APPROVED.value]),
        )
        .order_by(col(Asset.created_at).desc(), col(Asset.id).desc())
    ).first()


def supersede_current_asset(session: Session, asset_id: int | None, *, superseded_by: int | None) -> None:
    asset = session.get(Asset, asset_id) if asset_id else None
    if asset is None or asset.id == superseded_by:
        return
    asset.status = AssetStatus.SUPERSEDED
    asset.superseded_by_asset_id = superseded_by
    session.add(asset)


def _copy_current_approved_keyframe_for_revision(session: Session, shot: Shot) -> Asset | None:
    previous = session.get(Asset, shot.approved_keyframe_asset_id) if shot.approved_keyframe_asset_id else None
    if previous is None:
        return None
    if previous.type != AssetType.KEYFRAME or previous.status != AssetStatus.APPROVED:
        return None
    copied = Asset(
        project_id=previous.project_id,
        shot_id=previous.shot_id,
        type=previous.type,
        status=AssetStatus.APPROVED,
        revision=shot.spec_revision,
        path=previous.path,
        mime_type=previous.mime_type,
        source_asset_id=previous.source_asset_id,
        sha256=previous.sha256,
        file_size=previous.file_size,
        width=previous.width,
        height=previous.height,
        duration_seconds=previous.duration_seconds,
        fps=previous.fps,
        frame_count=previous.frame_count,
        video_codec=previous.video_codec,
        audio_codec=previous.audio_codec,
    )
    session.add(copied)
    session.flush()
    previous.status = AssetStatus.SUPERSEDED
    previous.superseded_by_asset_id = copied.id
    session.add(previous)
    return copied


def get_current_approved_keyframe(session: Session, shot: Shot) -> Asset | None:
    asset = current_asset_by_id(session, shot.approved_keyframe_asset_id, revision=shot.spec_revision)
    return asset if asset and asset.type == AssetType.KEYFRAME else None


def get_current_display_keyframe(session: Session, shot: Shot) -> Asset | None:
    return get_current_approved_keyframe(session, shot) or latest_current_revision_asset(session, shot, AssetType.KEYFRAME)


def get_current_approved_video(session: Session, shot: Shot) -> Asset | None:
    asset = current_asset_by_id(session, shot.approved_video_asset_id, revision=shot.spec_revision)
    return asset if asset and asset.type == AssetType.VIDEO and asset.status == AssetStatus.APPROVED else None


def get_current_locked_tail_frame(session: Session, shot: Shot) -> Asset | None:
    asset = current_asset_by_id(session, shot.locked_tail_frame_asset_id, revision=shot.spec_revision)
    return asset if asset and asset.type == AssetType.TAIL_FRAME else None


def invalidate_shot_assets(
    session: Session,
    shot: Shot,
    *,
    asset_types: set[AssetType],
    clear_keyframe: bool = False,
    clear_video: bool = False,
    clear_tail: bool = False,
) -> list[int]:
    invalidated: list[int] = []
    for asset in session.exec(
        select(Asset).where(
            Asset.shot_id == shot.id,
            col(Asset.type).in_([item.value for item in asset_types]),
            col(Asset.status).in_([AssetStatus.ACTIVE.value, AssetStatus.APPROVED.value]),
        )
    ).all():
        asset.status = AssetStatus.STALE
        session.add(asset)
        if asset.id is not None:
            invalidated.append(asset.id)
    if clear_keyframe:
        shot.approved_keyframe_asset_id = None
    if clear_video:
        shot.approved_video_asset_id = None
    if clear_tail:
        shot.locked_tail_frame_asset_id = None
    session.add(shot)
    return invalidated


def invalidate_downstream_shots(session: Session, shot: Shot, *, reason: str) -> list[int]:
    affected: list[int] = []
    downstream = list(
        session.exec(
            select(Shot)
            .where(Shot.project_id == shot.project_id, Shot.sort_order > shot.sort_order)
            .order_by(col(Shot.sort_order))
        ).all()
    )
    for child in downstream:
        if child.start_frame_source_type == StartFrameSourceType.MANUAL:
            break
        if child.start_frame_source_type != StartFrameSourceType.INHERITED:
            continue
        _clear_start_frame(session, child)
        invalidate_shot_assets(
            session,
            child,
            asset_types={AssetType.VIDEO, AssetType.TAIL_FRAME},
            clear_video=True,
            clear_tail=True,
        )
        previous = child.status
        child.status = ShotStatus.KEYFRAME_APPROVED if get_current_approved_keyframe(session, child) else ShotStatus.DRAFT
        child.updated_at = utcnow()
        session.add(child)
        session.add(ShotStateChange(shot_id=child.id or 0, from_status=previous, to_status=child.status, reason=reason))
        if child.id is not None:
            affected.append(child.id)
    return affected


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
            status=AssetStatus.STALE if request.shot_spec_revision != shot.spec_revision else AssetStatus.ACTIVE,
            revision=request.shot_spec_revision,
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
        if request.shot_spec_revision == shot.spec_revision:
            transition_shot(session, shot, next_status, f"{request.kind.value.lower()}_generation_succeeded")
            log_task(session, request, shot, f"{request.kind.value.lower()} request succeeded", task=task)
            if request.kind == GenerationKind.VIDEO:
                quality_service.maybe_run_video_quality_checks(session, shot.id or 0, asset.id)
        else:
            task_service.record_task_error(
                session,
                task.id or 0,
                error_code="STALE_SPEC_REVISION",
                error_message="Task result was produced for an older shot spec revision.",
            )
            log_task(session, request, shot, "stale generation result registered without advancing shot", task=task)
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
    if shot.status != ShotStatus.KEYFRAME_REVIEW:
        raise AppError("INVALID_SHOT_STATE", "Keyframe approval requires KEYFRAME_REVIEW status.", 409)
    asset = latest_current_revision_asset(session, shot, AssetType.KEYFRAME)
    if asset is None:
        raise AppError("KEYFRAME_ASSET_MISSING", "Cannot approve without a current keyframe asset.", 409)
    supersede_current_asset(session, shot.approved_keyframe_asset_id, superseded_by=asset.id)
    asset.status = AssetStatus.APPROVED
    asset.revision = shot.spec_revision
    shot.approved_keyframe_asset_id = asset.id
    session.add(asset)
    session.add(shot)
    transition_shot(session, shot, ShotStatus.KEYFRAME_APPROVED, "keyframe_approved", commit=False)
    validate_shot_invariants(session, shot)
    session.commit()
    session.refresh(shot)
    return shot


def reject_keyframe(session: Session, shot_id: int) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    asset = latest_current_revision_asset(session, shot, AssetType.KEYFRAME)
    if asset is not None:
        asset.status = AssetStatus.REJECTED
        session.add(asset)
        session.commit()
    return transition_shot(session, shot, ShotStatus.DRAFT, "keyframe_rejected")


def approve_video(session: Session, shot_id: int) -> Shot:
    settings = get_settings()
    shot = get_shot_or_404(session, shot_id)
    if shot.status == ShotStatus.COMPLETED:
        return shot
    if shot.status != ShotStatus.VIDEO_REVIEW:
        raise AppError("INVALID_SHOT_STATE", "Video approval requires VIDEO_REVIEW status.", 409)
    video = latest_current_revision_asset(session, shot, AssetType.VIDEO)
    if video is None:
        raise AppError("VIDEO_ASSET_MISSING", "Cannot extract tail frame without a video asset.", 409)
    video_path = Path(video.path)
    if not video_path.exists():
        raise AppError("VIDEO_ASSET_FILE_MISSING", "Cannot extract tail frame because the video file is missing.", 409)
    temp_dir = settings.storage_dir / "temp" / "tails"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_tail_path = temp_dir / f"shot-{shot.id}-{uuid4().hex}.png"
    final_tail_path = (
        settings.storage_dir
        / f"project-{shot.project_id}"
        / f"shot-{shot.id}"
        / f"tail-frame-shot-{shot.id}-rev-{shot.spec_revision}-{uuid4().hex}.png"
    )
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
                    status=AssetStatus.APPROVED,
                    revision=shot.spec_revision,
                    path=str(final_tail_path),
                    mime_type="image/png",
                    source_asset_id=video.id,
                )
                session.add(tail_asset)
                session.flush()
            else:
                tail_asset.path = str(final_tail_path)
                tail_asset.status = AssetStatus.APPROVED
                tail_asset.revision = shot.spec_revision
                session.add(tail_asset)
                session.flush()
            supersede_current_asset(session, shot.approved_video_asset_id, superseded_by=video.id)
            video.status = AssetStatus.APPROVED
            video.revision = shot.spec_revision
            shot.approved_video_asset_id = video.id
            shot.locked_tail_frame_asset_id = tail_asset.id
            session.add(video)
            session.add(shot)
            transition_shot(session, shot, ShotStatus.TAIL_FRAME_LOCKED, "tail_frame_extracted", commit=False)
            rebuild_project_continuity_chain(session, shot.project_id, reason="tail_frame_locked")
            transition_shot(session, shot, ShotStatus.COMPLETED, "shot_completed", commit=False)
            validate_project_continuity_invariants(session, shot.project_id)
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
    asset = latest_current_revision_asset(session, shot, AssetType.VIDEO)
    if asset is not None:
        asset.status = AssetStatus.REJECTED
        session.add(asset)
        session.commit()
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
    list[dict[str, object]],
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
    quality_checks = [
        quality_payload(item)
        for shot in shots
        for item in quality_service.list_shot_quality_checks(session, shot.id or 0)
        if shot.id is not None
    ]
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
    return project, serialized_shots, serialized_assets, requests, tasks, renders, project_completion(shots, assets), quality_checks, logs


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


def quality_payload(result: object) -> dict[str, object]:
    details_json = getattr(result, "details_json", "{}")
    try:
        details = json.loads(details_json) if isinstance(details_json, str) else {}
    except json.JSONDecodeError:
        details = {}
    return {
        "id": getattr(result, "id", None),
        "project_id": getattr(result, "project_id", None),
        "shot_id": getattr(result, "shot_id", None),
        "asset_id": getattr(result, "asset_id", None),
        "reference_asset_id": getattr(result, "reference_asset_id", None),
        "check_type": getattr(result, "check_type", ""),
        "severity": getattr(result, "severity", None),
        "score": getattr(result, "score", None),
        "threshold": getattr(result, "threshold", None),
        "message": getattr(result, "message", ""),
        "details_json": details_json,
        "details": details,
        "algorithm_version": getattr(result, "algorithm_version", "quality-v1"),
        "created_at": getattr(result, "created_at", None),
    }


def project_completion(shots: list[Shot], assets: list[Asset]) -> dict[str, object]:
    video_by_id = {asset.id: asset for asset in assets if asset.id is not None}
    missing: list[int] = []
    estimated = 0.0
    for shot in shots:
        if shot.id is None:
            continue
        video = video_by_id.get(shot.approved_video_asset_id or -1)
        if shot.status != ShotStatus.COMPLETED or video is None or video.status != AssetStatus.APPROVED or video.revision != shot.spec_revision:
            missing.append(shot.id)
            continue
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
        "status": asset.status,
        "revision": asset.revision,
        "superseded_by_asset_id": asset.superseded_by_asset_id,
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
        "status": asset.status,
        "revision": asset.revision,
        "created_at": asset.created_at,
    }


def shot_payload(session: Session, shot: Shot) -> dict[str, object]:
    start_asset = session.get(Asset, shot.start_frame_asset_id) if shot.start_frame_asset_id else None
    start_source_type = shot.start_frame_source_type.value.lower()
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
        "spec_revision": shot.spec_revision,
        "approved_keyframe_asset_id": shot.approved_keyframe_asset_id,
        "approved_video_asset_id": shot.approved_video_asset_id,
        "locked_tail_frame_asset_id": shot.locked_tail_frame_asset_id,
        "start_frame_source_type": shot.start_frame_source_type,
        "start_frame": asset_summary(session, start_asset, start_source_type),
        "target_keyframe": asset_summary(session, get_current_display_keyframe(session, shot), "generated"),
        "locked_tail_frame": asset_summary(
            session,
            get_current_locked_tail_frame(session, shot),
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
