import json
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, or_, true, update
from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.core.redaction import redact_sensitive
from app.domain.task_state_machine import (
    ACTIVE_TASK_STATUSES,
    LEASEABLE_TASK_STATUSES,
    ensure_task_transition_allowed,
)
from app.models.entities import (
    Asset,
    AssetType,
    GenerationKind,
    GenerationMode,
    GenerationRequest,
    GenerationTaskStatus,
    GenerationTask,
    GenerationTaskResult,
    GenerationTaskResultStatus,
    GenerationTaskType,
    ResultMediaKind,
    ReliableTaskStatus,
    Shot,
    ShotStatus,
    TaskCommand,
    TaskCommandStatus,
    TaskCommandType,
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
    effective_provider_id: str | None = None,
    model: str | None = None,
    generation_mode: str | GenerationMode | None = None,
    aspect_ratio: str | None = None,
    seed: int | None = None,
    duration_seconds: float | None = None,
    allow_capability_fallback: bool = False,
    prompt_snapshot: str = "",
    negative_prompt_snapshot: str = "",
    input_asset_ids: list[int] | None = None,
    commit: bool = True,
) -> GenerationRequest:
    request = GenerationRequest(
        project_id=project_id,
        shot_id=shot_id,
        kind=kind,
        provider_name=provider_name,
        effective_provider_id=effective_provider_id,
        model=model,
        generation_mode=generation_mode,
        aspect_ratio=aspect_ratio,
        seed=seed,
        duration_seconds=duration_seconds,
        allow_capability_fallback=allow_capability_fallback,
        prompt_snapshot=prompt_snapshot,
        negative_prompt_snapshot=negative_prompt_snapshot,
        input_asset_ids=json.dumps(input_asset_ids or []),
    )
    session.add(request)
    if commit:
        session.commit()
        session.refresh(request)
    else:
        session.flush()
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


def primary_result_status(session: Session, task_id: int) -> str | None:
    result = session.exec(
        select(GenerationTaskResult).where(
            GenerationTaskResult.generation_task_id == task_id,
            col(GenerationTaskResult.is_primary).is_(true()),
        )
    ).first()
    return result.status.value if result else None


def task_is_latest_attempt(session: Session, task_id: int) -> bool:
    task = get_task(session, task_id)
    latest = session.exec(
        select(GenerationTask)
        .where(GenerationTask.generation_request_id == task.generation_request_id)
        .order_by(col(GenerationTask.created_at).desc(), col(GenerationTask.id).desc())
    ).first()
    return latest is not None and latest.id == task.id


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
    commit: bool = True,
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
    if commit:
        session.commit()
        session.refresh(task)
    else:
        session.flush()
    if task.root_task_id is None:
        task.root_task_id = task.id
        session.add(task)
        if commit:
            session.commit()
            session.refresh(task)
        else:
            session.flush()
    session.add(
        TaskStateChange(
            task_id=task.id or 0,
            from_status=None,
            to_status=task.status,
            reason_code="task_created",
            reason="Task attempt created.",
        )
    )
    if commit:
        session.commit()
        session.refresh(task)
    else:
        session.flush()
    return task


def create_or_get_command(
    session: Session,
    *,
    task_id: int,
    command_type: TaskCommandType,
    idempotency_key: str,
    reason: str = "",
) -> TaskCommand:
    existing = session.exec(
        select(TaskCommand).where(
            TaskCommand.command_type == command_type,
            TaskCommand.idempotency_key == idempotency_key,
        )
    ).first()
    if existing is not None:
        if existing.task_id != task_id:
            raise AppError("COMMAND_IDEMPOTENCY_CONFLICT", "Idempotency key was used for another task.", 409)
        return existing
    command = TaskCommand(
        task_id=task_id,
        command_type=command_type,
        idempotency_key=idempotency_key,
        reason=reason,
    )
    session.add(command)
    session.commit()
    session.refresh(command)
    return command


def complete_command(
    session: Session,
    command: TaskCommand,
    *,
    result_task_id: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    now: datetime | None = None,
) -> TaskCommand:
    command.status = TaskCommandStatus.FAILED if error_code else TaskCommandStatus.SUCCEEDED
    command.completed_at = db_time(now)
    command.result_task_id = result_task_id
    command.error_code = error_code
    command.error_message = error_message
    session.add(command)
    session.commit()
    session.refresh(command)
    return command


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
        if target in {ReliableTaskStatus.SUCCEEDED, ReliableTaskStatus.FAILED, ReliableTaskStatus.CANCELLED}:
            values["raw_result_urls_json"] = "[]"
    if target == ReliableTaskStatus.CANCELLED:
        values["cancelled_at"] = task.cancelled_at or current_time
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
    if target in {ReliableTaskStatus.SUCCEEDED, ReliableTaskStatus.FAILED, ReliableTaskStatus.CANCELLED}:
        session.execute(
            update(GenerationTaskResult)
            .where(col(GenerationTaskResult.generation_task_id) == task_id)
            .values(source_url="", updated_at=current_time)
            .execution_options(synchronize_session=False)
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
    job_timeout_seconds: int | None = None,
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
    if job_timeout_seconds is not None:
        task.job_deadline_at = current_time + timedelta(seconds=job_timeout_seconds)
    task.submission_deadline_at = None
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


def store_cancelling_remote_job(
    session: Session,
    task_id: int,
    *,
    remote_job_id: str,
    remote_status: str,
    response_summary: str,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status != ReliableTaskStatus.CANCELLING:
        raise AppError("TASK_NOT_CANCELLING", "Task must be CANCELLING to store cancellation remote job.", 409)
    current_time = db_time(now)
    task.remote_job_id = remote_job_id
    task.remote_status = remote_status
    task.response_summary_json = dumps_sanitized({"submit_for_cancel": response_summary})
    task.submitted_at = task.submitted_at or current_time
    task.updated_at = current_time
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def record_cancel_pending(
    session: Session,
    task_id: int,
    *,
    remote_status: str,
    response_summary: str,
    poll_delay_seconds: int,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status != ReliableTaskStatus.CANCELLING:
        raise AppError("TASK_NOT_CANCELLING", "Task must be CANCELLING to record cancel pending.", 409)
    current_time = db_time(now)
    task.remote_status = remote_status
    task.response_summary_json = dumps_sanitized({"cancel": response_summary})
    task.last_polled_at = current_time
    task.next_poll_at = current_time + timedelta(seconds=poll_delay_seconds)
    task.updated_at = current_time
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


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
    remote_progress: float | None = None,
    processing_stage: str | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status != ReliableTaskStatus.RUNNING:
        raise AppError("TASK_NOT_RUNNING", f"Task in {task.status.value} cannot be polled.", 409)
    current_time = db_time(now)
    task.remote_status = remote_status
    task.remote_progress = remote_progress
    task.processing_stage = processing_stage
    task.processing_progress = remote_progress
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
    remote_progress: float | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    if not result_urls:
        raise AppError("TASK_RESULT_URLS_REQUIRED", "At least one result URL is required.", 409)
    raw_urls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result_urls:
        url = str(item.get("url", ""))
        if not url or "://" not in url or url in seen:
            continue
        if len(url) > 8 and url[1:3] == ":\\":
            continue
        seen.add(url)
        raw_urls.append(dict(item))
    if not raw_urls:
        raise AppError("TASK_RESULT_URLS_REQUIRED", "At least one valid result URL is required.", 409)
    current_time = db_time(now)
    task = get_task(session, task_id)
    existing_raw = [item for item in loads_json_list(task.raw_result_urls_json) if isinstance(item, dict)]
    existing_by_hash = {
        source_url_hash(str(item.get("url"))): item for item in existing_raw if isinstance(item.get("url"), str)
    }
    for item in raw_urls:
        existing_by_hash[source_url_hash(str(item["url"]))] = item
    raw_values = list(existing_by_hash.values())
    task.raw_result_urls_json = dumps_sanitized(raw_values)
    task.result_urls_json = dumps_sanitized(
        [result_url_summary(item, is_primary=index == 0) for index, item in enumerate(raw_values)]
    )
    task.remote_status = remote_status
    task.remote_progress = remote_progress
    task.processing_stage = "result_ready"
    task.processing_progress = 1
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


def mark_task_processing_result(
    session: Session,
    task_id: int,
    *,
    max_result_attempts: int,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.PROCESSING_RESULT:
        return task
    task.max_result_attempts = max_result_attempts
    task.next_result_retry_at = None
    task.last_result_retry_delay_seconds = None
    task.updated_at = db_time(now)
    session.add(task)
    session.commit()
    return transition_task(
        session,
        task_id,
        ReliableTaskStatus.PROCESSING_RESULT,
        expected_current=ReliableTaskStatus.RESULT_READY,
        reason_code="result_processing_started",
        now=now,
    )


def expected_media_kind_for_task(task: GenerationTask) -> ResultMediaKind:
    if task.task_type == GenerationTaskType.KEYFRAME_GENERATION:
        return ResultMediaKind.IMAGE
    if task.task_type == GenerationTaskType.VIDEO_GENERATION:
        return ResultMediaKind.VIDEO
    raise AppError("UNSUPPORTED_RESULT_TASK_TYPE", f"Task type {task.task_type.value} has no result media kind.", 400)


def source_url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def result_url_summary(item: dict[str, Any], *, is_primary: bool = False) -> dict[str, Any]:
    url = str(item.get("url", ""))
    parsed = urlsplit(url)
    name = parsed.path.rsplit("/", 1)[-1] if parsed.path else ""
    if len(name) > 80:
        name = name[:77] + "..."
    return {
        "url_hash": source_url_hash(url),
        "host": parsed.hostname or "",
        "path_summary": f"/.../{name}" if name and parsed.path.count("/") > 1 else parsed.path or "/",
        "mime_type": item.get("mime_type") if isinstance(item.get("mime_type"), str) else None,
        "output_type": item.get("output_type") if isinstance(item.get("output_type"), str) else None,
        "is_primary": is_primary,
    }


def initialize_task_results(
    session: Session,
    task_id: int,
    *,
    max_attempts: int,
    now: datetime | None = None,
) -> list[GenerationTaskResult]:
    task = get_task(session, task_id)
    urls = [item for item in loads_json_list(task.raw_result_urls_json) if isinstance(item, dict) and item.get("url")]
    if not urls:
        urls = [item for item in loads_json_list(task.result_urls_json) if isinstance(item, dict) and item.get("url")]
    if not urls:
        raise AppError("TASK_RESULT_URLS_REQUIRED", "Task has no result URLs to process.", 409)
    expected = expected_media_kind_for_task(task)
    primary_index = 0
    for index, item in enumerate(urls):
        metadata = item.get("metadata")
        if isinstance(metadata, dict) and metadata.get("primary") is True:
            primary_index = index
            break
        if item.get("primary") is True:
            primary_index = index
            break
    current_time = db_time(now)
    results: list[GenerationTaskResult] = []
    for index, item in enumerate(urls):
        url = str(item["url"])
        url_hash = source_url_hash(url)
        existing = session.exec(
            select(GenerationTaskResult).where(
                GenerationTaskResult.generation_task_id == task_id,
                GenerationTaskResult.source_url_hash == url_hash,
            )
        ).first()
        if existing is not None:
            results.append(existing)
            continue
        result = GenerationTaskResult(
            generation_task_id=task_id,
            result_index=index,
            source_url=url,
            source_url_hash=url_hash,
            expected_media_kind=expected,
            is_primary=index == primary_index,
            max_attempts=max_attempts,
            created_at=current_time,
            updated_at=current_time,
        )
        session.add(result)
        session.commit()
        session.refresh(result)
        results.append(result)
    return sorted(results, key=lambda item: item.result_index)


def get_primary_task_result(session: Session, task_id: int) -> GenerationTaskResult:
    result = session.exec(
        select(GenerationTaskResult).where(
            GenerationTaskResult.generation_task_id == task_id,
            col(GenerationTaskResult.is_primary).is_(true()),
        )
    ).first()
    if result is None:
        raise AppError("TASK_RESULT_NOT_FOUND", "Primary task result was not initialized.", 409)
    return result


def transition_result(
    session: Session,
    result_id: int,
    status: GenerationTaskResultStatus,
    *,
    now: datetime | None = None,
) -> GenerationTaskResult:
    result = session.get(GenerationTaskResult, result_id)
    if result is None:
        raise AppError("TASK_RESULT_NOT_FOUND", f"Task result {result_id} was not found.", 404)
    if result.status == status:
        return result
    current_time = db_time(now)
    result.status = status
    result.updated_at = current_time
    if status == GenerationTaskResultStatus.DOWNLOADING:
        result.download_started_at = result.download_started_at or current_time
        result.attempt_count += 1
    elif status == GenerationTaskResultStatus.DOWNLOADED:
        result.download_completed_at = current_time
    elif status == GenerationTaskResultStatus.VALIDATED:
        result.validation_completed_at = current_time
    elif status == GenerationTaskResultStatus.COMPLETED:
        result.finalized_at = current_time
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def record_result_downloaded(
    session: Session,
    result_id: int,
    *,
    temporary_relative_path: str,
    file_size: int,
    sha256: str,
    mime_type: str | None,
    file_name: str | None,
    now: datetime | None = None,
) -> GenerationTaskResult:
    result = transition_result(session, result_id, GenerationTaskResultStatus.DOWNLOADED, now=now)
    result.temporary_relative_path = temporary_relative_path
    result.file_size = file_size
    result.sha256 = sha256
    result.mime_type = mime_type
    result.file_name = file_name
    result.updated_at = db_time(now)
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def record_result_validated(
    session: Session,
    result_id: int,
    *,
    media_kind: ResultMediaKind,
    mime_type: str,
    width: int | None,
    height: int | None,
    duration_seconds: float | None = None,
    fps: float | None = None,
    frame_count: int | None = None,
    video_codec: str | None = None,
    audio_codec: str | None = None,
    now: datetime | None = None,
) -> GenerationTaskResult:
    result = transition_result(session, result_id, GenerationTaskResultStatus.VALIDATED, now=now)
    result.media_kind = media_kind
    result.mime_type = mime_type
    result.width = width
    result.height = height
    result.duration_seconds = duration_seconds
    result.fps = fps
    result.frame_count = frame_count
    result.video_codec = video_codec
    result.audio_codec = audio_codec
    result.updated_at = db_time(now)
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def record_result_final_path(
    session: Session,
    result_id: int,
    *,
    final_relative_path: str,
    now: datetime | None = None,
) -> GenerationTaskResult:
    result = transition_result(session, result_id, GenerationTaskResultStatus.FINALIZING, now=now)
    result.final_relative_path = final_relative_path
    result.updated_at = db_time(now)
    session.add(result)
    session.commit()
    session.refresh(result)
    return result


def schedule_result_retry(
    session: Session,
    task_id: int,
    result_id: int,
    *,
    delay_seconds: float,
    error_code: TaskErrorCode | str,
    error_message: str,
    error_details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> GenerationTaskResult:
    current_time = db_time(now)
    task = get_task(session, task_id)
    result = session.get(GenerationTaskResult, result_id)
    if result is None:
        raise AppError("TASK_RESULT_NOT_FOUND", f"Task result {result_id} was not found.", 404)
    task.result_retry_count += 1
    result.error_code = error_code.value if isinstance(error_code, TaskErrorCode) else error_code
    result.error_message = error_message
    result.error_details_json = dumps_sanitized(error_details or {})
    if task.result_retry_count >= task.max_result_attempts or result.attempt_count >= result.max_attempts:
        result.status = GenerationTaskResultStatus.FAILED
        result.next_retry_at = None
        result.updated_at = current_time
        task.next_result_retry_at = None
        task.last_result_retry_delay_seconds = None
        session.add(result)
        session.add(task)
        session.commit()
        mark_task_failed(
            session,
            task_id,
            error_code=error_code,
            error_message=error_message,
            error_details=error_details,
            now=current_time,
        )
        return result
    result.status = GenerationTaskResultStatus.RETRY_WAIT
    result.next_retry_at = current_time + timedelta(seconds=delay_seconds)
    result.updated_at = current_time
    task.next_result_retry_at = result.next_retry_at
    task.last_result_retry_delay_seconds = delay_seconds
    task.updated_at = current_time
    record_task_error(
        session,
        task_id,
        error_code=error_code,
        error_message=error_message,
        error_details=error_details,
        now=current_time,
    )
    session.add(result)
    session.add(task)
    session.commit()
    session.refresh(result)
    return result


def register_result_asset(
    session: Session,
    task_id: int,
    result_id: int,
    *,
    final_path: str,
    asset_type: AssetType,
    shot_next_status: ShotStatus,
    workflow_reason: str,
    now: datetime | None = None,
) -> tuple[GenerationTask, Any]:
    from app.services import studio

    current_time = db_time(now)
    task = get_task(session, task_id)
    result = session.get(GenerationTaskResult, result_id)
    if result is None:
        raise AppError("TASK_RESULT_NOT_FOUND", f"Task result {result_id} was not found.", 404)
    if task.result_asset_id is not None and result.asset_id is not None:
        return task, session.get(Asset, result.asset_id)
    request = session.get(GenerationRequest, task.generation_request_id)
    if request is None:
        raise AppError("REQUEST_NOT_FOUND", f"Generation request {task.generation_request_id} was not found.", 404)
    shot = session.get(Shot, task.shot_id)
    if shot is None:
        raise AppError("SHOT_NOT_FOUND", f"Shot {task.shot_id} was not found.", 404)
    latest = studio.active_or_latest_task_for_request(session, request.id or 0)
    if latest and latest.id != task.id:
        record_task_error(
            session,
            task_id,
            error_code="STALE_RESULT",
            error_message="Task result is stale and will not update the shot.",
            now=current_time,
        )
        transition_task(session, task_id, ReliableTaskStatus.FAILED, reason_code="stale_result", now=current_time)
        return get_task(session, task_id), None
    if result.asset_id is not None:
        asset = session.get(Asset, result.asset_id)
    else:
        asset = session.exec(
            select(Asset).where(
                Asset.project_id == task.project_id,
                Asset.shot_id == task.shot_id,
                Asset.type == asset_type,
                Asset.sha256 == result.sha256,
            )
        ).first()
        if asset is None:
            asset = Asset(
                project_id=task.project_id,
                shot_id=task.shot_id,
                type=asset_type,
                path=final_path,
                mime_type=result.mime_type or "application/octet-stream",
                sha256=result.sha256,
                file_size=result.file_size,
                width=result.width,
                height=result.height,
                duration_seconds=result.duration_seconds,
                fps=result.fps,
                frame_count=result.frame_count,
                video_codec=result.video_codec,
                audio_codec=result.audio_codec,
                created_at=current_time,
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)
        result.asset_id = asset.id
    result.status = GenerationTaskResultStatus.COMPLETED
    result.finalized_at = result.finalized_at or current_time
    result.updated_at = current_time
    task.result_asset_id = result.asset_id
    task.next_result_retry_at = None
    task.last_result_retry_delay_seconds = None
    session.add(result)
    session.add(task)
    request.status = GenerationTaskStatus.SUCCEEDED
    request.output_asset_ids = json.dumps([result.asset_id])
    request.updated_at = current_time
    session.add(request)
    session.commit()
    if shot.status != shot_next_status:
        studio.transition_shot(session, shot, shot_next_status, workflow_reason)
    studio.log_task(session, request, shot, f"{request.kind.value.lower()} result registered", task=task)
    completed = mark_task_succeeded(
        session,
        task_id,
        result_asset_id=result.asset_id,
        response_summary={"asset_id": result.asset_id, "asset_type": asset_type.value},
        now=current_time,
    )
    return completed, session.get(Asset, result.asset_id)


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
    delay_seconds: float,
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
        task.next_retry_at = None
        task.last_retry_delay_seconds = None
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
    task.last_retry_delay_seconds = delay_seconds
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


def schedule_cancel_retry(
    session: Session,
    task_id: int,
    *,
    delay_seconds: float,
    error_code: TaskErrorCode | str = TaskErrorCode.UNKNOWN_ERROR,
    error_message: str = "",
    error_details: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    current_time = db_time(now)
    task = get_task(session, task_id)
    if task.status != ReliableTaskStatus.CANCELLING:
        raise AppError("TASK_NOT_CANCELLING", "Task must be CANCELLING to schedule a cancel retry.", 409)
    record_task_error(
        session,
        task_id,
        error_code=error_code,
        error_message=error_message,
        error_details=error_details,
        now=current_time,
    )
    task = get_task(session, task_id)
    next_retry_count = task.retry_count + 1
    if next_retry_count >= task.max_attempts:
        task.retry_count = next_retry_count
        task.next_poll_at = None
        task.last_retry_delay_seconds = None
        session.add(task)
        session.commit()
        return transition_task(
            session,
            task_id,
            ReliableTaskStatus.FAILED,
            reason_code="cancel_retry_limit_exceeded",
            now=current_time,
        )
    task.retry_count = next_retry_count
    task.next_poll_at = current_time + timedelta(seconds=delay_seconds)
    task.last_retry_delay_seconds = delay_seconds
    task.updated_at = current_time
    session.add(task)
    session.commit()
    return task


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
    if task.status not in {
        ReliableTaskStatus.RUNNING,
        ReliableTaskStatus.SUBMITTING,
        ReliableTaskStatus.PROCESSING_RESULT,
    }:
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


def request_task_cancel(
    session: Session,
    task_id: int,
    *,
    reason: str = "",
    requested_by: str = "local-user",
    cancellation_timeout_seconds: int | None = None,
    now: datetime | None = None,
) -> GenerationTask:
    task = get_task(session, task_id)
    current_time = db_time(now)
    if task.status == ReliableTaskStatus.SUCCEEDED:
        raise AppError("TASK_NOT_CANCELLABLE", "Succeeded tasks cannot be cancelled.", 409)
    if task.status == ReliableTaskStatus.PROCESSING_RESULT:
        raise AppError("TASK_NOT_CANCELLABLE", "Tasks processing local results cannot be cancelled.", 409)
    if task.status in {ReliableTaskStatus.FAILED, ReliableTaskStatus.CANCELLED}:
        return task
    task.cancel_requested_at = task.cancel_requested_at or current_time
    task.cancel_reason = reason
    task.cancel_requested_by = requested_by
    task.next_retry_at = None
    task.next_poll_at = None
    if cancellation_timeout_seconds is not None and task.status not in {
        ReliableTaskStatus.QUEUED,
        ReliableTaskStatus.RETRY_WAIT,
        ReliableTaskStatus.RESULT_READY,
    }:
        task.cancellation_deadline_at = current_time + timedelta(seconds=cancellation_timeout_seconds)
    session.add(task)
    session.commit()
    if task.status == ReliableTaskStatus.QUEUED:
        return transition_task(
            session, task_id, ReliableTaskStatus.CANCELLED, reason_code="cancelled_before_start", now=current_time
        )
    if task.status in {ReliableTaskStatus.RETRY_WAIT, ReliableTaskStatus.RESULT_READY}:
        return transition_task(session, task_id, ReliableTaskStatus.CANCELLED, reason_code="cancelled_local", now=current_time)
    if task.status == ReliableTaskStatus.CANCELLING:
        return task
    return transition_task(session, task_id, ReliableTaskStatus.CANCELLING, reason_code="cancel_requested", now=current_time)


def mark_task_cancelled(session: Session, task_id: int, *, now: datetime | None = None) -> GenerationTask:
    task = get_task(session, task_id)
    if task.status == ReliableTaskStatus.CANCELLED:
        return task
    if task.status != ReliableTaskStatus.CANCELLING:
        raise AppError("TASK_NOT_CANCELLING", "Task must be cancelling before it can be cancelled.", 409)
    return transition_task(session, task_id, ReliableTaskStatus.CANCELLED, reason_code="task_cancelled", now=now)


def manual_retry_task(
    session: Session,
    task_id: int,
    *,
    idempotency_key: str,
    reason: str = "",
    now: datetime | None = None,
) -> GenerationTask:
    source = get_task(session, task_id)
    if source.status not in {ReliableTaskStatus.FAILED, ReliableTaskStatus.CANCELLED}:
        raise AppError("TASK_NOT_RETRYABLE_MANUALLY", f"Task in {source.status.value} cannot be manually retried.", 409)
    command = create_or_get_command(
        session,
        task_id=task_id,
        command_type=TaskCommandType.MANUAL_RETRY,
        idempotency_key=idempotency_key,
        reason=reason,
    )
    if command.result_task_id is not None:
        return get_task(session, command.result_task_id)
    request = session.get(GenerationRequest, source.generation_request_id)
    if request is None:
        raise AppError("GENERATION_REQUEST_NOT_FOUND", "Generation request for retry was not found.", 404)
    retry_task = create_task_attempt(
        session,
        generation_request=request,
        task_type=source.task_type,
        provider_id=source.provider_id,
        retry_of_task_id=source.id,
        max_attempts=source.max_attempts,
        request_payload=loads_json_object(source.request_payload_json),
        provider_config_snapshot=loads_json_object(source.provider_config_snapshot_json),
        idempotency_key=f"manual-retry:{task_id}:{idempotency_key}",
    )
    complete_command(session, command, result_task_id=retry_task.id, now=now)
    return retry_task


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
    if task.status in {ReliableTaskStatus.RESULT_READY, ReliableTaskStatus.PROCESSING_RESULT}:
        if task.next_result_retry_at and task.next_result_retry_at > current_time:
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
            or_(
                col(GenerationTask.next_result_retry_at).is_(None),
                col(GenerationTask.next_result_retry_at) <= current_time,
            ),
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
