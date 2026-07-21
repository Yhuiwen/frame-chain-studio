from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.models.entities import (
    Asset, AssetType, GenerationKind, GenerationRequest, GenerationUsageRecord, Project,
    ProviderVerificationRun, ProviderVerificationStatus, ProviderVerificationType,
    ReliableTaskStatus, Shot, ShotStatus, ToApisVerificationStage, UsageRecordType, utcnow,
)
from app.models.schemas import GenerationStartRequest, ProjectCreate, ShotCreate
from app.providers.config_loader import load_registry
from app.services import live_orchestration, provider_management, provider_resolution, studio, structured

PROMPT = "A small red toy robot standing beside a blue cube on a clean light-gray studio tabletop, fixed camera composition, soft studio lighting, simple product photography, 16:9, no text, no logo, no watermark, no extra objects."
WORKFLOW_VERSION = "toapis-image-canary-v1"
ESTIMATE = Decimal("6.3")
MAXIMUM = Decimal("10")
WAITING = {
    ReliableTaskStatus.QUEUED, ReliableTaskStatus.SUBMITTING, ReliableTaskStatus.RUNNING,
    ReliableTaskStatus.RETRY_WAIT, ReliableTaskStatus.RESULT_READY,
    ReliableTaskStatus.PROCESSING_RESULT, ReliableTaskStatus.CANCELLING,
}


def advance(session: Session, run_id: int) -> dict[str, Any]:
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
        run = session.get(ProviderVerificationRun, run_id)
    else:
        run = session.exec(select(ProviderVerificationRun).where(ProviderVerificationRun.id == run_id).with_for_update()).first()
    if run is None or run.verification_type != ProviderVerificationType.LIVE_CANARY:
        raise AppError("PROVIDER_VERIFICATION_RUN_NOT_FOUND", "Canary verification run was not found.", 404)
    if run.status in {ProviderVerificationStatus.PASSED, ProviderVerificationStatus.FAILED, ProviderVerificationStatus.FAILED_BUT_BILLED, ProviderVerificationStatus.BLOCKED, ProviderVerificationStatus.CANCELLED}:
        return payload(session, run)
    run.state_version += 1
    session.add(run)
    try:
        _advance_one(session, run)
    except AppError as exc:
        _fail(session, run, exc.code)
    except Exception:
        _fail(session, run, "CANARY_STEP_FAILED")
    session.commit()
    session.refresh(run)
    return payload(session, run)


def _advance_one(session: Session, run: ProviderVerificationRun) -> None:
    if run.current_stage == "CREATED":
        if run.verification_project_id is None:
            project = Project(**ProjectCreate(
                name=f"TOAPIS image canary {run.id}", description="Isolated one-image paid canary.",
                image_provider_id="toapis", image_model=live_orchestration.IMAGE_MODEL_KEY,
                default_aspect_ratio="16:9", default_seed=None,
            ).model_dump())
            session.add(project)
            session.flush()
            run.verification_project_id = project.id
        run.current_stage = ToApisVerificationStage.PROJECT_READY.value
    elif run.current_stage == ToApisVerificationStage.PROJECT_READY.value:
        shots = session.exec(select(Shot).where(Shot.project_id == run.verification_project_id)).all()
        if not shots:
            shot = Shot(project_id=run.verification_project_id or 0, sort_order=0, **ShotCreate(title="Paid image canary", duration_seconds=4, prompt=PROMPT).model_dump())
            session.add(shot)
            session.flush()
            structured.create_initial_shot_spec(session, shot, commit=False)
            shots = [shot]
        if len(shots) != 1:
            raise AppError("CANARY_SHOT_LIMIT_EXCEEDED", "Canary must contain exactly one Shot.", 409)
        run.shot_1_id = shots[0].id
        run.current_stage = ToApisVerificationStage.SHOTS_READY.value
    elif run.current_stage == ToApisVerificationStage.SHOTS_READY.value:
        _create_request(session, run)
    elif run.current_stage == ToApisVerificationStage.CANARY_REQUESTED.value:
        _wait_result(session, run)


def _create_request(session: Session, run: ProviderVerificationRun) -> None:
    maximum = Decimal(str(run.max_cost))
    live_orchestration.validate_live_orchestration_gate(
        session, expected_snapshot_hash=run.pricing_snapshot_hash,
        required_billing_units=maximum, exclude_verification_run_id=run.id,
        check_active_verification=True,
    )
    if maximum < ESTIMATE or maximum > MAXIMUM:
        raise AppError("BLOCKED_BY_CANARY_BUDGET", "Canary budget must be between 6.3 and 10 credits.", 409)
    existing = session.exec(select(GenerationRequest).where(GenerationRequest.project_id == run.verification_project_id)).all()
    if not existing:
        shot = studio.get_shot_or_404(session, run.shot_1_id or 0)
        project = studio.get_project_or_404(session, run.verification_project_id or 0)
        resolved = provider_resolution.resolve_generation(
            session, project=project, shot=shot, kind=GenerationKind.KEYFRAME,
            payload=GenerationStartRequest(provider_id="toapis", model=live_orchestration.IMAGE_MODEL_KEY, aspect_ratio="16:9", seed=None),
            registry=load_registry(session),
        )
        request = studio.start_keyframe_generation_atomic(session, shot=shot, resolved=resolved, request_payload=resolved.request_payload(shot))
        provider_management.create_estimate_for_request(session, request)
        run.shot_1_keyframe_request_id = request.id
    elif len(existing) == 1 and existing[0].kind == GenerationKind.KEYFRAME:
        run.shot_1_keyframe_request_id = existing[0].id
    else:
        raise AppError("CANARY_REQUEST_LIMIT_EXCEEDED", "Canary permits one image request and no video requests.", 409)
    run.current_stage = ToApisVerificationStage.CANARY_REQUESTED.value


def _wait_result(session: Session, run: ProviderVerificationRun) -> None:
    request = session.get(GenerationRequest, run.shot_1_keyframe_request_id) if run.shot_1_keyframe_request_id else None
    task = studio.active_or_latest_task_for_request(session, request.id or 0) if request else None
    if task is None or task.status in WAITING:
        return
    if task.status != ReliableTaskStatus.SUCCEEDED:
        raise AppError("CANARY_GENERATION_FAILED", "Canary generation task failed.", 409)
    shot = studio.get_shot_or_404(session, run.shot_1_id or 0)
    asset_ids = provider_management.loads_list(request.output_asset_ids) if request else []
    asset = session.get(Asset, int(asset_ids[0])) if asset_ids else None
    if shot.status != ShotStatus.KEYFRAME_REVIEW or asset is None or asset.type != AssetType.KEYFRAME or not Path(asset.path).is_file() or not asset.sha256 or not asset.width or not asset.height:
        raise AppError("CANARY_ASSET_INVALID", "Canary result Asset is invalid.", 409)
    actual = session.exec(select(GenerationUsageRecord).where(
        GenerationUsageRecord.generation_task_id == task.id,
        col(GenerationUsageRecord.record_type).in_([UsageRecordType.PROVIDER_REPORTED, UsageRecordType.MANUAL_ADJUSTMENT]),
    ).order_by(GenerationUsageRecord.record_type)).first()
    run.actual_cost = actual.actual_cost if actual and actual.actual_cost else run.actual_cost
    run.summary_json = provider_management.dumps({
        "usage_record_status": actual.status.value if actual else "NOT_REPORTED",
        "actual_billing_source": (
            "TOAPIS_CONSOLE_REVIEW" if actual and actual.record_type == UsageRecordType.MANUAL_ADJUSTMENT
            else "PROVIDER_RESPONSE" if actual else "UNKNOWN"
        ),
        "provider_request_id": "REDACTED",
        "asset_id": asset.id, "mime_type": asset.mime_type, "width": asset.width,
        "height": asset.height, "sha256": asset.sha256,
    })
    run.status = ProviderVerificationStatus.PASSED
    run.current_stage = ToApisVerificationStage.PASSED.value
    run.completed_at = utcnow()
    profile = live_orchestration.get_toapis_profile(session)
    profile.live_orchestration_enabled = False
    session.add(profile)


def _fail(session: Session, run: ProviderVerificationRun, code: str) -> None:
    run_id = run.id or 0
    session.rollback()
    run = session.get(ProviderVerificationRun, run_id) or run
    run.status = (
        ProviderVerificationStatus.FAILED_BUT_BILLED
        if run.actual_cost is not None else ProviderVerificationStatus.FAILED
    )
    run.current_stage = ToApisVerificationStage.FAILED.value
    run.failure_code = code
    run.error_code = code
    run.error_message = "TOAPIS image canary failed."
    run.completed_at = utcnow()
    profile = live_orchestration.get_toapis_profile(session)
    profile.live_orchestration_enabled = False
    session.add(profile)
    session.add(run)


def payload(session: Session, run: ProviderVerificationRun) -> dict[str, Any]:
    request_count = len(session.exec(select(GenerationRequest).where(GenerationRequest.project_id == run.verification_project_id)).all()) if run.verification_project_id else 0
    return {
        "run_id": run.id, "status": run.status, "stage": ToApisVerificationStage(run.current_stage),
        "waiting_for": "GENERATION_TASK" if run.current_stage == ToApisVerificationStage.CANARY_REQUESTED.value else None,
        "project_id": run.verification_project_id, "shot_ids": [run.shot_1_id] if run.shot_1_id else [],
        "request_ids": {"canary_image": run.shot_1_keyframe_request_id} if run.shot_1_keyframe_request_id else {},
        "render_id": None, "final_render_asset_id": None, "image_requests_created": request_count,
        "video_requests_created": 0, "estimated_billing_units": run.estimated_billing_units,
        "actual_billing_units": run.actual_cost, "can_advance": run.status == ProviderVerificationStatus.RUNNING,
        "terminal": run.status in {ProviderVerificationStatus.PASSED, ProviderVerificationStatus.FAILED, ProviderVerificationStatus.FAILED_BUT_BILLED, ProviderVerificationStatus.BLOCKED, ProviderVerificationStatus.CANCELLED},
    }
