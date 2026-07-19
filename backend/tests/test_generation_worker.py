import asyncio
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.models.entities import (
    Asset,
    AssetType,
    GenerationKind,
    GenerationTask,
    Project,
    ProviderAssetCache,
    ReliableTaskStatus,
    Shot,
    TaskErrorCode,
    WorkerHeartbeat,
)
from app.providers.async_base import AsyncGenerationProvider
from app.providers.http import MappedAsyncHttpProvider
from app.providers.models import (
    MappedHttpProviderConfig,
    ImageGenerationRequest,
    ProviderCapabilities,
    ProviderCancelResult,
    ProviderJobResult,
    ProviderResultUrl,
    ProviderSubmitResult,
    ProviderMappingConfig,
    RemoteJobStatus,
    RequestFieldMapping,
    ResponseMappingConfig,
    VideoGenerationRequest,
)
from app.providers.registry import ProviderRegistry
from app.services import task_service
from app.workers.generation_worker import GenerationWorker
from app.workers.execution_service import ProviderExecutionService
from app.workers.settings import WorkerSettings
from fake_provider.app import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def worker_config() -> MappedHttpProviderConfig:
    response = ResponseMappingConfig(
        remote_job_id_path="data.task_id",
        status_path="data.status",
        result_urls_path="data.output.image_url",
    )
    return MappedHttpProviderConfig(
        provider_id="fake-http",
        display_name="Fake HTTP",
        base_url="http://testserver",
        capabilities=ProviderCapabilities(
            provider_id="fake-http",
            display_name="Fake HTTP",
            text_to_image=True,
            image_to_video=True,
            first_last_frame_video=True,
            supports_cancel=True,
            supports_seed=True,
            max_reference_images=2,
        ),
        mapping=ProviderMappingConfig(
            submit_response=response,
            job_response=response,
            image_request=RequestFieldMapping(fields={"prompt": "input.text", "client_request_id": "client_request_id"}),
            video_request=RequestFieldMapping(fields={"prompt": "input.text", "client_request_id": "client_request_id"}),
        ),
    )


async def make_registry(scenario: str = "success", running_polls: str = "1") -> ProviderRegistry:
    transport = httpx.ASGITransport(app=app)
    provider = MappedAsyncHttpProvider(
        worker_config(),
        transport=transport,
        extra_headers={
            "X-Fake-Scenario": scenario,
            "X-Fake-Running-Polls": running_polls,
        },
    )
    registry = ProviderRegistry()
    registry.register(provider)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/fake/v1/test/reset")
    return registry


async def fake_stats() -> dict[str, object]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        return (await client.get("/fake/v1/test/stats")).json()


@contextmanager
def file_session_factory(tmp_path: Path) -> Generator[tuple[Callable[[], AbstractContextManager[Session]], object], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def factory() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    yield factory, engine


def create_task(session: Session, *, status: ReliableTaskStatus = ReliableTaskStatus.QUEUED) -> GenerationTask:
    project = Project(name="Worker", description="")
    session.add(project)
    session.commit()
    session.refresh(project)
    shot = Shot(project_id=project.id or 0, title="Shot 1")
    session.add(shot)
    session.commit()
    session.refresh(shot)
    request = task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot.id or 0,
        kind=GenerationKind.KEYFRAME,
        provider_name="fake-http",
        prompt_snapshot="prompt",
    )
    task = task_service.create_task_attempt(session, generation_request=request, provider_id="fake-http")
    if status == ReliableTaskStatus.SUBMITTING:
        task_service.transition_task(session, task.id or 0, ReliableTaskStatus.SUBMITTING)
    elif status == ReliableTaskStatus.RUNNING:
        task_service.mark_task_remote_submitted(
            session,
            task.id or 0,
            remote_job_id="fake-existing",
            remote_status="running",
            response_summary="{}",
            poll_delay_seconds=0,
        )
    return task_service.get_task(session, task.id or 0)


class UploadProvider(AsyncGenerationProvider):
    def __init__(self) -> None:
        self.upload_calls = 0
        self.video_requests: list[VideoGenerationRequest] = []

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="upload-provider",
            display_name="Upload Provider",
            image_to_video=True,
            max_reference_images=1,
        )

    async def upload_asset(self, path: Path, *, client_request_id: str) -> ProviderResultUrl:
        assert path.exists()
        self.upload_calls += 1
        return ProviderResultUrl(url=f"https://assets.example.test/{client_request_id}")

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        raise AssertionError("image submit should not be called")

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        self.video_requests.append(request)
        return ProviderSubmitResult(
            remote_job_id=f"job-{self.upload_calls}",
            remote_status=RemoteJobStatus.RUNNING,
        )

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        raise AssertionError("poll should not be called")

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        raise AssertionError("cancel should not be called")


class SlowSubmitProvider(AsyncGenerationProvider):
    def __init__(self, *, delay_seconds: float = 5, provider_id: str = "slow-provider") -> None:
        self.delay_seconds = delay_seconds
        self.provider_id = provider_id
        self.submit_calls = 0

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_id=self.provider_id, display_name="Slow Provider", text_to_image=True)

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        self.submit_calls += 1
        await asyncio.sleep(self.delay_seconds)
        return ProviderSubmitResult(remote_job_id="late-job", remote_status=RemoteJobStatus.RUNNING)

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        raise AssertionError("video submit should not be called")

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        raise AssertionError("poll should not be called")

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        raise AssertionError("cancel should not be called")


class SlowPollProvider(AsyncGenerationProvider):
    def __init__(self, *, delay_seconds: float = 2.2) -> None:
        self.delay_seconds = delay_seconds
        self.submit_calls = 0
        self.poll_calls = 0

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_id="slow-poll-provider", display_name="Slow Poll Provider", text_to_image=True)

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        self.submit_calls += 1
        return ProviderSubmitResult(remote_job_id="existing-job", remote_status=RemoteJobStatus.RUNNING)

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        raise AssertionError("video submit should not be called")

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        self.poll_calls += 1
        await asyncio.sleep(self.delay_seconds)
        return ProviderJobResult(
            remote_job_id=remote_job_id,
            remote_status="succeeded",
            normalized_status=RemoteJobStatus.SUCCEEDED,
            result_urls=[ProviderResultUrl(url="https://cdn.example.test/result.png?token=secret")],
        )

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        raise AssertionError("cancel should not be called")


@pytest.mark.anyio
async def test_worker_submits_queued_task_and_polls_to_result_ready(tmp_path: Path) -> None:
    registry = await make_registry()
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
            shot = session.get(Shot, task.shot_id)
            assert shot is not None
            shot_status = shot.status
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
        )

        assert await worker.run_once() == 1
        with factory() as session:
            submitted = task_service.get_task(session, task.id or 0)
            assert submitted.status == ReliableTaskStatus.RUNNING
            assert submitted.remote_job_id is not None
            assert submitted.next_poll_at is not None
            assert submitted.locked_by is None
            assert session.exec(select(Asset)).all() == []
            shot = session.get(Shot, task.shot_id)
            assert shot is not None
            assert shot.status == shot_status

        await worker.run_until_idle()
        with factory() as session:
            ready = task_service.get_task(session, task.id or 0)
            assert ready.status == ReliableTaskStatus.RESULT_READY
            assert task_service.loads_json_list(ready.result_urls_json)
            assert session.exec(select(Asset)).all() == []


@pytest.mark.anyio
async def test_execution_service_uploads_remote_input_assets_and_reuses_cache(tmp_path: Path) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    provider = UploadProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            project = Project(name="Upload", description="")
            session.add(project)
            session.commit()
            session.refresh(project)
            shot = Shot(project_id=project.id or 0, title="Shot 1")
            session.add(shot)
            session.commit()
            asset_path = settings.storage_dir / "project-1" / "shot-1" / "keyframe.png"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_bytes(b"asset-bytes")
            asset = Asset(
                project_id=project.id or 0,
                shot_id=shot.id,
                type=AssetType.KEYFRAME,
                path=str(asset_path),
                mime_type="image/png",
            )
            session.add(asset)
            session.commit()
            session.refresh(asset)
            request = task_service.create_generation_request(
                session,
                project_id=project.id or 0,
                shot_id=shot.id or 0,
                kind=GenerationKind.VIDEO,
                provider_name="upload-provider",
                input_asset_ids=[asset.id or 0],
                prompt_snapshot="prompt",
            )
            task = task_service.create_task_attempt(
                session,
                generation_request=request,
                provider_id="upload-provider",
                request_payload={"input_asset_ids": [asset.id or 0], "duration_seconds": 2, "prompt": "prompt"},
            )
            task_service.acquire_task_lease(session, task.id or 0, worker_id="worker-a", lease_seconds=30)

        service = ProviderExecutionService(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
        )

        assert await service.process_task_once(task.id or 0)
        with factory() as session:
            submitted = task_service.get_task(session, task.id or 0)
            assert submitted.status == ReliableTaskStatus.RUNNING
            assert session.exec(select(ProviderAssetCache)).one().reference_value.startswith(
                "https://assets.example.test/"
            )
            request_again = await service._build_provider_request(session, submitted, provider)

        assert provider.upload_calls == 1
        assert provider.video_requests
        assert isinstance(request_again, VideoGenerationRequest)
        assert provider.video_requests[0].start_frame is not None
        assert provider.video_requests[0].start_frame.url.startswith("https://assets.example.test/")
        assert request_again.start_frame is not None
        assert request_again.start_frame.url == provider.video_requests[0].start_frame.url


@pytest.mark.anyio
async def test_execution_service_stops_long_submit_when_lease_is_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SlowSubmitProvider()
    registry = ProviderRegistry()
    registry.register(provider)
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            project = Project(name="Slow", description="")
            session.add(project)
            session.commit()
            session.refresh(project)
            shot = Shot(project_id=project.id or 0, title="Shot 1")
            session.add(shot)
            session.commit()
            request = task_service.create_generation_request(
                session,
                project_id=project.id or 0,
                shot_id=shot.id or 0,
                kind=GenerationKind.KEYFRAME,
                provider_name="slow-provider",
                prompt_snapshot="prompt",
            )
            task = task_service.create_task_attempt(
                session,
                generation_request=request,
                provider_id="slow-provider",
                request_payload={"prompt": "prompt"},
            )
            task_service.acquire_task_lease(session, task.id or 0, worker_id="worker-a", lease_seconds=1)

        monkeypatch.setattr(task_service, "renew_task_lease", lambda *_args, **_kwargs: None)
        service = ProviderExecutionService(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", lease_seconds=2, poll_interval_seconds=0),
        )

        assert not await service.process_task_once(task.id or 0)
        with factory() as session:
            current = task_service.get_task(session, task.id or 0)
            assert current.status == ReliableTaskStatus.SUBMITTING
            assert current.remote_job_id is None


@pytest.mark.anyio
async def test_generation_worker_long_submit_renews_lease_and_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SlowSubmitProvider(delay_seconds=2.2, provider_id="slow-submit-provider")
    registry = ProviderRegistry()
    registry.register(provider)
    renew_count = 0
    real_renew = task_service.renew_task_lease

    def counting_renew(
        session: Session,
        task_id: int,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> object:
        nonlocal renew_count
        renew_count += 1
        return real_renew(session, task_id, worker_id=worker_id, lease_seconds=lease_seconds, now=now)

    monkeypatch.setattr(task_service, "renew_task_lease", counting_renew)
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            project = Project(name="Slow Submit", description="")
            session.add(project)
            session.commit()
            shot = Shot(project_id=project.id or 0, title="Shot 1")
            session.add(shot)
            session.commit()
            request = task_service.create_generation_request(
                session,
                project_id=project.id or 0,
                shot_id=shot.id or 0,
                kind=GenerationKind.KEYFRAME,
                provider_name="slow-submit-provider",
                prompt_snapshot="prompt",
            )
            task = task_service.create_task_attempt(
                session,
                generation_request=request,
                provider_id="slow-submit-provider",
                request_payload={"prompt": "prompt"},
            )
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", lease_seconds=2, poll_interval_seconds=0),
        )

        assert await worker.run_once() == 1

        with factory() as session:
            current = task_service.get_task(session, task.id or 0)
            heartbeat = session.exec(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == "worker-a")).one()
            assert current.status == ReliableTaskStatus.RUNNING
            assert current.remote_job_id == "late-job"
            assert current.locked_by is None
            assert heartbeat.current_task_id is None
        assert provider.submit_calls == 1
        assert renew_count >= 2


@pytest.mark.anyio
async def test_generation_worker_long_poll_renews_lease_and_records_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = SlowPollProvider(delay_seconds=2.2)
    registry = ProviderRegistry()
    registry.register(provider)
    renew_count = 0
    real_renew = task_service.renew_task_lease

    def counting_renew(
        session: Session,
        task_id: int,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> object:
        nonlocal renew_count
        renew_count += 1
        return real_renew(session, task_id, worker_id=worker_id, lease_seconds=lease_seconds, now=now)

    monkeypatch.setattr(task_service, "renew_task_lease", counting_renew)
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            project = Project(name="Slow Poll", description="")
            session.add(project)
            session.commit()
            shot = Shot(project_id=project.id or 0, title="Shot 1")
            session.add(shot)
            session.commit()
            request = task_service.create_generation_request(
                session,
                project_id=project.id or 0,
                shot_id=shot.id or 0,
                kind=GenerationKind.KEYFRAME,
                provider_name="slow-poll-provider",
                prompt_snapshot="prompt",
            )
            task = task_service.create_task_attempt(
                session,
                generation_request=request,
                provider_id="slow-poll-provider",
                request_payload={"prompt": "prompt"},
            )
            task_service.mark_task_remote_submitted(
                session,
                task.id or 0,
                remote_job_id="existing-job",
                remote_status="running",
                response_summary="{}",
                poll_delay_seconds=0,
            )
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", lease_seconds=2, poll_interval_seconds=0),
        )

        assert await worker.run_once() == 1

        with factory() as session:
            current = task_service.get_task(session, task.id or 0)
            assert current.status == ReliableTaskStatus.RESULT_READY
            assert current.locked_by is None
            assert task_service.loads_json_list(current.raw_result_urls_json)
            assert "token=secret" not in current.result_urls_json
        assert provider.submit_calls == 0
        assert provider.poll_calls == 1
        assert renew_count >= 2


@pytest.mark.anyio
async def test_submitting_crash_recovery_reuses_same_fake_job(tmp_path: Path) -> None:
    registry = await make_registry()
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session, status=ReliableTaskStatus.SUBMITTING)
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
        )
        await worker.run_once()
        with factory() as session:
            first = task_service.get_task(session, task.id or 0)
            first_remote = first.remote_job_id
            first.status = ReliableTaskStatus.SUBMITTING
            first.remote_job_id = None
            session.add(first)
            session.commit()

        await worker.run_once()
        with factory() as session:
            recovered = task_service.get_task(session, task.id or 0)
            assert recovered.remote_job_id == first_remote
            assert recovered.status == ReliableTaskStatus.RUNNING
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            stats = (await client.get("/fake/v1/test/stats")).json()
        assert stats["submit_calls"] == 2
        assert stats["created_jobs"] == 1


@pytest.mark.anyio
async def test_two_workers_compete_and_only_one_submits(tmp_path: Path) -> None:
    registry = await make_registry(running_polls="3")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
        worker_a = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=60),
        )
        worker_b = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-b", poll_interval_seconds=60),
        )
        results = await __import__("asyncio").gather(worker_a.run_once(), worker_b.run_once())
        assert sum(results) == 1
        with factory() as session:
            assert task_service.get_task(session, task.id or 0).remote_job_id is not None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            stats = (await client.get("/fake/v1/test/stats")).json()
        assert stats["created_jobs"] == 1


@pytest.mark.anyio
async def test_expired_lease_takeover_and_retryable_error(tmp_path: Path) -> None:
    registry = await make_registry("submit_429_once")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
            now = task.created_at
            assert task_service.acquire_task_lease(
                session,
                task.id or 0,
                worker_id="worker-a",
                lease_seconds=1,
                now=now,
            )
        worker_b = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-b", lease_seconds=30, retry_base_seconds=5, retry_jitter_ratio=0),
        )
        assert await worker_b.run_once(now=now + timedelta(seconds=2)) == 1
        with factory() as session:
            retried = task_service.get_task(session, task.id or 0)
            assert retried.status == ReliableTaskStatus.RETRY_WAIT
            assert retried.next_retry_at is not None


@pytest.mark.anyio
async def test_running_without_remote_job_and_unknown_limit_fail(tmp_path: Path) -> None:
    registry = await make_registry("unknown_status")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
            task_service.transition_task(session, task.id or 0, ReliableTaskStatus.SUBMITTING)
            task_service.transition_task(session, task.id or 0, ReliableTaskStatus.RUNNING)
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0, max_unknown_polls=1),
        )
        await worker.run_once()
        with factory() as session:
            assert task_service.get_task(session, task.id or 0).status == ReliableTaskStatus.FAILED


@pytest.mark.anyio
async def test_worker_cancels_running_task_remotely(tmp_path: Path) -> None:
    registry = await make_registry("cancel_success", running_polls="10")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
        )
        await worker.run_once()
        with factory() as session:
            running = task_service.get_task(session, task.id or 0)
            assert running.status == ReliableTaskStatus.RUNNING
            task_service.request_task_cancel(session, running.id or 0, reason="manual stop", cancellation_timeout_seconds=30)

        await worker.run_once()

        with factory() as session:
            cancelled = task_service.get_task(session, task.id or 0)
            assert cancelled.status == ReliableTaskStatus.CANCELLED
            assert cancelled.error_code == TaskErrorCode.CANCELLED.value
            assert cancelled.cancelled_at is not None
        stats = await fake_stats()
        assert stats["cancel_calls"] == 1
        assert stats["cancelled_jobs"] == 1


@pytest.mark.anyio
async def test_worker_retries_transient_cancel_error_without_leaving_cancelling(tmp_path: Path) -> None:
    registry = await make_registry("cancel_500_once", running_polls="10")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(
                worker_id="worker-a",
                poll_interval_seconds=0,
                retry_base_seconds=5,
                retry_jitter_ratio=0,
            ),
        )
        now = task.created_at
        await worker.run_once(now=now)
        with factory() as session:
            task_service.request_task_cancel(
                session,
                task.id or 0,
                reason="manual stop",
                cancellation_timeout_seconds=60,
                now=now,
            )

        await worker.run_once(now=now)
        with factory() as session:
            waiting = task_service.get_task(session, task.id or 0)
            assert waiting.status == ReliableTaskStatus.CANCELLING
            assert waiting.retry_count == 1
            assert waiting.next_poll_at == (now + timedelta(seconds=5)).replace(tzinfo=None)

        await worker.run_once(now=now + timedelta(seconds=5))
        with factory() as session:
            assert task_service.get_task(session, task.id or 0).status == ReliableTaskStatus.CANCELLED
        stats = await fake_stats()
        assert stats["cancel_calls"] == 2


@pytest.mark.anyio
async def test_worker_resubmits_submitting_task_before_cancel_when_remote_id_missing(tmp_path: Path) -> None:
    registry = await make_registry("cancel_success", running_polls="10")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session, status=ReliableTaskStatus.SUBMITTING)
            task_service.request_task_cancel(session, task.id or 0, reason="manual stop", cancellation_timeout_seconds=30)
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0),
        )

        await worker.run_once()

        with factory() as session:
            cancelled = task_service.get_task(session, task.id or 0)
            assert cancelled.status == ReliableTaskStatus.CANCELLED
            assert cancelled.remote_job_id is not None
        stats = await fake_stats()
        assert stats["submit_calls"] == 1
        assert stats["cancel_calls"] == 1


@pytest.mark.anyio
async def test_worker_job_timeout_requests_cancellation(tmp_path: Path) -> None:
    registry = await make_registry("cancel_success", running_polls="10")
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_task(session)
        worker = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="worker-a", poll_interval_seconds=0, job_timeout_seconds=1),
        )
        now = task.created_at
        await worker.run_once(now=now)

        await worker.run_once(now=now + timedelta(seconds=2))

        with factory() as session:
            cancelling = task_service.get_task(session, task.id or 0)
            assert cancelling.status == ReliableTaskStatus.CANCELLING
            assert cancelling.error_code == TaskErrorCode.JOB_TIMEOUT.value
            assert cancelling.cancellation_deadline_at is not None
