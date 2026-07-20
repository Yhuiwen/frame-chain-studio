from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.request_id import register_request_id_middleware
from app.db import engine as app_engine
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    GenerationKind,
    GenerationRequest,
    Project,
    Shot,
    ShotStateChange,
    ShotStatus,
)
from app.models.schemas import ProjectCreate, ReorderShot, ShotCreate
from app.providers.exceptions import ProviderUnsupportedCapabilityError
from app.providers.models import AssetReference, ImageGenerationRequest, ProviderCapabilities, VideoGenerationRequest
from app.services import studio, task_service
from app.workers.request_factory import ProviderRequestFactory


def _resolved(provider_id: str = "mock") -> SimpleNamespace:
    return SimpleNamespace(
        input_asset_ids=[],
        provider_id=provider_id,
        model="model",
        generation_mode=SimpleNamespace(value="TEXT_TO_IMAGE"),
        aspect_ratio="16:9",
        seed=1,
        duration_seconds=None,
        allow_capability_fallback=False,
        provider_info=SimpleNamespace(configured=True),
    )


def _video_review_shot(session: Session, tmp_path: Path, *, with_next: bool = False) -> tuple[Project, Shot, Path]:
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="S"))
    if with_next:
        studio.create_shot(session, project.id or 0, ShotCreate(title="Next"))
    keyframe = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.KEYFRAME,
        status=AssetStatus.APPROVED,
        revision=shot.spec_revision,
        path=str(tmp_path / f"keyframe-{shot.id}.png"),
        mime_type="image/png",
    )
    session.add(keyframe)
    session.flush()
    shot.approved_keyframe_asset_id = keyframe.id
    shot.status = ShotStatus.VIDEO_REVIEW
    session.add(shot)
    video_path = tmp_path / f"video-{shot.id}.mp4"
    video_path.write_bytes(b"fake video")
    session.add(
        Asset(
            project_id=project.id or 0,
            shot_id=shot.id,
            type=AssetType.VIDEO,
            status=AssetStatus.ACTIVE,
            revision=shot.spec_revision,
            path=str(video_path),
            mime_type="video/mp4",
        )
    )
    session.commit()
    return project, shot, video_path


def _write_valid_tail(output_path: Path) -> None:
    output_path.write_bytes(Path("tests/fixtures/mock-keyframe.png").read_bytes())


def test_generation_task_creation_failure_rolls_back_shot_and_request(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="S"))

    def fail_task(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected task failure")

    monkeypatch.setattr(task_service, "create_task_attempt", fail_task)

    with pytest.raises(RuntimeError, match="injected task failure"):
        studio.start_keyframe_generation_atomic(
            session,
            shot=shot,
            resolved=_resolved(),
            request_payload={"provider_id": "mock"},
        )

    session.refresh(shot)
    assert shot.status == ShotStatus.DRAFT
    assert session.exec(select(GenerationRequest).where(GenerationRequest.shot_id == shot.id)).all() == []


def test_project_create_persists_generation_settings(session: Session) -> None:
    project = studio.create_project(
        session,
        ProjectCreate(
            name="P",
            image_provider_id="fake-http",
            video_provider_id="mock",
            image_model="img",
            video_model="vid",
            default_aspect_ratio="9:16",
            default_video_duration_seconds=3,
            default_seed=123,
        ),
    )
    assert project.image_provider_id == "fake-http"
    assert project.video_provider_id == "mock"
    assert project.image_model == "img"
    assert project.video_model == "vid"
    assert project.default_aspect_ratio == "9:16"
    assert project.default_video_duration_seconds == 3
    assert project.default_seed == 123


def test_reorder_rejects_duplicate_ids_and_orders(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    first = studio.create_shot(session, project.id or 0, ShotCreate(title="A"))
    second = studio.create_shot(session, project.id or 0, ShotCreate(title="B"))
    with pytest.raises(Exception, match="duplicate shot IDs"):
        studio.reorder_shots(
            session,
            project.id or 0,
            [ReorderShot(id=first.id or 0, sort_order=0), ReorderShot(id=first.id or 0, sort_order=1)],
        )
    with pytest.raises(Exception, match="duplicate sort orders"):
        studio.reorder_shots(
            session,
            project.id or 0,
            [ReorderShot(id=first.id or 0, sort_order=0), ReorderShot(id=second.id or 0, sort_order=0)],
        )


def test_video_approval_ffmpeg_failure_keeps_video_review(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="S"))
    keyframe = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.KEYFRAME,
        status=AssetStatus.APPROVED,
        revision=shot.spec_revision,
        path=str(tmp_path / "k.png"),
        mime_type="image/png",
    )
    session.add(keyframe)
    session.flush()
    shot.approved_keyframe_asset_id = keyframe.id
    shot.status = ShotStatus.VIDEO_REVIEW
    session.add(shot)
    video_path = tmp_path / "v.mp4"
    video_path.write_bytes(b"not a real video")
    session.add(
        Asset(
            project_id=project.id or 0,
            shot_id=shot.id,
            type=AssetType.VIDEO,
            status=AssetStatus.ACTIVE,
            revision=shot.spec_revision,
            path=str(video_path),
            mime_type="video/mp4",
        )
    )
    session.commit()

    def fail_extract(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(studio, "extract_tail_frame", fail_extract)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        studio.approve_video(session, shot.id or 0)
    session.refresh(shot)
    assert shot.status == ShotStatus.VIDEO_REVIEW
    assert session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).first() is None


def test_video_approval_db_failure_removes_moved_tail_file(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="S"))
    keyframe = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.KEYFRAME,
        status=AssetStatus.APPROVED,
        revision=shot.spec_revision,
        path=str(tmp_path / "k.png"),
        mime_type="image/png",
    )
    session.add(keyframe)
    session.flush()
    shot.approved_keyframe_asset_id = keyframe.id
    shot.status = ShotStatus.VIDEO_REVIEW
    session.add(shot)
    video_path = tmp_path / "v.mp4"
    video_path.write_bytes(b"fake video")
    video = Asset(
        project_id=project.id or 0,
        shot_id=shot.id,
        type=AssetType.VIDEO,
        status=AssetStatus.ACTIVE,
        revision=shot.spec_revision,
        path=str(video_path),
        mime_type="video/mp4",
    )
    session.add(video)
    session.commit()

    def fake_extract(_video_path: Path, output_path: Path) -> None:
        _write_valid_tail(output_path)

    real_commit = session.commit

    def fail_commit_once() -> None:
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(studio, "extract_tail_frame", fake_extract)
    monkeypatch.setattr(session, "commit", fail_commit_once)
    with pytest.raises(RuntimeError, match="database commit failed"):
        studio.approve_video(session, shot.id or 0)

    monkeypatch.setattr(session, "commit", real_commit)
    session.rollback()
    session.refresh(shot)
    final_tail = tmp_path / "storage" / f"project-{project.id}" / f"shot-{shot.id}" / f"tail-frame-shot-{shot.id}.png"
    assert shot.status == ShotStatus.VIDEO_REVIEW
    assert not final_tail.exists()
    assert session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).first() is None


def test_video_approval_rejects_invalid_temp_tail_without_db_changes(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _project, shot, _video_path = _video_review_shot(session, tmp_path, with_next=True)
    before_logs = len(session.exec(select(ShotStateChange).where(ShotStateChange.shot_id == shot.id)).all())
    next_shot = studio.list_project_shots(session, shot.project_id)[1]

    def invalid_extract(_video_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"not an image")

    monkeypatch.setattr(studio, "extract_tail_frame", invalid_extract)
    with pytest.raises(Exception, match="invalid image"):
        studio.approve_video(session, shot.id or 0)

    session.refresh(shot)
    session.refresh(next_shot)
    final_tail = get_settings().storage_dir / f"project-{shot.project_id}" / f"shot-{shot.id}" / f"tail-frame-shot-{shot.id}.png"
    assert shot.status == ShotStatus.VIDEO_REVIEW
    assert next_shot.start_frame_asset_id is None
    assert not final_tail.exists()
    assert session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).first() is None
    assert len(session.exec(select(ShotStateChange).where(ShotStateChange.shot_id == shot.id)).all()) == before_logs
    assert not list((get_settings().storage_dir / "temp" / "tails").glob("*.png"))


def test_video_approval_replace_failure_rolls_back_without_asset(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _project, shot, _video_path = _video_review_shot(session, tmp_path)
    monkeypatch.setattr(studio, "extract_tail_frame", lambda _video_path, output_path: _write_valid_tail(output_path))
    monkeypatch.setattr(studio.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))

    with pytest.raises(OSError, match="replace failed"):
        studio.approve_video(session, shot.id or 0)

    session.refresh(shot)
    final_tail = get_settings().storage_dir / f"project-{shot.project_id}" / f"shot-{shot.id}" / f"tail-frame-shot-{shot.id}.png"
    assert shot.status == ShotStatus.VIDEO_REVIEW
    assert not final_tail.exists()
    assert session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).first() is None
    assert not list((get_settings().storage_dir / "temp" / "tails").glob("*.png"))


def test_video_approval_flush_failure_deletes_moved_final_file(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _project, shot, _video_path = _video_review_shot(session, tmp_path, with_next=True)
    next_shot = studio.list_project_shots(session, shot.project_id)[1]
    monkeypatch.setattr(studio, "extract_tail_frame", lambda _video_path, output_path: _write_valid_tail(output_path))
    original_flush = session.flush

    def fail_flush() -> None:
        raise RuntimeError("flush failed")

    monkeypatch.setattr(session, "flush", fail_flush)
    with pytest.raises(RuntimeError, match="flush failed"):
        studio.approve_video(session, shot.id or 0)

    monkeypatch.setattr(session, "flush", original_flush)
    session.rollback()
    session.refresh(shot)
    session.refresh(next_shot)
    final_tail = get_settings().storage_dir / f"project-{shot.project_id}" / f"shot-{shot.id}" / f"tail-frame-shot-{shot.id}.png"
    assert shot.status == ShotStatus.VIDEO_REVIEW
    assert next_shot.start_frame_asset_id is None
    assert not final_tail.exists()
    assert session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).first() is None


def test_video_approval_is_idempotent_after_completed(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _project, shot, _video_path = _video_review_shot(session, tmp_path, with_next=True)
    calls = 0

    def fake_extract(_video_path: Path, output_path: Path) -> None:
        nonlocal calls
        calls += 1
        _write_valid_tail(output_path)

    monkeypatch.setattr(studio, "extract_tail_frame", fake_extract)
    studio.approve_video(session, shot.id or 0)
    studio.approve_video(session, shot.id or 0)

    tail_assets = session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).all()
    start_assets = session.exec(select(Asset).where(Asset.type == AssetType.START_FRAME)).all()
    changes = session.exec(select(ShotStateChange).where(ShotStateChange.shot_id == shot.id)).all()
    assert calls == 1
    assert len(tail_assets) == 1
    assert len(start_assets) == 1
    assert [change.reason for change in changes].count("shot_completed") == 1


def test_video_approval_last_shot_creates_tail_without_start_reference(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _project, shot, _video_path = _video_review_shot(session, tmp_path)
    monkeypatch.setattr(studio, "extract_tail_frame", lambda _video_path, output_path: _write_valid_tail(output_path))

    completed = studio.approve_video(session, shot.id or 0)

    assert completed.status == ShotStatus.COMPLETED
    assert len(session.exec(select(Asset).where(Asset.type == AssetType.TAIL_FRAME)).all()) == 1
    assert session.exec(select(Asset).where(Asset.type == AssetType.START_FRAME)).all() == []


def test_delete_shared_asset_file_keeps_until_last_reference(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    first = studio.create_shot(session, project.id or 0, ShotCreate(title="A"))
    second = studio.create_shot(session, project.id or 0, ShotCreate(title="B"))
    shared = get_settings().storage_dir / "project-shared" / "shared.png"
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_bytes(b"shared")
    for shot in [first, second]:
        session.add(
            Asset(
                project_id=project.id or 0,
                shot_id=shot.id,
                type=AssetType.KEYFRAME,
                path=str(shared),
                mime_type="image/png",
            )
        )
    session.commit()

    studio.delete_shot(session, first.id or 0)
    assert shared.exists()
    assert len(session.exec(select(Asset)).all()) == 1

    studio.delete_shot(session, second.id or 0)
    assert not shared.exists()
    assert session.exec(select(Asset)).all() == []


def test_delete_symlink_asset_removes_link_not_external_target(session: Session, tmp_path: Path) -> None:
    if not hasattr(Path, "symlink_to"):
        pytest.skip("symlink is not supported on this platform")
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="A"))
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret")
    link = get_settings().storage_dir / "project-link" / "linked.txt"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is not permitted on this platform")
    session.add(
        Asset(
            project_id=project.id or 0,
            shot_id=shot.id,
            type=AssetType.KEYFRAME,
            path=str(link),
            mime_type="text/plain",
        )
    )
    session.commit()

    studio.delete_shot(session, shot.id or 0)

    assert outside.exists()
    assert not link.exists()


def test_delete_file_permission_failure_does_not_rollback_database(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="A"))
    path = get_settings().storage_dir / "project-permission" / "blocked.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"blocked")
    session.add(
        Asset(
            project_id=project.id or 0,
            shot_id=shot.id,
            type=AssetType.KEYFRAME,
            path=str(path),
            mime_type="image/png",
        )
    )
    session.commit()

    def fail_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == path.name:
            raise PermissionError("denied")
        return original_unlink(self, missing_ok=missing_ok)

    original_unlink = Path.unlink
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    warnings: list[str] = []

    def capture_warning(message: str, *args: object, **_kwargs: object) -> None:
        warnings.append(message % args)

    monkeypatch.setattr(studio.logger, "warning", capture_warning)
    studio.delete_shot(session, shot.id or 0)

    warning_text = "\n".join(warnings)
    assert session.get(Shot, shot.id) is None
    assert session.exec(select(Asset)).all() == []
    assert path.exists()
    assert "denied" not in warning_text
    assert "blocked.png" in warning_text


def test_result_url_summary_does_not_persist_query_after_terminal(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="P"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="S"))
    request = task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot.id or 0,
        kind=GenerationKind.KEYFRAME,
        provider_name="fake-http",
    )
    task = task_service.create_task_attempt(session, generation_request=request, provider_id="fake-http")
    task_service.mark_task_running(session, task.id or 0)
    task_service.mark_task_result_ready(
        session,
        task.id or 0,
        remote_status="success",
        result_urls=[
            {
                "url": "https://cdn.example.test/result.png?X-Amz-Signature=secret&token=abc",
                "mime_type": "image/png",
            }
        ],
        response_summary="ok",
    )
    ready = task_service.get_task(session, task.id or 0)
    assert "X-Amz-Signature" not in ready.result_urls_json
    assert "token=abc" not in ready.result_urls_json
    assert "cdn.example.test" in ready.result_urls_json
    task_service.mark_task_failed(session, task.id or 0, error_code="FAILED", error_message="done")
    terminal = task_service.get_task(session, task.id or 0)
    assert terminal.raw_result_urls_json == "[]"


def test_request_factory_rejects_asset_scheme_for_remote_provider(session: Session) -> None:
    request = GenerationRequest(project_id=1, shot_id=1, kind=GenerationKind.VIDEO, provider_name="fake-http")
    task = SimpleNamespace(
        provider_id="fake-http",
        task_type=SimpleNamespace(value="VIDEO_GENERATION"),
        request_payload_json='{"input_asset_ids":[123],"duration_seconds":2}',
        idempotency_key="key",
    )
    factory = ProviderRequestFactory()
    with pytest.raises(ProviderUnsupportedCapabilityError, match="PROVIDER_ASSET_UPLOAD_UNSUPPORTED"):
        factory.build(request, task, SimpleNamespace(image_to_video=True, max_reference_images=2))  # type: ignore[arg-type]


def test_request_factory_truncates_image_references_to_provider_limit() -> None:
    request = GenerationRequest(project_id=1, shot_id=1, kind=GenerationKind.KEYFRAME, provider_name="mock")
    task = SimpleNamespace(
        provider_id="mock",
        task_type=SimpleNamespace(value="KEYFRAME_GENERATION"),
        request_payload_json='{"reference_asset_ids":[1,2,3],"metadata":{"source":"test"}}',
        idempotency_key="key",
    )
    capabilities = ProviderCapabilities(
        provider_id="mock",
        display_name="Mock",
        text_to_image=True,
        max_reference_images=2,
    )

    built = ProviderRequestFactory().build(request, task, capabilities)  # type: ignore[arg-type]

    assert isinstance(built, ImageGenerationRequest)
    assert built.reference_asset_ids == [1, 2]
    assert built.metadata["source"] == "test"
    assert built.metadata["reference_asset_ids_truncated"] is True
    assert built.metadata["dropped_reference_asset_count"] == 1


def test_request_factory_reserves_video_reference_slots_for_anchor_frames() -> None:
    request = GenerationRequest(project_id=1, shot_id=1, kind=GenerationKind.VIDEO, provider_name="fake-http")
    task = SimpleNamespace(
        provider_id="fake-http",
        task_type=SimpleNamespace(value="VIDEO_GENERATION"),
        request_payload_json='{"input_asset_ids":[10],"reference_asset_ids":[1,2],"duration_seconds":2}',
        idempotency_key="key",
    )
    capabilities = ProviderCapabilities(
        provider_id="fake-http",
        display_name="Fake HTTP",
        image_to_video=True,
        max_reference_images=2,
    )

    built = ProviderRequestFactory().build(
        request,
        task,  # type: ignore[arg-type]
        capabilities,
        prepared_assets={
            1: AssetReference(asset_id=1, url="https://assets.example.test/1.png"),
            2: AssetReference(asset_id=2, url="https://assets.example.test/2.png"),
            10: AssetReference(asset_id=10, url="https://assets.example.test/10.png", role="start_frame"),
        },
    )

    assert isinstance(built, VideoGenerationRequest)
    assert built.start_frame is not None
    assert built.start_frame.asset_id == 10
    assert [asset.asset_id for asset in built.reference_assets] == [1]
    assert built.metadata["reference_asset_ids_truncated"] is True
    assert built.metadata["used_reference_asset_count"] == 1
    assert built.metadata["dropped_reference_asset_count"] == 1
    assert built.metadata["reserved_reference_asset_count"] == 1


def test_sqlite_foreign_keys_enabled_on_app_engine() -> None:
    with app_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_internal_error_has_safe_request_id() -> None:
    app = FastAPI()
    register_request_id_middleware(app)
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret local path C:/secret")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "req-123"
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Internal server error.",
            "request_id": "req-123",
        }
    }


def test_ready_not_ready_uses_503(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    monkeypatch.setattr("app.api.routes._alembic_head_revision", lambda: "different")
    client = TestClient(app)
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
