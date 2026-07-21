from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    GenerationKind,
    GenerationRequest,
    Project,
    ProjectRender,
    ProjectRenderStatus,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ReliableTaskStatus,
    Shot,
    ShotStatus,
    ToApisVerificationStage,
    utcnow,
)
from app.models.schemas import GenerationStartRequest, ProjectCreate, ShotCreate
from app.providers.config_loader import load_registry
from app.services import live_orchestration, provider_management, provider_resolution, studio, structured
from app.workers import render_service

WORKFLOW_VERSION = "toapis-two-shot-v1"
SHOT_PROMPTS = {
    (1, GenerationKind.KEYFRAME): "The same small red toy robot stands on a clean light-gray studio tabletop beside the same blue cube. The robot has just turned its head toward the cube. Fixed camera, stable composition, consistent proportions and colors, soft studio lighting, 16:9, no text, no logo, no watermark, no extra objects.",
    (1, GenerationKind.VIDEO): "The small red toy robot slowly turns its head toward the blue cube. Keep the camera completely fixed. Preserve the robot design, colors, tabletop, lighting and object positions. Smooth subtle motion, no new objects, no text, no logo, no watermark.",
    (2, GenerationKind.KEYFRAME): "The same small red toy robot on the same light-gray studio tabletop gently raises its right hand toward the same blue cube. Fixed camera, stable composition, consistent proportions and colors, soft studio lighting, 16:9, no text, no logo, no watermark, no extra objects.",
    (2, GenerationKind.VIDEO): "The same red toy robot gently raises its right hand toward the blue cube. Continue naturally from the provided first frame. Keep the camera fixed and preserve the robot design, colors, tabletop, lighting and cube position. Smooth subtle motion, no new objects, no text, no logo, no watermark.",
}
IMAGE_LIMIT = 2
VIDEO_LIMIT = 2
ABSOLUTE_BILLING_LIMIT = Decimal("500")
TERMINAL_TASK_STATUSES = {
    ReliableTaskStatus.FAILED,
    ReliableTaskStatus.CANCELLED,
}
WAITING_TASK_STATUSES = {
    ReliableTaskStatus.QUEUED,
    ReliableTaskStatus.SUBMITTING,
    ReliableTaskStatus.RUNNING,
    ReliableTaskStatus.RETRY_WAIT,
    ReliableTaskStatus.RESULT_READY,
    ReliableTaskStatus.PROCESSING_RESULT,
    ReliableTaskStatus.CANCELLING,
}
TERMINAL_STAGES = {
    ToApisVerificationStage.PASSED,
    ToApisVerificationStage.FAILED,
    ToApisVerificationStage.BLOCKED,
    ToApisVerificationStage.CANCELLED,
}


def advance(session: Session, run_id: int) -> dict[str, Any]:
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
        run = session.get(ProviderVerificationRun, run_id)
    else:
        run = session.exec(
            select(ProviderVerificationRun).where(ProviderVerificationRun.id == run_id).with_for_update()
        ).first()
    if run is None or run.verification_type.value != "LIVE_CHAIN":
        raise AppError("PROVIDER_VERIFICATION_RUN_NOT_FOUND", "Provider verification run was not found.", 404)
    stage = _stage(run)
    if stage in TERMINAL_STAGES:
        result = payload(session, run)
        session.commit()
        return result
    run.state_version += 1
    session.add(run)
    try:
        _advance_one(session, run, stage)
    except AppError as exc:
        _fail(session, run, stage, exc.code)
    except Exception:
        _fail(session, run, stage, "VERIFICATION_STEP_FAILED")
    session.commit()
    session.refresh(run)
    result = payload(session, run)
    session.commit()
    return result


def set_initial_anchor(session: Session, run_id: int, *, content: bytes, content_type: str | None) -> dict[str, Any]:
    run = session.get(ProviderVerificationRun, run_id)
    if run is None:
        raise AppError("PROVIDER_VERIFICATION_RUN_NOT_FOUND", "Provider verification run was not found.", 404)
    if _stage(run) != ToApisVerificationStage.PROJECT_READY or run.verification_project_id is None:
        raise AppError("VERIFICATION_ANCHOR_STAGE_INVALID", "Initial anchor can only be set after project creation and before Shot creation.", 409)
    asset = studio.create_project_image_asset(
        session, run.verification_project_id, content=content, content_type=content_type,
    )
    run.initial_anchor_asset_id = asset.id
    session.add(run)
    session.commit()
    return payload(session, run)


def _advance_one(session: Session, run: ProviderVerificationRun, stage: ToApisVerificationStage) -> None:
    if stage == ToApisVerificationStage.CREATED:
        _create_project(session, run)
    elif stage == ToApisVerificationStage.PROJECT_READY:
        _create_shots_and_anchor(session, run)
    elif stage == ToApisVerificationStage.SHOTS_READY:
        _create_generation(session, run, shot_number=1, kind=GenerationKind.KEYFRAME)
    elif stage == ToApisVerificationStage.SHOT_1_KEYFRAME_REQUESTED:
        _wait_for_review(session, run, run.shot_1_keyframe_request_id, run.shot_1_id, ShotStatus.KEYFRAME_REVIEW, ToApisVerificationStage.SHOT_1_KEYFRAME_READY)
    elif stage == ToApisVerificationStage.SHOT_1_KEYFRAME_READY:
        _approve_keyframe(session, run, 1)
    elif stage == ToApisVerificationStage.SHOT_1_KEYFRAME_APPROVED:
        _create_generation(session, run, shot_number=1, kind=GenerationKind.VIDEO)
    elif stage == ToApisVerificationStage.SHOT_1_VIDEO_REQUESTED:
        _wait_for_review(session, run, run.shot_1_video_request_id, run.shot_1_id, ShotStatus.VIDEO_REVIEW, ToApisVerificationStage.SHOT_1_VIDEO_READY)
    elif stage == ToApisVerificationStage.SHOT_1_VIDEO_READY:
        _approve_video(session, run, 1)
    elif stage == ToApisVerificationStage.SHOT_1_VIDEO_APPROVED:
        _verify_continuity(session, run)
    elif stage == ToApisVerificationStage.SHOT_2_START_FRAME_VERIFIED:
        _create_generation(session, run, shot_number=2, kind=GenerationKind.KEYFRAME)
    elif stage == ToApisVerificationStage.SHOT_2_KEYFRAME_REQUESTED:
        _wait_for_review(session, run, run.shot_2_keyframe_request_id, run.shot_2_id, ShotStatus.KEYFRAME_REVIEW, ToApisVerificationStage.SHOT_2_KEYFRAME_READY)
    elif stage == ToApisVerificationStage.SHOT_2_KEYFRAME_READY:
        _approve_keyframe(session, run, 2)
    elif stage == ToApisVerificationStage.SHOT_2_KEYFRAME_APPROVED:
        _verify_continuity(session, run)
        _create_generation(session, run, shot_number=2, kind=GenerationKind.VIDEO)
    elif stage == ToApisVerificationStage.SHOT_2_VIDEO_REQUESTED:
        _wait_for_review(session, run, run.shot_2_video_request_id, run.shot_2_id, ShotStatus.VIDEO_REVIEW, ToApisVerificationStage.SHOT_2_VIDEO_READY)
    elif stage == ToApisVerificationStage.SHOT_2_VIDEO_READY:
        _approve_video(session, run, 2)
    elif stage == ToApisVerificationStage.SHOT_2_VIDEO_APPROVED:
        _create_render(session, run)
    elif stage == ToApisVerificationStage.RENDER_REQUESTED:
        _wait_render(session, run)
    elif stage == ToApisVerificationStage.RENDER_READY:
        _pass(session, run)


def _create_project(session: Session, run: ProviderVerificationRun) -> None:
    if run.verification_project_id is None:
        payload = ProjectCreate(
            name=f"TOAPIS verification run {run.id}",
            description="Isolated two-shot workflow verification project.",
            image_provider_id="toapis", video_provider_id="toapis",
            image_model=live_orchestration.IMAGE_MODEL_KEY,
            video_model=live_orchestration.VIDEO_MODEL_KEY,
            default_aspect_ratio="16:9", default_video_duration_seconds=4,
        )
        project = Project(**payload.model_dump())
        session.add(project)
        session.flush()
        run.verification_project_id = project.id
    _set_stage(session, run, ToApisVerificationStage.PROJECT_READY)


def _create_shots_and_anchor(session: Session, run: ProviderVerificationRun) -> None:
    if run.verification_project_id is None:
        raise AppError("VERIFICATION_PROJECT_MISSING", "Verification project is missing.", 409)
    shots = list(session.exec(select(Shot).where(Shot.project_id == run.verification_project_id).order_by(col(Shot.sort_order))).all())
    if not shots:
        shot_payloads = [
            ShotCreate(title="Verification Shot 1", duration_seconds=4, prompt=SHOT_PROMPTS[(1, GenerationKind.KEYFRAME)]),
            ShotCreate(title="Verification Shot 2", duration_seconds=4, prompt=SHOT_PROMPTS[(2, GenerationKind.KEYFRAME)]),
        ]
        shots = []
        for sort_order, payload in enumerate(shot_payloads):
            shot = Shot(project_id=run.verification_project_id, sort_order=sort_order, **payload.model_dump())
            session.add(shot)
            session.flush()
            structured.create_initial_shot_spec(session, shot, commit=False)
            shots.append(shot)
    if len(shots) != 2:
        raise AppError("VERIFICATION_SHOT_COUNT_INVALID", "Verification project must contain exactly two shots.", 409)
    run.shot_1_id, run.shot_2_id = shots[0].id, shots[1].id
    session.add(run)
    session.flush()
    if run.initial_anchor_asset_id is None:
        fixture = get_settings().fixture_dir / "mock-keyframe.png"
        if not fixture.is_file():
            raise AppError("VERIFICATION_ANCHOR_FIXTURE_MISSING", "Verification anchor fixture is missing.", 500)
        anchor = studio.create_project_image_asset(session, run.verification_project_id, content=fixture.read_bytes(), content_type="image/png")
        run.initial_anchor_asset_id = anchor.id
    shot_1 = studio.set_shot_start_frame(session, run.shot_1_id or 0, action="SELECT", asset_id=run.initial_anchor_asset_id)
    if shot_1.start_frame_asset_id != run.initial_anchor_asset_id:
        raise AppError("VERIFICATION_ANCHOR_ASSIGNMENT_FAILED", "Shot 1 initial anchor assignment failed.", 500)
    _set_stage(session, run, ToApisVerificationStage.SHOTS_READY)


def _create_generation(session: Session, run: ProviderVerificationRun, *, shot_number: int, kind: GenerationKind) -> None:
    _check_paid_gate(session, run, kind)
    shot_id = run.shot_1_id if shot_number == 1 else run.shot_2_id
    shot = studio.get_shot_or_404(session, shot_id or 0)
    shot.prompt = SHOT_PROMPTS[(shot_number, kind)]
    shot.updated_at = utcnow()
    session.add(shot)
    session.flush()
    project = studio.get_project_or_404(session, run.verification_project_id or 0)
    request_field = f"shot_{shot_number}_{'keyframe' if kind == GenerationKind.KEYFRAME else 'video'}_request_id"
    if getattr(run, request_field) is None:
        resolved = provider_resolution.resolve_generation(
            session, project=project, shot=shot, kind=kind,
            payload=GenerationStartRequest(provider_id="toapis", model=(live_orchestration.IMAGE_MODEL_KEY if kind == GenerationKind.KEYFRAME else live_orchestration.VIDEO_MODEL_KEY), duration_seconds=4 if kind == GenerationKind.VIDEO else None, aspect_ratio="16:9", seed=None),
            registry=load_registry(session),
        )
        if kind == GenerationKind.KEYFRAME:
            request = studio.start_keyframe_generation_atomic(session, shot=shot, resolved=resolved, request_payload=resolved.request_payload(shot))
        else:
            request = studio.start_video_generation_atomic(session, shot=shot, resolved=resolved, request_payload=resolved.request_payload(shot))
        provider_management.create_estimate_for_request(session, request)
        setattr(run, request_field, request.id)
    target = ToApisVerificationStage[f"SHOT_{shot_number}_{'KEYFRAME' if kind == GenerationKind.KEYFRAME else 'VIDEO'}_REQUESTED"]
    _set_stage(session, run, target)


def _wait_for_review(session: Session, run: ProviderVerificationRun, request_id: int | None, shot_id: int | None, expected_shot_status: ShotStatus, ready_stage: ToApisVerificationStage) -> None:
    if request_id is None:
        raise AppError("VERIFICATION_REQUEST_MISSING", "Verification generation request is missing.", 409)
    task = studio.active_or_latest_task_for_request(session, request_id)
    shot = studio.get_shot_or_404(session, shot_id or 0)
    if shot.status == expected_shot_status:
        _set_stage(session, run, ready_stage)
        return
    if task is None or task.status in WAITING_TASK_STATUSES:
        return
    if task.status in TERMINAL_TASK_STATUSES:
        failure_code = (
            task.error_message
            if task.error_message == "ANCHOR_ASPECT_RATIO_MISMATCH"
            else "GENERATION_TASK_TERMINAL_FAILURE"
        )
        raise AppError(failure_code, "Verification generation task failed or was cancelled.", 409)


def _approve_keyframe(session: Session, run: ProviderVerificationRun, shot_number: int) -> None:
    shot_id = run.shot_1_id if shot_number == 1 else run.shot_2_id
    shot = studio.get_shot_or_404(session, shot_id or 0)
    if run.auto_approve_for_verification:
        studio.approve_keyframe(session, shot_id or 0)
        _audit_approval(session, run, f"shot_{shot_number}_keyframe")
    elif shot.status != ShotStatus.KEYFRAME_APPROVED:
        return
    _set_stage(session, run, ToApisVerificationStage[f"SHOT_{shot_number}_KEYFRAME_APPROVED"])


def _approve_video(session: Session, run: ProviderVerificationRun, shot_number: int) -> None:
    shot_id = run.shot_1_id if shot_number == 1 else run.shot_2_id
    shot = studio.get_shot_or_404(session, shot_id or 0)
    if run.auto_approve_for_verification:
        studio.approve_video(session, shot_id or 0)
        _audit_approval(session, run, f"shot_{shot_number}_video")
    elif shot.status != ShotStatus.COMPLETED:
        return
    _set_stage(session, run, ToApisVerificationStage[f"SHOT_{shot_number}_VIDEO_APPROVED"])


def _audit_approval(session: Session, run: ProviderVerificationRun, item: str) -> None:
    summary = provider_management.loads_dict(run.summary_json)
    approvals = summary.get("workflow_approvals")
    safe = [str(value) for value in approvals] if isinstance(approvals, list) else []
    marker = f"WORKFLOW_VERIFICATION_APPROVAL:{item}"
    if marker not in safe:
        safe.append(marker)
    summary["workflow_approvals"] = safe
    run.summary_json = provider_management.dumps(summary)
    session.add(run)
    session.commit()


def _verify_continuity(session: Session, run: ProviderVerificationRun) -> None:
    shot_1 = studio.get_shot_or_404(session, run.shot_1_id or 0)
    shot_2 = studio.get_shot_or_404(session, run.shot_2_id or 0)
    tail = session.get(Asset, shot_1.locked_tail_frame_asset_id) if shot_1.locked_tail_frame_asset_id else None
    inherited = session.get(Asset, shot_2.start_frame_asset_id) if shot_2.start_frame_asset_id else None
    valid = bool(
        tail and inherited and inherited.source_asset_id == tail.id
        and inherited.project_id == run.verification_project_id
        and inherited.shot_id == shot_2.id and inherited.type == AssetType.START_FRAME
        and inherited.revision == shot_2.spec_revision and inherited.status == AssetStatus.APPROVED
        and tail.type == AssetType.TAIL_FRAME and tail.shot_id == shot_1.id
        and Path(inherited.path).is_file() and Path(inherited.path).resolve() == Path(tail.path).resolve()
        and bool(tail.sha256)
        and bool(inherited.width) and bool(inherited.height) and bool(inherited.file_size)
    )
    if not valid:
        raise AppError("SHOT_2_START_FRAME_CONTINUITY_FAILED", "Shot 2 did not inherit Shot 1's validated local tail frame.", 409)
    if _stage(run) == ToApisVerificationStage.SHOT_1_VIDEO_APPROVED:
        _set_stage(session, run, ToApisVerificationStage.SHOT_2_START_FRAME_VERIFIED)


def _create_render(session: Session, run: ProviderVerificationRun) -> None:
    if run.render_id is None:
        render = render_service.create_project_render(session, project_id=run.verification_project_id or 0, idempotency_key=f"toapis-verification:{run.id}:render")
        run.render_id = render.id
    _set_stage(session, run, ToApisVerificationStage.RENDER_REQUESTED)


def _wait_render(session: Session, run: ProviderVerificationRun) -> None:
    render = session.get(ProjectRender, run.render_id) if run.render_id else None
    if render is None:
        raise AppError("VERIFICATION_RENDER_MISSING", "Verification render is missing.", 409)
    if render.status == ProjectRenderStatus.SUCCEEDED and render.output_asset_id:
        asset = session.get(Asset, render.output_asset_id)
        if asset is None or asset.type != AssetType.PROJECT_RENDER or not Path(asset.path).is_file():
            raise AppError("VERIFICATION_RENDER_ASSET_INVALID", "Verification render asset is invalid.", 409)
        run.final_render_asset_id = asset.id
        _set_stage(session, run, ToApisVerificationStage.RENDER_READY)
    elif render.status in {ProjectRenderStatus.FAILED, ProjectRenderStatus.CANCELLED}:
        raise AppError("VERIFICATION_RENDER_FAILED", "Verification render failed or was cancelled.", 409)


def _check_paid_gate(session: Session, run: ProviderVerificationRun, kind: GenerationKind) -> None:
    live_orchestration.validate_live_orchestration_gate(
        session, expected_snapshot_hash=run.pricing_snapshot_hash,
        exclude_verification_run_id=run.id, check_active_verification=True,
        required_billing_units=_decimal(run.max_cost, "BUDGET_NOT_CONFIRMED"),
    )
    if run.billing_unit != live_orchestration.BILLING_UNIT:
        raise AppError("BILLING_UNIT_MISMATCH", "Verification billing unit changed.", 409)
    estimate = _decimal(run.estimated_billing_units, "PRICING_SCHEMA_INVALID")
    maximum = _decimal(run.max_cost, "BUDGET_NOT_CONFIRMED")
    if estimate > maximum or maximum > ABSOLUTE_BILLING_LIMIT:
        raise AppError("BLOCKED_BY_BUDGET", "Verification budget gate failed.", 409)
    count = session.exec(select(GenerationRequest).where(GenerationRequest.project_id == run.verification_project_id, GenerationRequest.kind == kind)).all()
    limit = IMAGE_LIMIT if kind == GenerationKind.KEYFRAME else VIDEO_LIMIT
    if len(count) >= limit:
        raise AppError("VERIFICATION_TASK_LIMIT_REACHED", "Verification generation request limit was reached.", 409)


def _decimal(value: str | None, code: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AppError(code, "A valid positive billing value is required.", 409) from exc
    if parsed <= 0:
        raise AppError(code, "A valid positive billing value is required.", 409)
    return parsed


def _set_stage(session: Session, run: ProviderVerificationRun, stage: ToApisVerificationStage) -> None:
    run.current_stage = stage.value
    run.status = ProviderVerificationStatus.PASSED if stage == ToApisVerificationStage.PASSED else ProviderVerificationStatus.RUNNING
    session.add(run)
    session.commit()


def _fail(session: Session, run: ProviderVerificationRun, stage: ToApisVerificationStage, code: str) -> None:
    session.rollback()
    run = session.get(ProviderVerificationRun, run.id or 0) or run
    run.status = ProviderVerificationStatus.FAILED
    run.current_stage = ToApisVerificationStage.FAILED.value
    run.failure_stage = stage.value
    run.failure_code = code
    run.error_code = code
    run.error_message = "TOAPIS verification workflow failed."
    run.completed_at = utcnow()
    profile = live_orchestration.get_toapis_profile(session)
    profile.live_orchestration_enabled = False
    session.add(profile)
    session.add(run)
    session.commit()


def _pass(session: Session, run: ProviderVerificationRun) -> None:
    run.status = ProviderVerificationStatus.PASSED
    run.current_stage = ToApisVerificationStage.PASSED.value
    run.completed_at = utcnow()
    profile = live_orchestration.get_toapis_profile(session)
    profile.live_orchestration_enabled = False
    session.add(profile)
    session.add(run)
    session.commit()


def _stage(run: ProviderVerificationRun) -> ToApisVerificationStage:
    try:
        return ToApisVerificationStage(run.current_stage)
    except ValueError as exc:
        raise AppError("VERIFICATION_STAGE_INVALID", "Verification stage is invalid.", 409) from exc


def payload(session: Session, run: ProviderVerificationRun) -> dict[str, Any]:
    requests = [value for value in [run.shot_1_keyframe_request_id, run.shot_1_video_request_id, run.shot_2_keyframe_request_id, run.shot_2_video_request_id] if value]
    image_count = len([item for item in requests if (request := session.get(GenerationRequest, item)) and request.kind == GenerationKind.KEYFRAME])
    video_count = len(requests) - image_count
    stage = _stage(run)
    waiting = "GENERATION_TASK" if stage.value.endswith("REQUESTED") and stage != ToApisVerificationStage.RENDER_REQUESTED else ("PROJECT_RENDER" if stage == ToApisVerificationStage.RENDER_REQUESTED else None)
    return {
        "run_id": run.id, "status": run.status, "stage": stage, "waiting_for": waiting,
        "project_id": run.verification_project_id,
        "shot_ids": [value for value in [run.shot_1_id, run.shot_2_id] if value],
        "request_ids": {key: value for key, value in {
            "shot_1_keyframe": run.shot_1_keyframe_request_id, "shot_1_video": run.shot_1_video_request_id,
            "shot_2_keyframe": run.shot_2_keyframe_request_id, "shot_2_video": run.shot_2_video_request_id,
        }.items() if value},
        "render_id": run.render_id, "final_render_asset_id": run.final_render_asset_id,
        "image_requests_created": image_count, "video_requests_created": video_count,
        "estimated_billing_units": run.estimated_billing_units, "actual_billing_units": run.actual_cost,
        "can_advance": waiting is None and stage not in TERMINAL_STAGES,
        "terminal": stage in TERMINAL_STAGES,
    }
