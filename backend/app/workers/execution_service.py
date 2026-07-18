from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from sqlmodel import Session

from app.models.entities import GenerationRequest, GenerationTask, ReliableTaskStatus, TaskErrorCode
from app.providers.async_base import AsyncGenerationProvider
from app.providers.exceptions import ProviderError
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
        return False

    async def submit_task_once(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            task = task_service.transition_task(
                session,
                task_id,
                ReliableTaskStatus.SUBMITTING,
                expected_current=ReliableTaskStatus.QUEUED,
                reason_code="worker_submit",
                now=now,
            )
        return await self._submit_existing_task(task.id or task_id, now=now)

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
            self._record_provider_error(task_id, exc, now=now)
            return True
        if not self._lease_owned(task_id, now=now):
            return False
        self._apply_poll_result(task_id, result, now=now)
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
            if exc.retryable:
                task_service.schedule_retry(
                    session,
                    task_id,
                    delay_seconds=self.settings.retry_delay_seconds,
                    error_code=exc.to_task_error_code(),
                    error_message=exc.message,
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

    def _apply_poll_result(self, task_id: int, result: ProviderJobResult, *, now: datetime | None = None) -> None:
        with self.session_factory() as session:
            if result.normalized_status in {RemoteJobStatus.QUEUED, RemoteJobStatus.RUNNING}:
                task_service.record_running_poll(
                    session,
                    task_id,
                    remote_status=str(result.remote_status or result.normalized_status.value),
                    response_summary=result.raw_response_summary,
                    poll_delay_seconds=self.settings.poll_interval_seconds,
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
