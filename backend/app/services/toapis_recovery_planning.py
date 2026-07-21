from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.models.entities import (
    Asset,
    GenerationTask,
    GenerationUsageRecord,
    ProviderModelProfile,
    ProviderProfile,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    ReliableTaskStatus,
    UsageRecordType,
    VideoInputFrameNormalization,
)
from app.services.video_input_normalization import (
    MAX_OUTPUT_BYTES,
    NORMALIZATION_VERSION,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)

EXPECTED_PRICING_HASH = "6debc7c7a4995a1eefc7f055f11fe3ab5e06af0403628809619cf4143800d8b8"
HISTORICAL_BILLING = Decimal("6.3")
ESTIMATED_REMAINING = Decimal("166.3")
ESTIMATED_LINEAGE = Decimal("172.6")
MAXIMUM_LINEAGE = Decimal("190")


def repair_historical_anchor_failure_evidence(session: Session, *, failed_run_id: int) -> None:
    run = session.get(ProviderVerificationRun, failed_run_id)
    if run is None or run.status != ProviderVerificationStatus.FAILED or run.current_stage != "FAILED":
        raise AppError("FAILED_RUN_IDENTITY_INVALID", "The failed run identity is invalid.", 409)
    task = _failed_video_task(session, run)
    if task.remote_job_id is not None or task.error_message != "ANCHOR_ASPECT_RATIO_MISMATCH":
        raise AppError("FAILED_RUN_EVIDENCE_CONFLICT", "The failed run does not have pre-submit anchor evidence.", 409)
    if run.failure_code == "ANCHOR_ASPECT_RATIO_MISMATCH":
        return
    if run.failure_code != "GENERATION_TASK_TERMINAL_FAILURE":
        raise AppError("FAILED_RUN_EVIDENCE_CONFLICT", "The historical failure code cannot be corrected.", 409)
    summary = _loads(run.summary_json)
    summary["failure_evidence_corrected_from"] = run.failure_code
    summary["failure_evidence_source_task_id"] = task.id
    run.failure_code = "ANCHOR_ASPECT_RATIO_MISMATCH"
    run.error_code = "ANCHOR_ASPECT_RATIO_MISMATCH"
    run.summary_json = _dumps(summary)
    session.add(run)
    session.commit()


def build_recovery_plan(
    session: Session,
    *,
    failed_run_id: int,
    maximum_billing_units: Decimal,
    pricing_snapshot_hash: str,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    run = session.get(ProviderVerificationRun, failed_run_id)
    checks["failedRunExists"] = run is not None and run.verification_type == ProviderVerificationType.LIVE_CHAIN
    if run is None:
        return _empty_plan(failed_run_id, checks)
    checks["failedRunStatusValid"] = run.status == ProviderVerificationStatus.FAILED and run.current_stage == "FAILED"
    checks["failureCodeValid"] = run.failure_code == "ANCHOR_ASPECT_RATIO_MISMATCH"
    task = _failed_video_task_or_none(session, run)
    checks["failureBeforeProviderCall"] = bool(
        task and task.status == ReliableTaskStatus.FAILED and task.remote_job_id is None
        and task.error_message == "ANCHOR_ASPECT_RATIO_MISMATCH"
    )
    tasks = session.exec(
        select(GenerationTask).where(
            GenerationTask.project_id == run.verification_project_id,
            GenerationTask.provider_id == "toapis",
        )
    ).all()
    image_remote = sum(t.task_type.value == "KEYFRAME_GENERATION" and bool(t.remote_job_id) for t in tasks)
    video_remote = sum(t.task_type.value == "VIDEO_GENERATION" and bool(t.remote_job_id) for t in tasks)
    checks["historicalImageSubmitsValid"] = image_remote == 1
    checks["historicalVideoSubmitsValid"] = video_remote == 0
    checks["noRetryRemoteTask"] = not any(t.retry_of_task_id is not None or t.attempt_number != 1 for t in tasks)

    start = session.get(Asset, run.initial_anchor_asset_id) if run.initial_anchor_asset_id else None
    keyframe_task = session.exec(
        select(GenerationTask).where(GenerationTask.generation_request_id == run.shot_1_keyframe_request_id)
    ).first()
    keyframe = session.get(Asset, keyframe_task.result_asset_id) if keyframe_task and keyframe_task.result_asset_id else None
    start_norm = _normalization(session, start.id if start else None)
    end_norm = _normalization(session, keyframe.id if keyframe else None)
    checks["startAssetValid"] = _source_asset_valid(start)
    checks["keyframeAssetValid"] = _source_asset_valid(keyframe)
    checks["normalizedStartValid"] = _normalization_valid(session, start_norm, start)
    checks["normalizedEndValid"] = _normalization_valid(session, end_norm, keyframe)
    checks["normalizedDimensionsMatch"] = bool(
        start_norm and end_norm
        and _normalized_asset(session, start_norm).width == _normalized_asset(session, end_norm).width == TARGET_WIDTH
        and _normalized_asset(session, start_norm).height == _normalized_asset(session, end_norm).height == TARGET_HEIGHT
    )
    checks["noCropOrStretch"] = bool(
        start_norm and end_norm and not start_norm.crop_applied and not end_norm.crop_applied
        and start_norm.resize_mode == end_norm.resize_mode == "contain"
    )
    checks["noRemoteConflict"] = not any(
        t.task_type.value == "VIDEO_GENERATION" and bool(t.remote_job_id) for t in tasks
    )

    profile = session.exec(select(ProviderProfile).where(ProviderProfile.provider_key == "toapis")).one()
    now = datetime.now(timezone.utc)
    models = session.exec(select(ProviderModelProfile).where(ProviderModelProfile.provider_profile_id == profile.id)).all()
    checks["liveDisabled"] = not profile.live_orchestration_enabled
    checks["noActiveRuns"] = not session.exec(
        select(ProviderVerificationRun).where(
            col(ProviderVerificationRun.status).in_([ProviderVerificationStatus.PENDING, ProviderVerificationStatus.RUNNING])
        )
    ).first()
    checks["noUnfinishedTasks"] = not any(
        t.status not in {ReliableTaskStatus.SUCCEEDED, ReliableTaskStatus.FAILED, ReliableTaskStatus.CANCELLED}
        for t in session.exec(select(GenerationTask).where(GenerationTask.provider_id == "toapis")).all()
    )
    checks["pricingReviewed"] = len(models) == 2 and all(m.pricing_review_status.value == "REVIEWED" for m in models)
    checks["pricingHashMatched"] = pricing_snapshot_hash == EXPECTED_PRICING_HASH and all(
        m.pricing_snapshot_hash == EXPECTED_PRICING_HASH for m in models
    )
    checks["pricingFresh"] = all(
        m.pricing_reviewed_at is not None and _aware(m.pricing_reviewed_at) >= now - timedelta(days=7) for m in models
    )
    balance_at = _aware(profile.account_balance_reviewed_at) if profile.account_balance_reviewed_at else None
    checks["balanceReviewValid"] = bool(
        profile.account_balance_sufficient and balance_at and balance_at >= now - timedelta(hours=24)
        and profile.account_balance_pricing_snapshot_hash == EXPECTED_PRICING_HASH
        and Decimal(profile.account_balance_confirmed_units or "0") >= maximum_billing_units
    )
    checks["canariesPassed"] = _canaries_passed(session)
    billing = session.exec(
        select(GenerationUsageRecord).where(
            GenerationUsageRecord.generation_task_id == (keyframe_task.id if keyframe_task else -1),
            GenerationUsageRecord.record_type == UsageRecordType.MANUAL_ADJUSTMENT,
        )
    ).all()
    checks["historicalBillingValid"] = len(billing) == 1 and billing[0].actual_cost == "6.3"
    checks["lineageBudgetValid"] = maximum_billing_units == MAXIMUM_LINEAGE
    checks["noExistingRecoveryRun"] = not session.exec(
        select(ProviderVerificationRun).where(ProviderVerificationRun.recovery_of_run_id == failed_run_id)
    ).first()

    normalized_start_asset = _normalized_asset(session, start_norm) if start_norm else None
    normalized_end_asset = _normalized_asset(session, end_norm) if end_norm else None
    hash_input = {
        "failedRunId": failed_run_id,
        "projectId": run.verification_project_id,
        "shotId": run.shot_1_id,
        "keyframeAssetId": keyframe.id if keyframe else None,
        "normalizedStartAssetId": normalized_start_asset.id if normalized_start_asset else None,
        "normalizedEndAssetId": normalized_end_asset.id if normalized_end_asset else None,
        "historicalImageSubmits": 1,
        "historicalVideoSubmits": 0,
        "remainingImageSubmitLimit": 1,
        "remainingVideoSubmitLimit": 2,
        "historicalBilling": "6.3",
        "estimatedRemainingBilling": "166.3",
        "estimatedLineageBilling": "172.6",
        "maximumLineageBilling": "190",
        "pricingSnapshotHash": pricing_snapshot_hash,
        "normalizationVersion": NORMALIZATION_VERSION,
    }
    plan_hash = sha256(_dumps(hash_input).encode()).hexdigest()
    return {
        "failedRunId": failed_run_id,
        "failedRunStatus": run.status.value,
        "failureCode": run.failure_code,
        "failureRecoverable": checks["failureBeforeProviderCall"],
        "projectId": run.verification_project_id,
        "shotId": run.shot_1_id,
        "reusedKeyframeAssetId": keyframe.id if keyframe else None,
        "normalizedStartAssetId": normalized_start_asset.id if normalized_start_asset else None,
        "normalizedEndAssetId": normalized_end_asset.id if normalized_end_asset else None,
        "historicalImageSubmits": image_remote,
        "historicalVideoSubmits": video_remote,
        "remainingImageSubmitLimit": 1,
        "remainingVideoSubmitLimit": 2,
        "maximumLineageImageSubmits": 2,
        "maximumLineageVideoSubmits": 2,
        "historicalBillingUnits": "6.3",
        "estimatedRemainingBillingUnits": "166.3",
        "estimatedLineageBillingUnits": "172.6",
        "maximumLineageBillingUnits": str(maximum_billing_units),
        "billingUnit": "TOAPIS_CREDIT",
        "recoveryPlanHash": plan_hash,
        "checks": checks,
        "ready": all(checks.values()),
        "networkCalled": False,
        "databaseUpdated": False,
    }


def create_authorized_recovery_run(
    session: Session,
    *,
    failed_run_id: int,
    recovery_plan_hash: str,
    authorization_reference: str,
) -> ProviderVerificationRun:
    if not authorization_reference.strip():
        raise AppError("RECOVERY_AUTHORIZATION_REQUIRED", "Explicit recovery authorization is required.", 409)
    plan = build_recovery_plan(
        session,
        failed_run_id=failed_run_id,
        maximum_billing_units=MAXIMUM_LINEAGE,
        pricing_snapshot_hash=EXPECTED_PRICING_HASH,
    )
    if not plan["ready"] or recovery_plan_hash != plan["recoveryPlanHash"]:
        raise AppError("RECOVERY_PLAN_HASH_MISMATCH", "The recovery plan is stale or invalid.", 409)
    failed = session.get(ProviderVerificationRun, failed_run_id)
    if failed is None:
        raise AppError("FAILED_RUN_IDENTITY_INVALID", "The failed run does not exist.", 409)
    recovery = ProviderVerificationRun(
        provider_profile_id=failed.provider_profile_id,
        model_profile_id=failed.model_profile_id,
        verification_type=ProviderVerificationType.LIVE_TWO_SHOT_RECOVERY,
        status=ProviderVerificationStatus.PENDING,
        workflow_version="toapis-two-shot-recovery-v1",
        current_stage="SHOT_1_VIDEO_PREPARING",
        verification_project_id=failed.verification_project_id,
        shot_1_id=failed.shot_1_id,
        shot_2_id=failed.shot_2_id,
        recovery_of_run_id=failed_run_id,
        lineage_root_run_id=failed_run_id,
        normalized_start_asset_id=plan["normalizedStartAssetId"],
        normalized_end_asset_id=plan["normalizedEndAssetId"],
        reused_keyframe_asset_id=plan["reusedKeyframeAssetId"],
        historical_image_submits=1,
        historical_video_submits=0,
        remaining_image_submit_limit=1,
        remaining_video_submit_limit=2,
        historical_billing_units="6.3",
        estimated_remaining_billing_units="166.3",
        estimated_lineage_billing_units="172.6",
        maximum_lineage_billing_units="190",
        pricing_snapshot_hash=EXPECTED_PRICING_HASH,
        billing_unit="TOAPIS_CREDIT",
        recovery_plan_hash=recovery_plan_hash,
        recovery_authorization_reference=authorization_reference.strip(),
    )
    session.add(recovery)
    session.commit()
    session.refresh(recovery)
    return recovery


def _failed_video_task(session: Session, run: ProviderVerificationRun) -> GenerationTask:
    task = _failed_video_task_or_none(session, run)
    if task is None:
        raise AppError("FAILED_VIDEO_TASK_MISSING", "The failed video task is missing.", 409)
    return task


def _failed_video_task_or_none(session: Session, run: ProviderVerificationRun) -> GenerationTask | None:
    if run.shot_1_video_request_id is None:
        return None
    tasks = session.exec(
        select(GenerationTask).where(GenerationTask.generation_request_id == run.shot_1_video_request_id)
    ).all()
    return tasks[0] if len(tasks) == 1 else None


def _normalization(session: Session, source_id: int | None) -> VideoInputFrameNormalization | None:
    if source_id is None:
        return None
    return session.exec(
        select(VideoInputFrameNormalization).where(
            VideoInputFrameNormalization.source_asset_id == source_id,
            VideoInputFrameNormalization.normalization_version == NORMALIZATION_VERSION,
            VideoInputFrameNormalization.target_width == TARGET_WIDTH,
            VideoInputFrameNormalization.target_height == TARGET_HEIGHT,
        )
    ).first()


def _normalized_asset(session: Session, evidence: VideoInputFrameNormalization) -> Asset:
    asset = session.get(Asset, evidence.normalized_asset_id)
    if asset is None:
        raise AppError("NORMALIZED_VIDEO_FRAME_INVALID", "The normalized frame asset is missing.", 409)
    return asset


def _source_asset_valid(asset: Asset | None) -> bool:
    if asset is None or not asset.sha256:
        return False
    path = Path(asset.path)
    return path.is_file() and _sha256_file(path) == asset.sha256


def _normalization_valid(
    session: Session,
    evidence: VideoInputFrameNormalization | None,
    source: Asset | None,
) -> bool:
    if evidence is None or source is None:
        return False
    asset = session.get(Asset, evidence.normalized_asset_id)
    path = Path(asset.path) if asset else Path("")
    return bool(
        asset
        and evidence.source_asset_id == source.id
        and evidence.source_sha256 == source.sha256
        and evidence.target_width == TARGET_WIDTH
        and evidence.target_height == TARGET_HEIGHT
        and evidence.resize_mode == "contain"
        and not evidence.crop_applied
        and asset.width == TARGET_WIDTH and asset.height == TARGET_HEIGHT
        and asset.mime_type == "image/png"
        and asset.sha256 == evidence.normalized_sha256
        and path.is_file()
        and path.stat().st_size <= MAX_OUTPUT_BYTES
        and _sha256_file(path) == evidence.normalized_sha256
    )


def _canaries_passed(session: Session) -> bool:
    image = session.exec(select(ProviderVerificationRun).where(
        ProviderVerificationRun.verification_type == ProviderVerificationType.LIVE_CANARY,
        ProviderVerificationRun.status == ProviderVerificationStatus.PASSED,
    )).first()
    video = session.exec(select(ProviderVerificationRun).where(
        ProviderVerificationRun.verification_type == ProviderVerificationType.LIVE_VIDEO_CANARY,
        ProviderVerificationRun.status == ProviderVerificationStatus.PASSED,
        col(ProviderVerificationRun.actual_cost).is_not(None),
    )).first()
    return image is not None and video is not None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _loads(value: str) -> dict[str, Any]:
    parsed = json.loads(value or "{}")
    return parsed if isinstance(parsed, dict) else {}


def _empty_plan(failed_run_id: int, checks: dict[str, bool]) -> dict[str, Any]:
    return {
        "failedRunId": failed_run_id,
        "checks": checks,
        "ready": False,
        "networkCalled": False,
        "databaseUpdated": False,
    }
