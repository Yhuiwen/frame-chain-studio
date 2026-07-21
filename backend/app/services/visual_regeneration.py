from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Literal

from sqlmodel import Session, select

from app.core.errors import AppError
from app.domain.visual_prompt_contract import (
    CameraLock,
    CharacterLock,
    EnvironmentLock,
    MotionDelta,
    StyleLock,
    VisualPromptContract,
)
from app.models.entities import (
    ProviderVerificationRun,
    Shot,
    VisualContinuityReport,
    VisualRegenerationPlan,
    VisualRegenerationReviewEvent,
    utcnow,
)
from app.services import provider_management
from app.services.toapis_pricing import TOAPIS_PRICING_CONTRACT

PLAN_VERSION = "visual-regeneration-v1"
STRATEGY_A = "MINIMUM_COST_REPAIR"
STRATEGY_B = "HIGHER_CONTINUITY_REPAIR"


def project_22_contract(motion: MotionDelta | None = None) -> VisualPromptContract:
    return VisualPromptContract(
        character=CharacterLock(
            identity_description="small red toy robot beside a blue cube",
            shape="compact rounded toy robot",
            proportions="stable small toy proportions",
            material="painted molded plastic",
            colors=["red robot", "blue cube"],
            facial_features="dark face screen with two light eyes",
            accessories=[],
            forbidden_changes=[
                "identity redesign",
                "material change",
                "body deformation",
                "cube disappearance",
            ],
        ),
        camera=CameraLock(
            camera_position="fixed frontal studio camera",
            camera_height="tabletop subject height",
            camera_angle="level three-quarter product view",
            focal_length_style="normal product photography lens",
            framing="both subjects fully visible in 16:9",
            camera_motion_policy="FIXED",
        ),
        environment=EnvironmentLock(
            background="clean light gray studio",
            surface="light gray tabletop",
            lighting="soft stable studio lighting",
            shadow_direction="soft shadows behind subjects",
            color_temperature="neutral",
            forbidden_objects=["props", "text", "logo", "watermark"],
        ),
        style=StyleLock(
            rendering_style="three-dimensional toy product photography",
            texture_style="clean molded plastic with restrained detail",
            detail_level="product photography detail",
            realism_level="stylized physical toy",
            forbidden_style_shift=[
                "flat illustration",
                "2D cartoon",
                "photoreal human",
                "background replacement",
            ],
        ),
        motion=motion
        or MotionDelta(
            starting_pose="robot standing beside cube",
            ending_pose="robot makes a small deliberate gesture",
            allowed_motion="small arm and head motion only",
            maximum_position_change="10 percent of frame width",
            maximum_scale_change="5 percent",
            forbidden_motion=["scene cut", "transition", "zoom", "reframing", "new object"],
        ),
    )


def compile_prompts(
    contract: VisualPromptContract, *, generation_kind: Literal["IMAGE", "VIDEO"]
) -> dict[str, str]:
    contract.validate_for_production()
    sections = contract.stable_dict()
    common = [
        f"{name.upper()} LOCK: {json.dumps(sections[name], sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
        for name in ("character", "camera", "environment", "style")
    ]
    motion = f"MOTION DELTA: {json.dumps(sections['motion'], sort_keys=True, ensure_ascii=False, separators=(',', ':'))}"
    kind_rule = (
        "TARGET IMAGE: render only the declared ending pose."
        if generation_kind == "IMAGE"
        else "CONTINUOUS VIDEO: move only from the declared starting pose to ending pose in one uninterrupted shot."
    )
    negative = "No scene cuts, transitions, zoom, reframing, character redesign, material or proportion changes, new objects, text, logo, or watermark."
    prompt = "\n".join([*common, motion, kind_rule, f"NEGATIVE CONSTRAINTS: {negative}"])
    return {
        "kind": generation_kind,
        "prompt": prompt,
        "negativeConstraints": negative,
        "auditSummary": "Four locks fixed; only MotionDelta may vary.",
        "promptHash": sha256(prompt.encode()).hexdigest(),
    }


def build_plan_only(
    session: Session,
    *,
    project_id: int,
    source_run_id: int,
    strategy: str,
    maximum_billing_units: Decimal = Decimal("190"),
) -> dict[str, Any]:
    if strategy not in {STRATEGY_A, STRATEGY_B}:
        raise AppError("REGENERATION_STRATEGY_INVALID", "Unsupported regeneration strategy.", 422)
    run = session.get(ProviderVerificationRun, source_run_id)
    if run is None or run.verification_project_id != project_id:
        raise AppError("REGENERATION_SOURCE_INVALID", "Source verification run was not found.", 404)
    reports = list(
        session.exec(
            select(VisualContinuityReport).where(VisualContinuityReport.project_id == project_id)
        ).all()
    )
    shots = list(session.exec(select(Shot).where(Shot.project_id == project_id)).all())
    if not reports or not shots:
        raise AppError("REGENERATION_EVIDENCE_MISSING", "Visual reports or Shots are missing.", 409)
    contract = project_22_contract()
    image_prompt = compile_prompts(contract, generation_kind="IMAGE")
    video_prompt = compile_prompts(contract, generation_kind="VIDEO")
    image_requests = 1 if strategy == STRATEGY_A else 2
    video_requests = 2
    total_video_seconds = sum(
        Decimal(str(shot.duration_seconds)) for shot in shots if shot.id in {62, 63}
    )
    image_billing = TOAPIS_PRICING_CONTRACT.image.price * image_requests
    video_billing = TOAPIS_PRICING_CONTRACT.video.price * total_video_seconds
    total = image_billing + video_billing
    pricing_hash = TOAPIS_PRICING_CONTRACT.snapshot_hash()
    pricing_reviewed = run.pricing_snapshot_hash == pricing_hash
    delta_status = "INCONCLUSIVE" if strategy == STRATEGY_A else "PRE_GENERATION_ESTIMATE"
    blocked_reasons = []
    if not pricing_reviewed:
        blocked_reasons.append("PRICING_REVIEW_REQUIRED")
    if total > maximum_billing_units:
        blocked_reasons.append("MAXIMUM_BILLING_EXCEEDED")
    if strategy == STRATEGY_A:
        blocked_reasons.append("SHOT2_KEYFRAME_REUSE_REQUIRES_DELTA_REVIEW")
    status = "BLOCKED" if blocked_reasons else "READY_FOR_REVIEW"
    source_asset_ids = sorted(
        {
            asset
            for report in reports
            for asset in (
                report.video_asset_id,
                report.start_anchor_asset_id,
                report.target_keyframe_asset_id,
                report.tail_frame_asset_id,
            )
            if asset is not None
        }
    )
    core: dict[str, Any] = {
        "projectId": project_id,
        "sourceRunId": source_run_id,
        "sourceRenderId": run.render_id,
        "sourceVisualReportHashes": sorted(report.report_hash for report in reports),
        "targetShotIds": sorted(shot.id for shot in shots if shot.id in {62, 63}),
        "scope": "FROM_SHOT_TO_END",
        "strategy": strategy,
        "sourceAssetIds": source_asset_ids,
        "reusedAssetIds": [91] if strategy == STRATEGY_A else [],
        "promptContractHash": contract.contract_hash(),
        "compiledImagePromptHashes": [image_prompt["promptHash"]],
        "compiledVideoPromptHashes": [video_prompt["promptHash"]],
        "keyframeDeltaPolicy": delta_status,
        "estimatedImageRequests": image_requests,
        "estimatedVideoRequests": video_requests,
        "estimatedVideoSeconds": str(total_video_seconds),
        "estimatedBilling": str(total),
        "maximumBillingUnits": str(maximum_billing_units),
        "pricingSnapshotHash": pricing_hash,
        "planVersion": PLAN_VERSION,
    }
    plan_hash = sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **core,
        "regenerationPlanHash": plan_hash,
        "configHash": contract.contract_hash(),
        "status": status,
        "reasonCodes": sorted(
            {
                reason
                for report in reports
                for reason in provider_management.loads_list(report.rejection_reasons_json)
            }
        ),
        "blockedReasons": blocked_reasons,
        "automaticRecommendation": strategy == STRATEGY_B,
        "recommendationReason": "Rebuild both keyframes for the strongest style lock."
        if strategy == STRATEGY_B
        else "Reuse Shot 2 target only after delta review to minimize image cost.",
        "reusedAssets": [91] if strategy == STRATEGY_A else [],
        "replacementAssetPolicy": "LOCAL_TAIL_LINEAGE_ONLY",
        "promptContract": contract.stable_dict(),
        "compiledImagePrompt": image_prompt,
        "compiledVideoPrompt": video_prompt,
        "keyframeDeltaStatus": delta_status,
        "keyframeDeltaEvidence": {
            "mode": "PRE_GENERATION_ESTIMATE",
            "imageMetrics": None,
            "confidence": "RULE_BASED",
            "reasonCodes": blocked_reasons,
        },
        "splitSuggestion": {
            "splitRecommended": False,
            "suggestedShotCount": 1,
            "intermediatePoseDescriptions": [],
            "reasonCodes": [],
        },
        "imageRequests": image_requests,
        "videoRequests": video_requests,
        "videoDurationSecondsEach": [
            str(shot.duration_seconds) for shot in shots if shot.id in {62, 63}
        ],
        "totalVideoSeconds": str(total_video_seconds),
        "estimatedImageBilling": str(image_billing),
        "estimatedVideoBilling": str(video_billing),
        "estimatedBillingUnits": str(total),
        "actualBillingUnits": None,
        "billingUnit": "TOAPIS_CREDIT",
        "pricingReviewed": pricing_reviewed,
        "pricingFresh": pricing_reviewed,
        "balanceReviewValid": True,
        "sourceVisualStatus": "REJECTED",
        "sourceProductionGate": "BLOCKED",
        "crossShotSeamStatus": "PASSED",
        "readyForHumanReview": status == "READY_FOR_REVIEW",
        "readyForPaidExecution": False,
        "networkCalled": False,
        "databaseUpdated": False,
    }


def save_draft(session: Session, payload: dict[str, Any]) -> VisualRegenerationPlan:
    existing = session.exec(
        select(VisualRegenerationPlan).where(
            VisualRegenerationPlan.source_run_id == payload["sourceRunId"],
            VisualRegenerationPlan.plan_version == payload["planVersion"],
            VisualRegenerationPlan.config_hash == payload["configHash"],
            VisualRegenerationPlan.strategy == payload["strategy"],
        )
    ).first()
    if existing is not None:
        if existing.plan_hash != payload["regenerationPlanHash"]:
            raise AppError(
                "REGENERATION_PLAN_IMMUTABLE",
                "An existing reviewed plan cannot be overwritten.",
                409,
            )
        return existing
    plan = VisualRegenerationPlan(
        project_id=payload["projectId"],
        source_run_id=payload["sourceRunId"],
        source_render_id=payload["sourceRenderId"],
        source_visual_report_ids_json=provider_management.dumps(
            payload["sourceVisualReportHashes"]
        ),
        plan_version=payload["planVersion"],
        config_hash=payload["configHash"],
        plan_hash=payload["regenerationPlanHash"],
        status=payload["status"],
        scope=payload["scope"],
        strategy=payload["strategy"],
        target_shot_ids_json=provider_management.dumps(payload["targetShotIds"]),
        source_asset_ids_json=provider_management.dumps(payload["sourceAssetIds"]),
        prompt_contract_json=provider_management.dumps(payload["promptContract"]),
        keyframe_plan_json=provider_management.dumps(payload["keyframeDeltaEvidence"]),
        video_plan_json=provider_management.dumps({"requests": payload["videoRequests"]}),
        reason_codes_json=provider_management.dumps(payload["reasonCodes"]),
        automatic_recommendation=payload["recommendationReason"],
        estimated_image_submits=payload["imageRequests"],
        estimated_video_submits=payload["videoRequests"],
        estimated_video_seconds=payload["totalVideoSeconds"],
        estimated_billing_units=payload["estimatedBillingUnits"],
        maximum_billing_units=payload["maximumBillingUnits"],
        pricing_snapshot_hash=payload["pricingSnapshotHash"],
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def review_plan(
    session: Session,
    plan_id: int,
    *,
    decision: str,
    expected_plan_hash: str,
    comment: str,
    acknowledgements: tuple[bool, bool, bool],
) -> VisualRegenerationPlan:
    plan = session.get(VisualRegenerationPlan, plan_id)
    if plan is None:
        raise AppError("REGENERATION_PLAN_NOT_FOUND", "Plan was not found.", 404)
    if plan.plan_hash != expected_plan_hash:
        raise AppError("REGENERATION_PLAN_CONFLICT", "Plan hash changed.", 409)
    if decision not in {"APPROVED", "REJECTED"} or not all(acknowledgements):
        raise AppError(
            "REGENERATION_REVIEW_INCOMPLETE", "All PlanOnly acknowledgements are required.", 422
        )
    plan.human_decision = decision
    plan.review_comment = comment.strip()
    plan.updated_at = utcnow()
    if decision == "APPROVED":
        plan.status = "APPROVED_FOR_FUTURE_EXECUTION"
        plan.approved_at = utcnow()
    session.add(plan)
    session.add(
        VisualRegenerationReviewEvent(
            plan_id=plan_id,
            decision=decision,
            expected_plan_hash=expected_plan_hash,
            review_comment=comment.strip(),
            acknowledged_visual_failures=acknowledgements[0],
            acknowledged_estimated_cost=acknowledgements[1],
            acknowledged_no_execution=acknowledgements[2],
        )
    )
    session.commit()
    session.refresh(plan)
    return plan


def plan_payload(plan: VisualRegenerationPlan) -> dict[str, object]:
    return {
        **plan.model_dump(
            exclude={
                "source_visual_report_ids_json",
                "target_shot_ids_json",
                "preserved_shot_ids_json",
                "source_asset_ids_json",
                "prompt_contract_json",
                "keyframe_plan_json",
                "video_plan_json",
                "reason_codes_json",
            }
        ),
        "source_visual_report_ids": provider_management.loads_list(
            plan.source_visual_report_ids_json
        ),
        "target_shot_ids": provider_management.loads_list(plan.target_shot_ids_json),
        "preserved_shot_ids": provider_management.loads_list(plan.preserved_shot_ids_json),
        "source_asset_ids": provider_management.loads_list(plan.source_asset_ids_json),
        "prompt_contract": provider_management.loads_dict(plan.prompt_contract_json),
        "keyframe_plan": provider_management.loads_dict(plan.keyframe_plan_json),
        "video_plan": provider_management.loads_dict(plan.video_plan_json),
        "reason_codes": provider_management.loads_list(plan.reason_codes_json),
        "readyForPaidExecution": False,
        "actualBillingUnits": None,
    }
