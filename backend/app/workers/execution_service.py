from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, select

from app.core.errors import AppError
from app.core.redaction import redact_sensitive
from app.domain.retry_policy import RetryPolicyConfig, decide_error
from app.core.config import get_settings
from app.models.entities import (
    Asset,
    GenerationRequest,
    GenerationTask,
    ProviderAssetCache,
    ReliableTaskStatus,
    TaskErrorCode,
    WorkerStatus,
    WorkerType,
)
from app.providers.async_base import AsyncGenerationProvider
from app.providers.exceptions import ProviderCancellationError, ProviderError, ProviderUnsupportedCapabilityError
from app.providers.models import (
    AssetReference,
    ImageGenerationRequest,
    ProviderJobResult,
    ProviderResultUrl,
    RemoteJobStatus,
    VideoGenerationRequest,
)
from app.providers.registry import ProviderRegistry
from app.services import live_orchestration, provider_management, task_service, worker_status
from app.workers.request_factory import ProviderRequestFactory
from app.workers.settings import WorkerSettings
from app.workers.lease_guard import LeaseLostError, TaskLeaseGuard, TaskLeaseGuardConfig

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
        async with TaskLeaseGuard(
            TaskLeaseGuardConfig(
                task_id=task_id,
                worker_id=self.settings.worker_id,
                lease_seconds=self.settings.lease_seconds,
                session_factory=self.session_factory,
                heartbeat=lambda: worker_status.safe_heartbeat(
                    self.session_factory,
                    worker_id=self.settings.worker_id,
                    worker_type=WorkerType.GENERATION,
                    status=WorkerStatus.BUSY,
                    current_task_id=task_id,
                ),
            )
        ) as lease_guard:
            with self.session_factory() as session:
                task = task_service.get_task(session, task_id)
                status = task.status
            if status == ReliableTaskStatus.QUEUED:
                return await self.submit_task_once(task_id, now=now, lease_guard=lease_guard)
            if status == ReliableTaskStatus.SUBMITTING:
                return await self.recover_submitting_once(task_id, now=now, lease_guard=lease_guard)
            if status == ReliableTaskStatus.RUNNING:
                return await self.poll_task_once(task_id, now=now, lease_guard=lease_guard)
            if status == ReliableTaskStatus.RETRY_WAIT:
                return await self.recover_retry_once(task_id, now=now, lease_guard=lease_guard)
            if status == ReliableTaskStatus.CANCELLING:
                return await self.cancel_task_once(task_id, now=now, lease_guard=lease_guard)
            return False

    async def submit_task_once(
        self, task_id: int, *, now: datetime | None = None, lease_guard: TaskLeaseGuard | None = None
    ) -> bool:
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
        return await self._submit_existing_task(task_id, now=now, lease_guard=lease_guard)

    async def recover_submitting_once(
        self, task_id: int, *, now: datetime | None = None, lease_guard: TaskLeaseGuard | None = None
    ) -> bool:
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
        return await self._submit_existing_task(task_id, now=now, lease_guard=lease_guard)

    async def recover_retry_once(
        self, task_id: int, *, now: datetime | None = None, lease_guard: TaskLeaseGuard | None = None
    ) -> bool:
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
        return await self._submit_existing_task(task_id, now=now, lease_guard=lease_guard)

    async def poll_task_once(
        self, task_id: int, *, now: datetime | None = None, lease_guard: TaskLeaseGuard | None = None
    ) -> bool:
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
            result = await (lease_guard.run_cancellable(provider.get_job(remote_job_id)) if lease_guard else provider.get_job(remote_job_id))
        except ProviderError as exc:
            self._record_provider_error(task_id, exc, now=now)
            return True
        except LeaseLostError:
            return False
        except Exception as exc:
            self._record_unexpected_error(task_id, exc, now=now)
            return True
        if not self._lease_owned(task_id, now=now):
            return False
        if lease_guard:
            lease_guard.ensure_owned()
        self._apply_poll_result(task_id, result, now=now)
        return True

    async def cancel_task_once(
        self, task_id: int, *, now: datetime | None = None, lease_guard: TaskLeaseGuard | None = None
    ) -> bool:
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
                try:
                    request = await self._build_provider_request(session, task, provider)
                except ProviderError as exc:
                    self._record_provider_error(task_id, exc, now=now)
                    return True
                except Exception as exc:
                    self._record_unexpected_error(task_id, exc, now=now)
                    return True
        if not self._lease_owned(task_id, now=now):
            return False
        if needs_submit_lookup:
            try:
                if isinstance(request, ImageGenerationRequest):
                    submit = await (
                        lease_guard.run_cancellable(provider.submit_image(request))
                        if lease_guard
                        else provider.submit_image(request)
                    )
                else:
                    submit = await (
                        lease_guard.run_cancellable(provider.submit_video(request))
                        if lease_guard
                        else provider.submit_video(request)
                    )
            except ProviderError as exc:
                self._record_provider_error(task_id, exc, now=now)
                return True
            except LeaseLostError:
                return False
            except Exception as exc:
                self._record_unexpected_error(task_id, exc, now=now)
                return True
            remote_job_id = submit.remote_job_id
            if lease_guard:
                lease_guard.ensure_owned()
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
            cancel_result = await (
                lease_guard.run_cancellable(provider.cancel_job(remote_job_id or ""))
                if lease_guard
                else provider.cancel_job(remote_job_id or "")
            )
        except ProviderCancellationError as exc:
            with self.session_factory() as session:
                task_service.record_task_error(
                    session,
                    task_id,
                    error_code=TaskErrorCode.CANCELLED,
                    error_message=f"Provider does not support remote cancellation: {self._safe_message(exc.message)}",
                    error_details=exc.as_details(),
                    now=now,
                )
                task_service.mark_task_cancelled(session, task_id, now=now)
            return True
        except ProviderError as exc:
            self._record_provider_error(task_id, exc, now=now)
            return True
        except LeaseLostError:
            return False
        except Exception as exc:
            self._record_unexpected_error(task_id, exc, now=now)
            return True
        if lease_guard:
            lease_guard.ensure_owned()
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

    async def _submit_existing_task(
        self, task_id: int, *, now: datetime | None = None, lease_guard: TaskLeaseGuard | None = None
    ) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            provider = self._provider_or_fail(session, task)
            try:
                generation_request = session.get(GenerationRequest, task.generation_request_id)
                if generation_request is not None:
                    if task.provider_id == "toapis":
                        if not generation_request.provider_live_enable_snapshot:
                            raise AppError("LIVE_ORCHESTRATION_DISABLED", "Generation request was created without an enabled TOAPIS live gate.", 409)
                        live_orchestration.validate_live_orchestration_gate(
                            session, expected_snapshot_hash=generation_request.pricing_snapshot_hash
                        )
                    provider_management.check_budget_before_task(session, generation_request)
                provider_management.ensure_task_usage_estimate(session, task)
                request = await self._build_provider_request(session, task, provider)
            except AppError as exc:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=TaskErrorCode.CONFIGURATION_ERROR,
                    error_message=self._safe_message(exc.message),
                    error_details={"error_code": exc.code},
                    now=now,
                )
                return True
            except ProviderError as exc:
                self._record_provider_error(task_id, exc, now=now)
                return True
            except Exception as exc:
                self._record_unexpected_error(task_id, exc, now=now)
                return True
        if not self._lease_owned(task_id, now=now):
            return False
        try:
            if isinstance(request, ImageGenerationRequest):
                result = await (
                    lease_guard.run_cancellable(provider.submit_image(request))
                    if lease_guard
                    else provider.submit_image(request)
                )
            else:
                result = await (
                    lease_guard.run_cancellable(provider.submit_video(request))
                    if lease_guard
                    else provider.submit_video(request)
                )
        except ProviderError as exc:
            self._record_provider_error(task_id, exc, now=now)
            return True
        except LeaseLostError:
            return False
        except Exception as exc:
            self._record_unexpected_error(task_id, exc, now=now)
            return True
        if not self._lease_owned(task_id, now=now):
            return False
        if lease_guard:
            lease_guard.ensure_owned()
        with self.session_factory() as session:
            if result.response_mode == "INLINE_RESULT" and result.result_urls:
                task_service.mark_inline_submit_result_ready(
                    session,
                    task_id,
                    result_urls=[self._result_url_payload(item) for item in result.result_urls],
                    response_summary=result.raw_response_summary,
                    now=now,
                )
            elif result.remote_job_id:
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
            else:
                task_service.mark_task_failed(
                    session, task_id, error_code=TaskErrorCode.INVALID_REMOTE_RESPONSE,
                    error_message="Provider submit returned neither a job ID nor an inline result.", now=now,
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
                error_message=self._safe_message(exc.message),
                error_details=exc.as_details(),
            )
            raise

    async def _build_provider_request(
        self,
        session: Session,
        task: GenerationTask,
        provider: AsyncGenerationProvider,
    ) -> ImageGenerationRequest | VideoGenerationRequest:
        generation_request = session.get(GenerationRequest, task.generation_request_id)
        if generation_request is None:
            raise ProviderError("Generation request was not found.")
        prepared = await self._prepare_assets(session, task, provider)
        return self.request_factory.build(generation_request, task, provider.get_capabilities(), prepared_assets=prepared)

    async def _prepare_assets(
        self,
        session: Session,
        task: GenerationTask,
        provider: AsyncGenerationProvider,
    ) -> dict[int, AssetReference]:
        payload = task_service.loads_json_object(task.request_payload_json)
        input_asset_ids = [item for item in payload.get("input_asset_ids", []) if isinstance(item, int)] if isinstance(payload.get("input_asset_ids"), list) else []
        reference_asset_ids = [item for item in payload.get("reference_asset_ids", []) if isinstance(item, int)] if isinstance(payload.get("reference_asset_ids"), list) else []
        asset_ids = list(dict.fromkeys(input_asset_ids + reference_asset_ids))
        if task.provider_id == "mock" or not asset_ids:
            return {}
        assets: dict[int, Asset] = {}
        paths: dict[int, Path] = {}
        settings = get_settings()
        storage_root = settings.storage_dir.resolve()
        for asset_id in asset_ids:
            asset = session.get(Asset, asset_id)
            if asset is None:
                raise ProviderError("Input asset was not found.", retryable=False)
            path = Path(asset.path).resolve()
            if path != storage_root and storage_root not in path.parents:
                raise ProviderError("Input asset path is outside storage.", retryable=False)
            if not path.exists() or not path.is_file():
                raise ProviderError("Input asset file is missing.", retryable=False)
            assets[asset_id] = asset
            paths[asset_id] = path
        if (
            task.provider_id == "toapis"
            and payload.get("generation_mode") == "FIRST_LAST_FRAME"
            and len(input_asset_ids) >= 2
        ):
            _validate_toapis_video_anchors(
                [paths[input_asset_ids[0]], paths[input_asset_ids[1]]],
                max_pixels=settings.result_max_image_pixels,
            )
        upload = getattr(provider, "upload_asset", None)
        if upload is None:
            raise ProviderUnsupportedCapabilityError("PROVIDER_ASSET_UPLOAD_UNSUPPORTED")
        prepared: dict[int, AssetReference] = {}
        for asset_id in asset_ids:
            asset = assets[asset_id]
            path = paths[asset_id]
            max_upload_bytes = (
                settings.result_max_image_bytes
                if str(asset.mime_type).lower().startswith("image/")
                else settings.result_max_video_bytes
            )
            if path.stat().st_size > max_upload_bytes:
                raise ProviderError("Input asset exceeds the provider upload size limit.", retryable=False)
            sha256 = _sha256_file(path)
            if asset.sha256 and asset.sha256 != sha256:
                raise ProviderError("Input asset SHA-256 does not match the stored Asset metadata.", retryable=False)
            cached = session.exec(
                select(ProviderAssetCache).where(
                    ProviderAssetCache.provider_id == task.provider_id,
                    ProviderAssetCache.asset_sha256 == sha256,
                )
            ).first()
            current_time = task_service.db_time()
            if cached and (cached.expires_at is None or cached.expires_at > current_time):
                prepared[asset_id] = AssetReference(asset_id=asset_id, url=cached.reference_value)
                continue
            result = await upload(path, client_request_id=f"{task.idempotency_key}:asset:{asset_id}")
            if cached is None:
                cache = ProviderAssetCache(
                    provider_id=task.provider_id,
                    asset_id=asset_id,
                    asset_sha256=sha256,
                    reference_kind=result.output_type or "url",
                    reference_value=result.url,
                )
            else:
                cache = cached
            cache.reference_kind = result.output_type or "url"
            cache.reference_value = result.url
            cache.expires_at = (
                current_time + timedelta(seconds=getattr(provider, "config").upload_expiry_seconds)
                if getattr(getattr(provider, "config", None), "upload_expiry_seconds", None)
                else None
            )
            cache.updated_at = current_time
            session.add(cache)
            session.commit()
            prepared[asset_id] = AssetReference(asset_id=asset_id, url=result.url)
        return prepared
    def _record_provider_error(self, task_id: int, exc: ProviderError, *, now: datetime | None = None) -> None:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if task.status == ReliableTaskStatus.CANCELLING:
                self._record_cancel_provider_error(task_id, exc, now=now)
                return
        self._record_task_error(
            task_id,
            exc.to_task_error_code(),
            self._safe_message(exc.message),
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
                    error_message=self._safe_message(exc.message),
                    error_details=exc.as_details(),
                    now=now,
                )
            else:
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=exc.to_task_error_code(),
                    error_message=self._safe_message(exc.message),
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

    def _record_unexpected_error(self, task_id: int, exc: Exception, *, now: datetime | None = None) -> None:
        safe_message = self._safe_message(str(exc)) or exc.__class__.__name__
        with self.session_factory() as session:
            task_service.mark_task_failed(
                session,
                task_id,
                error_code=TaskErrorCode.UNKNOWN_ERROR,
                error_message=str(safe_message),
                error_details={"exception_type": exc.__class__.__name__},
                now=now,
            )

    def _safe_message(self, message: str) -> str:
        redacted = redact_sensitive({"message": message}).get("message")
        if isinstance(redacted, str) and redacted != message:
            return redacted
        return " ".join(str(redact_sensitive(token)) for token in message.split())

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
                task = task_service.get_task(session, task_id)
                provider_management.record_actual_from_provider(session, task, self._usage_metadata(result))
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
                task = task_service.get_task(session, task_id)
                provider_management.record_actual_from_provider(session, task, self._usage_metadata(result))
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
                task = task_service.get_task(session, task_id)
                provider_management.record_actual_from_provider(session, task, self._usage_metadata(result))
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

    def _usage_metadata(self, result: ProviderJobResult) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for item in result.result_urls:
            metadata.update(item.metadata)
        return metadata

    def _lease_owned(self, task_id: int, *, now: datetime | None = None) -> bool:
        with self.session_factory() as session:
            return task_service.task_lease_is_owned(
                session,
                task_id,
                worker_id=self.settings.worker_id,
                now=now,
            )


def _validate_toapis_video_anchors(paths: list[Path], *, max_pixels: int) -> None:
    """Validate ordered first/last anchors before any remote upload can occur."""
    dimensions: list[tuple[int, int]] = []
    for path in paths:
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                image.load()
                width, height = image.size
                orientation = image.getexif().get(274, 1)
                if orientation not in (None, 1):
                    raise ProviderUnsupportedCapabilityError("ANCHOR_EXIF_ORIENTATION_UNSUPPORTED")
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ProviderUnsupportedCapabilityError("ANCHOR_DIMENSIONS_UNSUPPORTED")
                dimensions.append((width, height))
        except ProviderUnsupportedCapabilityError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ProviderUnsupportedCapabilityError("ANCHOR_IMAGE_INVALID") from exc
    if len(dimensions) == 2:
        first_width, first_height = dimensions[0]
        last_width, last_height = dimensions[1]
        if first_width * last_height != last_width * first_height:
            raise ProviderUnsupportedCapabilityError("ANCHOR_ASPECT_RATIO_MISMATCH")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
