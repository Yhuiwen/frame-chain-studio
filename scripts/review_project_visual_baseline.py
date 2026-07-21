from __future__ import annotations

# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import Session  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.db import engine  # noqa: E402
from app.models.entities import Asset  # noqa: E402
from app.services.visual_experiment import (
    baseline_hash,
    create_baseline_draft,
    production_contracts,
    review_baseline,
)  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--project-id", type=int, required=True)
parser.add_argument("--selected-baseline-asset-id", type=int, required=True)
parser.add_argument("--expected-source-review-status", required=True)
parser.add_argument("--expected-baseline-draft-hash", required=True)
parser.add_argument("--acknowledge-baseline-review", action="store_true")
parser.add_argument("--acknowledge-three-dimensional-toy-style", action="store_true")
parser.add_argument("--acknowledge-character-consistency", action="store_true")
parser.add_argument("--acknowledge-camera-and-environment", action="store_true")
parser.add_argument("--acknowledge-no-text-logo-watermark", action="store_true")
parser.add_argument("--comment", default="")
args = parser.parse_args()
acks = [
    args.acknowledge_baseline_review,
    args.acknowledge_three_dimensional_toy_style,
    args.acknowledge_character_consistency,
    args.acknowledge_camera_and_environment,
    args.acknowledge_no_text_logo_watermark,
]
if not all(acks):
    raise AppError(
        "BASELINE_REVIEW_NOT_ACKNOWLEDGED", "All baseline acknowledgements are required.", 409
    )
if args.expected_source_review_status != "PENDING":
    raise AppError(
        "BASELINE_SOURCE_STATUS_MISMATCH", "Expected source review status must be PENDING.", 409
    )
with Session(engine) as session:
    asset = session.get(Asset, args.selected_baseline_asset_id)
    if asset is None or not asset.sha256:
        raise AppError("VISUAL_BASELINE_ASSET_INVALID", "Asset or SHA missing.", 422)
    expected = baseline_hash(asset.id, asset.sha256, production_contracts()[0])
    if expected != args.expected_baseline_draft_hash:
        raise AppError("BASELINE_HASH_MISMATCH", "Baseline draft hash mismatch.", 409)
    draft = create_baseline_draft(session, project_id=args.project_id, source_asset_id=asset.id)
    if draft.human_review_status not in {"PENDING", "APPROVED"}:
        raise AppError("BASELINE_SOURCE_STATUS_MISMATCH", "Baseline is not reviewable.", 409)
    approved = review_baseline(
        session,
        baseline_id=draft.id,
        expected_hash=expected,
        decision="APPROVED",
        comment=args.comment,
        acknowledged=True,
    )
    print(
        json.dumps(
            {
                "selectedBaselineAssetId": asset.id,
                "selectedBaselineAssetSha": asset.sha256,
                "baselineVersion": approved.baseline_version,
                "baselineHash": approved.baseline_hash,
                "baselineHumanReviewStatus": approved.human_review_status,
                "reviewSource": approved.review_source,
            },
            indent=2,
        )
    )
