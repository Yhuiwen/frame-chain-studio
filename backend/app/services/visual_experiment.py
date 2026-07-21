from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from sqlmodel import Session, select

from app.core.errors import AppError
from app.domain.visual_prompt_contract import MotionDelta, VisualPromptContract
from app.models.entities import (
    Asset,
    ProjectVisualBaseline,
    VisualExperimentAuthorizationPackage,
    utcnow,
)
from app.services.toapis_pricing import TOAPIS_PRICING_CONTRACT
from app.services.visual_regeneration import (
    STRATEGY_A,
    STRATEGY_B,
    build_plan_only,
    compile_prompts,
    project_22_contract,
)

SHORT = "SHORT_CONTINUITY_CANARY"
FULL = "FULL_CONTINUITY_RETEST"
BASELINE_VERSION = "project-visual-baseline-v1"


def _stable_hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def production_contracts() -> tuple[dict[str, Any], dict[str, Any]]:
    shot1 = project_22_contract().model_copy(
        update={
            "motion": MotionDelta(
                **{
                    "starting_pose": "robot standing beside the stationary blue cube, facing forward",
                    "ending_pose": "robot slowly turns only its head toward the blue cube",
                    "allowed_motion": "small slow head rotation with minimal natural torso follow",
                    "maximum_position_change": "3 percent of frame width",
                    "maximum_scale_change": "2 percent",
                    "forbidden_motion": [
                        "walking",
                        "leg lift",
                        "large lean",
                        "camera movement",
                        "zoom",
                        "scene cut",
                        "style shift",
                    ],
                }
            )
        }
    )
    shot2 = shot1.inherit_for_next_shot(
        shot1.motion.model_copy(
            update={
                "starting_pose": "local FFmpeg tail of new Shot 1; robot looking at cube",
                "ending_pose": "near arm slowly raises slightly toward the stationary cube",
                "allowed_motion": "small slow single-arm motion only",
                "forbidden_motion": [
                    "walking",
                    "body turn",
                    "distance jump",
                    "subject scaling",
                    "cube movement",
                    "scene cut",
                    "camera movement",
                    "style shift",
                ],
            }
        )
    )
    return shot1.stable_dict(), shot2.stable_dict()


def baseline_candidates(session: Session, project_id: int) -> list[dict[str, Any]]:
    candidates = []
    for asset_id in (82, 83, 89, 87, 93):
        asset = session.get(Asset, asset_id)
        if (
            asset is None
            or asset.project_id != project_id
            or not asset.mime_type.startswith("image/")
        ):
            continue
        excluded = asset_id == 82
        score = 0 if excluded else (92 if asset_id in {83, 89} else 72)
        candidates.append(
            {
                "assetId": asset_id,
                "shotId": asset.shot_id,
                "width": asset.width,
                "height": asset.height,
                "aspectRatio": str(Decimal(asset.width or 0) / Decimal(asset.height or 1)),
                "automaticScore": score,
                "styleAssessment": "REJECTED_STYLE"
                if excluded
                else "THREE_DIMENSIONAL_TOY_CANDIDATE",
                "exclusionReasons": ["FLAT_CARTOON_ANCHOR", "PRODUCTION_BASELINE_FORBIDDEN"]
                if excluded
                else [],
                "metrics": {
                    "characterProportion": "HUMAN_REVIEW_REQUIRED",
                    "materialColor": "HUMAN_REVIEW_REQUIRED",
                    "cubeShapeColor": "HUMAN_REVIEW_REQUIRED",
                    "cameraComposition": "HUMAN_REVIEW_REQUIRED",
                    "backgroundLightingShadow": "HUMAN_REVIEW_REQUIRED",
                    "textWatermarkExtraSubject": "HUMAN_REVIEW_REQUIRED",
                },
            }
        )
    return candidates


def baseline_hash(asset_id: int, contract: dict[str, Any]) -> str:
    return _stable_hash(
        {
            "version": BASELINE_VERSION,
            "sourceAssetId": asset_id,
            "locks": {k: contract[k] for k in ("character", "camera", "environment", "style")},
        }
    )


def create_baseline_draft(
    session: Session, *, project_id: int, source_asset_id: int, source_run_id: int = 6
) -> ProjectVisualBaseline:
    asset = session.get(Asset, source_asset_id)
    if asset is None or asset.project_id != project_id or not asset.mime_type.startswith("image/"):
        raise AppError(
            "VISUAL_BASELINE_ASSET_INVALID",
            "Baseline source must be a verified image in this project.",
            422,
        )
    if source_asset_id == 82:
        raise AppError("VISUAL_BASELINE_ASSET_EXCLUDED", "Flat cartoon Anchor 82 is excluded.", 409)
    contract, _ = production_contracts()
    value_hash = baseline_hash(source_asset_id, contract)
    existing = session.exec(
        select(ProjectVisualBaseline).where(
            ProjectVisualBaseline.project_id == project_id,
            ProjectVisualBaseline.baseline_hash == value_hash,
        )
    ).first()
    if existing:
        return existing
    baseline = ProjectVisualBaseline(
        project_id=project_id,
        source_asset_id=source_asset_id,
        source_run_id=source_run_id,
        source_shot_id=asset.shot_id,
        baseline_version=BASELINE_VERSION,
        baseline_hash=value_hash,
        status="READY_FOR_REVIEW",
        character_lock_json=json.dumps(contract["character"], ensure_ascii=False),
        camera_lock_json=json.dumps(contract["camera"], ensure_ascii=False),
        environment_lock_json=json.dumps(contract["environment"], ensure_ascii=False),
        style_lock_json=json.dumps(contract["style"], ensure_ascii=False),
        forbidden_changes_json=json.dumps(
            ["flat cartoon", "character redesign", "camera cut", "style shift"]
        ),
        automatic_metrics_json=json.dumps(
            {"sourceAssetId": source_asset_id, "automaticApproval": False}
        ),
        human_review_status="PENDING",
    )
    session.add(baseline)
    session.commit()
    session.refresh(baseline)
    return baseline


def review_baseline(
    session: Session, *, baseline_id: int, expected_hash: str, decision: str, comment: str = ""
) -> ProjectVisualBaseline:
    baseline = session.get(ProjectVisualBaseline, baseline_id)
    if baseline is None:
        raise AppError("VISUAL_BASELINE_NOT_FOUND", "Baseline not found.", 404)
    if baseline.baseline_hash != expected_hash:
        raise AppError("VISUAL_BASELINE_HASH_CONFLICT", "Baseline changed; refresh review.", 409)
    if decision not in {"APPROVED", "REJECTED"}:
        raise AppError(
            "VISUAL_BASELINE_DECISION_INVALID", "Decision must be APPROVED or REJECTED.", 422
        )
    if decision == "APPROVED":
        active = session.exec(
            select(ProjectVisualBaseline).where(
                ProjectVisualBaseline.project_id == baseline.project_id,
                ProjectVisualBaseline.status == "APPROVED",
                ProjectVisualBaseline.id != baseline.id,
            )
        ).all()
        for old in active:
            old.status = "SUPERSEDED"
            old.superseded_by_id = baseline.id
            old.updated_at = utcnow()
            session.add(old)
        baseline.approved_at = utcnow()
    baseline.status = decision
    baseline.human_review_status = decision
    baseline.human_review_comment = comment
    baseline.updated_at = utcnow()
    session.add(baseline)
    session.commit()
    session.refresh(baseline)
    return baseline


def build_authorization_plan_only(
    session: Session,
    *,
    project_id: int,
    source_run_id: int,
    candidate: str,
    selected_baseline_asset_id: int | None = None,
) -> dict[str, Any]:
    if candidate not in {SHORT, FULL}:
        raise AppError("VISUAL_EXPERIMENT_CANDIDATE_INVALID", "Unsupported candidate.", 422)
    minimum = build_plan_only(
        session, project_id=project_id, source_run_id=source_run_id, strategy=STRATEGY_A
    )
    plan = build_plan_only(
        session, project_id=project_id, source_run_id=source_run_id, strategy=STRATEGY_B
    )
    duration = 2 if candidate == SHORT else 4
    total_seconds = duration * 2
    image_billing = TOAPIS_PRICING_CONTRACT.image.price * 2
    video_billing = TOAPIS_PRICING_CONTRACT.video.price * Decimal(total_seconds)
    estimated = image_billing + video_billing
    maximum = Decimal("110") if candidate == SHORT else Decimal("190")
    contracts = production_contracts()
    compiled = []
    for contract in contracts:
        parsed = VisualPromptContract.model_validate(contract)
        compiled.append(
            {
                "image": compile_prompts(parsed, generation_kind="IMAGE"),
                "video": compile_prompts(parsed, generation_kind="VIDEO"),
            }
        )
    selected = next(
        (
            x
            for x in baseline_candidates(session, project_id)
            if x["assetId"] == selected_baseline_asset_id and not x["exclusionReasons"]
        ),
        None,
    )
    selected_hash = baseline_hash(selected["assetId"], contracts[0]) if selected else None
    core = {
        "projectId": project_id,
        "sourceRunId": source_run_id,
        "candidateType": candidate,
        "selectedRegenerationPlanHash": plan["regenerationPlanHash"],
        "selectedBaselineAssetId": selected_baseline_asset_id if selected else None,
        "baselineHash": selected_hash,
        "promptContractHash": plan["promptContractHash"],
        "compiledImagePromptHashes": [x["image"]["promptHash"] for x in compiled],
        "compiledVideoPromptHashes": [x["video"]["promptHash"] for x in compiled],
        "targetShotIds": [62, 63],
        "imageSubmitLimit": 2,
        "videoSubmitLimit": 2,
        "videoDurationSecondsEach": duration,
        "maximumTotalVideoSeconds": total_seconds,
        "estimatedBillingUnits": str(estimated),
        "maximumBillingUnits": str(maximum),
        "billingUnit": "TOAPIS_CREDIT",
        "pricingSnapshotHash": TOAPIS_PRICING_CONTRACT.snapshot_hash(),
        "visualAnalysisVersion": "visual-continuity-v1",
        "visualGateConfigHash": plan["configHash"],
    }
    experiment_hash = _stable_hash(core)
    return {
        **core,
        "experimentPlanHash": experiment_hash,
        "baselineCandidates": baseline_candidates(session, project_id),
        "baselineHumanReviewStatus": "PENDING",
        "planHumanReviewStatus": "PENDING",
        "authorizationStatus": "BLOCKED",
        "minimumCostRepairStatus": minimum["status"],
        "regenerationPlanStatus": plan["status"],
        "recommendedCandidate": SHORT,
        "humanCandidateDecision": "PENDING",
        "promptContracts": {"shot1": contracts[0], "shot2": contracts[1]},
        "compiledPrompts": compiled,
        "imageRequests": 2,
        "videoRequests": 2,
        "totalVideoSeconds": total_seconds,
        "estimatedImageBilling": str(image_billing),
        "estimatedVideoBilling": str(video_billing),
        "pricingReviewed": plan["pricingReviewed"],
        "pricingFresh": plan["pricingFresh"],
        "balanceReviewValid": False,
        "modelAccessValid": False,
        "readyForExplicitAuthorization": False,
        "readyForPaidExecution": False,
        "networkCalled": False,
        "databaseUpdated": False,
    }


def save_package_draft(
    session: Session, payload: dict[str, Any]
) -> VisualExperimentAuthorizationPackage:
    existing = session.exec(
        select(VisualExperimentAuthorizationPackage).where(
            VisualExperimentAuthorizationPackage.experiment_plan_hash
            == payload["experimentPlanHash"]
        )
    ).first()
    if existing:
        return existing
    item = VisualExperimentAuthorizationPackage(
        project_id=payload["projectId"],
        source_run_id=payload["sourceRunId"],
        candidate_type=payload["candidateType"],
        visual_baseline_id=None,
        baseline_hash=payload["baselineHash"],
        prompt_contract_hash=payload["promptContractHash"],
        compiled_prompt_hashes_json=json.dumps(
            {
                "image": payload["compiledImagePromptHashes"],
                "video": payload["compiledVideoPromptHashes"],
            }
        ),
        regeneration_plan_hash=payload["selectedRegenerationPlanHash"],
        experiment_plan_hash=payload["experimentPlanHash"],
        video_duration_seconds_each=payload["videoDurationSecondsEach"],
        maximum_total_video_seconds=payload["maximumTotalVideoSeconds"],
        estimated_billing_units=payload["estimatedBillingUnits"],
        maximum_billing_units=payload["maximumBillingUnits"],
        pricing_snapshot_hash=payload["pricingSnapshotHash"],
        pricing_reviewed=payload["pricingReviewed"],
        authorization_status="BLOCKED",
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
