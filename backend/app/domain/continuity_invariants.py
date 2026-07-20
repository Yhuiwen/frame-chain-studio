from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.models.entities import Asset, AssetStatus, AssetType, Shot, ShotStatus, StartFrameSourceType

VALID_CURRENT_STATUSES = {AssetStatus.ACTIVE, AssetStatus.APPROVED}
INVALID_CURRENT_STATUSES = {AssetStatus.REJECTED, AssetStatus.STALE, AssetStatus.SUPERSEDED}
IMAGE_ASSET_TYPES = {AssetType.KEYFRAME, AssetType.START_FRAME, AssetType.TAIL_FRAME}


def validate_shot_invariants(session: Session, shot: Shot) -> None:
    _validate_start_frame(session, shot)
    if shot.status == ShotStatus.DRAFT:
        _require_no_approved_pointers(shot)
    elif shot.status == ShotStatus.KEYFRAME_REVIEW:
        _require_review_asset(session, shot, AssetType.KEYFRAME)
        _require_no_video_pointers(shot)
    elif shot.status == ShotStatus.KEYFRAME_APPROVED:
        _require_approved_asset(session, shot, shot.approved_keyframe_asset_id, AssetType.KEYFRAME)
        _require_no_video_pointers(shot)
    elif shot.status == ShotStatus.VIDEO_REVIEW:
        _require_approved_asset(session, shot, shot.approved_keyframe_asset_id, AssetType.KEYFRAME)
        _require_review_asset(session, shot, AssetType.VIDEO)
        _require_no_video_pointers(shot)
    elif shot.status == ShotStatus.COMPLETED:
        _require_approved_asset(session, shot, shot.approved_keyframe_asset_id, AssetType.KEYFRAME)
        video = _require_approved_asset(session, shot, shot.approved_video_asset_id, AssetType.VIDEO)
        tail = _require_approved_asset(session, shot, shot.locked_tail_frame_asset_id, AssetType.TAIL_FRAME)
        if tail.source_asset_id != video.id:
            _violation(shot, "locked tail frame must be sourced from the approved video")


def validate_project_continuity_invariants(session: Session, project_id: int) -> None:
    shots = list(
        session.exec(select(Shot).where(Shot.project_id == project_id).order_by(col(Shot.sort_order))).all()
    )
    previous: Shot | None = None
    for shot in shots:
        validate_shot_invariants(session, shot)
        if shot.start_frame_source_type != StartFrameSourceType.INHERITED:
            previous = shot
            continue
        if previous is None:
            _violation(shot, "first shot cannot inherit a start frame")
        assert previous is not None
        inherited = _asset_or_violation(session, shot, shot.start_frame_asset_id, "start frame")
        if inherited.source_asset_id != previous.locked_tail_frame_asset_id:
            _violation(shot, "inherited start frame must point to the previous shot locked tail")
        previous = shot


def _require_no_approved_pointers(shot: Shot) -> None:
    if shot.approved_keyframe_asset_id or shot.approved_video_asset_id or shot.locked_tail_frame_asset_id:
        _violation(shot, "draft shot cannot have current approved asset pointers")


def _require_no_video_pointers(shot: Shot) -> None:
    if shot.approved_video_asset_id or shot.locked_tail_frame_asset_id:
        _violation(shot, "shot cannot have approved video or tail frame pointers in this state")


def _validate_start_frame(session: Session, shot: Shot) -> None:
    if shot.start_frame_source_type == StartFrameSourceType.NONE:
        if shot.start_frame_asset_id is not None:
            _violation(shot, "NONE start frame source requires no start frame asset")
        return
    if shot.start_frame_asset_id is None:
        _violation(shot, "start frame source requires a start frame asset")
    asset = _asset_or_violation(session, shot, shot.start_frame_asset_id, "start frame")
    if asset.project_id != shot.project_id:
        _violation(shot, "start frame asset must belong to the same project")
    if asset.status in INVALID_CURRENT_STATUSES:
        _violation(shot, "start frame asset is not current")
    if asset.type not in IMAGE_ASSET_TYPES or not asset.mime_type.startswith("image/"):
        _violation(shot, "start frame asset must be an image")
    if shot.start_frame_source_type == StartFrameSourceType.MANUAL:
        return
    if asset.type != AssetType.START_FRAME or asset.shot_id != shot.id or asset.source_asset_id is None:
        _violation(shot, "inherited start frame must be a shot-owned derived start frame")


def _require_review_asset(session: Session, shot: Shot, asset_type: AssetType) -> Asset:
    asset = session.exec(
        select(Asset)
        .where(
            Asset.project_id == shot.project_id,
            Asset.shot_id == shot.id,
            Asset.type == asset_type,
            Asset.revision == shot.spec_revision,
            Asset.status == AssetStatus.ACTIVE,
        )
        .order_by(col(Asset.created_at).desc(), col(Asset.id).desc())
    ).first()
    if asset is None:
        _violation(shot, f"{asset_type.value.lower()} review asset is missing")
    assert asset is not None
    return asset


def _require_approved_asset(session: Session, shot: Shot, asset_id: int | None, asset_type: AssetType) -> Asset:
    if asset_id is None:
        _violation(shot, f"approved {asset_type.value.lower()} pointer is missing")
    asset = _asset_or_violation(session, shot, asset_id, asset_type.value.lower())
    if asset.project_id != shot.project_id or asset.shot_id != shot.id:
        _violation(shot, f"approved {asset_type.value.lower()} must belong to the current shot and project")
    if asset.type != asset_type:
        _violation(shot, f"approved asset type must be {asset_type.value}")
    if asset.revision != shot.spec_revision:
        _violation(shot, f"approved {asset_type.value.lower()} revision must match shot revision")
    if asset.status != AssetStatus.APPROVED:
        _violation(shot, f"approved {asset_type.value.lower()} must be APPROVED")
    return asset


def _asset_or_violation(session: Session, shot: Shot, asset_id: int | None, label: str) -> Asset:
    asset = session.get(Asset, asset_id) if asset_id is not None else None
    if asset is None:
        _violation(shot, f"{label} asset does not exist")
    assert asset is not None
    return asset


def _violation(shot: Shot, message: str) -> None:
    raise AppError("SHOT_INVARIANT_VIOLATION", f"Shot {shot.id or 'unknown'} invariant violation: {message}.", 409)
