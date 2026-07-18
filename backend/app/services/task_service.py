import json
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import func, or_, update
from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.core.redaction import redact_sensitive
from app.domain.task_state_machine import (
    ACTIVE_TASK_STATUSES,
    LEASEABLE_TASK_STATUSES,
    ensure_task_transition_allowed,
)
from app.models.entities import (
    GenerationKind,
    GenerationRequest,
    GenerationTask,
    GenerationTaskType,
    ReliableTaskStatus,
    TaskErrorCode,
    TaskStateChange,
    utcnow,
)


def task_type_from_generation_kind(kind: GenerationKind) -> GenerationTaskType:
    if kind == GenerationKind.KEYFRAME:
        return GenerationTaskType.KEYFRAME_GENERATION
    if kind == GenerationKind.VIDEO:
        return GenerationTaskType.VIDEO_GENERATION
    raise AppError("UNSUPPORTED_TASK_TYPE", f"Unsupported generation kind {kind.value}.", 400)


def dumps_sanitized(value: Any) -> str:
    return json.dumps(redact_sensitive(value), ensure_ascii=True, sort_keys=True)


def loads_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    return parsed if isinstance(parsed, dict) else {}


def loads_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def db_time(value: datetime | None = None) -> datetime:
    candidate = value or utcnow()
    if candidate.tzinfo is not None:
        return candidate.astimezone(timezone.utc).replace(tzinfo=None)
    return candidate


def create_generation_request(
    session: Session,
    *,
    project_id: int,
    shot_id: int,
    kind: GenerationKind,
    provider_name: str,
    prompt_snapshot: str = "",
    negative_prompt_snapshot: str = "",
    input_asset_ids: list[int] | None = None,
) -> GenerationRequest:
    request = GenerationRequest(
        project_id=project_id,
        shot_id=shot_id,
        kind=kind,
        provider_name=provider_name,
        prompt_snapshot=prompt_snapshot,
        negative_prompt_snapshot=negative_prompt_snapshot,
        input_asset_ids=json.dumps(input_asset_ids or []),
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def get_task(session: Session, task_id: int) -> GenerationTask:
    task = session.get(GenerationTask, task_id)
    if task is None:
        raise AppError("TASK_NOT_FOUND", f"Generation task {task_id} was not found.", 404)
    return task


def task_lease_is_owned(
    session: Session,
    task_id: int,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> bool:
    task = get_task(session, task_id)
    current_time = db_time(now)
    return task.locked_by == worker_id and task.locked_until is not None and task.locked_until > current_time


def list_project_tasks(session: Session, project_id: int) -> list[GenerationTask]:
    return list(
        session.exec(
            select(GenerationTask)
            .where(GenerationTask.project_id == project_id)
            .order_by(col(GenerationTask.created_at))
        ).all()
    )


def list_shot_tasks(session: Session, shot_id: int) -> list[GenerationTask]:
    return list(
        session.exec(
            select(GenerationTask).where(GenerationTask.shot_id == shot_id).order_by(col(GenerationTask.created_at))
        ).all()
    )


def create_task_attempt(
    session: Session,
    *,
    generation_request: GenerationRequest,
    task_type: GenerationTaskType | None = None,
    provider_id: str = "mock",
    retry_of_task_id: int | None = None,
    max_attempts: int = 3,
    request_payload: dict[str, Any] | None = None,
    provider_config_snapshot: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> GenerationTask:
    resolved_type = task_type or task_type_from_generation_kind(generation_request.kind)
    base_key = idempotency_key or (
        f"generation-request:{generation_request.id}:"
        f"task-type:{resolved_type.value}:retry-of:{retry_of_task_id or 'root'}"
    )
    existing = session.exec(select(GenerationTask).where(GenerationTask.idempotency_key == base_key)).first()
    if existing is not None:
        return existing

    active_task = session.exec(
        select(GenerationTask).where(
            GenerationTask.generation_request_id == generation_request.id,
            col(GenerationTask.status).in_([status.value for status in ACTIVE_TASK_STATUSES]),
        )
    ).first()
    if active_task is not None:
        raise AppError("ACTIVE_TASK_EXISTS", "Generation request already has an active task.", 409)

    attempt_number = (
        session.exec(
            select(func.max(GenerationTask.attempt_number)).where(
                GenerationTask.generation_request_id == generation_request.id
            )
        ).one()
        or 0
    ) + 1
    retry_of = session.get(GenerationTask, retry_of_task_id) if retry_of_task_id else None
    if retry_of_task_id and retry_of is None:
        raise AppError("RETRY_TASK_NOT_FOUND", f"Retry source task {retry_of_task_id} was not found.", 404)
    root_task_id = retry_of.root_task_id or retry_of.id if retry_of else None

    task = GenerationTask(
        generation_request_id=generation_request.id or 0,
        project_id=generation_request.project_id,
        shot_id=generation_request.shot_id,
        task_type=resolved_type,
        provider_id=provider_id,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        retry_of_task_id=retry_of_task_id,
        root_task_id=root_task_id,
        idempotency_key=base_key,
        request_payload_json=dumps_sanitized(request_payload or {}),
        provider_config_snapshot_json=dumps_sanitized(provider_config_snapshot or {"provider_id": provider_id}),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    if task.root_task_id is None:
        task.root_task_id = task.id
        session.add(task)
        session.commit()
        session.refresh(task)
    session.add(
        TaskStateChange(
            task_id=task.id or 0,
            from_status=None,
            to_status=task.status,
            reason_code="task_created",
            reason="Task attempt created.",
        )
    )
    session.commit()
    session.refresh(task)
    return task


def transition_task(
    session: Session,
    task_id: int,
    target: ReliableTaskStatus,
    *,
    expected_current: ReliableTaskStatus | None = None,
    reason_code: str | None = None,
    reason: str = "",
    now: datetime | None = None,
) -> GenerationTask:
    current_time = db_time(now)
    task = get_task(session, task_id)
    if expected_current is not None and task.status != expected_current:
        raise AppError(
            "TASK_STATE_CHANGED",
            f"Expected task status {expected_current.value}, found {task.status.value}.",
            409,
        )
    if task.status == target:
        return task
    previous = task.status
    ensure_task_transition_allowed(previous, target)
    values: dict[str, Any] = {"status": target, "updated_at": current_time}
    if target in {ReliableTaskStatus.SUBMITTING, ReliableTaskStatus.RUNNING} and task.started_at is None:
        values["started_at"] = current_time
    if target in {
        ReliableTaskStatus.RESULT_READY,
        ReliableTaskStatus.SUCCEEDED,
        ReliableTaskStatus.FAILED,
        ReliableTaskStatus.CANCELLED,
    }:
        values.update(
            {
                "completed_at": task.completed_at or current_time
                if target != ReliableTaskStatus.RESULT_READY
                else task.completed_at,
                "locked_by": None,
                "locked_until": None,
                "lock_acquired_at": None,
            }
        )
    statement = (
        update(GenerationTask)
        .where(col(GenerationTask.id) == task_id, col(GenerationTask.status) == previous.value)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(statement)
    if getattr(result, "rowcount", 0) != 1:
        session.rollback()
        raise AppError("TASK_STATE_CHANGED", "Task status changed during transition.", 409)
    session.add(
        TaskStateChange(
            task_id=task_id,
            from_status=previous,
            to_status=target,
            reason_code=reason_code,
            reason=reason,
            created_at=current_time,
        )
    )
    session.commit()
    return get_task(session, task_id)


def mark_task_submitted(
    session: Session,
    task_id: int,
    *,
    remote_job_id: str | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.QUEUED:
        task = transition_task(session, task_id, ReliableTaskStatus.SUBMITTING, reason_code="task_submitting", now=now)
    if task.status == ReliableTaskStatus.SUBMITTING:
        task = transition_task(session, task_id, ReliableTaskStatus.RUNNING, reason_code="task_submitted", now=now)
    current_time = db_time(now)
    task.remote_job_id = remote_job_id
    task.remote_status = task.remote_status
    task.submitted_at = task.submitted_at or current_time
    task.updated_at = current_time
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def mark_task_remote_submitted(
    session: Session,
    task_id: int,
    *,
    remote_job_id: str,
    remote_status: str,
    response_summary: str,
    poll_delay_seconds: int,
    now: datetime | None = None,
) -> GenerationTask:
    current_time = db_time(now)
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.QUEUED:
        task = transition_task(
            session,
            task_id,
            ReliableTaskStatus.SUBMITTING,
            expected_current=ReliableTaskStatus.QUEUED,
            reason_code="remote_submit_started",
            now=current_time,
        )
    if task.status != ReliableTaskStatus.SUBMITTING:
        raise AppError("TASK_NOT_SUBMITTING", f"Task in {task.status.value} cannot store submit result.", 409)
    task.remote_job_id = remote_job_id
    task.remote_status = remote_status
    task.submitted_at = task.submitted_at or current_time
    task.response_summary_json = dumps_sanitized({"submit": response_summary})
    task.next_poll_at = current_time + timedelta(seconds=poll_delay_seconds)
    task.updated_at = current_time
    session.add(task)
    session.commit()
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.RUNNING,
        expected_current=ReliableTaskStatus.SUBMITTING,
        reason_code="remote_submit_succeeded",
        now=current_time,
    )


def repair_submitting_with_remote_job(
    session: Session,
    task_id: int,
    *,
    poll_delay_seconds: int,
    now: datetime | None = None,
) -> GenerationTask:
    current_time = db_time(now)
    task = get_task(session, task_id)
    if task.status != ReliableTaskStatus.SUBMITTING or not task.remote_job_id:
        raise AppError("TASK_NOT_REPAIRABLE", "Only SUBMITTING tasks with remote job IDs can be repaired.", 409)
    task.next_poll_at = current_time + timedelta(seconds=poll_delay_seconds)
    task.updated_at = current_time
    session.add(task)
    session.commit()
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.RUNNING,
        expected_current=ReliableTaskStatus.SUBMITTING,
        reason_code="remote_submit_recovered",
        now=current_time,
    )


def record_running_poll(
    session: Session,
    task_id: int,
    *,
    remote_status: str,
    response_summary: str,
    poll_delay_seconds: int,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status != ReliableTaskStatus.RUNNING:
        raise AppError("TASK_NOT_RUNNING", f"Task in {task.status.value} cannot be polled.", 409)
    current_time = db_time(now)
    task.remote_status = remote_status
    task.response_summary_json = dumps_sanitized({"poll": response_summary})
    task.poll_count += 1
    task.last_polled_at = current_time
    task.next_poll_at = current_time + timedelta(seconds=poll_delay_seconds)
    task.updated_at = current_time
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def mark_task_result_ready(
    session: Session,
    task_id: int,
    *,
    remote_status: str,
    result_urls: list[dict[str, Any]],
    response_summary: str,
    now: datetime | None = None,
) -> GenerationTask:
    if not result_urls:
        raise AppError("TASK_RESULT_URLS_REQUIRED", "At least one result URL is required.", 409)
    sanitized_urls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result_urls:
        url = str(item.get("url", ""))
        if not url or "://" not in url or url in seen:
            continue
        if len(url) > 8 and url[1:3] == ":\\":
            continue
        seen.add(url)
        sanitized_urls.append(redact_sensitive(item))
    if not sanitized_urls:
        raise AppError("TASK_RESULT_URLS_REQUIRED", "At least one valid result URL is required.", 409)
    current_time = db_time(now)
    task = get_task(session, task_id)
    existing_urls = loads_json_list(task.result_urls_json)
    existing_by_url = {
        str(item.get("url")): item for item in existing_urls if isinstance(item, dict) and item.get("url")
    }
    for item in sanitized_urls:
        existing_by_url[str(item["url"])] = item
    task.result_urls_json = dumps_sanitized(list(existing_by_url.values()))
    task.remote_status = remote_status
    task.response_summary_json = dumps_sanitized({"poll": response_summary})
    task.poll_count += 1
    task.last_polled_at = current_time
    task.next_poll_at = None
    task.updated_at = current_time
    session.add(task)
    session.commit()
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.RESULT_READY,
        expected_current=ReliableTaskStatus.RUNNING,
        reason_code="remote_result_ready",
        now=current_time,
    )


def mark_task_running(session: Session, task_id: int, *, now: datetime | None = None) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.QUEUED:
        transition_task(session, task_id, ReliableTaskStatus.SUBMITTING, reason_code="task_started", now=now)
    return transition_task(session, task_id, ReliableTaskStatus.RUNNING, reason_code="task_running", now=now)


def record_task_error(
    session: Session,
    task_id: int,
    *,
    error_code: TaskErrorCode | str,
    error_message: str,
    error_details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    task.error_code = error_code.value if isinstance(error_code, TaskErrorCode) else error_code
    task.error_message = error_message
    task.error_details_json = dumps_sanitized(error_details or {})
    current_time = db_time(now)
    task.last_error_at = current_time
    task.updated_at = current_time
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def schedule_retry(
    session: Session,
    task_id: int,
    *,
    delay_seconds: int,
    error_code: TaskErrorCode | str = TaskErrorCode.UNKNOWN_ERROR,
    error_message: str = "",
    now: datetime | None = None,
) -> GenerationTask:
    current_time = db_time(now)
    task = get_task(session, task_id)
    if task.status not in {
        ReliableTaskStatus.SUBMITTING,
        ReliableTaskStatus.RUNNING,
        ReliableTaskStatus.RETRY_WAIT,
    }:
        raise AppError("TASK_NOT_RETRYABLE", f"Task in {task.status.value} cannot be scheduled for retry.", 409)
    record_task_error(
        session,
        task_id,
        error_code=error_code,
        error_message=error_message,
        now=current_time,
    )
    task = get_task(session, task_id)
    next_retry_count = task.retry_count + 1
    if next_retry_count >= task.max_attempts:
        task.retry_count = next_retry_count
        session.add(task)
        session.commit()
        return transition_task(
            session,
            task_id,
            ReliableTaskStatus.FAILED,
            reason_code="retry_limit_exceeded",
            now=current_time,
        )
    task.retry_count = next_retry_count
    task.next_retry_at = current_time + timedelta(seconds=delay_seconds)
    task.updated_at = current_time
    session.add(task)
    session.commit()
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.RETRY_WAIT,
        reason_code="retry_scheduled",
        now=current_time,
    )


def mark_task_succeeded(
    session: Session,
    task_id: int,
    *,
    result_asset_id: int | None,
    response_summary: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.SUCCEEDED:
        if task.result_asset_id != result_asset_id:
            raise AppError("TASK_RESULT_CONFLICT", "Task already succeeded with a different result asset.", 409)
        return task
    if task.status not in {ReliableTaskStatus.RUNNING, ReliableTaskStatus.SUBMITTING}:
        raise AppError("TASK_NOT_COMPLETABLE", f"Task in {task.status.value} cannot be marked succeeded.", 409)
    task.result_asset_id = result_asset_id
    task.response_summary_json = dumps_sanitized(response_summary or {})
    session.add(task)
    session.commit()
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.SUCCEEDED,
        reason_code="task_succeeded",
        now=now,
    )


def mark_task_failed(
    session: Session,
    task_id: int,
    *,
    error_code: TaskErrorCode | str = TaskErrorCode.UNKNOWN_ERROR,
    error_message: str,
    error_details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    record_task_error(
        session,
        task_id,
        error_code=error_code,
        error_message=error_message,
        error_details=error_details,
        now=now,
    )
    return transition_task(session, task_id, ReliableTaskStatus.FAILED, reason_code="task_failed", now=now)


def mark_remote_cancelled(session: Session, task_id: int, *, now: datetime | None = None) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.CANCELLED:
        return task
    if task.status not in {ReliableTaskStatus.RUNNING, ReliableTaskStatus.SUBMITTING, ReliableTaskStatus.CANCELLING}:
        raise AppError("TASK_NOT_CANCELLABLE", f"Task in {task.status.value} cannot be marked cancelled.", 409)
    return transition_task(session, task_id, ReliableTaskStatus.CANCELLED, reason_code="remote_cancelled", now=now)


def request_task_cancel(session: Session, task_id: int, *, now: datetime | None = None) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.QUEUED:
        return transition_task(session, task_id, ReliableTaskStatus.CANCELLED, reason_code="cancelled_before_start", now=now)
    return transition_task(session, task_id, ReliableTaskStatus.CANCELLING, reason_code="cancel_requested", now=now)


def mark_task_cancelled(session: Session, task_id: int, *, now: datetime | None = None) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.CANCELLED:
        return task
    if task.status != ReliableTaskStatus.CANCELLING:
        raise AppError("TASK_NOT_CANCELLING", "Task must be cancelling before it can be cancelled.", 409)
    return transition_task(session, task_id, ReliableTaskStatus.CANCELLED, reason_code="task_cancelled", now=now)


def mark_task_running_after_cancel_failed(
    session: Session,
    task_id: int,
    *,
    reason: str,
    now: datetime | None = None,
) -> GenerationTask:
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.RUNNING,
        reason_code="remote_cancel_failed",
        reason=reason,
        now=now,
    )


def acquire_task_lease(
    session: Session,
    task_id: int,
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> GenerationTask | None:
    current_time = db_time(now)
    task = get_task(session, task_id)
    if task.status not in LEASEABLE_TASK_STATUSES:
        return None
    if task.status == ReliableTaskStatus.RETRY_WAIT and task.next_retry_at and task.next_retry_at > current_time:
        return None
    if task.next_poll_at and task.next_poll_at > current_time:
        return None
    statement = (
        update(GenerationTask)
        .where(
            col(GenerationTask.id) == task_id,
            col(GenerationTask.status).in_([status.value for status in LEASEABLE_TASK_STATUSES]),
            or_(
                col(GenerationTask.locked_until).is_(None),
                col(GenerationTask.locked_until) <= current_time,
                col(GenerationTask.locked_by) == worker_id,
            ),
            or_(col(GenerationTask.next_retry_at).is_(None), col(GenerationTask.next_retry_at) <= current_time),
            or_(col(GenerationTask.next_poll_at).is_(None), col(GenerationTask.next_poll_at) <= current_time),
        )
        .values(
            locked_by=worker_id,
            locked_until=current_time + timedelta(seconds=lease_seconds),
            lock_acquired_at=current_time,
            lock_version=col(GenerationTask.lock_version) + 1,
            updated_at=current_time,
        )
        .execution_options(synchronize_session=False)
    )
    result = session.execute(statement)
    if getattr(result, "rowcount", 0) != 1:
        session.rollback()
        return None
    session.commit()
    return get_task(session, task_id)


def renew_task_lease(
    session: Session,
    task_id: int,
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> GenerationTask | None:
    current_time = db_time(now)
    statement = (
        update(GenerationTask)
        .where(
            col(GenerationTask.id) == task_id,
            col(GenerationTask.locked_by) == worker_id,
            col(GenerationTask.locked_until).is_not(None),
            col(GenerationTask.locked_until) > current_time,
            col(GenerationTask.status).in_([status.value for status in LEASEABLE_TASK_STATUSES]),
        )
        .values(
            locked_until=current_time + timedelta(seconds=lease_seconds),
            lock_version=col(GenerationTask.lock_version) + 1,
            updated_at=current_time,
        )
        .execution_options(synchronize_session=False)
    )
    result = session.execute(statement)
    if getattr(result, "rowcount", 0) != 1:
        session.rollback()
        return None
    session.commit()
    return get_task(session, task_id)


def release_task_lease(session: Session, task_id: int, *, worker_id: str) -> GenerationTask | None:
    task = get_task(session, task_id)
    if task.locked_by is None:
        return task
    if task.locked_by != worker_id:
        return None
    task.locked_by = None
    task.locked_until = None
    task.lock_acquired_at = None
    task.updated_at = utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task
