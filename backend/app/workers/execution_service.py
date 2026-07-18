from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session

from app.domain.retry_policy import RetryPolicyConfig, decide_error
from app.models.entities import GenerationRequest, GenerationTask, ReliableTaskStatus, TaskErrorCode
from app.providers.async_base import AsyncGenerationProvider
from app.providers.exceptions import ProviderCancellationError, ProviderError
from app.providers.models import (
    ImageGenerationRequest,
    ProviderJobResult,
    ProviderResultUrl,
    RemoteJobStatus,
    VideoGenerationRequest,
)
from app.providers.registry import ProviderRegistry
from app.services import task_service
from app.workers.request_factory import ProviderRequestFactory
from app.workers.settings import WorkerSettings

SessionFactory = Callable[[], AbstractContextManager[Session]]


class ProviderExecutionService:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        registry: ProviderRegistry,
        settings: WorkerSettings,
        request_factory: ProviderRequestFactory | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.settings = settings
        self.request_factory = request_factory or ProviderRequestFactory()

    async def process_task_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            status = task.status
        if status == ReliableTaskStatus.QUEUED:
            return await self.submit_task_once(task_id, now=now)
        if status == ReliableTaskStatus.SUBMITTING:
            return await self.recover_submitting_once(task_id, now=now)
        if status == ReliableTaskStatus.RUNNING:
            return await self.poll_task_once(task_id, now=now)
        if status == ReliableTaskStatus.RETRY_WAIT:
            return await self.recover_retry_once(task_id, now=now)
        if status == ReliableTaskStatus.CANCELLING:
            return await self.cancel_task_once(task_id, now=now)
        return False

    async def submit_task_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task_service.transition_task(
                session,
                task_id,
                ReliableTaskStatus.SUBMITTING,
                expected_current=ReliableTaskStatus.QUEUED,
                reason_code="worker_submit",
                now=now,
            )
            refreshed = task_service.get_task(session, task_id)
            refreshed.submission_deadline_at = task_service.db_time(now) + timedelta(
                seconds=self.settings.submission_timeout_seconds
            )
            session.add(refreshed)
            session.commit()
        return await self._submit_existing_task(task_id, now=now)

    async def recover_submitting_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if task.remote_job_id:
                task_service.repair_submitting_with_remote_job(
                    session,
                    task_id,
                    poll_delay_seconds=self.settings.poll_interval_seconds,
                    now=now,
                )
                return True
            if task.submission_deadline_at and task.submission_deadline_at <= task_service.db_time(now):
                self._record_task_error(
                    task_id,
                    TaskErrorCode.REQUEST_TIMEOUT,
                    "Submission timed out before remote_job_id was stored.",
                    retryable=True,
                    now=now,
                )
                return True
        return await self._submit_existing_task(task_id, now=now)

    async def recover_retry_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if task.remote_job_id:
                task_service.transition_task(
                    session,
                    task_id,
                    ReliableTaskStatus.RUNNING,
                    expected_current=ReliableTaskStatus.RETRY_WAIT,
                    reason_code="retry_poll_recovered",
                    now=now,
                )
                return True
            task_service.transition_task(
                session,
                task_id,
                ReliableTaskStatus.SUBMITTING,
                expected_current=ReliableTaskStatus.RETRY_WAIT,
                reason_code="retry_submit_recovered",
                now=now,
            )
        return await self._submit_existing_task(task_id, now=now)

    async def poll_task_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if task.job_deadline_at and task.job_deadline_at <= task_service.db_time(now):
                if provider := self.registry.get(task.provider_id):
                    if provider.get_capabilities().supports_cancel:
                        task_service.request_task_cancel(
                            session,
                            task_id,
                            reason="Remote job timeout.",
                            cancellation_timeout_seconds=self.settings.cancellation_timeout_seconds,
                            now=now,
                        )
                        task_service.record_task_error(
                            session,
                            task_id,
                            error_code=TaskErrorCode.JOB_TIMEOUT,
                            error_message="Remote job exceeded configured timeout; cancellation requested.",
                            now=now,
                        )
                        return True
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=TaskErrorCode.JOB_TIMEOUT,
                    error_message="Remote job exceeded configured timeout.",
                    now=now,
                )
                return True
            if not task.remote_job_id:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=TaskErrorCode.INVALID_REMOTE_RESPONSE,
                    error_message="RUNNING task has no remote_job_id.",
                    now=now,
                )
                return True
            provider = self._provider_or_fail(session, task)
            remote_job_id = task.remote_job_id
        if not self._lease_owned(task_id, now=now):
            return False
        try:
            result = await provider.get_job(remote_job_id)
        except ProviderError as exc:
            self._record_cancel_provider_error(task_id, exc, now=now)
            return True
        if not self._lease_owned(task_id, now=now):
            return False
        self._apply_poll_result(task_id, result, now=now)
        return True

    async def cancel_task_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if task.cancellation_deadline_at and task.cancellation_deadline_at <= task_service.db_time(now):
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=TaskErrorCode.REQUEST_TIMEOUT,
                    error_message="Cancellation deadline elapsed without remote confirmation.",
                    now=now,
                )
                return True
            provider = self._provider_or_fail(session, task)
            remote_job_id = task.remote_job_id
            needs_submit_lookup = remote_job_id is None
            if needs_submit_lookup:
                request = self._build_provider_request(session, task, provider)
        if not self._lease_owned(task_id, now=now):
            return False
        if needs_submit_lookup:
            try:
                if isinstance(request, ImageGenerationRequest):
                    submit = await provider.submit_image(request)
                else:
                    submit = await provider.submit_video(request)
            except ProviderError as exc:
                self._record_provider_error(task_id, exc, now=now)
                return True
            remote_job_id = submit.remote_job_id
            with self.session_factory() as session:
                task_service.store_cancelling_remote_job(
                    session,
                    task_id,
                    remote_job_id=submit.remote_job_id,
                    remote_status=submit.remote_status.value,
                    response_summary=submit.raw_response_summary,
                    now=now,
                )
        try:
            cancel_result = await provider.cancel_job(remote_job_id or "")
        except ProviderCancellationError as exc:
            with self.session_factory() as session:
                task_service.record_task_error(
                    session,
                    task_id,
                    error_code=TaskErrorCode.CANCELLED,
                    error_message=f"Provider does not support remote cancellation: {exc.message}",
                    error_details=exc.as_details(),
                    now=now,
                )
                task_service.mark_task_cancelled(session, task_id, now=now)
            return True
        except ProviderError as exc:
            self._record_provider_error(task_id, exc, now=now)
            return True
        with self.session_factory() as session:
            if cancel_result.remote_status == RemoteJobStatus.CANCELLED:
                task_service.record_task_error(
                    session,
                    task_id,
                    error_code=TaskErrorCode.CANCELLED,
                    error_message="Task cancelled.",
                    now=now,
                )
                task_service.mark_task_cancelled(session, task_id, now=now)
            elif cancel_result.remote_status == RemoteJobStatus.SUCCEEDED:
                task_service.transition_task(
                    session,
                    task_id,
                    ReliableTaskStatus.RUNNING,
                    expected_current=ReliableTaskStatus.CANCELLING,
                    reason_code="cancel_late_remote_succeeded",
                    now=now,
                )
            else:
                task_service.record_cancel_pending(
                    session,
                    task_id,
                    remote_status=cancel_result.remote_status.value,
                    response_summary=cancel_result.raw_response_summary,
                    poll_delay_seconds=self.settings.poll_interval_seconds,
                    now=now,
                )
        return True

    async def _submit_existing_task(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            provider = self._provider_or_fail(session, task)
            request = self._build_provider_request(session, task, provider)
        if not self._lease_owned(task_id, now=now):
            return False
        try:
            if isinstance(request, ImageGenerationRequest):
                result = await provider.submit_image(request)
            else:
                result = await provider.submit_video(request)
        except ProviderError as exc:
            self._record_provider_error(task_id, exc, now=now)
            return True
        if not self._lease_owned(task_id, now=now):
            return False
        with self.session_factory() as session:
            task_service.mark_task_remote_submitted(
                session,
                task_id,
                remote_job_id=result.remote_job_id,
                remote_status=result.remote_status.value,
                response_summary=result.raw_response_summary,
                poll_delay_seconds=self.settings.poll_interval_seconds,
                job_timeout_seconds=self.settings.job_timeout_seconds,
                now=now,
            )
        return True

    def _provider_or_fail(self, session: Session, task: GenerationTask) -> AsyncGenerationProvider:
        try:
            return self.registry.get(task.provider_id)
        except ProviderError as exc:
            task_service.mark_task_failed(
                session,
                task.id or 0,
                error_code=exc.to_task_error_code(),
                error_message=exc.message,
                error_details=exc.as_details(),
            )
            raise

    def _build_provider_request(
        self,
        session: Session,
        task: GenerationTask,
        provider: AsyncGenerationProvider,
    ) -> ImageGenerationRequest | VideoGenerationRequest:
        generation_request = session.get(GenerationRequest, task.generation_request_id)
        if generation_request is None:
            raise ProviderError("Generation request was not found.")
        return self.request_factory.build(generation_request, task, provider.get_capabilities())

    def _record_provider_error(self, task_id: int, exc: ProviderError, *, now: datetime | None = None) -> None:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if task.status == ReliableTaskStatus.CANCELLING:
                self._record_cancel_provider_error(task_id, exc, now=now)
                return
        self._record_task_error(
            task_id,
            exc.to_task_error_code(),
            exc.message,
            retryable=exc.retryable,
            details=exc.as_details(),
            now=now,
        )

    def _record_cancel_provider_error(self, task_id: int, exc: ProviderError, *, now: datetime | None = None) -> None:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            decision = decide_error(
                exc.to_task_error_code(),
                retry_count=task.retry_count,
                now=now,
                config=RetryPolicyConfig(
                    base_seconds=self.settings.retry_base_seconds,
                    max_seconds=self.settings.retry_max_seconds,
                    jitter_ratio=self.settings.retry_jitter_ratio,
                ),
            )
            if exc.retryable and decision.retryable:
                task_service.schedule_cancel_retry(
                    session,
                    task_id,
                    delay_seconds=decision.retry_after_seconds or self.settings.retry_base_seconds,
                    error_code=exc.to_task_error_code(),
                    error_message=exc.message,
                    error_details=exc.as_details(),
                    now=now,
                )
            else:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=exc.to_task_error_code(),
                    error_message=exc.message,
                    error_details=exc.as_details(),
                    now=now,
                )

    def _record_task_error(
        self,
        task_id: int,
        error_code: TaskErrorCode | str,
        message: str,
        *,
        retryable: bool,
        details: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> None:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            decision = decide_error(
                error_code,
                retry_count=task.retry_count,
                now=now,
                config=RetryPolicyConfig(
                    base_seconds=self.settings.retry_base_seconds,
                    max_seconds=self.settings.retry_max_seconds,
                    jitter_ratio=self.settings.retry_jitter_ratio,
                ),
            )
            if retryable and decision.retryable:
                task_service.schedule_retry(
                    session,
                    task_id,
                    delay_seconds=decision.retry_after_seconds or self.settings.retry_base_seconds,
                    error_code=error_code,
                    error_message=message,
                    now=now,
                )
            else:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=error_code,
                    error_message=message,
                    error_details=details,
                    now=now,
                )

    def _apply_poll_result(self, task_id: int, result: ProviderJobResult, *, now: datetime | None = None) -> None:
        with self.session_factory() as session:
            if result.normalized_status in {RemoteJobStatus.QUEUED, RemoteJobStatus.RUNNING}:
                task_service.record_running_poll(
                    session,
                    task_id,
                    remote_status=str(result.remote_status or result.normalized_status.value),
                    response_summary=result.raw_response_summary,
                    poll_delay_seconds=self.settings.poll_interval_seconds,
                    remote_progress=result.progress,
                    processing_stage=result.normalized_status.value.lower(),
                    now=now,
                )
                return
            if result.normalized_status == RemoteJobStatus.SUCCEEDED:
                urls = [self._result_url_payload(item) for item in result.result_urls]
                if not urls:
                    task_service.mark_task_failed(
                        session,
                        task_id,
                        error_code=TaskErrorCode.INVALID_REMOTE_RESPONSE,
                        error_message="Remote job succeeded without result URLs.",
                        now=now,
                    )
                    return
                task_service.mark_task_result_ready(
                    session,
                    task_id,
                    remote_status=str(result.remote_status or result.normalized_status.value),
                    result_urls=urls,
                    response_summary=result.raw_response_summary,
                    remote_progress=result.progress,
                    now=now,
                )
                return
            if result.normalized_status == RemoteJobStatus.FAILED:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=result.error_code or TaskErrorCode.UNKNOWN_ERROR,
                    error_message=result.error_message or "Remote job failed.",
                    error_details={"remote_status": result.remote_status},
                    now=now,
                )
                return
            if result.normalized_status == RemoteJobStatus.CANCELLED:
                task_service.mark_remote_cancelled(session, task_id, now=now)
                return
            task = task_service.record_running_poll(
                session,
                task_id,
                remote_status=str(result.remote_status or "UNKNOWN"),
                response_summary=result.raw_response_summary,
                poll_delay_seconds=self.settings.poll_interval_seconds,
                remote_progress=result.progress,
                processing_stage="unknown",
                now=now,
            )
            if task.poll_count >= self.settings.max_unknown_polls:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=TaskErrorCode.INVALID_REMOTE_RESPONSE,
                    error_message="Remote status remained UNKNOWN beyond the configured limit.",
                    now=now,
                )

    def _result_url_payload(self, item: ProviderResultUrl) -> dict[str, Any]:
        url = item.url
        return {
            "url": url,
            "mime_type": item.mime_type,
            "file_name": url.rsplit("/", 1)[-1],
            "metadata": item.metadata,
        }

    def _lease_owned(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            return task_service.task_lease_is_owned(
                session,
                task_id,
                worker_id=self.settings.worker_id,
                now=now,
            )
