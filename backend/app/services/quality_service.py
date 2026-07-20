import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import time

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.media import quality
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    QualityCheckResult,
    QualityCheckSeverity,
    Shot,
    ShotStatus,
    TaskLog,
)

ALGORITHM_VERSION = "quality-v1"
MAX_DETAILS_JSON_LENGTH = 4000
MAX_MESSAGE_LENGTH = 500
MAX_SEGMENTS_PER_TYPE = 20


@dataclass(frozen=True)
class QualityItem:
    check_type: str
    severity: QualityCheckSeverity
    score: float | None
    threshold: float | None
    message: str
    details: dict[str, object]
    asset_id: int | None
    reference_asset_id: int | None = None


@dataclass(frozen=True)
class QualitySnapshot:
    project_id: int
    shot_id: int
    shot_revision: int
    shot_duration_seconds: float
    video_asset_id: int
    video_path: str
    keyframe_asset_id: int | None
    keyframe_path: str | None
    start_frame_asset_id: int | None
    start_frame_path: str | None


def list_shot_quality_checks(session: Session, shot_id: int) -> list[QualityCheckResult]:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise AppError("SHOT_NOT_FOUND", f"Shot {shot_id} was not found.", 404)
    current_video = _current_video_asset(session, shot)
    if current_video is None:
        return []
    return list(
        session.exec(
            select(QualityCheckResult)
            .where(
                QualityCheckResult.shot_id == shot_id,
                QualityCheckResult.asset_id == current_video.id,
                QualityCheckResult.algorithm_version == ALGORITHM_VERSION,
            )
            .order_by(col(QualityCheckResult.severity).desc(), col(QualityCheckResult.check_type))
        ).all()
    )


def run_shot_quality_checks(session: Session, shot_id: int) -> list[QualityCheckResult]:
    cleanup_quality_temp_files()
    snapshot = _snapshot_current_video(session, shot_id)
    session.add(TaskLog(shot_id=snapshot.shot_id, level="INFO", message=f"quality check started for asset {snapshot.video_asset_id}"))
    session.commit()

    items = _collect_items(snapshot)

    _write_results_with_retry(session, snapshot, items)
    return list_shot_quality_checks(session, snapshot.shot_id)


def _write_results_with_retry(session: Session, snapshot: QualitySnapshot, items: list[QualityItem]) -> None:
    for attempt in range(2):
        session.add(
            TaskLog(
                shot_id=snapshot.shot_id,
                level="WARNING" if any(item.severity == QualityCheckSeverity.ERROR for item in items) else "INFO",
                message=f"quality check completed for asset {snapshot.video_asset_id}",
            )
        )
        _replace_results(session, snapshot, items)
        try:
            session.commit()
            return
        except IntegrityError:
            session.rollback()
            if attempt == 0:
                continue
            raise


def maybe_run_video_quality_checks(session: Session, shot_id: int, video_asset_id: int | None) -> None:
    if video_asset_id is None:
        return
    try:
        shot = session.get(Shot, shot_id)
        asset = session.get(Asset, video_asset_id)
        if shot is None or asset is None or asset.type != AssetType.VIDEO:
            return
        if asset.revision != shot.spec_revision or asset.status not in {AssetStatus.ACTIVE, AssetStatus.APPROVED}:
            return
        run_shot_quality_checks(session, shot_id)
    except Exception as exc:
        session.rollback()
        session.add(TaskLog(shot_id=shot_id, level="WARNING", message=f"quality check partially failed: {exc.__class__.__name__}"))
        session.commit()


def cleanup_quality_temp_files(*, older_than_seconds: int = 3600) -> None:
    settings = get_settings()
    temp_root = (settings.storage_dir / "temp" / "quality").resolve()
    storage_root = settings.storage_dir.resolve()
    if temp_root == storage_root or storage_root not in temp_root.parents or not temp_root.exists():
        return
    cutoff = time() - older_than_seconds
    for child in temp_root.iterdir():
        try:
            resolved = child.resolve()
            if resolved == storage_root or temp_root not in resolved.parents or resolved.is_symlink():
                continue
            if child.stat().st_mtime > cutoff:
                continue
            if child.is_file():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                for item in child.rglob("*"):
                    if item.is_symlink():
                        continue
                import shutil

                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _snapshot_current_video(session: Session, shot_id: int) -> QualitySnapshot:
    shot = session.get(Shot, shot_id)
    if shot is None:
        raise AppError("SHOT_NOT_FOUND", f"Shot {shot_id} was not found.", 404)
    video = _current_video_asset(session, shot)
    if video is None:
        raise AppError("QUALITY_VIDEO_MISSING", "Shot has no current video for quality checks.", 409)
    if video.id is None or video.status not in {AssetStatus.ACTIVE, AssetStatus.APPROVED} or video.revision != shot.spec_revision:
        raise AppError("QUALITY_VIDEO_NOT_CURRENT", f"Video asset for Shot {shot.id} is not current.", 409)
    if video.shot_id != shot.id or video.project_id != shot.project_id:
        raise AppError("QUALITY_VIDEO_NOT_CURRENT", f"Video asset for Shot {shot.id} does not belong to the current shot.", 409)
    keyframe = session.get(Asset, shot.approved_keyframe_asset_id) if shot.approved_keyframe_asset_id else None
    start_frame = session.get(Asset, shot.start_frame_asset_id) if shot.start_frame_asset_id else None
    return QualitySnapshot(
        project_id=shot.project_id,
        shot_id=shot.id or 0,
        shot_revision=shot.spec_revision,
        shot_duration_seconds=float(shot.duration_seconds or 0.1),
        video_asset_id=video.id,
        video_path=video.path,
        keyframe_asset_id=keyframe.id if keyframe else None,
        keyframe_path=keyframe.path if keyframe else None,
        start_frame_asset_id=start_frame.id if start_frame else None,
        start_frame_path=start_frame.path if start_frame else None,
    )


def _current_video_asset(session: Session, shot: Shot) -> Asset | None:
    if shot.status == ShotStatus.VIDEO_REVIEW:
        return session.exec(
            select(Asset)
            .where(
                Asset.shot_id == shot.id,
                Asset.type == AssetType.VIDEO,
                Asset.revision == shot.spec_revision,
                Asset.status == AssetStatus.ACTIVE,
            )
            .order_by(col(Asset.created_at).desc(), col(Asset.id).desc())
        ).first()
    if shot.approved_video_asset_id:
        return session.get(Asset, shot.approved_video_asset_id)
    return None


def _collect_items(snapshot: QualitySnapshot) -> list[QualityItem]:
    settings = get_settings()
    items: list[QualityItem] = []
    temp_root = settings.storage_dir / "temp" / "quality"
    temp_root.mkdir(parents=True, exist_ok=True)
    video_path = Path(snapshot.video_path)
    try:
        metadata = quality.probe_video(video_path, timeout_seconds=settings.quality_check_timeout_seconds)
        expected_duration = snapshot.shot_duration_seconds
        actual_duration = metadata.duration_seconds or 0
        ratio = abs(actual_duration - expected_duration) / expected_duration if expected_duration > 0 else 0
        items.append(
            _item(
                "DURATION_DEVIATION",
                ratio,
                settings.quality_duration_warning_ratio,
                "Video duration differs from expected duration.",
                {"expected_seconds": expected_duration, "actual_seconds": actual_duration, "relative_difference": ratio},
                snapshot.video_asset_id,
            )
        )
        items.extend(
            [
                QualityItem("VIDEO_DIMENSIONS", QualityCheckSeverity.INFO, None, None, "Video dimensions recorded.", {"width": metadata.width, "height": metadata.height}, snapshot.video_asset_id),
                QualityItem("VIDEO_FPS", QualityCheckSeverity.INFO, metadata.fps, None, "Video FPS recorded.", {"fps": metadata.fps}, snapshot.video_asset_id),
                QualityItem("VIDEO_SAR", QualityCheckSeverity.INFO, None, None, "Video sample aspect ratio recorded.", {"sample_aspect_ratio": metadata.sample_aspect_ratio}, snapshot.video_asset_id),
                QualityItem("VIDEO_DAR", QualityCheckSeverity.INFO, None, None, "Video display aspect ratio recorded.", {"display_aspect_ratio": metadata.display_aspect_ratio}, snapshot.video_asset_id),
            ]
        )
        if metadata.audio_codec:
            items.append(QualityItem("UNEXPECTED_AUDIO_TRACK", QualityCheckSeverity.WARNING, None, None, "Video contains an audio track.", {"audio_codec": metadata.audio_codec}, snapshot.video_asset_id))
        black = quality.detect_black_segments(video_path, min_duration=settings.quality_black_min_duration, timeout_seconds=settings.quality_check_timeout_seconds)
        freeze = quality.detect_freeze_segments(video_path, min_duration=settings.quality_freeze_min_duration, timeout_seconds=settings.quality_check_timeout_seconds)
        items.extend(_segment_items("BLACK_FRAME_SEGMENT", black, actual_duration, settings.quality_black_min_duration, snapshot.video_asset_id))
        items.extend(_segment_items("FREEZE_FRAME_SEGMENT", freeze, actual_duration, settings.quality_freeze_min_duration, snapshot.video_asset_id))
        decode_error = quality.verify_decode(video_path, timeout_seconds=settings.quality_check_timeout_seconds)
        if decode_error:
            items.append(QualityItem("VIDEO_DECODE_ERROR", QualityCheckSeverity.ERROR, None, None, "Video could not be fully decoded.", {"error": decode_error}, snapshot.video_asset_id))
    except Exception as exc:
        items.append(QualityItem("VIDEO_DECODE_ERROR", QualityCheckSeverity.ERROR, None, None, "Video quality inspection failed.", {"error_type": exc.__class__.__name__}, snapshot.video_asset_id))
    with tempfile.TemporaryDirectory(dir=temp_root) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        if snapshot.keyframe_path is not None:
            items.extend(_image_compare_items("TAIL_TARGET", Path(snapshot.keyframe_path), video_path, temp_dir / "tail.png", snapshot.video_asset_id, snapshot.keyframe_asset_id, last=True))
        if snapshot.start_frame_path is not None:
            items.extend(_image_compare_items("START_ANCHOR", Path(snapshot.start_frame_path), video_path, temp_dir / "first.png", snapshot.video_asset_id, snapshot.start_frame_asset_id, last=False))
    return items


def _image_compare_items(prefix: str, reference: Path, video: Path, frame: Path, video_id: int | None, reference_id: int | None, *, last: bool) -> list[QualityItem]:
    settings = get_settings()
    try:
        if last:
            quality.extract_last_frame(video, frame, timeout_seconds=settings.quality_check_timeout_seconds)
        else:
            quality.extract_first_frame(video, frame, timeout_seconds=settings.quality_check_timeout_seconds)
        comparison = quality.compare_images(reference, frame)
    except Exception as exc:
        return [QualityItem(f"{prefix}_FRAME_ERROR", QualityCheckSeverity.ERROR, None, None, "Frame comparison failed.", {"error_type": exc.__class__.__name__}, video_id, reference_id)]
    return [
        _item(f"{prefix}_DHASH_DISTANCE", comparison.dhash_distance, settings.quality_dhash_warning_distance, "Frame perceptual hash distance recorded.", {"algorithm": "dhash"}, video_id, reference_id),
        _item(f"{prefix}_PIXEL_MAE", comparison.pixel_mae, settings.quality_pixel_mae_warning, "Frame pixel difference recorded.", {}, video_id, reference_id),
        _item(f"{prefix}_BRIGHTNESS_DIFF", comparison.brightness_diff, settings.quality_brightness_warning, "Frame brightness difference recorded.", {}, video_id, reference_id),
        _item(f"{prefix}_COLOR_SHIFT", comparison.color_shift, settings.quality_color_shift_warning, "Frame color shift recorded.", {"reference_rgb": comparison.reference_rgb, "actual_rgb": comparison.actual_rgb}, video_id, reference_id),
        _item(f"{prefix}_ASPECT_RATIO_DIFF", comparison.aspect_ratio_diff, 0.02, "Frame aspect ratio difference recorded.", {}, video_id, reference_id),
    ]


def _item(check_type: str, score: float | int, threshold: float | int, message: str, details: dict[str, object], asset_id: int | None, reference_id: int | None = None) -> QualityItem:
    severity = QualityCheckSeverity.WARNING if score > threshold else QualityCheckSeverity.INFO
    details = {**details, "threshold": threshold, "algorithm_version": ALGORITHM_VERSION}
    return QualityItem(check_type, severity, float(score), float(threshold), message, details, asset_id, reference_id)


def _segment_items(check_type: str, segments: list[quality.VideoSegment], total: float, threshold: float, asset_id: int | None) -> list[QualityItem]:
    return [
        QualityItem(
            check_type,
            QualityCheckSeverity.WARNING if segment.duration >= threshold else QualityCheckSeverity.INFO,
            segment.duration,
            threshold,
            f"Detected {check_type.lower().replace('_', ' ')}.",
            {"start": segment.start, "end": segment.end, "duration": segment.duration, "ratio": segment.duration / total if total else None},
            asset_id,
        )
        for segment in segments[:MAX_SEGMENTS_PER_TYPE]
    ]


def _replace_results(session: Session, snapshot: QualitySnapshot, items: list[QualityItem]) -> None:
    shot = session.get(Shot, snapshot.shot_id)
    video = session.get(Asset, snapshot.video_asset_id)
    if shot is None or video is None:
        raise AppError("QUALITY_TARGET_CHANGED", "Quality check target no longer exists.", 409)
    if (
        shot.project_id != snapshot.project_id
        or shot.spec_revision != snapshot.shot_revision
        or video.project_id != snapshot.project_id
        or video.shot_id != snapshot.shot_id
        or video.revision != snapshot.shot_revision
        or video.status not in {AssetStatus.ACTIVE, AssetStatus.APPROVED}
    ):
        raise AppError("QUALITY_TARGET_CHANGED", "Quality check target changed before results were saved.", 409)
    for existing in session.exec(
        select(QualityCheckResult).where(
            QualityCheckResult.asset_id == snapshot.video_asset_id,
            QualityCheckResult.algorithm_version == ALGORITHM_VERSION,
        )
    ).all():
        session.delete(existing)
    for item in items:
        details_json = _safe_details_json(item.details)
        session.add(
            QualityCheckResult(
                project_id=snapshot.project_id,
                shot_id=snapshot.shot_id,
                asset_id=snapshot.video_asset_id,
                reference_asset_id=item.reference_asset_id,
                check_type=item.check_type,
                severity=item.severity,
                score=item.score,
                threshold=item.threshold,
                message=item.message[:MAX_MESSAGE_LENGTH],
                details_json=details_json,
                algorithm_version=ALGORITHM_VERSION,
            )
        )


def _safe_details_json(details: dict[str, object]) -> str:
    text = json.dumps(details, sort_keys=True, allow_nan=False)
    if len(text) <= MAX_DETAILS_JSON_LENGTH:
        return text
    return json.dumps({"truncated": True, "algorithm_version": ALGORITHM_VERSION}, sort_keys=True)
