from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session  # noqa: E402
from app.db import engine  # noqa: E402
from app.services.visual_regeneration import build_plan_only, save_draft  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline visual regeneration PlanOnly")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--max-billing-units", type=Decimal, default=Decimal("190"))
    parser.add_argument("--pricing-snapshot-hash")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--save-draft", action="store_true")
    args = parser.parse_args()
    if not args.plan_only:
        raise SystemExit("PLAN_ONLY_REQUIRED")
    with Session(engine) as session:
        plan = build_plan_only(session, project_id=args.project_id, source_run_id=args.source_run_id, strategy=args.strategy, maximum_billing_units=args.max_billing_units)
        if args.pricing_snapshot_hash and args.pricing_snapshot_hash != plan["pricingSnapshotHash"]:
            plan["status"] = "BLOCKED"; plan["readyForHumanReview"] = False; plan["blockedReasons"].append("PRICING_SNAPSHOT_MISMATCH")
        if args.save_draft:
            saved = save_draft(session, plan); plan["savedDraftId"] = saved.id; plan["databaseUpdated"] = True
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
