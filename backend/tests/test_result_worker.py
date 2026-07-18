from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import fake_provider.app as fake_provider_app
from app.core.config import get_settings
from app.models.entities import (
    Asset,
    AssetType,
    GenerationKind,
    GenerationTask,
    GenerationTaskResult,
    GenerationTaskType,
    ReliableTaskStatus,
    Shot,
    ShotStatus,
)
from app.models.schemas import ProjectCreate, ShotCreate
from app.services import studio, task_service
from app.workers.result_processing_service import ResultProcessingService, ResultWorkerSettings
from app.workers.result_worker import ResultWorker


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@contextmanager
def file_session_factory(tmp_path: Path) -> Generator[tuple[Callable[[], AbstractContextManager[Session]], object], None, None]:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.fixture_dir = Path("tests/fixtures")
    settings.env = "test"
    settings.result_allowed_private_hosts = "testserver"
    fake_provider_app.test_reset()
    engine = create_engine(f"sqlite:///{tmp_path / 'result-worker.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def factory() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    yield factory, engine


def resolver(host: str, _port: int | None) -> list[str]:
    return ["127.0.0.1"] if host == "testserver" else ["93.184.216.34"]


def add_fake_job(job_id: str, *, kind: str, scenario: str = "success") -> str:
    fake_provider_app.JOBS[job_id] = {
        "id": job_id,
        "kind": kind,
        "scenario": scenario,
        "status": "succeeded",
        "polls": 99,
        "running_polls": 1,
        "format": "A",
        "idempotency_key": None,
    }
    suffix = "png" if kind == "image" else "mp4"
    return f"http://testserver/fake/v1/results/{job_id}.{suffix}?token=secret"


def create_result_ready_task(
    session: Session,
    *,
    kind: GenerationKind = GenerationKind.KEYFRAME,
    url: str,
) -> GenerationTask:
    project = studio.create_project(session, ProjectCreate(name="Result Worker"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 1"))
    if kind == GenerationKind.KEYFRAME:
        studio.transition_shot(session, shot, ShotStatus.KEYFRAME_GENERATING, "test_keyframe")
        task_type = GenerationTaskType.KEYFRAME_GENERATION
    else:
        shot.status = ShotStatus.KEYFRAME_APPROVED
        session.add(shot)
        session.commit()
        studio.transition_shot(session, shot, ShotStatus.VIDEO_GENERATING, "test_video")
        task_type = GenerationTaskType.VIDEO_GENERATION
    request = task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot.id or 0,
        kind=kind,
        provider_name="fake-http",
    )
    task = task_service.create_task_attempt(
        session,
        generation_request=request,
        provider_id="fake-http",
        task_type=task_type,
    )
    task_service.mark_task_remote_submitted(
        session,
        task.id or 0,
        remote_job_id="remote-1",
        remote_status="running",
        response_summary="{}",
        poll_delay_seconds=0,
    )
    return task_service.mark_task_result_ready(
        session,
        task.id or 0,
        remote_status="succeeded",
        result_urls=[{"url": url}],
        response_summary="{}",
    )


def make_worker(factory: Callable[[], AbstractContextManager[Session]]) -> ResultWorker:
    service = ResultProcessingService(
        session_factory=factory,
        settings=ResultWorkerSettings(worker_id="result-worker", retry_jitter_ratio=0, retry_base_seconds=1),
        downloader_transport=httpx.ASGITransport(app=fake_provider_app.app),
        downloader_resolver=resolver,
    )
    return ResultWorker(
        session_factory=factory,
        settings=ResultWorkerSettings(worker_id="result-worker", retry_jitter_ratio=0, retry_base_seconds=1),
        processing_service=service,
    )


@pytest.mark.anyio
async def test_result_worker_downloads_keyframe_registers_asset_and_advances_shot(tmp_path: Path) -> None:
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_result_ready_task(session, url=add_fake_job("image-ok", kind="image"))
        worker = make_worker(factory)

        assert await worker.run_until_idle() == 1

        with factory() as session:
            completed = task_service.get_task(session, task.id or 0)
            shot = session.get(Shot, completed.shot_id)
            asset = session.get(Asset, completed.result_asset_id)
            result = session.exec(select(GenerationTaskResult).where(GenerationTaskResult.generation_task_id == task.id)).one()
            assert completed.status == ReliableTaskStatus.SUCCEEDED
            assert shot and shot.status == ShotStatus.KEYFRAME_REVIEW
            assert asset and asset.type == AssetType.KEYFRAME
            assert asset.sha256
            assert asset.width and asset.height
            assert result.asset_id == asset.id
            payload = studio.task_payload(session, completed)
            assert payload["result_hosts"] == ["testserver"]


@pytest.mark.anyio
async def test_result_worker_downloads_video_without_extracting_tail_frame(tmp_path: Path) -> None:
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_result_ready_task(
                session,
                kind=GenerationKind.VIDEO,
                url=add_fake_job("video-ok", kind="video"),
            )
        worker = make_worker(factory)

        assert await worker.run_until_idle() == 1

        with factory() as session:
            completed = task_service.get_task(session, task.id or 0)
            shot = session.get(Shot, completed.shot_id)
            asset = session.get(Asset, completed.result_asset_id)
            assert completed.status == ReliableTaskStatus.SUCCEEDED
            assert shot and shot.status == ShotStatus.VIDEO_REVIEW
            assert asset and asset.type == AssetType.VIDEO
            assert asset.duration_seconds and asset.duration_seconds > 0
            assert not session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).all()


@pytest.mark.anyio
async def test_result_worker_is_idempotent_after_success(tmp_path: Path) -> None:
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_result_ready_task(session, url=add_fake_job("image-idempotent", kind="image"))
        worker = make_worker(factory)

        await worker.run_until_idle()
        await worker.run_until_idle()

        with factory() as session:
            assert len(session.exec(select(Asset)).all()) == 1
            assert len(list((get_settings().storage_dir / "results").rglob("*.*"))) == 1
            assert task_service.get_task(session, task.id or 0).status == ReliableTaskStatus.SUCCEEDED


@pytest.mark.anyio
async def test_stale_result_is_not_downloaded_or_registered(tmp_path: Path) -> None:
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_result_ready_task(session, url=add_fake_job("stale-image", kind="image"))
            task_id = task.id or 0
            request = session.get(task_service.GenerationRequest, task.generation_request_id)
            assert request is not None
            task.status = ReliableTaskStatus.FAILED
            session.add(task)
            session.commit()
            task_service.create_task_attempt(
                session,
                generation_request=request,
                provider_id="fake-http",
                task_type=GenerationTaskType.KEYFRAME_GENERATION,
                retry_of_task_id=task.id,
                idempotency_key="newer-task",
            )
            task.status = ReliableTaskStatus.RESULT_READY
            task.error_code = None
            session.add(task)
            session.commit()
        worker = make_worker(factory)

        await worker.run_until_idle()

        with factory() as session:
            stale = task_service.get_task(session, task_id)
            assert stale.status == ReliableTaskStatus.FAILED
            assert stale.error_code == "STALE_RESULT"
            assert not session.exec(select(Asset)).all()
        assert fake_provider_app.DOWNLOAD_CALLS == 0


@pytest.mark.anyio
async def test_result_worker_retries_transient_download_error_without_polluting_provider_retry(tmp_path: Path) -> None:
    with file_session_factory(tmp_path) as (factory, _engine):
        with factory() as session:
            task = create_result_ready_task(
                session,
                url=add_fake_job("image-500", kind="image", scenario="result_500_once"),
            )
        worker = make_worker(factory)

        await worker.run_once()
        with factory() as session:
            waiting = task_service.get_task(session, task.id or 0)
            assert waiting.status == ReliableTaskStatus.PROCESSING_RESULT
            assert waiting.result_retry_count == 1
            assert waiting.retry_count == 0
            waiting.next_result_retry_at = None
            session.add(waiting)
            result = session.exec(select(GenerationTaskResult).where(GenerationTaskResult.generation_task_id == task.id)).one()
            assert result.status.value == "RETRY_WAIT"
            result.next_retry_at = None
            session.add(result)
            session.commit()

        await worker.run_until_idle()
        with factory() as session:
            assert task_service.get_task(session, task.id or 0).status == ReliableTaskStatus.SUCCEEDED
