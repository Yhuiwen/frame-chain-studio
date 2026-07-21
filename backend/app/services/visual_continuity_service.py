from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.core.errors import AppError
from app.media.validation import validate_video
from app.media.visual_continuity import (
    ANALYSIS_VERSION,
    FrameMetric,
    VisualContinuityConfig,
    camera_and_composition_status,
    classify_cut,
    compare_images,
    match_status,
    sample_times,
    sampled_frames,
    scene_candidates,
    stable_report_hash,
    style_drift_status,
)
from app.models.entities import (
    Asset,
    AssetType,
    HumanVisualStatus,
    ProductionGateStatus,
    VisualAnalysisStatus,
    VisualContinuityReport,
    utcnow,
)
from app.services import provider_management


def analyze_asset(
    session: Session,
    *,
    video_asset_id: int,
    start_anchor_asset_id: int | None,
    target_keyframe_asset_id: int | None,
    tail_frame_asset_id: int | None,
    config: VisualContinuityConfig | None = None,
    human_status: HumanVisualStatus = HumanVisualStatus.PENDING,
    human_rejection_reasons: list[str] | None = None,
) -> VisualContinuityReport:
    active_config = config or VisualContinuityConfig()
    config_hash = active_config.config_hash()
    existing = session.exec(
        select(VisualContinuityReport).where(
            VisualContinuityReport.video_asset_id == video_asset_id,
            VisualContinuityReport.analysis_version == ANALYSIS_VERSION,
            VisualContinuityReport.config_hash == config_hash,
        )
    ).first()
    if existing is not None:
        return existing
    video = _asset(session, video_asset_id, AssetType.VIDEO, AssetType.PROJECT_RENDER)
    start = _optional_asset(session, start_anchor_asset_id)
    target = _optional_asset(session, target_keyframe_asset_id)
    tail = _optional_asset(session, tail_frame_asset_id)
    video_path = Path(video.path)
    if not video_path.exists():
        raise AppError("VISUAL_VIDEO_MISSING", "The visual-analysis video is missing.", 409)
    metadata = validate_video(video_path, timeout_seconds=30)
    duration = metadata.duration_seconds or 0.0
    fps = metadata.fps or 24.0
    candidates = scene_candidates(video_path, active_config)
    times = sample_times(duration, active_config.sample_interval_seconds, candidates, fps=fps)
    metrics: dict[str, Any] = {
        "analysisVersion": ANALYSIS_VERSION,
        "config": active_config.stable_dict(),
        "video": {
            "assetId": video_asset_id,
            "sha256": video.sha256,
            "duration": duration,
            "fps": fps,
        },
        "samples": [{"seconds": value, "pts": round(value * fps)} for value in times],
        "sceneCutCandidates": [],
    }
    reasons = list(human_rejection_reasons or [])
    with sampled_frames(video_path, times, fps=fps) as frames:
        first, last = frames[0], frames[-1]
        anchor_metric = compare_images(Path(start.path), first.path) if start else None
        target_metric = compare_images(Path(target.path), last.path) if target else None
        anchor_status = _match(
            anchor_metric,
            active_config.anchor_ssim_threshold,
            active_config.anchor_phash_distance_threshold,
        )
        target_status = _match(
            target_metric,
            active_config.target_ssim_threshold,
            active_config.target_phash_distance_threshold,
        )
        metrics["anchorMatch"] = _metric_payload(anchor_metric, anchor_status)
        metrics["targetMatch"] = _metric_payload(target_metric, target_status)
        relative_metrics = [compare_images(first.path, item.path) for item in frames[1:]]
        style_status = style_drift_status(relative_metrics, active_config)
        metrics["style"] = {
            "status": style_status,
            "relativeToFirst": [asdict(item) for item in relative_metrics],
        }
        worst = max(
            relative_metrics,
            key=lambda item: item.centroid_shift + item.salient_area_ratio_change,
            default=None,
        )
        composition = (
            camera_and_composition_status(worst, active_config) if worst else _inconclusive_camera()
        )
        metrics["cameraAndComposition"] = composition
        cut_status = VisualAnalysisStatus.PASSED
        for candidate in candidates:
            before = min(frames, key=lambda item: abs(item.seconds - max(0.0, candidate - 1 / fps)))
            after = min(
                frames, key=lambda item: abs(item.seconds - min(duration, candidate + 1 / fps))
            )
            metric = compare_images(before.path, after.path)
            decision = classify_cut(metric, active_config)
            metrics["sceneCutCandidates"].append(
                {
                    "seconds": candidate,
                    "beforeSeconds": before.seconds,
                    "afterSeconds": after.seconds,
                    "metrics": asdict(metric),
                    "decision": decision,
                }
            )
            if decision == "UNEXPECTED_HARD_CUT":
                cut_status = VisualAnalysisStatus.FAILED
                if "INTRA_SHOT_SCENE_CUT" not in reasons:
                    reasons.append("INTRA_SHOT_SCENE_CUT")
            elif decision == "INCONCLUSIVE" and cut_status != VisualAnalysisStatus.FAILED:
                cut_status = VisualAnalysisStatus.INCONCLUSIVE
        if style_status == "FAILED" and "CHARACTER_STYLE_DRIFT" not in reasons:
            reasons.append("CHARACTER_STYLE_DRIFT")
        if (
            composition["compositionStatus"] == "FAILED"
            and "COMPOSITION_DISCONTINUITY" not in reasons
        ):
            reasons.append("COMPOSITION_DISCONTINUITY")
        if composition["subjectScaleStatus"] == "FAILED" and "SUBJECT_SCALE_DRIFT" not in reasons:
            reasons.append("SUBJECT_SCALE_DRIFT")

    statuses = [
        cut_status.value,
        anchor_status,
        target_status,
        style_status,
        str(composition["cameraStatus"]),
        str(composition["compositionStatus"]),
        str(composition["subjectScaleStatus"]),
    ]
    automatic = (
        VisualAnalysisStatus.FAILED
        if "FAILED" in statuses
        else (
            VisualAnalysisStatus.INCONCLUSIVE
            if "INCONCLUSIVE" in statuses
            else VisualAnalysisStatus.PASSED
        )
    )
    gate = production_gate(
        technical=VisualAnalysisStatus.PASSED,
        automatic=automatic,
        human=human_status,
        lineage_verified=tail is not None,
    )
    report_core: dict[str, object] = {
        "videoAssetId": video_asset_id,
        "startAnchorAssetId": start_anchor_asset_id,
        "targetKeyframeAssetId": target_keyframe_asset_id,
        "tailFrameAssetId": tail_frame_asset_id,
        "analysisVersion": ANALYSIS_VERSION,
        "configHash": config_hash,
        "technicalStatus": "PASSED",
        "automaticVisualStatus": automatic.value,
        "humanVisualStatus": human_status.value,
        "productionGateStatus": gate.value,
        "metrics": metrics,
        "rejectionReasons": sorted(set(reasons)),
    }
    report = VisualContinuityReport(
        project_id=video.project_id,
        shot_id=video.shot_id,
        video_asset_id=video_asset_id,
        start_anchor_asset_id=start_anchor_asset_id,
        target_keyframe_asset_id=target_keyframe_asset_id,
        tail_frame_asset_id=tail_frame_asset_id,
        analysis_version=ANALYSIS_VERSION,
        config_hash=config_hash,
        report_hash=stable_report_hash(report_core),
        technical_status=VisualAnalysisStatus.PASSED,
        automatic_visual_status=automatic,
        human_visual_status=human_status,
        overall_visual_status=_overall(automatic, human_status),
        scene_cut_status=cut_status,
        anchor_match_status=VisualAnalysisStatus(anchor_status),
        target_match_status=VisualAnalysisStatus(target_status),
        camera_stability_status=VisualAnalysisStatus(str(composition["cameraStatus"])),
        composition_drift_status=VisualAnalysisStatus(str(composition["compositionStatus"])),
        subject_scale_drift_status=VisualAnalysisStatus(str(composition["subjectScaleStatus"])),
        style_drift_status=VisualAnalysisStatus(style_status),
        cross_shot_seam_status=VisualAnalysisStatus.PENDING,
        production_gate_status=gate,
        metrics_json=provider_management.dumps(metrics),
        rejection_reasons_json=provider_management.dumps(sorted(set(reasons))),
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


def review_report(
    session: Session, report_id: int, *, status: HumanVisualStatus, reasons: list[str]
) -> VisualContinuityReport:
    report = session.get(VisualContinuityReport, report_id)
    if report is None:
        raise AppError("VISUAL_REPORT_NOT_FOUND", "Visual continuity report was not found.", 404)
    report.human_visual_status = status
    report.rejection_reasons_json = provider_management.dumps(sorted(set(reasons)))
    report.overall_visual_status = _overall(report.automatic_visual_status, status)
    report.production_gate_status = production_gate(
        technical=report.technical_status,
        automatic=report.automatic_visual_status,
        human=status,
        lineage_verified=report.tail_frame_asset_id is not None,
    )
    report.updated_at = utcnow()
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


def production_gate(
    *,
    technical: VisualAnalysisStatus,
    automatic: VisualAnalysisStatus,
    human: HumanVisualStatus,
    lineage_verified: bool,
) -> ProductionGateStatus:
    return (
        ProductionGateStatus.ALLOWED
        if (
            technical == VisualAnalysisStatus.PASSED
            and automatic == VisualAnalysisStatus.PASSED
            and human == HumanVisualStatus.APPROVED
            and lineage_verified
        )
        else ProductionGateStatus.BLOCKED
    )


def report_payload(report: VisualContinuityReport) -> dict[str, object]:
    return {
        **report.model_dump(exclude={"metrics_json", "rejection_reasons_json"}),
        "metrics": provider_management.loads_dict(report.metrics_json),
        "rejection_reasons": provider_management.loads_list(report.rejection_reasons_json),
    }


def analyze_cross_shot_seam(
    *,
    tail_frame: Path,
    next_first_frame: Path,
    render_before: Path,
    render_after: Path,
    lineage_verified: bool,
    remote_last_frame_used: bool,
    config: VisualContinuityConfig | None = None,
) -> dict[str, object]:
    active = config or VisualContinuityConfig()
    lineage_metric = compare_images(tail_frame, next_first_frame)
    render_metric = compare_images(render_before, render_after)
    lineage_status = match_status(
        lineage_metric,
        ssim_threshold=active.cross_shot_ssim_threshold,
        phash_threshold=active.cross_shot_phash_distance_threshold,
    )
    render_status = match_status(
        render_metric,
        ssim_threshold=active.cross_shot_ssim_threshold,
        phash_threshold=active.cross_shot_phash_distance_threshold,
    )
    seam_status = (
        "FAILED"
        if not lineage_verified or remote_last_frame_used
        else ("PASSED" if lineage_status == "PASSED" and render_status == "PASSED" else "REVIEW")
    )
    return {
        "lineageSource": "LOCAL_FFMPEG_TAIL_FRAME" if lineage_verified else "UNVERIFIED",
        "remoteLastFrameUsed": remote_last_frame_used,
        "lineageVerified": lineage_verified,
        "lineageMetrics": asdict(lineage_metric),
        "renderBoundaryMetrics": asdict(render_metric),
        "lineageMatchStatus": lineage_status,
        "renderBoundaryStatus": render_status,
        "seamStatus": seam_status,
    }


def _asset(session: Session, asset_id: int, *allowed: AssetType) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or asset.type not in allowed:
        raise AppError(
            "VISUAL_ASSET_INVALID", "Visual-analysis Asset is missing or has the wrong type.", 409
        )
    return asset


def _optional_asset(session: Session, asset_id: int | None) -> Asset | None:
    return session.get(Asset, asset_id) if asset_id is not None else None


def _match(metric: FrameMetric | None, threshold: Decimal, phash: int) -> str:
    return (
        match_status(metric, ssim_threshold=threshold, phash_threshold=phash)
        if metric is not None
        else "INCONCLUSIVE"
    )


def _metric_payload(metric: FrameMetric | None, status: str) -> dict[str, object]:
    return {"status": status, "metrics": asdict(metric) if metric is not None else None}


def _inconclusive_camera() -> dict[str, object]:
    return {
        "cameraStatus": "INCONCLUSIVE",
        "compositionStatus": "INCONCLUSIVE",
        "subjectScaleStatus": "INCONCLUSIVE",
        "confidence": 0,
    }


def _overall(automatic: VisualAnalysisStatus, human: HumanVisualStatus) -> VisualAnalysisStatus:
    if human == HumanVisualStatus.REJECTED or automatic == VisualAnalysisStatus.FAILED:
        return VisualAnalysisStatus.FAILED
    if human == HumanVisualStatus.APPROVED and automatic == VisualAnalysisStatus.PASSED:
        return VisualAnalysisStatus.PASSED
    return VisualAnalysisStatus.INCONCLUSIVE
