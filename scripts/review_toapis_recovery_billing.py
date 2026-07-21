from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session  # noqa: E402
from app.db import engine  # noqa: E402
from app.services.toapis_recovery_billing import review_recovery_console_billing  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--task-review", action="append", nargs=3, metavar=("TASK_ID", "REMOTE_TASK_ID", "ACTUAL"), required=True)
    args = parser.parse_args()
    reviews = {int(task_id): (remote_id, Decimal(actual)) for task_id, remote_id, actual in args.task_review}
    with Session(engine) as session:
        result = review_recovery_console_billing(
            session, run_id=args.run_id, acknowledged=True, task_reviews=reviews,
            billing_unit="TOAPIS_CREDIT", evidence_type="TOAPIS_CONSOLE_REVIEW",
        )
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
