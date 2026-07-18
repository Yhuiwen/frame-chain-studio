from app.core.errors import AppError
from app.models.entities import ShotStatus


ALLOWED_TRANSITIONS: dict[ShotStatus, set[ShotStatus]] = {
    ShotStatus.DRAFT: {ShotStatus.KEYFRAME_GENERATING},
    ShotStatus.KEYFRAME_GENERATING: {ShotStatus.KEYFRAME_REVIEW, ShotStatus.DRAFT},
    ShotStatus.KEYFRAME_REVIEW: {ShotStatus.KEYFRAME_APPROVED, ShotStatus.DRAFT},
    ShotStatus.KEYFRAME_APPROVED: {ShotStatus.VIDEO_GENERATING},
    ShotStatus.VIDEO_GENERATING: {ShotStatus.VIDEO_REVIEW, ShotStatus.KEYFRAME_APPROVED},
    ShotStatus.VIDEO_REVIEW: {ShotStatus.VIDEO_APPROVED, ShotStatus.KEYFRAME_APPROVED},
    ShotStatus.VIDEO_APPROVED: {ShotStatus.TAIL_FRAME_LOCKED},
    ShotStatus.TAIL_FRAME_LOCKED: {ShotStatus.COMPLETED},
    ShotStatus.COMPLETED: set(),
}


def ensure_transition_allowed(current: ShotStatus, target: ShotStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise AppError(
            "INVALID_STATE_TRANSITION",
            f"Cannot transition shot from {current.value} to {target.value}.",
            status_code=409,
        )
