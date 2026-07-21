from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session  # noqa: E402
from app.db import engine  # noqa: E402
from app.services.visual_experiment import build_authorization_plan_only, save_package_draft  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--project-id", type=int, required=True)
parser.add_argument("--source-run-id", type=int, required=True)
parser.add_argument(
    "--candidate", choices=["SHORT_CONTINUITY_CANARY", "FULL_CONTINUITY_RETEST"], required=True
)
parser.add_argument("--plan-only", action="store_true", required=True)
parser.add_argument("--selected-baseline-asset-id", type=int)
parser.add_argument("--save-draft", action="store_true")
args = parser.parse_args()
with Session(engine) as session:
    result = build_authorization_plan_only(
        session,
        project_id=args.project_id,
        source_run_id=args.source_run_id,
        candidate=args.candidate,
        selected_baseline_asset_id=args.selected_baseline_asset_id,
    )
    if args.save_draft:
        saved = save_package_draft(session, result)
        result["savedDraftId"] = saved.id
        result["databaseUpdated"] = True
print(json.dumps(result, ensure_ascii=False, indent=2))
