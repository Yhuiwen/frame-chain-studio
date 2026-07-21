from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.entities import (
    Asset,
    GenerationRequest,
    GenerationTask,
    GenerationUsageRecord,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
    TaskLog,
    utcnow,
)
from app.services import provider_management, task_service
from app.models.schemas import ToApisVideoCanaryConsoleReviewRequest


def record_existing_live_chain_image_result_review(
    session: Session,
    *,
    run_id: int,
    generation_request_id: int,
    existing_remote_task_id: str,
    actual_billing_units: Decimal,
) -> dict[str, object]:
    """Idempotently audit an already completed LIVE_CHAIN image task without advancing it."""
    run = session.get(ProviderVerificationRun, run_id)
    request = session.get(GenerationRequest, generation_request_id)
    if run is None or run.verification_type != ProviderVerificationType.LIVE_CHAIN:
        raise AppError("LIVE_CHAIN_RUN_NOT_FOUND", "The existing LIVE_CHAIN run was not found.", 409)
    if request is None or request.id not in {run.shot_1_keyframe_request_id, run.shot_2_keyframe_request_id}:
        raise AppError("LIVE_CHAIN_REQUEST_IDENTITY_INVALID", "The image request does not belong to the run.", 409)
    tasks = session.exec(
        select(GenerationTask).where(GenerationTask.generation_request_id == generation_request_id)
    ).all()
    if len(tasks) != 1 or tasks[0].retry_of_task_id is not None:
        raise AppError("LIVE_CHAIN_TASK_IDENTITY_INVALID", "Exactly one root image task is required.", 409)
    task = tasks[0]
    expected_business_id = "".join(
        char for char in task.idempotency_key if char.isascii() and (char.isalnum() or char in "-_")
    )[:96]
    expected_remote_job_id = f"image:{existing_remote_task_id}"
    if (
        task.provider_id != "toapis"
        or task.task_type.value != "KEYFRAME_GENERATION"
        or expected_business_id != "generation-request52task-typeKEYFRAME_GENERATIONretry-ofroot"
    ):
        raise AppError("LIVE_CHAIN_BUSINESS_ID_MISMATCH", "The persisted task identity is invalid.", 409)
    if task.remote_job_id != expected_remote_job_id:
        raise AppError("REMOTE_TASK_ID_CONFLICT", "The persisted remote task ID conflicts with the review.", 409)
    asset = session.get(Asset, task.result_asset_id) if task.result_asset_id else None
    if task.status.value != "SUCCEEDED" or asset is None or asset.type.value != "KEYFRAME":
        raise AppError("LIVE_CHAIN_RESULT_NOT_RECOVERED", "The existing image result is not registered.", 409)
    if actual_billing_units != Decimal("6.3"):
        raise AppError("CONSOLE_REVIEW_EVIDENCE_INVALID", "The reviewed image billing must be 6.3 TOAPIS_CREDIT.", 409)

    existing = session.exec(
        select(GenerationUsageRecord).where(
            GenerationUsageRecord.generation_task_id == task.id,
            GenerationUsageRecord.record_type == UsageRecordType.MANUAL_ADJUSTMENT,
        )
    ).first()
    if existing is None:
        existing = GenerationUsageRecord(
            project_id=task.project_id,
            shot_id=task.shot_id,
            generation_request_id=task.generation_request_id,
            generation_task_id=task.id,
            attempt_number=task.attempt_number,
            record_type=UsageRecordType.MANUAL_ADJUSTMENT,
            status=UsageRecordStatus.ACTUAL,
            currency="TOAPIS_CREDIT",
            billing_unit="TOAPIS_CREDIT",
            estimated_cost="6.3",
            actual_cost="6.3",
            cost_source=UsageCostSource.MANUAL,
            actual_units_json=provider_management.dumps({"generated_images": 1}),
            provider_usage_json=provider_management.dumps({"source": "TOAPIS_CONSOLE_REVIEW"}),
        )
        session.add(existing)
    elif existing.actual_cost != "6.3" or existing.billing_unit != "TOAPIS_CREDIT":
        raise AppError("CONSOLE_REVIEW_CONFLICT", "A conflicting manual billing review already exists.", 409)

    request.estimated_billing_units = "6.3"
    run.actual_cost = "6.3"
    summary = provider_management.loads_dict(run.summary_json)
    summary["actual_billing_source"] = "TOAPIS_CONSOLE_REVIEW"
    summary["historical_image_submits"] = 1
    summary["new_image_submits"] = 0
    run.summary_json = provider_management.dumps(summary)
    for message in ("EXISTING_REMOTE_TASK_BOUND", "INLINE_RESULT_RECOVERY_STARTED"):
        already_logged = session.exec(
            select(TaskLog).where(TaskLog.task_id == task.id, TaskLog.message == message)
        ).first()
        if already_logged is None:
            session.add(TaskLog(request_id=request.id, task_id=task.id, shot_id=task.shot_id, message=message))
    session.add(request)
    session.add(run)
    session.commit()
    return {
        "run_id": run.id or 0,
        "task_id": task.id or 0,
        "asset_id": asset.id or 0,
        "actual_billing_units": "6.3",
        "actual_billing_source": "TOAPIS_CONSOLE_REVIEW",
        "new_image_submits": 0,
    }


def prepare_existing_result_recovery(
    session: Session,
    *,
    run_id: int,
    existing_remote_task_id: str,
    existing_result_url: str,
    acknowledged: bool,
) -> dict[str, object]:
    if not acknowledged:
        raise AppError("EXISTING_TASK_RECOVERY_ACKNOWLEDGEMENT_REQUIRED", "Explicit recovery acknowledgement is required.", 409)
    run = session.get(ProviderVerificationRun, run_id)
    if run is None or run.verification_type != ProviderVerificationType.LIVE_CANARY:
        raise AppError("CANARY_RUN_NOT_RECOVERABLE", "Only an existing LIVE_CANARY run can be recovered.", 409)
    if run.status not in {ProviderVerificationStatus.FAILED, ProviderVerificationStatus.FAILED_BUT_BILLED}:
        raise AppError("CANARY_RUN_NOT_RECOVERABLE", "Canary run is not in a recoverable failed state.", 409)
    requests = session.exec(
        select(GenerationRequest).where(GenerationRequest.project_id == run.verification_project_id)
    ).all()
    if len(requests) != 1 or requests[0].id != run.shot_1_keyframe_request_id:
        raise AppError("CANARY_REQUEST_IDENTITY_INVALID", "Canary must have exactly one existing image request.", 409)
    tasks = session.exec(
        select(GenerationTask).where(GenerationTask.generation_request_id == requests[0].id)
    ).all()
    if len(tasks) != 1:
        raise AppError("CANARY_TASK_IDENTITY_INVALID", "Canary must have exactly one existing task.", 409)
    task = tasks[0]
    expected_business_id = "".join(
        char for char in task.idempotency_key if char.isascii() and (char.isalnum() or char in "-_")
    )[:96]
    if expected_business_id != "generation-request50task-typeKEYFRAME_GENERATIONretry-ofroot":
        raise AppError("CANARY_BUSINESS_ID_MISMATCH", "Persisted Canary identity does not match console evidence.", 409)
    _record_console_billing(session, run, task)
    run.status = ProviderVerificationStatus.RUNNING
    run.current_stage = "CANARY_REQUESTED"
    run.failure_code = None
    run.error_code = None
    run.error_message = ""
    run.actual_cost = "6.3"
    run.completed_at = None
    run.summary_json = provider_management.dumps({
        "recovery_mode": "EXISTING_RESULT_URL",
        "existing_remote_task_id": "REDACTED",
        "historical_image_submits": 1,
        "new_image_submits": 0,
        "actual_billing_source": "TOAPIS_CONSOLE_REVIEW",
    })
    session.add(run)
    session.commit()
    session.refresh(task)
    if task.status.value == "FAILED":
        task_service.recover_failed_canary_result_ready(
            session,
            task.id or 0,
            existing_remote_task_id=existing_remote_task_id,
            result_url=existing_result_url,
            response_summary="Console-confirmed existing TOAPIS Canary result; no submit performed.",
        )
    elif task.status.value == "SUCCEEDED":
        if task.remote_job_id != f"image:{existing_remote_task_id}" or task.result_asset_id is None:
            raise AppError("RECOVERED_CANARY_IDENTITY_MISMATCH", "Completed recovered task identity is invalid.", 409)
    else:
        raise AppError("CANARY_TASK_NOT_RECOVERABLE", "Canary task is not recoverable in its current state.", 409)
    return {"run_id": run.id or 0, "task_id": task.id or 0, "status": run.status.value, "new_image_submits": 0}


def _record_console_billing(session: Session, run: ProviderVerificationRun, task: GenerationTask) -> None:
    existing = session.exec(
        select(GenerationUsageRecord).where(
            GenerationUsageRecord.generation_task_id == task.id,
            GenerationUsageRecord.record_type == UsageRecordType.MANUAL_ADJUSTMENT,
        )
    ).first()
    if existing:
        return
    session.add(GenerationUsageRecord(
        project_id=task.project_id,
        shot_id=task.shot_id,
        generation_request_id=task.generation_request_id,
        generation_task_id=task.id,
        attempt_number=task.attempt_number,
        record_type=UsageRecordType.MANUAL_ADJUSTMENT,
        status=UsageRecordStatus.ACTUAL,
        currency="TOAPIS_CREDIT",
        billing_unit="TOAPIS_CREDIT",
        estimated_cost=run.estimated_billing_units or "6.3",
        actual_cost=str(Decimal("6.3")),
        cost_source=UsageCostSource.MANUAL,
        actual_units_json=provider_management.dumps({"generated_images": 1}),
        provider_usage_json=provider_management.dumps({
            "source": "TOAPIS_CONSOLE_REVIEW", "reviewed_at": utcnow().isoformat(),
        }),
    ))
    session.flush()


def review_video_canary_console_billing(
    session: Session, *, run_id: int, payload: ToApisVideoCanaryConsoleReviewRequest,
) -> dict[str, object]:
    if not payload.acknowledged:
        raise AppError("CONSOLE_REVIEW_ACKNOWLEDGEMENT_REQUIRED", "Explicit console review acknowledgement is required.", 409)
    if payload.billing_unit != "TOAPIS_CREDIT" or payload.evidence_type != "TOAPIS_CONSOLE_REVIEW":
        raise AppError("CONSOLE_REVIEW_EVIDENCE_INVALID", "Console review evidence is invalid.", 409)
    run = session.get(ProviderVerificationRun, run_id)
    if not run or run.verification_type != ProviderVerificationType.LIVE_VIDEO_CANARY or run.status != ProviderVerificationStatus.PASSED:
        raise AppError("VIDEO_CANARY_REVIEW_NOT_ALLOWED", "Only a passed video Canary can be reviewed.", 409)
    task = session.exec(select(GenerationTask).where(GenerationTask.project_id == run.verification_project_id)).one()
    if task.remote_job_id != f"video:{payload.existing_remote_task_id}":
        raise AppError("REMOTE_TASK_ID_MISMATCH", "Console task ID does not match the persisted video task.", 409)
    existing = session.exec(select(GenerationUsageRecord).where(
        GenerationUsageRecord.generation_task_id == task.id,
        GenerationUsageRecord.record_type == UsageRecordType.MANUAL_ADJUSTMENT,
    )).first()
    if existing is None:
        existing = GenerationUsageRecord(
            project_id=task.project_id, shot_id=task.shot_id,
            generation_request_id=task.generation_request_id, generation_task_id=task.id,
            attempt_number=task.attempt_number, record_type=UsageRecordType.MANUAL_ADJUSTMENT,
            status=UsageRecordStatus.ACTUAL, currency="TOAPIS_CREDIT", billing_unit="TOAPIS_CREDIT",
            estimated_cost=run.estimated_billing_units, cost_source=UsageCostSource.MANUAL,
        )
    existing.actual_cost = str(payload.actual_billing_units)
    existing.provider_usage_json = provider_management.dumps({"source": "TOAPIS_CONSOLE_REVIEW"})
    run.actual_cost = str(payload.actual_billing_units)
    summary = provider_management.loads_dict(run.summary_json)
    summary["actual_billing_source"] = "TOAPIS_CONSOLE_REVIEW"
    run.summary_json = provider_management.dumps(summary)
    session.add(existing)
    session.add(run)
    session.commit()
    return {"run_id": run_id, "actual_billing_units": run.actual_cost or "", "actual_billing_source": "TOAPIS_CONSOLE_REVIEW"}
