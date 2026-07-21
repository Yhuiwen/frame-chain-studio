from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--existing-remote-task-id", required=True)
    parser.add_argument("--actual-billing-units", required=True)
    args = parser.parse_args()
    payload = {
        "acknowledged": True,
        "existing_remote_task_id": args.existing_remote_task_id,
        "actual_billing_units": args.actual_billing_units,
        "billing_unit": "TOAPIS_CREDIT",
        "evidence_type": "TOAPIS_CONSOLE_REVIEW",
    }
    with TestClient(app) as client:
        response = client.post(f"/api/provider-verification-runs/{args.run_id}/video-canary-console-review", json=payload)
    if response.status_code != 200:
        print("VIDEO_CANARY_CONSOLE_REVIEW_FAILED", file=sys.stderr)
        return 1
    print(json.dumps(response.json(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
