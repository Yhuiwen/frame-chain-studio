from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from app.core.config import BACKEND_ROOT
from app.core.errors import AppError
from app.models.entities import (
    Asset, AssetType, GenerationKind, GenerationRequest, Project, ProviderVerificationRun,
    ProviderVerificationStatus, ProviderVerificationType, ReliableTaskStatus, Shot, ShotStatus,
    ToApisVerificationStage, utcnow,
)
from app.models.schemas import GenerationStartRequest, ProjectCreate, ShotCreate
from app.providers.config_loader import load_registry
from app.services import live_orchestration, provider_management, provider_resolution, studio, structured

PROMPT = (
    "The small red toy robot makes one subtle, smooth movement toward the blue cube while the camera remains "
    "completely fixed. Preserve the exact robot design, colors, tabletop, lighting and cube position. Use the "
    "provided first and last frames as strict anchors. No new objects, no text, no logo, no watermark."
)
WAITING = {
    ReliableTaskStatus.QUEUED, ReliableTaskStatus.SUBMITTING, ReliableTaskStatus.RUNNING,
    ReliableTaskStatus.RETRY_WAIT, ReliableTaskStatus.RESULT_READY, ReliableTaskStatus.PROCESSING_RESULT,
}


def advance(session: Session, run_id: int) -> dict[str, Any]:
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    run = session.get(ProviderVerificationRun, run_id)
    if run is None or run.verification_type != ProviderVerificationType.LIVE_VIDEO_CANARY:
        raise AppError("VIDEO_CANARY_NOT_FOUND", "Video Canary run was not found.", 404)
    if run.status != ProviderVerificationStatus.RUNNING:
        return payload(session, run)
    try:
        _advance_one(session, run)
    except AppError as exc:
        session.rollback()
        run = session.get(ProviderVerificationRun, run_id) or run
        run.status = ProviderVerificationStatus.FAILED
        run.current_stage = ToApisVerificationStage.FAILED.value
        run.failure_code = exc.code
        run.error_code = exc.code
        run.error_message = "TOAPIS video Canary failed."
        run.completed_at = utcnow()
        profile = live_orchestration.get_toapis_profile(session)
        profile.live_orchestration_enabled = False
        session.add(profile)
        session.add(run)
    session.commit()
    session.refresh(run)
    return payload(session, run)


def _advance_one(session: Session, run: ProviderVerificationRun) -> None:
    if run.current_stage == "CREATED":
        project = Project(**ProjectCreate(
            name=f"TOAPIS first-last video Canary {run.id}", description="Isolated one-second video Canary.",
            video_provider_id="toapis", video_model=live_orchestration.VIDEO_MODEL_KEY,
            default_video_duration_seconds=1, default_aspect_ratio="16:9",
        ).model_dump())
        session.add(project)
        session.flush()
        run.verification_project_id = project.id
        run.current_stage = ToApisVerificationStage.PROJECT_READY.value
    elif run.current_stage == ToApisVerificationStage.PROJECT_READY.value:
        _create_frames(session, run)
    elif run.current_stage == ToApisVerificationStage.FRAMES_READY.value:
        _create_video_request(session, run)
    elif run.current_stage == ToApisVerificationStage.VIDEO_REQUESTED.value:
        _wait_result(session, run)


def _create_frames(session: Session, run: ProviderVerificationRun) -> None:
    project_id = run.verification_project_id or 0
    shots = session.exec(select(Shot).where(Shot.project_id == project_id)).all()
    if not shots:
        shot = Shot(project_id=project_id, sort_order=0, **ShotCreate(title="First-last video Canary", duration_seconds=1, prompt=PROMPT).model_dump())
        session.add(shot)
        session.flush()
        structured.create_initial_shot_spec(session, shot, commit=False)
        shots = [shot]
    if len(shots) != 1:
        raise AppError("VIDEO_CANARY_SHOT_LIMIT", "Video Canary requires exactly one Shot.", 409)
    run.shot_1_id = shots[0].id
    root = BACKEND_ROOT.parent
    start = root / ".run" / "toapis-video-canary-start.jpg"
    end = root / ".run" / "toapis-video-canary-end.jpg"
    if not start.is_file() or not end.is_file():
        raise AppError("VIDEO_CANARY_FRAMES_MISSING", "Prepared local video Canary frames are missing.", 409)
    if run.initial_anchor_asset_id is None:
        run.initial_anchor_asset_id = studio.create_project_image_asset(session, project_id, content=start.read_bytes(), content_type="image/jpeg").id
    if run.end_frame_asset_id is None:
        run.end_frame_asset_id = studio.create_project_image_asset(session, project_id, content=end.read_bytes(), content_type="image/jpeg").id
    first = session.get(Asset, run.initial_anchor_asset_id)
    last = session.get(Asset, run.end_frame_asset_id)
    if not first or not last or first.sha256 == last.sha256 or (first.width, first.height) != (last.width, last.height):
        raise AppError("VIDEO_CANARY_FRAME_IDENTITY_INVALID", "Prepared frame identity is invalid.", 409)
    studio.set_shot_start_frame(session, run.shot_1_id or 0, action="SELECT", asset_id=first.id)
    studio.set_shot_target_keyframe(session, run.shot_1_id or 0, asset_id=last.id or 0)
    studio.approve_keyframe(session, run.shot_1_id or 0)
    run.current_stage = ToApisVerificationStage.FRAMES_READY.value


def _create_video_request(session: Session, run: ProviderVerificationRun) -> None:
    live_orchestration.validate_live_orchestration_gate(
        session, expected_snapshot_hash=run.pricing_snapshot_hash,
        required_billing_units=Decimal(str(run.max_cost)),
        exclude_verification_run_id=run.id, check_active_verification=True,
    )
    requests = session.exec(select(GenerationRequest).where(GenerationRequest.project_id == run.verification_project_id)).all()
    if not requests:
        shot = studio.get_shot_or_404(session, run.shot_1_id or 0)
        project = studio.get_project_or_404(session, run.verification_project_id or 0)
        resolved = provider_resolution.resolve_generation(
            session, project=project, shot=shot, kind=GenerationKind.VIDEO,
            payload=GenerationStartRequest(provider_id="toapis", model=live_orchestration.VIDEO_MODEL_KEY, duration_seconds=1, seed=None),
            registry=load_registry(session),
        )
        request = studio.start_video_generation_atomic(session, shot=shot, resolved=resolved, request_payload=resolved.request_payload(shot))
        provider_management.create_estimate_for_request(session, request)
        run.shot_1_video_request_id = request.id
    elif len(requests) == 1 and requests[0].kind == GenerationKind.VIDEO:
        run.shot_1_video_request_id = requests[0].id
    else:
        raise AppError("VIDEO_CANARY_REQUEST_LIMIT", "Video Canary permits one video request only.", 409)
    run.current_stage = ToApisVerificationStage.VIDEO_REQUESTED.value


def _wait_result(session: Session, run: ProviderVerificationRun) -> None:
    task = studio.active_or_latest_task_for_request(session, run.shot_1_video_request_id or 0)
    if task is None or task.status in WAITING:
        return
    if task.status != ReliableTaskStatus.SUCCEEDED:
        raise AppError("VIDEO_CANARY_GENERATION_FAILED", "Video Canary generation failed.", 409)
    shot = studio.get_shot_or_404(session, run.shot_1_id or 0)
    if shot.status == ShotStatus.VIDEO_REVIEW:
        shot = studio.approve_video(session, shot.id or 0)
    video = session.get(Asset, shot.approved_video_asset_id) if shot.approved_video_asset_id else studio.latest_asset(session, shot.id or 0, AssetType.VIDEO)
    tail = session.get(Asset, shot.locked_tail_frame_asset_id) if shot.locked_tail_frame_asset_id else studio.latest_asset(session, shot.id or 0, AssetType.TAIL_FRAME)
    if not video or not tail or not video.width or not video.height or not video.duration_seconds or not Path(tail.path).is_file():
        raise AppError("VIDEO_CANARY_RESULT_INVALID", "Video or local tail-frame Asset is invalid.", 409)
    run.tail_frame_asset_id = tail.id
    run.final_render_asset_id = video.id
    run.status = ProviderVerificationStatus.PASSED
    run.current_stage = ToApisVerificationStage.PASSED.value
    run.completed_at = utcnow()
    profile = live_orchestration.get_toapis_profile(session)
    profile.live_orchestration_enabled = False
    session.add(profile)


def payload(session: Session, run: ProviderVerificationRun) -> dict[str, Any]:
    count = len(session.exec(select(GenerationRequest).where(GenerationRequest.project_id == run.verification_project_id)).all()) if run.verification_project_id else 0
    return {
        "run_id": run.id, "status": run.status, "stage": ToApisVerificationStage(run.current_stage),
        "project_id": run.verification_project_id, "shot_ids": [run.shot_1_id] if run.shot_1_id else [],
        "request_ids": {"video": run.shot_1_video_request_id} if run.shot_1_video_request_id else {},
        "render_id": None, "final_render_asset_id": run.final_render_asset_id,
        "image_requests_created": 0, "video_requests_created": count,
        "estimated_billing_units": run.estimated_billing_units, "actual_billing_units": run.actual_cost,
        "can_advance": run.status == ProviderVerificationStatus.RUNNING,
        "terminal": run.status != ProviderVerificationStatus.RUNNING,
    }
