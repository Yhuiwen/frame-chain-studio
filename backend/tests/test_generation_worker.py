from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.entities import Asset, GenerationKind, GenerationTask, Project, ReliableTaskStatus, Shot, TaskErrorCode
from app.providers.http import MappedAsyncHttpProvider
from app.providers.models import (
    MappedHttpProviderConfig,
    ProviderCapabilities,
    ProviderMappingConfig,
    RequestFieldMapping,
    ResponseMappingConfig,
)
from app.providers.registry import ProviderRegistry
from app.services import task_service
from app.workers.generation_worker import GenerationWorker
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
