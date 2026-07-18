import pytest

from app.core.errors import AppError
from app.domain.state_machine import ensure_transition_allowed
from app.models.entities import ShotStatus


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ShotStatus.DRAFT, ShotStatus.KEYFRAME_GENERATING),
        (ShotStatus.KEYFRAME_GENERATING, ShotStatus.KEYFRAME_REVIEW),
        (ShotStatus.KEYFRAME_REVIEW, ShotStatus.KEYFRAME_APPROVED),
        (ShotStatus.KEYFRAME_APPROVED, ShotStatus.VIDEO_GENERATING),
        (ShotStatus.VIDEO_GENERATING, ShotStatus.VIDEO_REVIEW),
        (ShotStatus.VIDEO_REVIEW, ShotStatus.VIDEO_APPROVED),
        (ShotStatus.VIDEO_APPROVED, ShotStatus.TAIL_FRAME_LOCKED),
        (ShotStatus.TAIL_FRAME_LOCKED, ShotStatus.COMPLETED),
    ],
)
def test_allowed_transitions(current: ShotStatus, target: ShotStatus) -> None:
    ensure_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ShotStatus.DRAFT, ShotStatus.VIDEO_GENERATING),
        (ShotStatus.KEYFRAME_REVIEW, ShotStatus.VIDEO_GENERATING),
        (ShotStatus.VIDEO_REVIEW, ShotStatus.COMPLETED),
        (ShotStatus.COMPLETED, ShotStatus.DRAFT),
    ],
)
def test_rejects_illegal_transitions(current: ShotStatus, target: ShotStatus) -> None:
    with pytest.raises(AppError) as exc:
        ensure_transition_allowed(current, target)
    assert exc.value.code == "INVALID_STATE_TRANSITION"
