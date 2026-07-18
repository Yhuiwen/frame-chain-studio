from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.main import app
from app.media.ffmpeg import create_test_video
from app.media.validation import validate_video
from app.models.entities import Asset, AssetType, Project, ProjectRender, ProjectRenderStatus, Shot, ShotStatus, WorkerHeartbeat
from app.workers.render_service import RenderProcessingService, create_project_render
from app.workers.render_worker import RenderWorker


def test_render_requires_completed_shots(session: Session) -> None:
    project = Project(name="Render")
    session.add(project)
    session.commit()
    session.refresh(project)
    session.add(Shot(project_id=project.id or 0, title="Missing"))
    session.commit()

    with pytest.raises(AppError) as exc_info:
        create_project_render(session, project_id=project.id or 0, idempotency_key="r1")

    assert exc_info.value.code == "RENDER_INPUT_INCOMPLETE"


def test_render_idempotency_returns_same_row(session: Session, tmp_path: Path) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    project, _shot, _asset = completed_project_with_video(session, tmp_path)

    first = create_project_render(session, project_id=project.id or 0, idempotency_key="same")
    second = create_project_render(session, project_id=project.id or 0, idempotency_key="same")

    assert first.id == second.id
    assert first.input_manifest_json == second.input_manifest_json


@pytest.mark.anyio
async def test_render_worker_outputs_probeable_asset(tmp_path: Path) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project, _shot, _asset = completed_project_with_video(session, tmp_path)
        render = create_project_render(session, project_id=project.id or 0, idempotency_key="worker")

    def session_factory() -> Session:
        return Session(engine)

    worker = RenderWorker(
        session_factory=session_factory,
        worker_id="render-test",
        lease_seconds=30,
        processing_service=RenderProcessingService(session_factory=session_factory),
    )
    processed = await worker.run_until_idle()

    with Session(engine) as session:
        saved = session.get(ProjectRender, render.id)
        assert processed == 1
        assert saved is not None
        assert saved.status == ProjectRenderStatus.SUCCEEDED
        assert saved.output_asset_id is not None
        asset = session.get(Asset, saved.output_asset_id)
        assert asset is not None
        metadata = validate_video(Path(asset.path), timeout_seconds=10)
        assert metadata.width == settings.render_width
        assert metadata.height == settings.render_height
        assert len(session.exec(select(WorkerHeartbeat)).all()) == 1


def test_media_range_response(session: Session, tmp_path: Path) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    project, _shot, asset = completed_project_with_video(session, tmp_path)

    def override_session():
        yield session

    app.dependency_overrides.clear()
    from app.db import get_session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/media/{asset.id}", headers={"Range": "bytes=0-15"})
            assert response.status_code == 206
            assert response.headers["content-range"].startswith("bytes 0-15/")
            assert len(response.content) == 16
            invalid = client.get(f"/api/media/{asset.id}", headers={"Range": "bytes=999999-1000000"})
            assert invalid.status_code == 416
    finally:
        app.dependency_overrides.clear()


def completed_project_with_video(session: Session, tmp_path: Path) -> tuple[Project, Shot, Asset]:
    storage_dir = get_settings().storage_dir
    storage_dir.mkdir(parents=True, exist_ok=True)
    video_path = storage_dir / f"input-{len(list(storage_dir.glob('input-*.mp4')))}.mp4"
    create_test_video(video_path, duration_seconds=0.5)
    project = Project(name="Render")
    session.add(project)
    session.commit()
    session.refresh(project)
    shot = Shot(project_id=project.id or 0, title="Done", status=ShotStatus.COMPLETED)
    session.add(shot)
    session.commit()
    session.refresh(shot)
    asset = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.VIDEO,
        path=str(video_path),
        mime_type="video/mp4",
        duration_seconds=0.5,
        width=1280,
        height=720,
        fps=24,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return project, shot, asset
