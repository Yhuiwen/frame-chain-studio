from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.entities import (
    GenerationRequest,
    GenerationTask,
    GenerationUsageRecord,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
    utcnow,
)
from app.services import provider_management, task_service
from app.models.schemas import ToApisVideoCanaryConsoleReviewRequest


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
