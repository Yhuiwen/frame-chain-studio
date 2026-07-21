from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.services.toapis_recovery_planning import build_recovery_plan  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed-run-id", type=int, required=True)
    parser.add_argument("--billing-unit", required=True)
    parser.add_argument("--max-billing-units", required=True)
    parser.add_argument("--pricing-snapshot-hash", required=True)
    args = parser.parse_args()
    with Session(engine) as session:
        plan = build_recovery_plan(
            session,
            failed_run_id=args.failed_run_id,
            maximum_billing_units=Decimal(args.max_billing_units),
            pricing_snapshot_hash=args.pricing_snapshot_hash,
        )
    for key, value in plan.items():
        if key == "checks":
            for check, passed in value.items():
                print(f"{check}={str(passed).lower()}")
        elif isinstance(value, bool):
            print(f"{key}={str(value).lower()}")
        elif value is not None:
            print(f"{key}={value}")
    if plan.get("recoveryPlanHash"):
        print(
            "suggestedRecoveryCommand="
            "powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\e2e-real-provider.ps1 "
            f"-ConfirmLive -ExecutePaid -RecoverFailedRunId {args.failed_run_id} "
            f"-RecoveryPlanHash {plan['recoveryPlanHash']} -BillingUnit TOAPIS_CREDIT "
            f"-MaxBillingUnits {args.max_billing_units} -PricingSnapshotHash {args.pricing_snapshot_hash} "
            "-AutoApproveForVerification -PollIntervalSeconds 10 -TimeoutMinutes 45"
        )
        print("suggestedRecoveryCommandExecuted=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
