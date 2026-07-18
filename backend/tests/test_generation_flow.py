import json
from pathlib import Path

from sqlmodel import Session, select

from app.media.ffmpeg import assert_probeable
from app.models.entities import Asset, AssetType, GenerationTaskStatus, Shot, ShotStatus, TaskLog
from app.models.schemas import ProjectCreate, ShotCreate
from app.providers.mock import MockGenerationProvider
from app.services import studio


def create_two_shot_project(session: Session) -> tuple[Shot, Shot]:
    project = studio.create_project(session, ProjectCreate(name="Pilot"))
    first = studio.create_shot(
        session,
        project.id or 0,
        ShotCreate(title="Opening", prompt="wide establishing shot"),
    )
    second = studio.create_shot(
        session,
        project.id or 0,
        ShotCreate(title="Follow up", prompt="continue from tail frame"),
    )
    return first, second


def test_generation_flow_persists_assets_requests_logs_and_tail_frame(session: Session) -> None:
    first, second = create_two_shot_project(session)
    provider = MockGenerationProvider()

    keyframe_request = studio.start_keyframe_generation(session, first.id or 0)
    keyframe_request = studio.run_generation_request(session, keyframe_request.id or 0, provider)
    assert keyframe_request.status == GenerationTaskStatus.SUCCEEDED
    keyframe_asset_ids = json.loads(keyframe_request.output_asset_ids)
    assert len(keyframe_asset_ids) == 1

    first = studio.get_shot_or_404(session, first.id or 0)
    assert first.status == ShotStatus.KEYFRAME_REVIEW
    studio.approve_keyframe(session, first.id or 0)

    video_request = studio.start_video_generation(session, first.id or 0)
    video_request = studio.run_generation_request(session, video_request.id or 0, provider)
    assert video_request.status == GenerationTaskStatus.SUCCEEDED
    video_asset_id = json.loads(video_request.output_asset_ids)[0]
    video_asset = session.get(Asset, video_asset_id)
    assert video_asset is not None
    assert_probeable(Path(video_asset.path))

    first = studio.get_shot_or_404(session, first.id or 0)
    assert first.status == ShotStatus.VIDEO_REVIEW
    completed = studio.approve_video(session, first.id or 0)
    assert completed.status == ShotStatus.COMPLETED

    tail_asset = studio.latest_asset(session, first.id or 0, AssetType.TAIL_FRAME)
    assert tail_asset is not None
    assert Path(tail_asset.path).exists()

    second = studio.get_shot_or_404(session, second.id or 0)
    assert second.start_frame_asset_id is not None
    start_asset = session.get(Asset, second.start_frame_asset_id)
    assert start_asset is not None
    assert start_asset.type == AssetType.START_FRAME
    assert start_asset.source_asset_id == tail_asset.id

    logs = session.exec(select(TaskLog)).all()
    assert len(logs) >= 4


def test_video_generation_requires_approved_keyframe(session: Session) -> None:
    first, _ = create_two_shot_project(session)

    try:
        studio.start_video_generation(session, first.id or 0)
    except Exception as exc:
        assert getattr(exc, "code") == "KEYFRAME_NOT_APPROVED"
    else:
        raise AssertionError("Expected video generation to fail before keyframe approval")
