from __future__ import annotations

from hashlib import sha256
import json

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    GenerationTask,
    HumanVisualStatus,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVisualReview,
    QualityCheckResult,
    Shot,
    VisualAnalysisStatus,
    VisualContinuityReport,
    VisualReviewDecision,
    VisualReviewerSource,
)
from app.services import provider_management


REASON_CODES = frozenset(
    {
        "CHARACTER_STYLE_DRIFT",
        "CHARACTER_GEOMETRY_DRIFT",
        "FACE_IDENTITY_DRIFT",
        "MATERIAL_COLOR_DRIFT",
        "CAMERA_DISCONTINUITY",
        "COMPOSITION_DISCONTINUITY",
        "SUBJECT_POSITION_DRIFT",
        "SUBJECT_SCALE_DRIFT",
        "BACKGROUND_DRIFT",
        "LIGHTING_DRIFT",
        "UNEXPECTED_SCENE_CUT",
        "MOTION_ARTIFACT",
        "DECODE_OR_MEDIA_ISSUE",
        "OTHER",
    }
)

BLOCKER_ORDER = (
    "TECHNICAL_NOT_PASSED",
    "LINEAGE_NOT_PASSED",
    "HUMAN_VISUAL_PENDING",
    "HUMAN_VISUAL_REJECTED",
    "BLOCKING_VISUAL_EVIDENCE",
    "AUTOMATED_VISUAL_CHECK_INCOMPLETE",
    "UNEXPECTED_SCENE_CUT",
)


def get_run_or_404(session: Session, run_id: int) -> ProviderVerificationRun:
    run = session.get(ProviderVerificationRun, run_id)
    if run is None:
        raise AppError("RUN_NOT_FOUND", "Provider verification run was not found.", 404)
    return run


def selected_review_asset_id(run: ProviderVerificationRun) -> int | None:
    return run.final_render_asset_id or run.tail_frame_asset_id or run.end_frame_asset_id


def linked_asset_ids(session: Session, run: ProviderVerificationRun) -> set[int]:
    result = {
        value
        for value in (
            run.initial_anchor_asset_id,
            run.end_frame_asset_id,
            run.tail_frame_asset_id,
            run.normalized_start_asset_id,
            run.normalized_end_asset_id,
            run.reused_keyframe_asset_id,
            run.final_render_asset_id,
        )
        if value is not None
    }
    shot_ids = [value for value in (run.shot_1_id, run.shot_2_id) if value is not None]
    for shot_id in shot_ids:
        shot = session.get(Shot, shot_id)
        if shot is None:
            continue
        result.update(
            value
            for value in (
                shot.start_frame_asset_id,
                shot.approved_keyframe_asset_id,
                shot.approved_video_asset_id,
                shot.locked_tail_frame_asset_id,
            )
            if value is not None
        )
    request_ids = [
        value
        for value in (
            run.shot_1_keyframe_request_id,
            run.shot_1_video_request_id,
            run.shot_2_keyframe_request_id,
            run.shot_2_video_request_id,
        )
        if value is not None
    ]
    if request_ids:
        tasks = session.exec(
            select(GenerationTask).where(col(GenerationTask.generation_request_id).in_(request_ids))
        ).all()
        result.update(task.result_asset_id for task in tasks if task.result_asset_id is not None)
    return result


def normalize_review(
    *, decision: VisualReviewDecision, reason_codes: list[str], notes: str
) -> tuple[list[str], str]:
    normalized_notes = notes.strip()
    if len(normalized_notes) > 2000:
        raise AppError("VISUAL_REVIEW_NOTES_INVALID", "Visual review notes are too long.", 422)
    normalized_codes = sorted(set(reason_codes))
    if any(code not in REASON_CODES for code in normalized_codes):
        raise AppError(
            "VISUAL_REVIEW_REASON_INVALID", "A visual review reason code is unsupported.", 422
        )
    if decision == VisualReviewDecision.REJECTED and not normalized_codes:
        raise AppError(
            "VISUAL_REVIEW_REASON_REQUIRED", "Rejected visual reviews require a reason.", 422
        )
    if "OTHER" in normalized_codes and not normalized_notes:
        raise AppError("VISUAL_REVIEW_NOTES_REQUIRED", "OTHER requires review notes.", 422)
    return normalized_codes, normalized_notes


def create_review(
    session: Session,
    *,
    run_id: int,
    asset_id: int,
    decision: VisualReviewDecision,
    reason_codes: list[str],
    notes: str,
    idempotency_key: str | None,
) -> ProviderVisualReview:
    run = get_run_or_404(session, run_id)
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise AppError("ASSET_NOT_FOUND", "The reviewed Asset was not found.", 404)
    if asset.project_id != run.verification_project_id:
        raise AppError("ASSET_PROJECT_MISMATCH", "The Asset belongs to another project.", 409)
    if asset_id not in linked_asset_ids(session, run):
        raise AppError(
            "ASSET_NOT_LINKED_TO_RUN", "The Asset is not traceable to this verification run.", 409
        )
    if not asset.sha256:
        raise AppError("ASSET_SHA256_REQUIRED", "The reviewed Asset has no SHA-256 evidence.", 409)
    codes, normalized_notes = normalize_review(
        decision=decision, reason_codes=reason_codes, notes=notes
    )
    key = idempotency_key.strip() if idempotency_key else None
    if key is not None and (not key or len(key) > 160):
        raise AppError("IDEMPOTENCY_KEY_INVALID", "Idempotency-Key is invalid.", 422)
    core = {
        "runId": run_id,
        "assetId": asset_id,
        "assetSha256": asset.sha256,
        "decision": decision.value,
        "reasonCodes": codes,
        "notes": normalized_notes,
    }
    request_hash = sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if key:
        existing = session.exec(
            select(ProviderVisualReview).where(
                ProviderVisualReview.provider_verification_run_id == run_id,
                ProviderVisualReview.idempotency_key == key,
            )
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AppError(
                    "IDEMPOTENCY_CONFLICT",
                    "The Idempotency-Key was already used with another payload.",
                    409,
                )
            return existing
    review = ProviderVisualReview(
        project_id=asset.project_id,
        provider_verification_run_id=run_id,
        asset_id=asset_id,
        asset_sha256=asset.sha256,
        decision=decision,
        reason_codes_json=provider_management.dumps(codes),
        notes=normalized_notes,
        reviewer_source=VisualReviewerSource.HUMAN_OPERATOR,
        idempotency_key=key,
        request_hash=request_hash,
    )
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if key:
            existing = session.exec(
                select(ProviderVisualReview).where(
                    ProviderVisualReview.provider_verification_run_id == run_id,
                    ProviderVisualReview.idempotency_key == key,
                )
            ).first()
            if existing is not None and existing.request_hash == request_hash:
                return existing
        raise AppError("IDEMPOTENCY_CONFLICT", "The review request conflicted.", 409) from exc
    session.refresh(review)
    return review


def list_reviews(session: Session, run_id: int) -> list[ProviderVisualReview]:
    get_run_or_404(session, run_id)
    return list(
        session.exec(
            select(ProviderVisualReview)
            .where(ProviderVisualReview.provider_verification_run_id == run_id)
            .order_by(
                col(ProviderVisualReview.reviewed_at).desc(),
                col(ProviderVisualReview.id).desc(),
            )
        ).all()
    )


def _legacy_reports(session: Session, run: ProviderVerificationRun) -> list[VisualContinuityReport]:
    shot_ids = {value for value in (run.shot_1_id, run.shot_2_id) if value is not None}
    if not shot_ids or run.verification_project_id is None:
        return []
    reports = session.exec(
        select(VisualContinuityReport).where(
            VisualContinuityReport.project_id == run.verification_project_id,
            col(VisualContinuityReport.shot_id).in_(shot_ids),
        )
    ).all()
    valid_video_ids = {
        shot.approved_video_asset_id
        for shot_id in shot_ids
        if (shot := session.get(Shot, shot_id)) is not None
        and shot.approved_video_asset_id is not None
    }
    return [report for report in reports if report.video_asset_id in valid_video_ids]


def _lineage_status(session: Session, run: ProviderVerificationRun) -> str:
    if run.status in {
        ProviderVerificationStatus.PENDING,
        ProviderVerificationStatus.RUNNING,
    }:
        return "PENDING"
    if run.status != ProviderVerificationStatus.PASSED:
        return "BLOCKED"
    project_id = run.verification_project_id
    shot_1 = session.get(Shot, run.shot_1_id) if run.shot_1_id else None
    shot_2 = session.get(Shot, run.shot_2_id) if run.shot_2_id else None
    render = session.get(Asset, run.final_render_asset_id) if run.final_render_asset_id else None
    if not project_id or shot_1 is None or shot_2 is None or render is None:
        return "FAILED"
    tail = (
        session.get(Asset, shot_1.locked_tail_frame_asset_id)
        if shot_1.locked_tail_frame_asset_id
        else None
    )
    inherited = (
        session.get(Asset, shot_2.start_frame_asset_id) if shot_2.start_frame_asset_id else None
    )
    valid = bool(
        render.project_id == project_id
        and shot_1.project_id == project_id
        and shot_2.project_id == project_id
        and tail is not None
        and inherited is not None
        and inherited.source_asset_id == tail.id
        and inherited.project_id == project_id
        and tail.project_id == project_id
        and inherited.type == AssetType.START_FRAME
        and tail.type == AssetType.TAIL_FRAME
        and inherited.status == AssetStatus.APPROVED
        and tail.status == AssetStatus.APPROVED
        and inherited.path == tail.path
        and tail.sha256
    )
    return "PASSED" if valid else "FAILED"


def _automated_status(reports: list[VisualContinuityReport]) -> str:
    if not reports:
        return "NOT_RUN"
    statuses = {report.automatic_visual_status for report in reports}
    if VisualAnalysisStatus.FAILED in statuses:
        return "FAILED"
    if VisualAnalysisStatus.INCONCLUSIVE in statuses:
        return "WARNING"
    if VisualAnalysisStatus.PENDING in statuses:
        return "PENDING"
    return "PASSED"


def _scene_cut_summary(session: Session, run: ProviderVerificationRun) -> dict[str, object]:
    asset_ids: list[int] = []
    for shot_id in (run.shot_1_id, run.shot_2_id):
        shot = session.get(Shot, shot_id) if shot_id else None
        if shot is not None and shot.approved_video_asset_id is not None:
            asset_ids.append(shot.approved_video_asset_id)
    checks = list(
        session.exec(
            select(QualityCheckResult).where(
                col(QualityCheckResult.asset_id).in_(asset_ids or [-1]),
                QualityCheckResult.check_type == "INTRA_SHOT_SCENE_CUT",
                QualityCheckResult.algorithm_version == "scene-cut-v1",
            )
        ).all()
    )
    by_asset = {check.asset_id: check for check in checks}
    missing = sorted(asset_id for asset_id in asset_ids if asset_id not in by_asset)
    evidence = [
        provider_management.loads_dict(check.details_json)
        for check in sorted(checks, key=lambda item: (item.asset_id or 0, item.id or 0))
    ]
    hard_count = sum(int(item.get("hard_cut_count", 0)) for item in evidence)
    review_count = sum(int(item.get("review_candidate_count", 0)) for item in evidence)
    incomplete = bool(missing) or not asset_ids or any(item.get("status") == "NOT_RUN" for item in evidence)
    if incomplete:
        status = "NOT_RUN"
    elif hard_count:
        status = "FAILED"
    elif review_count:
        status = "WARNING"
    else:
        status = "PASSED"
    events = sorted(
        [
            {**event, "asset_id": item.get("asset_id")}
            for item in evidence
            for event in item.get("events", [])
            if isinstance(event, dict)
        ],
        key=lambda event: (int(event.get("asset_id") or 0), str(event.get("timestamp_seconds", ""))),
    )
    return {
        "status": status,
        "asset_ids": asset_ids,
        "algorithm_version": "scene-cut-v1",
        "hard_cut_count": hard_count,
        "review_candidate_count": review_count,
        "events": events,
        "missing_asset_ids": missing,
        "calibration_scope": "SYNTHETIC_FIXTURES_ONLY",
    }


def review_payload(review: ProviderVisualReview) -> dict[str, object]:
    return {
        **review.model_dump(exclude={"reason_codes_json", "request_hash"}),
        "reason_codes": provider_management.loads_list(review.reason_codes_json),
        "asset_url": f"/api/media/{review.asset_id}",
    }


def readiness_payload(session: Session, run_id: int) -> dict[str, object]:
    run = get_run_or_404(session, run_id)
    selected_asset_id = selected_review_asset_id(run)
    reviews = list_reviews(session, run_id)
    current = next((item for item in reviews if item.asset_id == selected_asset_id), None)
    legacy = _legacy_reports(session, run)
    legacy_rejected = any(
        report.human_visual_status == HumanVisualStatus.REJECTED for report in legacy
    )
    if current is not None:
        human = current.decision.value
    elif legacy_rejected:
        human = "REJECTED"
    else:
        human = "PENDING"
    technical = run.status.value
    lineage = _lineage_status(session, run)
    automated = _automated_status(legacy)
    scene_cut = _scene_cut_summary(session, run)
    legacy_blocking_visual = automated in {"FAILED", "WARNING"}
    if scene_cut["status"] == "FAILED":
        automated = "FAILED"
    elif scene_cut["status"] == "WARNING" and automated in {"NOT_RUN", "PASSED"}:
        automated = "WARNING"
    elif scene_cut["status"] == "PASSED" and automated == "NOT_RUN":
        automated = "PASSED"
    blockers: list[str] = []
    if technical != "PASSED":
        blockers.append("TECHNICAL_NOT_PASSED")
    if lineage != "PASSED":
        blockers.append("LINEAGE_NOT_PASSED")
    if human == "PENDING":
        blockers.append("HUMAN_VISUAL_PENDING")
    elif human == "REJECTED":
        blockers.append("HUMAN_VISUAL_REJECTED")
    if legacy_blocking_visual:
        blockers.append("BLOCKING_VISUAL_EVIDENCE")
    if scene_cut["status"] == "NOT_RUN":
        blockers.append("AUTOMATED_VISUAL_CHECK_INCOMPLETE")
    elif scene_cut["status"] == "FAILED":
        blockers.append("UNEXPECTED_SCENE_CUT")
    blockers.sort(key=BLOCKER_ORDER.index)
    selected_asset = session.get(Asset, selected_asset_id) if selected_asset_id else None
    return {
        "run_id": run_id,
        "technical_status": technical,
        "lineage_status": lineage,
        "automated_visual_status": automated,
        "human_visual_status": human,
        "production_status": "READY" if not blockers else "BLOCKED",
        "production_ready": not blockers,
        "production_blockers": blockers,
        "selected_review_asset": (
            {
                "id": selected_asset.id,
                "type": selected_asset.type,
                "sha256": selected_asset.sha256,
                "created_at": selected_asset.created_at,
                "url": f"/api/media/{selected_asset.id}",
            }
            if selected_asset is not None
            else None
        ),
        "current_visual_review": review_payload(current) if current is not None else None,
        "legacy_review_evidence": legacy_rejected,
        "legacy_review_report_ids": [report.id for report in legacy if report.id is not None],
        "legacy_reason_codes": sorted(
            {
                str(code)
                for report in legacy
                for code in provider_management.loads_list(report.rejection_reasons_json)
            }
        ),
        "workflow_approval_only": run.auto_approve_for_verification,
        "scene_cut_check": scene_cut,
    }
