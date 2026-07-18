import json
from pathlib import Path

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
    Project,
    Shot,
    ShotStateChange,
    ShotStatus,
    TaskLog,
    utcnow,
)
from app.models.schemas import ProjectCreate, ProjectUpdate, ReorderShot, ShotCreate, ShotUpdate
from app.providers.base import GenerationProvider


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
    project = Project(name=payload.name, description=payload.description)
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
    session.delete(project)
    session.commit()


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
    try:
        if next_shot is not None:
            relink_start_frame_after_delete(session, previous_shot, next_shot)

        for state_change in session.exec(select(ShotStateChange).where(ShotStateChange.shot_id == shot_id)).all():
            session.delete(state_change)
        for log in session.exec(select(TaskLog).where(TaskLog.shot_id == shot_id)).all():
            session.delete(log)
        for request in session.exec(select(GenerationRequest).where(GenerationRequest.shot_id == shot_id)).all():
            session.delete(request)
        assets_to_delete = list(session.exec(select(Asset).where(Asset.shot_id == shot_id)).all())
        asset_ids_to_delete = {asset.id for asset in assets_to_delete if asset.id is not None}
        for asset in assets_to_delete:
            references = session.exec(select(Asset).where(Asset.source_asset_id == asset.id)).all()
            external_references = [reference for reference in references if reference.id not in asset_ids_to_delete]
            if not external_references:
                session.delete(asset)

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
    requested_ids = {item.id for item in items}
    if requested_ids != set(shots):
        raise AppError("INVALID_SHOT_ORDER", "Reorder payload must include every shot in the project.", 400)
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
) -> None:
    session.add(ShotStateChange(shot_id=shot.id or 0, from_status=from_status, to_status=to_status, reason=reason))
    session.commit()


def transition_shot(session: Session, shot: Shot, target: ShotStatus, reason: str) -> Shot:
    previous = shot.status
    ensure_transition_allowed(previous, target)
    shot.status = target
    shot.updated_at = utcnow()
    session.add(shot)
    session.commit()
    session.refresh(shot)
    log_state(session, shot, previous, target, reason)
    return shot


def log_task(
    session: Session,
    request: GenerationRequest | None,
    shot: Shot | None,
    message: str,
    level: str = "INFO",
) -> None:
    session.add(
        TaskLog(
            request_id=request.id if request else None,
            shot_id=shot.id if shot else None,
            level=level,
            message=message,
        )
    )
    session.commit()


def create_generation_request(
    session: Session,
    shot: Shot,
    kind: GenerationKind,
    input_asset_ids: list[int] | None = None,
) -> GenerationRequest:
    request = GenerationRequest(
        project_id=shot.project_id,
        shot_id=shot.id or 0,
        kind=kind,
        provider_name="mock",
        prompt_snapshot=shot.prompt,
        negative_prompt_snapshot=shot.negative_prompt,
        input_asset_ids=json.dumps(input_asset_ids or []),
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    log_task(session, request, shot, f"{kind.value.lower()} request created")
    return request


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
        transition_shot(session, shot, next_status, f"{request.kind.value.lower()}_generation_succeeded")
        log_task(session, request, shot, f"{request.kind.value.lower()} request succeeded")
    except Exception as exc:
        request.status = GenerationTaskStatus.FAILED
        request.error_code = exc.__class__.__name__
        request.error_message = str(exc)
        request.updated_at = utcnow()
        session.add(request)
        session.commit()
        fallback = ShotStatus.DRAFT if request.kind == GenerationKind.KEYFRAME else ShotStatus.KEYFRAME_APPROVED
        transition_shot(session, shot, fallback, f"{request.kind.value.lower()}_generation_failed")
        log_task(session, request, shot, str(exc), "ERROR")
    session.refresh(request)
    return request


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
    transition_shot(session, shot, ShotStatus.VIDEO_APPROVED, "video_approved")
    video = latest_asset(session, shot_id, AssetType.VIDEO)
    if video is None:
        raise AppError("VIDEO_ASSET_MISSING", "Cannot extract tail frame without a video asset.", 409)
    tail_path = (
        settings.storage_dir
        / f"project-{shot.project_id}"
        / f"shot-{shot.id}"
        / f"tail-frame-shot-{shot.id}.png"
    )
    extract_tail_frame(Path(video.path), tail_path)
    tail_asset = session.exec(
        select(Asset).where(
            Asset.shot_id == shot.id,
            Asset.type == AssetType.TAIL_FRAME,
            Asset.source_asset_id == video.id,
        )
    ).first()
    if tail_asset is None:
        tail_asset = Asset(
            project_id=shot.project_id,
            shot_id=shot.id,
            type=AssetType.TAIL_FRAME,
            path=str(tail_path),
            mime_type="image/png",
            source_asset_id=video.id,
        )
        session.add(tail_asset)
        session.commit()
        session.refresh(tail_asset)
    transition_shot(session, shot, ShotStatus.TAIL_FRAME_LOCKED, "tail_frame_extracted")
    next_shot = session.exec(
        select(Shot)
        .where(Shot.project_id == shot.project_id, Shot.sort_order > shot.sort_order)
        .order_by(col(Shot.sort_order))
    ).first()
    if next_shot and tail_asset.id:
        start_asset = session.exec(
            select(Asset).where(
                Asset.shot_id == next_shot.id,
                Asset.type == AssetType.START_FRAME,
                Asset.source_asset_id == tail_asset.id,
            )
        ).first()
        if start_asset is None:
            start_asset = Asset(
                project_id=shot.project_id,
                shot_id=next_shot.id,
                type=AssetType.START_FRAME,
                path=tail_asset.path,
                mime_type=tail_asset.mime_type,
                source_asset_id=tail_asset.id,
            )
            session.add(start_asset)
            session.commit()
            session.refresh(start_asset)
        next_shot.start_frame_asset_id = start_asset.id
        next_shot.updated_at = utcnow()
        session.add(next_shot)
        session.commit()
    return transition_shot(session, shot, ShotStatus.COMPLETED, "shot_completed")


def reject_video(session: Session, shot_id: int) -> Shot:
    shot = get_shot_or_404(session, shot_id)
    return transition_shot(session, shot, ShotStatus.KEYFRAME_APPROVED, "video_rejected")


def project_detail(
    session: Session,
    project_id: int,
) -> tuple[Project, list[dict[str, object]], list[dict[str, object]], list[GenerationRequest], list[TaskLog]]:
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
    return project, serialized_shots, serialized_assets, requests, logs


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
        "created_at": shot.created_at,
        "updated_at": shot.updated_at,
    }
