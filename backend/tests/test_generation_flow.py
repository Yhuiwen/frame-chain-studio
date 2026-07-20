import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.routes import asset_response
from app.core.config import get_settings
from app.core.errors import AppError
from app.db import get_session
from app.main import app
from app.media.ffmpeg import assert_probeable
from app.models.entities import Asset, AssetStatus, AssetType, GenerationRequest, GenerationTaskStatus, Shot, ShotStatus, TaskLog
from app.models.schemas import ProjectCreate, ReorderShot, ShotCreate, ShotRevisionRequest, ShotUpdate
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

    first = studio.get_shot_or_404(session, first.id or 0)
    tail_asset = studio.get_current_locked_tail_frame(session, first)
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


def test_revision_prompt_invalidates_completed_shot_and_downstream(session: Session) -> None:
    first, second = create_two_shot_project(session)
    complete_first_shot(session, first)
    complete_first_shot(session, second)

    result = studio.revise_shot_spec(
        session,
        first.id or 0,
        ShotRevisionRequest(reason="change action", changes={"prompt": "new action"}),
    )

    first_after = studio.get_shot_or_404(session, first.id or 0)
    second_after = studio.get_shot_or_404(session, second.id or 0)
    assert result["old_spec_revision"] == 1
    assert result["new_spec_revision"] == 2
    assert first_after.status == ShotStatus.DRAFT
    assert first_after.approved_keyframe_asset_id is None
    assert first_after.approved_video_asset_id is None
    assert first_after.locked_tail_frame_asset_id is None
    assert second_after.status in {ShotStatus.DRAFT, ShotStatus.KEYFRAME_APPROVED}
    assert session.exec(select(Asset).where(Asset.shot_id == first.id, Asset.status == AssetStatus.STALE)).all()


def test_revision_duration_keeps_keyframe_but_invalidates_video(session: Session) -> None:
    first, _second = create_two_shot_project(session)
    complete_first_shot(session, first)
    before = studio.get_shot_or_404(session, first.id or 0)
    before_revision = before.spec_revision
    keyframe_id = before.approved_keyframe_asset_id

    studio.revise_shot_spec(
        session,
        first.id or 0,
        ShotRevisionRequest(reason="retime", changes={"duration_seconds": 6}),
    )

    after = studio.get_shot_or_404(session, first.id or 0)
    assert after.spec_revision == before_revision + 1
    assert after.status == ShotStatus.KEYFRAME_APPROVED
    assert after.approved_keyframe_asset_id != keyframe_id
    assert after.approved_video_asset_id is None
    assert after.locked_tail_frame_asset_id is None
    old_keyframe = session.get(Asset, keyframe_id)
    new_keyframe = session.get(Asset, after.approved_keyframe_asset_id)
    assert old_keyframe is not None
    assert new_keyframe is not None
    assert old_keyframe.status == AssetStatus.SUPERSEDED
    assert old_keyframe.superseded_by_asset_id == new_keyframe.id
    assert new_keyframe.status == AssetStatus.APPROVED
    assert new_keyframe.revision == after.spec_revision


def test_title_patch_does_not_increment_revision(session: Session) -> None:
    first, _second = create_two_shot_project(session)
    before = first.spec_revision

    updated = studio.update_shot(session, first.id or 0, ShotUpdate(title="Renamed"))

    assert updated.title == "Renamed"
    assert updated.spec_revision == before


def test_patch_generation_field_requires_revision_api(session: Session) -> None:
    first, _second = create_two_shot_project(session)

    with pytest.raises(AppError) as exc:
        studio.update_shot(session, first.id or 0, ShotUpdate(prompt="silent mutation"))

    assert exc.value.code == "SHOT_REVISION_REQUIRED"


def complete_first_shot(session: Session, shot: Shot) -> None:
    provider = MockGenerationProvider()
    keyframe_request = studio.start_keyframe_generation(session, shot.id or 0)
    studio.run_generation_request(session, keyframe_request.id or 0, provider)
    studio.approve_keyframe(session, shot.id or 0)
    video_request = studio.start_video_generation(session, shot.id or 0)
    studio.run_generation_request(session, video_request.id or 0, provider)
    studio.approve_video(session, shot.id or 0)


def test_delete_shot_without_related_records(session: Session) -> None:
    first, second = create_two_shot_project(session)
    studio.delete_shot(session, second.id or 0)

    remaining = studio.list_project_shots(session, first.project_id)
    assert [shot.id for shot in remaining] == [first.id]
    assert remaining[0].sort_order == 0


def test_delete_shot_with_mock_tasks_and_assets(session: Session) -> None:
    first, _ = create_two_shot_project(session)
    complete_first_shot(session, first)

    studio.delete_shot(session, first.id or 0)

    assert session.get(Shot, first.id) is None
    assert session.exec(select(GenerationRequest).where(GenerationRequest.shot_id == first.id)).all() == []
    assert session.exec(select(TaskLog).where(TaskLog.shot_id == first.id)).all() == []
    assert session.exec(select(Asset).where(Asset.shot_id == first.id)).all() == []


def test_delete_middle_shot_rebuilds_start_frame_inheritance(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Three shots"))
    first = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 1"))
    middle = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 2"))
    last = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 3"))
    complete_first_shot(session, first)
    complete_first_shot(session, middle)

    before = studio.get_shot_or_404(session, last.id or 0)
    before_start = session.get(Asset, before.start_frame_asset_id)
    middle_tail = studio.get_current_locked_tail_frame(session, studio.get_shot_or_404(session, middle.id or 0))
    assert before_start is not None
    assert middle_tail is not None
    assert before_start.source_asset_id == middle_tail.id

    studio.delete_shot(session, middle.id or 0)

    after = studio.get_shot_or_404(session, last.id or 0)
    after_start = session.get(Asset, after.start_frame_asset_id)
    first_tail = studio.get_current_locked_tail_frame(session, studio.get_shot_or_404(session, first.id or 0))
    assert after.sort_order == 1
    assert after_start is not None
    assert first_tail is not None
    assert after_start.source_asset_id == first_tail.id


def test_delete_first_and_last_shot_reindex_and_clear_inheritance(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Edges"))
    first = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 1"))
    second = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 2"))
    third = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 3"))
    complete_first_shot(session, first)

    studio.delete_shot(session, first.id or 0)
    second_after = studio.get_shot_or_404(session, second.id or 0)
    assert second_after.sort_order == 0
    assert second_after.start_frame_asset_id is None

    studio.delete_shot(session, third.id or 0)
    remaining = studio.list_project_shots(session, project.id or 0)
    assert [shot.id for shot in remaining] == [second.id]
    assert remaining[0].sort_order == 0


def test_repeated_delete_returns_standard_404(session: Session) -> None:
    first, _ = create_two_shot_project(session)
    studio.delete_shot(session, first.id or 0)

    with pytest.raises(AppError) as exc:
        studio.delete_shot(session, first.id or 0)
    assert exc.value.code == "SHOT_NOT_FOUND"
    assert exc.value.status_code == 404


def test_delete_rolls_back_when_relink_fails(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = create_two_shot_project(session)

    def fail_relink(*_: object) -> None:
        raise RuntimeError("forced rollback")

    monkeypatch.setattr(studio, "relink_start_frame_after_delete", fail_relink)
    with pytest.raises(RuntimeError):
        studio.delete_shot(session, first.id or 0)

    assert session.get(Shot, first.id) is not None
    assert session.get(Shot, second.id) is not None


def test_project_detail_returns_start_frame_source_and_readable_url(session: Session) -> None:
    first, second = create_two_shot_project(session)
    complete_first_shot(session, first)

    _, shots, _, _, _, _, _, _, _ = studio.project_detail(session, first.project_id)
    second_payload = next(shot for shot in shots if shot["id"] == second.id)
    start_frame = second_payload["start_frame"]
    assert isinstance(start_frame, dict)
    assert start_frame["url"] == f"/api/media/{start_frame['asset_id']}"
    assert start_frame["source_type"] == "inherited"
    assert start_frame["source_shot_id"] == first.id
    assert start_frame["source_shot_title"] == first.title

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get(start_frame["url"])
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
    finally:
        app.dependency_overrides.clear()


def test_asset_read_rejects_outside_storage_and_missing_asset(session: Session, tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not real image")
    project = studio.create_project(session, ProjectCreate(name="Unsafe"))
    asset = Asset(
        project_id=project.id or 0,
        shot_id=None,
        type=AssetType.KEYFRAME,
        path=str(outside),
        mime_type="image/png",
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)

    with pytest.raises(AppError) as denied:
        asset_response(asset.id or 0, session=session)
    assert denied.value.code == "ASSET_ACCESS_DENIED"

    with pytest.raises(AppError) as missing:
        asset_response(999999, session=session)
    assert missing.value.code == "ASSET_NOT_FOUND"


def test_project_image_upload_validates_and_deduplicates(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Uploads"))
    image_bytes = png_bytes()

    first = studio.create_project_image_asset(
        session,
        project.id or 0,
        content=image_bytes,
        content_type="image/png",
    )
    assert first.sha256 == hashlib.sha256(image_bytes).hexdigest()
    assert ".." not in Path(first.path).name
    assert "\\" not in Path(first.path).name

    duplicate = studio.create_project_image_asset(
        session,
        project.id or 0,
        content=image_bytes,
        content_type="image/png",
    )
    assert duplicate.id == first.id

    with pytest.raises(AppError) as exc:
        studio.create_project_image_asset(
            session,
            project.id or 0,
            content=b"not an image",
            content_type="image/png",
        )
    assert exc.value.code == "MEDIA_VALIDATION_ERROR"


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def create_shot_chain(session: Session, count: int) -> list[Shot]:
    project = studio.create_project(session, ProjectCreate(name=f"{count} shot chain"))
    return [
        studio.create_shot(session, project.id or 0, ShotCreate(title=f"Shot {index + 1}"))
        for index in range(count)
    ]


def test_four_shot_middle_prompt_revision_recursively_invalidates_inherited_chain(session: Session) -> None:
    first, second, third, fourth = create_shot_chain(session, 4)
    for shot in [first, second, third, fourth]:
        complete_first_shot(session, shot)
    second_before = studio.get_shot_or_404(session, second.id or 0)
    third_before = studio.get_shot_or_404(session, third.id or 0)
    fourth_before = studio.get_shot_or_404(session, fourth.id or 0)
    stale_ids = {
        second_before.approved_keyframe_asset_id,
        second_before.approved_video_asset_id,
        second_before.locked_tail_frame_asset_id,
        third_before.start_frame_asset_id,
        third_before.approved_video_asset_id,
        third_before.locked_tail_frame_asset_id,
        fourth_before.start_frame_asset_id,
        fourth_before.approved_video_asset_id,
        fourth_before.locked_tail_frame_asset_id,
    }

    studio.revise_shot_spec(
        session,
        second.id or 0,
        ShotRevisionRequest(reason="rewrite middle", changes={"prompt": "different middle"}),
    )

    first_after = studio.get_shot_or_404(session, first.id or 0)
    second_after = studio.get_shot_or_404(session, second.id or 0)
    third_after = studio.get_shot_or_404(session, third.id or 0)
    fourth_after = studio.get_shot_or_404(session, fourth.id or 0)
    assert first_after.status == ShotStatus.COMPLETED
    assert second_after.status == ShotStatus.DRAFT
    assert third_after.status in {ShotStatus.DRAFT, ShotStatus.KEYFRAME_APPROVED}
    assert fourth_after.status in {ShotStatus.DRAFT, ShotStatus.KEYFRAME_APPROVED}
    assert second_after.approved_keyframe_asset_id is None
    assert second_after.approved_video_asset_id is None
    assert second_after.locked_tail_frame_asset_id is None
    assert third_after.start_frame_asset_id is None
    assert fourth_after.start_frame_asset_id is None
    assert third_after.approved_video_asset_id is None
    assert fourth_after.approved_video_asset_id is None
    for asset_id in stale_ids:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.status == AssetStatus.STALE
    completion = studio.project_completion(
        [first_after, second_after, third_after, fourth_after],
        list(session.exec(select(Asset).where(Asset.project_id == first.project_id)).all()),
    )
    assert completion["can_render"] is False


def test_manual_start_frame_breaks_upstream_continuity_propagation(session: Session) -> None:
    first, second, third = create_shot_chain(session, 3)
    manual = studio.create_project_image_asset(
        session,
        first.project_id,
        content=png_bytes(),
        content_type="image/png",
    )
    studio.set_shot_start_frame(session, second.id or 0, action="SELECT", asset_id=manual.id)
    for shot in [first, second, third]:
        complete_first_shot(session, shot)
    second_before = studio.get_shot_or_404(session, second.id or 0)
    third_before = studio.get_shot_or_404(session, third.id or 0)

    studio.revise_shot_spec(
        session,
        first.id or 0,
        ShotRevisionRequest(reason="rewrite first", changes={"prompt": "new first"}),
    )

    second_after = studio.get_shot_or_404(session, second.id or 0)
    third_after = studio.get_shot_or_404(session, third.id or 0)
    assert second_after.status == ShotStatus.COMPLETED
    assert third_after.status == ShotStatus.COMPLETED
    assert second_after.start_frame_source_type == second_before.start_frame_source_type == "MANUAL"
    assert second_after.start_frame_asset_id == second_before.start_frame_asset_id
    assert third_after.start_frame_asset_id == third_before.start_frame_asset_id
    assert second_after.approved_video_asset_id == second_before.approved_video_asset_id
    assert third_after.approved_video_asset_id == third_before.approved_video_asset_id


def test_reorder_rebuilds_inherited_start_frames_and_invalidates_changed_segments(session: Session) -> None:
    first, second, third = create_shot_chain(session, 3)
    for shot in [first, second, third]:
        complete_first_shot(session, shot)
    second_before = studio.get_shot_or_404(session, second.id or 0)
    third_before = studio.get_shot_or_404(session, third.id or 0)
    old_second_start = second_before.start_frame_asset_id
    old_third_start = third_before.start_frame_asset_id
    old_third_video = third_before.approved_video_asset_id
    first_tail = studio.get_current_locked_tail_frame(session, studio.get_shot_or_404(session, first.id or 0))
    assert first_tail is not None

    studio.reorder_shots(
        session,
        first.project_id,
        [
            ReorderShot(id=first.id or 0, sort_order=0),
            ReorderShot(id=third.id or 0, sort_order=1),
            ReorderShot(id=second.id or 0, sort_order=2),
        ],
    )

    third_after = studio.get_shot_or_404(session, third.id or 0)
    second_after = studio.get_shot_or_404(session, second.id or 0)
    third_start = session.get(Asset, third_after.start_frame_asset_id)
    assert third_start is not None
    assert third_start.source_asset_id == first_tail.id
    assert second_after.start_frame_asset_id is None
    assert third_after.approved_video_asset_id is None
    assert second_after.approved_video_asset_id is None
    old_second_start_asset = session.get(Asset, old_second_start)
    old_third_start_asset = session.get(Asset, old_third_start)
    old_third_video_asset = session.get(Asset, old_third_video)
    assert old_second_start_asset is not None
    assert old_third_start_asset is not None
    assert old_third_video_asset is not None
    assert old_second_start_asset.status == AssetStatus.STALE
    assert old_third_start_asset.status == AssetStatus.STALE
    assert old_third_video_asset.status == AssetStatus.STALE


def test_target_keyframe_replacement_enters_review_and_invalidates_downstream(session: Session) -> None:
    first, second = create_two_shot_project(session)
    complete_first_shot(session, first)
    complete_first_shot(session, second)
    first_before = studio.get_shot_or_404(session, first.id or 0)
    second_before = studio.get_shot_or_404(session, second.id or 0)
    stale_ids = [
        first_before.approved_keyframe_asset_id,
        first_before.approved_video_asset_id,
        first_before.locked_tail_frame_asset_id,
        second_before.start_frame_asset_id,
        second_before.approved_video_asset_id,
        second_before.locked_tail_frame_asset_id,
    ]
    upload = studio.create_project_image_asset(
        session,
        first.project_id,
        content=png_bytes(),
        content_type="image/png",
    )

    studio.set_shot_target_keyframe(session, first.id or 0, asset_id=upload.id or 0)

    first_after = studio.get_shot_or_404(session, first.id or 0)
    second_after = studio.get_shot_or_404(session, second.id or 0)
    assert first_after.status == ShotStatus.KEYFRAME_REVIEW
    assert first_after.approved_keyframe_asset_id is None
    assert first_after.approved_video_asset_id is None
    assert first_after.locked_tail_frame_asset_id is None
    assert second_after.start_frame_asset_id is None
    for asset_id in stale_ids:
        asset = session.get(Asset, asset_id)
        assert asset is not None
        assert asset.status == AssetStatus.STALE


def test_repeated_video_approval_does_not_duplicate_tail_or_start_assets(session: Session) -> None:
    first, second = create_two_shot_project(session)
    complete_first_shot(session, first)

    tail_count = len(session.exec(select(Asset).where(Asset.shot_id == first.id, Asset.type == AssetType.TAIL_FRAME)).all())
    start_count = len(
        session.exec(select(Asset).where(Asset.shot_id == second.id, Asset.type == AssetType.START_FRAME)).all()
    )
    studio.approve_video(session, first.id or 0)

    assert (
        len(session.exec(select(Asset).where(Asset.shot_id == first.id, Asset.type == AssetType.TAIL_FRAME)).all())
        == tail_count
    )
    assert (
        len(session.exec(select(Asset).where(Asset.shot_id == second.id, Asset.type == AssetType.START_FRAME)).all())
        == start_count
    )


def test_mock_provider_reads_committed_fixtures_without_modifying_them(
    session: Session,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    fixture_dir = Path("tests/fixtures")
    keyframe_fixture = fixture_dir / "mock-keyframe.png"
    video_fixture = fixture_dir / "mock-video.mp4"
    before = {
        keyframe_fixture: hashlib.sha256(keyframe_fixture.read_bytes()).hexdigest(),
        video_fixture: hashlib.sha256(video_fixture.read_bytes()).hexdigest(),
    }
    settings.fixture_dir = fixture_dir
    settings.storage_dir = tmp_path / "empty-storage"

    first, _ = create_two_shot_project(session)
    complete_first_shot(session, first)

    assert settings.storage_dir.exists()
    assert list(settings.storage_dir.rglob("*.png"))
    assert list(settings.storage_dir.rglob("*.mp4"))
    after = {
        keyframe_fixture: hashlib.sha256(keyframe_fixture.read_bytes()).hexdigest(),
        video_fixture: hashlib.sha256(video_fixture.read_bytes()).hexdigest(),
    }
    assert after == before
