from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import AppError, register_error_handlers
from app.core.request_id import register_request_id_middleware
from app.db import get_session
from app.media import quality as media_quality
from app.media.ffmpeg import create_test_video
from app.media.quality import extract_first_frame, extract_last_frame
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    Project,
    QualityCheckResult,
    QualityCheckSeverity,
    Shot,
    ShotStatus,
    StartFrameSourceType,
)
from app.models.schemas import ProjectCreate, ShotCreate, ShotRevisionRequest
from app.providers.mock import MockGenerationProvider
from app.services import quality_service, studio
from app.workers.render_service import sha256_file


def test_duration_revision_copies_keyframe_with_same_sha_and_distinct_revision(session: Session, tmp_path: Path) -> None:
    first, _second = _two_shots(session)
    _complete_shot(session, first)
    before = studio.get_shot_or_404(session, first.id or 0)
    old_id = before.approved_keyframe_asset_id
    old_asset = session.get(Asset, old_id)
    assert old_asset is not None

    studio.revise_shot_spec(
        session,
        first.id or 0,
        ShotRevisionRequest(reason="retime", changes={"duration_seconds": 6}),
    )

    after = studio.get_shot_or_404(session, first.id or 0)
    new_asset = session.get(Asset, after.approved_keyframe_asset_id)
    assert new_asset is not None
    assert old_asset.sha256 == new_asset.sha256
    assert old_asset.revision != new_asset.revision
    assert old_asset.status == AssetStatus.SUPERSEDED
    assert new_asset.status == AssetStatus.APPROVED
    assert Path(new_asset.path).exists()


def test_quality_checks_manual_run_is_idempotent_and_does_not_change_review_state(session: Session, tmp_path: Path) -> None:
    shot, video = _video_review_shot_with_matching_refs(session, tmp_path)

    first_run = quality_service.run_shot_quality_checks(session, shot.id or 0)
    second_run = quality_service.run_shot_quality_checks(session, shot.id or 0)

    session.refresh(shot)
    assert shot.status == ShotStatus.VIDEO_REVIEW
    assert len(first_run) == len(second_run)
    assert len(session.exec(select(QualityCheckResult).where(QualityCheckResult.asset_id == video.id)).all()) == len(second_run)
    check_types = {item.check_type for item in second_run}
    assert {"DURATION_DEVIATION", "START_ANCHOR_DHASH_DISTANCE", "TAIL_TARGET_DHASH_DISTANCE", "VIDEO_FPS"} <= check_types
    assert all(item.algorithm_version for item in second_run)
    assert any(item.severity == "INFO" for item in second_run)


def test_quality_api_rejects_no_current_video_and_hides_old_revision_results(session: Session, tmp_path: Path) -> None:
    shot, video = _video_review_shot_with_matching_refs(session, tmp_path)
    quality_service.run_shot_quality_checks(session, shot.id or 0)
    shot.spec_revision += 1
    video.status = AssetStatus.STALE
    session.add(shot)
    session.add(video)
    session.commit()

    app = _test_app(session)
    with TestClient(app) as client:
        get_response = client.get(f"/api/shots/{shot.id}/quality-checks")
        assert get_response.status_code == 200
        assert get_response.json() == []
        post_response = client.post(f"/api/shots/{shot.id}/quality-checks/run")
        assert post_response.status_code == 409
        assert str(tmp_path) not in post_response.text


def test_quality_results_are_not_saved_when_target_changes_during_analysis(
    monkeypatch: pytest.MonkeyPatch, session: Session, tmp_path: Path
) -> None:
    shot, video = _video_review_shot_with_matching_refs(session, tmp_path)

    def stale_collect(snapshot: quality_service.QualitySnapshot) -> list[quality_service.QualityItem]:
        current = session.get(Shot, snapshot.shot_id)
        assert current is not None
        current.spec_revision += 1
        session.add(current)
        session.commit()
        return [
            quality_service.QualityItem(
                "DURATION_DEVIATION",
                QualityCheckSeverity.INFO,
                0.0,
                0.12,
                "stale result",
                {},
                video.id,
            )
        ]

    monkeypatch.setattr(quality_service, "_collect_items", stale_collect)

    with pytest.raises(AppError) as exc_info:
        quality_service.run_shot_quality_checks(session, shot.id or 0)

    assert exc_info.value.code == "QUALITY_TARGET_CHANGED"
    assert session.exec(select(QualityCheckResult).where(QualityCheckResult.asset_id == video.id)).all() == []


def test_same_sha_same_revision_is_rejected_but_cross_revision_allowed(session: Session, tmp_path: Path) -> None:
    project = Project(name="P")
    session.add(project)
    session.commit()
    session.refresh(project)
    shot = Shot(project_id=project.id or 0, title="S")
    session.add(shot)
    session.commit()
    session.refresh(shot)
    path = tmp_path / "a.png"
    path.write_bytes(b"same")
    first = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.KEYFRAME, revision=1, path=str(path), mime_type="image/png", sha256="same")
    second = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.KEYFRAME, revision=2, path=str(path), mime_type="image/png", sha256="same")
    session.add(first)
    session.add(second)
    session.commit()
    duplicate = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.KEYFRAME, revision=2, path=str(path), mime_type="image/png", sha256="same")
    session.add(duplicate)
    with pytest.raises(sa.exc.IntegrityError):
        session.commit()


def test_ffmpeg_segment_parser_handles_crlf_scientific_and_partial_lines() -> None:
    text = (
        "[blackdetect] black_start:0\r\n"
        "[blackdetect] black_end:1.2e+0 black_duration:1.2e+0\n"
        "noise\n"
        "[blackdetect] black_end:2.5 black_duration:.5\n"
        "[blackdetect] black_start:9.0\n"
    )
    segments = media_quality._segments(text, "black")
    assert [(item.start, item.end, item.duration) for item in segments] == [(0.0, 1.2, 1.2), (2.0, 2.5, 0.5)]


def test_deleting_superseded_shared_keyframe_keeps_current_file_accessible(session: Session, tmp_path: Path) -> None:
    first, _second = _two_shots(session)
    _complete_shot(session, first)
    before = studio.get_shot_or_404(session, first.id or 0)
    old_id = before.approved_keyframe_asset_id
    studio.revise_shot_spec(
        session,
        first.id or 0,
        ShotRevisionRequest(reason="retime", changes={"duration_seconds": 6}),
    )
    after = studio.get_shot_or_404(session, first.id or 0)
    old_asset = session.get(Asset, old_id)
    new_asset = session.get(Asset, after.approved_keyframe_asset_id)
    assert old_asset is not None
    assert new_asset is not None
    shared_path = Path(new_asset.path)
    session.delete(old_asset)
    session.commit()
    studio._cleanup_unreferenced_paths(session, [shared_path])
    assert shared_path.exists()


def _two_shots(session: Session) -> tuple[Shot, Shot]:
    project = studio.create_project(session, ProjectCreate(name="Quality"))
    return (
        studio.create_shot(session, project.id or 0, ShotCreate(title="A")),
        studio.create_shot(session, project.id or 0, ShotCreate(title="B")),
    )


def _complete_shot(session: Session, shot: Shot) -> None:
    provider = MockGenerationProvider()
    keyframe_request = studio.start_keyframe_generation(session, shot.id or 0)
    studio.run_generation_request(session, keyframe_request.id or 0, provider)
    studio.approve_keyframe(session, shot.id or 0)
    video_request = studio.start_video_generation(session, shot.id or 0)
    studio.run_generation_request(session, video_request.id or 0, provider)
    studio.approve_video(session, shot.id or 0)


def _video_review_shot_with_matching_refs(session: Session, tmp_path: Path) -> tuple[Shot, Asset]:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.quality_check_timeout_seconds = 20
    project = studio.create_project(session, ProjectCreate(name="Quality"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="S", duration_seconds=0.5))
    video_path = settings.storage_dir / "video.mp4"
    create_test_video(video_path, duration_seconds=0.5)
    first_frame = settings.storage_dir / "first.png"
    last_frame = settings.storage_dir / "last.png"
    extract_first_frame(video_path, first_frame, timeout_seconds=20)
    extract_last_frame(video_path, last_frame, timeout_seconds=20)
    start = Asset(project_id=project.id or 0, shot_id=None, type=AssetType.START_FRAME, path=str(first_frame), mime_type="image/png", sha256=sha256_file(first_frame), status=AssetStatus.APPROVED)
    keyframe = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.KEYFRAME, path=str(last_frame), mime_type="image/png", sha256=sha256_file(last_frame), status=AssetStatus.APPROVED, revision=shot.spec_revision)
    video = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.VIDEO, path=str(video_path), mime_type="video/mp4", sha256=sha256_file(video_path), status=AssetStatus.ACTIVE, revision=shot.spec_revision, duration_seconds=0.5, fps=24)
    session.add(start)
    session.add(keyframe)
    session.add(video)
    session.flush()
    shot.start_frame_asset_id = start.id
    shot.start_frame_source_type = StartFrameSourceType.MANUAL
    shot.approved_keyframe_asset_id = keyframe.id
    shot.status = ShotStatus.VIDEO_REVIEW
    session.add(shot)
    session.commit()
    return shot, video


def _test_app(session: Session) -> FastAPI:
    app = FastAPI()
    register_request_id_middleware(app)
    register_error_handlers(app)
    app.include_router(router, prefix="/api")

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    return app
