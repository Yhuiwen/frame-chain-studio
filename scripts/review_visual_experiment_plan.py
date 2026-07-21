from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session
from app.db import engine
from app.services.visual_experiment import approve_short_plan, build_authorization_plan_only

parser = argparse.ArgumentParser()
parser.add_argument("--project-id", type=int, required=True)
parser.add_argument("--candidate", required=True)
parser.add_argument("--expected-regeneration-plan-hash", required=True)
parser.add_argument("--expected-baseline-hash", required=True)
parser.add_argument("--expected-experiment-plan-hash", required=True)
parser.add_argument("--selected-baseline-asset-id", type=int, required=True)
for name in (
    "plan-review",
    "run6-failures",
    "prompt-contract",
    "motion-delta",
    "task-limits",
    "estimated-billing",
    "no-paid-execution",
):
    parser.add_argument(f"--acknowledge-{name}", action="store_true")
parser.add_argument("--comment", default="")
args = parser.parse_args()
acks = (
    args.acknowledge_plan_review,
    args.acknowledge_run6_failures,
    args.acknowledge_prompt_contract,
    args.acknowledge_motion_delta,
    args.acknowledge_task_limits,
    args.acknowledge_estimated_billing,
    args.acknowledge_no_paid_execution,
)
with Session(engine) as session:
    payload = build_authorization_plan_only(
        session,
        project_id=args.project_id,
        source_run_id=6,
        candidate=args.candidate,
        selected_baseline_asset_id=args.selected_baseline_asset_id,
    )
    item = approve_short_plan(
        session,
        payload,
        expected_regeneration_hash=args.expected_regeneration_plan_hash,
        expected_baseline_hash=args.expected_baseline_hash,
        expected_experiment_hash=args.expected_experiment_plan_hash,
        acknowledgements=acks,
        comment=args.comment,
    )
    print(
        json.dumps(
            {
                "packageId": item.id,
                "candidateDecision": item.candidate_type,
                "planHumanReviewStatus": item.human_plan_review_status,
                "authorizationStatus": item.authorization_status,
                "experimentPlanHash": item.experiment_plan_hash,
                "readyForPaidExecution": False,
            },
            indent=2,
        )
    )
