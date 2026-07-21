from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.models.entities import (
    Asset,
    AssetType,
    GenerationKind,
    GenerationRequest,
    GenerationTask,
    GenerationTaskType,
    GenerationUsageRecord,
    PricingReviewStatus,
    Project,
    ProviderAdapterType,
    ProviderModelGenerationType,
    ProviderModelProfile,
    ProviderProfile,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    ReliableTaskStatus,
    Shot,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
    utcnow,
)
from app.models.schemas import ProviderVerificationRunRead
from app.services import provider_management
from app.services.toapis_recovery_billing import review_recovery_console_billing
from app.services.toapis_recovery_planning import (
    EXPECTED_PRICING_HASH,
    build_recovery_plan,
    create_authorized_recovery_run,
    start_authorized_recovery_run,
)
from app.services.video_input_normalization import normalize_video_input_frame


def _png(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> tuple[str, int]:
    from PIL import Image

    Image.new("RGB", size, color).save(path, format="PNG")
    payload = path.read_bytes()
    return sha256(payload).hexdigest(), len(payload)


def _configured_failed_run(session: Session, tmp_path: Path) -> ProviderVerificationRun:
    profile = ProviderProfile(
        name="TOAPIS", provider_key="toapis", adapter_type=ProviderAdapterType.TOAPIS,
        preflight_image_model_accessible=True, preflight_video_model_accessible=True,
        account_balance_reviewed_at=utcnow(), account_balance_sufficient=True,
        account_balance_pricing_snapshot_hash=EXPECTED_PRICING_HASH,
        account_balance_confirmed_units="190", account_balance_evidence_type="TOKEN_BALANCE_READ_ONLY",
        live_orchestration_enabled=False,
    )
    session.add(profile)
    session.flush()
    for key, kind in (("image", ProviderModelGenerationType.IMAGE), ("video", ProviderModelGenerationType.VIDEO)):
        session.add(ProviderModelProfile(
            provider_profile_id=profile.id or 0, model_key=key, generation_type=kind,
            pricing_review_status=PricingReviewStatus.REVIEWED, pricing_reviewed_at=utcnow(),
            pricing_snapshot_hash=EXPECTED_PRICING_HASH, billing_unit="TOAPIS_CREDIT",
        ))
    project = Project(name="recovery")
    session.add(project)
    session.flush()
    shot = Shot(project_id=project.id or 0, title="shot", duration_seconds=4, prompt="", sort_order=0)
    session.add(shot)
    session.flush()
    start_path, end_path = tmp_path / "start.png", tmp_path / "end.png"
    start_sha, start_size = _png(start_path, (1280, 720), (80, 120, 160))
    end_sha, end_size = _png(end_path, (2848, 1600), (160, 120, 80))
    start = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.START_FRAME, path=str(start_path), mime_type="image/png", sha256=start_sha, file_size=start_size, width=1280, height=720)
    end = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.KEYFRAME, path=str(end_path), mime_type="image/png", sha256=end_sha, file_size=end_size, width=2848, height=1600)
    session.add(start)
    session.add(end)
    session.flush()
    image_request = GenerationRequest(project_id=project.id or 0, shot_id=shot.id or 0, kind=GenerationKind.KEYFRAME, provider_name="toapis")
    video_request = GenerationRequest(project_id=project.id or 0, shot_id=shot.id or 0, kind=GenerationKind.VIDEO, provider_name="toapis")
    session.add(image_request)
    session.add(video_request)
    session.flush()
    image_task = GenerationTask(generation_request_id=image_request.id or 0, project_id=project.id or 0, shot_id=shot.id or 0, task_type=GenerationTaskType.KEYFRAME_GENERATION, provider_id="toapis", status=ReliableTaskStatus.SUCCEEDED, remote_job_id="image:test-image", idempotency_key="image-root", result_asset_id=end.id)
    video_task = GenerationTask(generation_request_id=video_request.id or 0, project_id=project.id or 0, shot_id=shot.id or 0, task_type=GenerationTaskType.VIDEO_GENERATION, provider_id="toapis", status=ReliableTaskStatus.FAILED, idempotency_key="video-root", error_code="CONFIGURATION_ERROR", error_message="ANCHOR_ASPECT_RATIO_MISMATCH")
    session.add(image_task)
    session.add(video_task)
    session.flush()
    run = ProviderVerificationRun(
        provider_profile_id=profile.id or 0,
        verification_type=ProviderVerificationType.LIVE_CHAIN,
        status=ProviderVerificationStatus.FAILED,
        current_stage="FAILED",
        failure_code="ANCHOR_ASPECT_RATIO_MISMATCH",
        verification_project_id=project.id,
        shot_1_id=shot.id,
        initial_anchor_asset_id=start.id,
        shot_1_keyframe_request_id=image_request.id,
        shot_1_video_request_id=video_request.id,
        pricing_snapshot_hash=EXPECTED_PRICING_HASH,
        billing_unit="TOAPIS_CREDIT",
    )
    session.add(run)
    session.add(GenerationUsageRecord(
        project_id=project.id or 0, shot_id=shot.id, generation_request_id=image_request.id,
        generation_task_id=image_task.id, attempt_number=1, record_type=UsageRecordType.MANUAL_ADJUSTMENT,
        status=UsageRecordStatus.ACTUAL, currency="TOAPIS_CREDIT", billing_unit="TOAPIS_CREDIT",
        estimated_cost="6.3", actual_cost="6.3", cost_source=UsageCostSource.MANUAL,
    ))
    session.add(ProviderVerificationRun(provider_profile_id=profile.id or 0, verification_type=ProviderVerificationType.LIVE_CANARY, status=ProviderVerificationStatus.PASSED))
    session.add(ProviderVerificationRun(provider_profile_id=profile.id or 0, verification_type=ProviderVerificationType.LIVE_VIDEO_CANARY, status=ProviderVerificationStatus.PASSED, actual_cost="20"))
    session.commit()
    normalize_video_input_frame(session, source_asset_id=start.id or 0, frame_role="START")
    normalize_video_input_frame(session, source_asset_id=end.id or 0, frame_role="END")
    session.refresh(run)
    return run


def test_recovery_plan_is_read_only_deterministic_and_counts_remote_submits(session: Session, tmp_path: Path) -> None:
    run = _configured_failed_run(session, tmp_path)
    before = len(session.exec(select(GenerationTask)).all()), len(session.exec(select(ProviderVerificationRun)).all())
    first = build_recovery_plan(session, failed_run_id=run.id or 0, maximum_billing_units=Decimal("190"), pricing_snapshot_hash=EXPECTED_PRICING_HASH)
    second = build_recovery_plan(session, failed_run_id=run.id or 0, maximum_billing_units=Decimal("190"), pricing_snapshot_hash=EXPECTED_PRICING_HASH)
    after = len(session.exec(select(GenerationTask)).all()), len(session.exec(select(ProviderVerificationRun)).all())
    assert first["ready"] is True
    assert first["recoveryPlanHash"] == second["recoveryPlanHash"]
    assert first["historicalImageSubmits"] == 1
    assert first["historicalVideoSubmits"] == 0
    assert first["remainingImageSubmitLimit"] == 1
    assert first["remainingVideoSubmitLimit"] == 2
    assert first["estimatedRemainingBillingUnits"] == "166.3"
    assert first["estimatedLineageBillingUnits"] == "172.6"
    assert first["networkCalled"] is False and first["databaseUpdated"] is False
    assert before == after
    failed = session.get(ProviderVerificationRun, run.id)
    assert failed is not None and failed.status == ProviderVerificationStatus.FAILED


def test_recovery_plan_rejects_live_or_remote_video(session: Session, tmp_path: Path) -> None:
    run = _configured_failed_run(session, tmp_path)
    profile = session.get(ProviderProfile, run.provider_profile_id)
    assert profile is not None
    profile.live_orchestration_enabled = True
    video = session.exec(select(GenerationTask).where(GenerationTask.task_type == GenerationTaskType.VIDEO_GENERATION)).one()
    video.remote_job_id = "video:conflict"
    session.add(profile)
    session.add(video)
    session.commit()
    plan = build_recovery_plan(session, failed_run_id=run.id or 0, maximum_billing_units=Decimal("190"), pricing_snapshot_hash=EXPECTED_PRICING_HASH)
    assert plan["ready"] is False
    assert plan["checks"]["liveDisabled"] is False
    assert plan["checks"]["failureBeforeProviderCall"] is False
    assert plan["checks"]["noRemoteConflict"] is False


def test_recovery_run_requires_authorization_and_current_hash(session: Session, tmp_path: Path) -> None:
    run = _configured_failed_run(session, tmp_path)
    plan = build_recovery_plan(session, failed_run_id=run.id or 0, maximum_billing_units=Decimal("190"), pricing_snapshot_hash=EXPECTED_PRICING_HASH)
    with pytest.raises(AppError, match="Explicit recovery authorization"):
        create_authorized_recovery_run(session, failed_run_id=run.id or 0, recovery_plan_hash=plan["recoveryPlanHash"], authorization_reference="")
    with pytest.raises(AppError, match="stale or invalid"):
        create_authorized_recovery_run(session, failed_run_id=run.id or 0, recovery_plan_hash="0" * 64, authorization_reference="test-authorization")
    recovery = create_authorized_recovery_run(session, failed_run_id=run.id or 0, recovery_plan_hash=plan["recoveryPlanHash"], authorization_reference="test-authorization")
    assert recovery.recovery_of_run_id == run.id
    assert recovery.reused_keyframe_asset_id == plan["reusedKeyframeAssetId"]
    assert recovery.verification_type == ProviderVerificationType.LIVE_TWO_SHOT_RECOVERY
    failed = session.get(ProviderVerificationRun, run.id)
    assert failed is not None and failed.status == ProviderVerificationStatus.FAILED
    duplicate = create_authorized_recovery_run(
        session,
        failed_run_id=run.id or 0,
        recovery_plan_hash=plan["recoveryPlanHash"],
        authorization_reference="test-authorization",
    )
    assert duplicate.id == recovery.id


def test_authorized_recovery_start_creates_one_pre_submit_retry(session: Session, tmp_path: Path) -> None:
    run = _configured_failed_run(session, tmp_path)
    plan = build_recovery_plan(session, failed_run_id=run.id or 0, maximum_billing_units=Decimal("190"), pricing_snapshot_hash=EXPECTED_PRICING_HASH)
    profile = session.get(ProviderProfile, run.provider_profile_id)
    assert profile is not None
    profile.live_orchestration_enabled = True
    session.add(profile)
    session.commit()
    recovery = start_authorized_recovery_run(
        session,
        failed_run_id=run.id or 0,
        recovery_plan_hash=plan["recoveryPlanHash"],
        authorization_reference="test-authorization",
    )
    retries = session.exec(select(GenerationTask).where(col(GenerationTask.retry_of_task_id).is_not(None))).all()
    assert len(retries) == 1
    assert retries[0].remote_job_id is None
    assert retries[0].max_attempts == 1
    assert retries[0].recovery_run_id == recovery.id
    assert recovery.status == ProviderVerificationStatus.RUNNING
    assert recovery.current_stage == "SHOT_1_VIDEO_REQUESTED"
    response = ProviderVerificationRunRead.model_validate(provider_management.verification_payload(recovery))
    assert response.recovery_of_run_id == run.id
    assert response.lineage_root_run_id == run.id
    assert response.verification_project_id == run.verification_project_id
    assert response.shot_1_id == run.shot_1_id
    assert response.shot_2_id == run.shot_2_id
    assert response.actual_cost is None
    again = start_authorized_recovery_run(
        session,
        failed_run_id=run.id or 0,
        recovery_plan_hash=plan["recoveryPlanHash"],
        authorization_reference="test-authorization",
    )
    assert again.id == recovery.id
    assert len(session.exec(select(GenerationTask).where(col(GenerationTask.retry_of_task_id).is_not(None))).all()) == 1


def test_recovery_billing_review_is_atomic_and_idempotent(session: Session, tmp_path: Path) -> None:
    failed = _configured_failed_run(session, tmp_path)
    plan = build_recovery_plan(session, failed_run_id=failed.id or 0, maximum_billing_units=Decimal("190"), pricing_snapshot_hash=EXPECTED_PRICING_HASH)
    recovery = create_authorized_recovery_run(
        session, failed_run_id=failed.id or 0, recovery_plan_hash=plan["recoveryPlanHash"], authorization_reference="test",
    )
    project_id = failed.verification_project_id or 0
    shot_id = failed.shot_1_id or 0
    for index, (kind, task_type, remote_id) in enumerate(
        [
            (GenerationKind.VIDEO, GenerationTaskType.VIDEO_GENERATION, "video:one"),
            (GenerationKind.KEYFRAME, GenerationTaskType.KEYFRAME_GENERATION, "image:two"),
            (GenerationKind.VIDEO, GenerationTaskType.VIDEO_GENERATION, "video:three"),
        ], start=1,
    ):
        request = GenerationRequest(project_id=project_id, shot_id=shot_id, kind=kind, provider_name="toapis")
        session.add(request)
        session.flush()
        session.add(GenerationTask(
            generation_request_id=request.id or 0, project_id=project_id, shot_id=shot_id,
            task_type=task_type, provider_id="toapis", status=ReliableTaskStatus.SUCCEEDED,
            remote_job_id=remote_id, max_attempts=1, idempotency_key=f"billing-{index}", recovery_run_id=recovery.id,
        ))
    recovery.status = ProviderVerificationStatus.PASSED
    session.add(recovery)
    session.commit()
    recovery_tasks = session.exec(select(GenerationTask).where(GenerationTask.recovery_run_id == recovery.id)).all()
    reviews = {task.id or 0: (task.remote_job_id or "", Decimal(str(index))) for index, task in enumerate(recovery_tasks, start=1)}
    result = review_recovery_console_billing(
        session, run_id=recovery.id or 0, acknowledged=True, task_reviews=reviews,
        billing_unit="TOAPIS_CREDIT", evidence_type="TOAPIS_CONSOLE_REVIEW",
    )
    assert result["recovery_actual_billing_units"] == "6"
    assert result["lineage_actual_billing_units"] == "12.3"
    again = review_recovery_console_billing(
        session, run_id=recovery.id or 0, acknowledged=True, task_reviews=reviews,
        billing_unit="TOAPIS_CREDIT", evidence_type="TOAPIS_CONSOLE_REVIEW",
    )
    assert again == result
    with pytest.raises(AppError, match="different manual billing review"):
        changed = dict(reviews)
        task_id = next(iter(changed))
        changed[task_id] = (changed[task_id][0], Decimal("99"))
        review_recovery_console_billing(
            session, run_id=recovery.id or 0, acknowledged=True, task_reviews=changed,
            billing_unit="TOAPIS_CREDIT", evidence_type="TOAPIS_CONSOLE_REVIEW",
        )
