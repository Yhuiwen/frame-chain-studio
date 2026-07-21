from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pricing-snapshot-hash", required=True)
    parser.add_argument("--required-billing-units", required=True)
    args = parser.parse_args()
    note = (
        "LOCAL_OPERATOR confirmed readiness using the read-only TOAPIS token balance endpoint "
        f"for pricing snapshot {args.pricing_snapshot_hash} and a required ceiling of "
        f"{args.required_billing_units} TOAPIS_CREDIT."
    )
    payload = {
        "acknowledged": True, "sufficient": True, "note": note,
        "evidence_type": "TOKEN_BALANCE_READ_ONLY",
        "pricing_snapshot_hash": args.pricing_snapshot_hash,
        "confirmed_billing_units": args.required_billing_units,
    }
    with TestClient(app) as client:
        response = client.post("/api/provider-profiles/toapis/account-balance-review", json=payload)
    if response.status_code != 200:
        print("ACCOUNT_BALANCE_REVIEW_FAILED", file=sys.stderr)
        return 1
    print(json.dumps(response.json(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
