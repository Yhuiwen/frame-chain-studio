from __future__ import annotations

from decimal import Decimal

from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.entities import (
    GenerationTask,
    GenerationTaskType,
    GenerationUsageRecord,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    ReliableTaskStatus,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
)
from app.services import provider_management


def review_recovery_console_billing(
    session: Session,
    *,
    run_id: int,
    acknowledged: bool,
    task_reviews: dict[int, tuple[str, Decimal]],
    billing_unit: str,
    evidence_type: str,
) -> dict[str, object]:
    if not acknowledged:
        raise AppError("CONSOLE_REVIEW_ACKNOWLEDGEMENT_REQUIRED", "Explicit console review acknowledgement is required.", 409)
    if billing_unit != "TOAPIS_CREDIT" or evidence_type != "TOAPIS_CONSOLE_REVIEW":
        raise AppError("CONSOLE_REVIEW_EVIDENCE_INVALID", "Console review evidence is invalid.", 409)
    run = session.get(ProviderVerificationRun, run_id)
    if (
        run is None
        or run.verification_type != ProviderVerificationType.LIVE_TWO_SHOT_RECOVERY
        or run.status != ProviderVerificationStatus.PASSED
        or run.recovery_of_run_id is None
    ):
        raise AppError("RECOVERY_BILLING_REVIEW_NOT_ALLOWED", "Only a passed recovery Run can be reviewed.", 409)
    tasks = session.exec(select(GenerationTask).where(GenerationTask.recovery_run_id == run_id)).all()
    expected = {task.id or 0: task for task in tasks}
    if len(expected) != 3 or set(task_reviews) != set(expected):
        raise AppError("RECOVERY_TASK_SET_MISMATCH", "All and only the three recovery tasks must be reviewed.", 409)
    if sorted(task.task_type for task in tasks) != sorted(
        [GenerationTaskType.KEYFRAME_GENERATION, GenerationTaskType.VIDEO_GENERATION, GenerationTaskType.VIDEO_GENERATION],
        key=lambda value: value.value,
    ):
        raise AppError("RECOVERY_TASK_SET_MISMATCH", "The recovery task types are invalid.", 409)

    total = Decimal("0")
    for task_id, task in expected.items():
        remote_task_id, actual = task_reviews[task_id]
        if actual < 0:
            raise AppError("ACTUAL_BILLING_INVALID", "Actual billing units cannot be negative.", 409)
        if task.status != ReliableTaskStatus.SUCCEEDED or task.max_attempts != 1 or task.remote_job_id != remote_task_id:
            raise AppError("REMOTE_TASK_ID_MISMATCH", "Console task ID does not match the persisted recovery task.", 409)
        existing = session.exec(
            select(GenerationUsageRecord).where(
                GenerationUsageRecord.generation_task_id == task_id,
                GenerationUsageRecord.record_type == UsageRecordType.MANUAL_ADJUSTMENT,
            )
        ).first()
        actual_text = str(actual)
        if existing is not None and (
            existing.actual_cost != actual_text
            or existing.billing_unit != billing_unit
            or provider_management.loads_dict(existing.provider_usage_json).get("source") != evidence_type
        ):
            raise AppError("BILLING_REVIEW_CONFLICT", "A different manual billing review already exists.", 409)
        if existing is None:
            estimated = "6.3" if task.task_type == GenerationTaskType.KEYFRAME_GENERATION else "80"
            existing = GenerationUsageRecord(
                project_id=task.project_id,
                shot_id=task.shot_id,
                generation_request_id=task.generation_request_id,
                generation_task_id=task_id,
                attempt_number=task.attempt_number,
                record_type=UsageRecordType.MANUAL_ADJUSTMENT,
                status=UsageRecordStatus.ACTUAL,
                currency=billing_unit,
                billing_unit=billing_unit,
                estimated_cost=estimated,
                actual_cost=actual_text,
                cost_source=UsageCostSource.MANUAL,
                provider_usage_json=provider_management.dumps({"source": evidence_type}),
            )
            session.add(existing)
        total += actual

    historical = Decimal("6.3")
    run.actual_cost = str(total)
    summary = provider_management.loads_dict(run.summary_json)
    summary.update(
        {
            "actual_billing_source": evidence_type,
            "billing_console_reviewed": True,
            "recovery_actual_billing_units": str(total),
            "lineage_actual_billing_units": str(historical + total),
        }
    )
    run.summary_json = provider_management.dumps(summary)
    session.add(run)
    session.commit()
    return {
        "run_id": run_id,
        "recovery_actual_billing_units": str(total),
        "lineage_actual_billing_units": str(historical + total),
        "actual_billing_source": evidence_type,
    }
