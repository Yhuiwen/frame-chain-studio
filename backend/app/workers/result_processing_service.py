import os
import secrets
import socket
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

import httpx
from sqlmodel import Session

from app.core.config import get_settings
from app.domain.retry_policy import RetryPolicyConfig, decide_error
from app.media.result_downloader import DownloadConfig, DownloadError, Resolver, ResultDownloader, UrlSafetyConfig
from app.media.validation import MediaValidationError, validate_media
from app.models.entities import (
    AssetType,
    GenerationTaskResultStatus,
    GenerationTaskType,
    ReliableTaskStatus,
    ShotStatus,
    TaskErrorCode,
)
from app.services import task_service

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class ResultWorkerSettings:
    worker_id: str
    lease_seconds: int = 300
    batch_size: int = 10
    poll_interval_seconds: float = 1
    max_attempts: int = 3
    retry_base_seconds: float = 2
    retry_max_seconds: float = 300
    retry_jitter_ratio: float = 0.2
    max_image_bytes: int = 50 * 1024 * 1024
    max_video_bytes: int = 2 * 1024 * 1024 * 1024
    max_image_pixels: int = 80_000_000
    download_chunk_bytes: int = 1024 * 1024
    connect_timeout_seconds: float = 10
    read_timeout_seconds: float = 60
    total_timeout_seconds: float = 900
    max_redirects: int = 3
    ffprobe_timeout_seconds: int = 30


def load_result_worker_settings() -> ResultWorkerSettings:
    settings = get_settings()
    return ResultWorkerSettings(
        worker_id=os.getenv(
            "FCS_RESULT_WORKER_ID",
            f"result-{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(4)}",
        ),
        lease_seconds=settings.result_worker_lease_seconds,
        batch_size=int(os.getenv("FCS_RESULT_WORKER_BATCH_SIZE", "10")),
        max_attempts=settings.result_max_attempts,
        retry_base_seconds=settings.result_retry_base_seconds,
        retry_max_seconds=settings.result_retry_max_seconds,
        retry_jitter_ratio=settings.result_retry_jitter_ratio,
        max_image_bytes=settings.result_max_image_bytes,
        max_video_bytes=settings.result_max_video_bytes,
        max_image_pixels=settings.result_max_image_pixels,
        download_chunk_bytes=settings.result_download_chunk_bytes,
        connect_timeout_seconds=settings.result_connect_timeout_seconds,
        read_timeout_seconds=settings.result_read_timeout_seconds,
        total_timeout_seconds=settings.result_total_timeout_seconds,
        max_redirects=settings.result_max_redirects,
        ffprobe_timeout_seconds=settings.ffprobe_timeout_seconds,
    )


class ResultProcessingService:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: ResultWorkerSettings,
        downloader_transport: httpx.AsyncBaseTransport | None = None,
        downloader_resolver: Resolver | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.downloader_transport = downloader_transport
        self.downloader_resolver = downloader_resolver

    async def process_task_once(self, task_id: int) -> bool:
        with self.session_factory() as session:
            task = task_service.get_task(session, task_id)
            if not task_service.task_is_latest_attempt(session, task_id):
                task_service.record_task_error(
                    session,
                    task_id,
                    error_code="STALE_RESULT",
                    error_message="Task result is stale and will not be downloaded.",
                )
                task_service.transition_task(
                    session,
                    task_id,
                    ReliableTaskStatus.FAILED,
                    reason_code="stale_result",
                )
                return True
            if task.status == ReliableTaskStatus.RESULT_READY:
                task_service.mark_task_processing_result(
                    session,
                    task_id,
                    max_result_attempts=self.settings.max_attempts,
                )
            task_service.initialize_task_results(session, task_id, max_attempts=self.settings.max_attempts)
            primary = task_service.get_primary_task_result(session, task_id)
            for result in task_service.initialize_task_results(session, task_id, max_attempts=self.settings.max_attempts):
                if not result.is_primary and result.status == GenerationTaskResultStatus.PENDING:
                    result.status = GenerationTaskResultStatus.SKIPPED
                    session.add(result)
            session.commit()
            if primary.status == GenerationTaskResultStatus.COMPLETED:
                return True
            if primary.status == GenerationTaskResultStatus.RETRY_WAIT:
                task_service.transition_result(session, primary.id or 0, GenerationTaskResultStatus.DOWNLOADING)
            elif primary.status == GenerationTaskResultStatus.PENDING:
                task_service.transition_result(session, primary.id or 0, GenerationTaskResultStatus.DOWNLOADING)
            source_url = primary.source_url
            expected_kind = primary.expected_media_kind
            task_type = task.task_type
        if not self._lease_owned(task_id):
            return False

        max_bytes = self.settings.max_image_bytes if expected_kind.value == "image" else self.settings.max_video_bytes
        app_settings = get_settings()
        downloader = ResultDownloader(
            DownloadConfig(
                storage_dir=app_settings.storage_dir,
                max_bytes=max_bytes,
                chunk_bytes=self.settings.download_chunk_bytes,
                connect_timeout_seconds=self.settings.connect_timeout_seconds,
                read_timeout_seconds=self.settings.read_timeout_seconds,
                total_timeout_seconds=self.settings.total_timeout_seconds,
                max_redirects=self.settings.max_redirects,
                url_safety=UrlSafetyConfig(
                    env=app_settings.env,
                    allowed_private_hosts=app_settings.allowed_private_result_hosts(),
                ),
            ),
            resolver=self.downloader_resolver,
            transport=self.downloader_transport,
        )
        try:
            downloaded = await downloader.download(source_url, result_id=primary.id or 0)
        except DownloadError as exc:
            self._record_result_error(
                task_id,
                primary.id or 0,
                error_code=_download_task_code(exc.code, retryable=exc.retryable),
                message=str(exc),
                retryable=exc.retryable,
                details={"download_error_code": exc.code, **exc.details},
            )
            return True
        if not self._lease_owned(task_id):
            downloaded.absolute_path.unlink(missing_ok=True)
            return False
        with self.session_factory() as session:
            task_service.record_result_downloaded(
                session,
                primary.id or 0,
                temporary_relative_path=downloaded.relative_path,
                file_size=downloaded.file_size,
                sha256=downloaded.sha256,
                mime_type=downloaded.mime_type,
                file_name=downloaded.file_name,
            )
        try:
            metadata = validate_media(
                downloaded.absolute_path,
                expected_kind=expected_kind,
                max_image_pixels=self.settings.max_image_pixels,
                ffprobe_timeout_seconds=self.settings.ffprobe_timeout_seconds,
            )
        except MediaValidationError as exc:
            downloaded.absolute_path.unlink(missing_ok=True)
            self._record_result_error(
                task_id,
                primary.id or 0,
                error_code=TaskErrorCode.MEDIA_VALIDATION_ERROR,
                message=str(exc),
                retryable=False,
                details={"validation_error_code": exc.code},
            )
            return True
        if metadata.media_kind != expected_kind:
            downloaded.absolute_path.unlink(missing_ok=True)
            self._record_result_error(
                task_id,
                primary.id or 0,
                error_code=TaskErrorCode.MEDIA_VALIDATION_ERROR,
                message="Result media kind does not match the task type.",
                retryable=False,
            )
            return True
        with self.session_factory() as session:
            task_service.record_result_validated(
                session,
                primary.id or 0,
                media_kind=metadata.media_kind,
                mime_type=metadata.mime_type,
                width=metadata.width,
                height=metadata.height,
                duration_seconds=metadata.duration_seconds,
                fps=metadata.fps,
                frame_count=metadata.frame_count,
                video_codec=metadata.video_codec,
                audio_codec=metadata.audio_codec,
            )
        if not self._lease_owned(task_id):
            downloaded.absolute_path.unlink(missing_ok=True)
            return False
        final_relative_path = self._final_relative_path(
            task_id=task_id,
            result_id=primary.id or 0,
            sha256=downloaded.sha256,
            media_kind=metadata.media_kind.value,
        )
        final_absolute_path = app_settings.storage_dir / final_relative_path
        final_absolute_path.parent.mkdir(parents=True, exist_ok=True)
        if final_absolute_path.exists():
            downloaded.absolute_path.unlink(missing_ok=True)
        else:
            os.replace(downloaded.absolute_path, final_absolute_path)
        with self.session_factory() as session:
            task_service.record_result_final_path(
                session,
                primary.id or 0,
                final_relative_path=final_relative_path.as_posix(),
            )
            asset_type, next_status, reason = _workflow_for_task_type(task_type)
            task_service.register_result_asset(
                session,
                task_id,
                primary.id or 0,
                final_path=str(app_settings.storage_dir / final_relative_path),
                asset_type=asset_type,
                shot_next_status=next_status,
                workflow_reason=reason,
            )
        return True

    def _record_result_error(
        self,
        task_id: int,
        result_id: int,
        *,
        error_code: TaskErrorCode,
        message: str,
        retryable: bool,
        details: dict[str, object] | None = None,
    ) -> None:
        decision = decide_error(
            error_code,
            retry_count=0,
            config=RetryPolicyConfig(
                base_seconds=self.settings.retry_base_seconds,
                max_seconds=self.settings.retry_max_seconds,
                jitter_ratio=self.settings.retry_jitter_ratio,
            ),
        )
        with self.session_factory() as session:
            if retryable and decision.retryable:
                task_service.schedule_result_retry(
                    session,
                    task_id,
                    result_id,
                    delay_seconds=decision.retry_after_seconds or self.settings.retry_base_seconds,
                    error_code=error_code,
                    error_message=message,
                    error_details=details,
                )
            else:
                result = session.get(task_service.GenerationTaskResult, result_id)
                if result is not None:
                    result.status = GenerationTaskResultStatus.FAILED
                    result.error_code = error_code.value
                    result.error_message = message
                    result.error_details_json = task_service.dumps_sanitized(details or {})
                    session.add(result)
                    session.commit()
                task_service.mark_task_failed(
                    session,
                    task_id,
                    error_code=error_code,
                    error_message=message,
                    error_details=details,
                )

    def _lease_owned(self, task_id: int) -> bool:
        with self.session_factory() as session:
            return task_service.task_lease_is_owned(
                session,
                task_id,
                worker_id=self.settings.worker_id,
            )

    def _final_relative_path(self, *, task_id: int, result_id: int, sha256: str, media_kind: str) -> Path:
        extension = ".png" if media_kind == "image" else ".mp4"
        return Path("results") / f"task-{task_id}" / f"result-{result_id}-{sha256[:16]}{extension}"


def _workflow_for_task_type(task_type: GenerationTaskType) -> tuple[AssetType, ShotStatus, str]:
    if task_type == GenerationTaskType.KEYFRAME_GENERATION:
        return AssetType.KEYFRAME, ShotStatus.KEYFRAME_REVIEW, "keyframe_generation_succeeded"
    if task_type == GenerationTaskType.VIDEO_GENERATION:
        return AssetType.VIDEO, ShotStatus.VIDEO_REVIEW, "video_generation_succeeded"
    raise ValueError(f"Unsupported result task type {task_type.value}.")


def _download_task_code(code: str, *, retryable: bool) -> TaskErrorCode:
    if code == "DOWNLOAD_TIMEOUT":
        return TaskErrorCode.REQUEST_TIMEOUT
    if code == "DOWNLOAD_NETWORK_ERROR":
        return TaskErrorCode.NETWORK_ERROR
    if code == "DOWNLOAD_HTTP_ERROR" and retryable:
        return TaskErrorCode.NETWORK_ERROR
    return TaskErrorCode.DOWNLOAD_ERROR
