from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
import sqlite3

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "backend" / "data" / "frame_chain.db"
EXPECTED_HASH = "6debc7c7a4995a1eefc7f055f11fe3ab5e06af0403628809619cf4143800d8b8"


def parsed(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--billing-unit", required=True)
    parser.add_argument("--max-billing-units", required=True)
    parser.add_argument("--pricing-snapshot-hash", required=True)
    parser.add_argument("--initial-anchor-path", required=True)
    args = parser.parse_args()
    checks: dict[str, bool] = {}
    maximum = Decimal(args.max_billing_units)
    checks["secretVisible"] = bool(os.getenv("TOAPIS_API_KEY"))
    checks["billingUnitValid"] = args.billing_unit == "TOAPIS_CREDIT"
    checks["maximumBillingUnitsValid"] = maximum == Decimal("190")
    checks["pricingHashInputValid"] = args.pricing_snapshot_hash == EXPECTED_HASH
    anchor = (ROOT / args.initial_anchor_path).resolve() if not Path(args.initial_anchor_path).is_absolute() else Path(args.initial_anchor_path)
    try:
        with Image.open(anchor) as image:
            image.load()
            checks["initialAnchorValid"] = image.width > 0 and image.height > 0 and image.mode in {"RGB", "RGBA"}
    except Exception:
        checks["initialAnchorValid"] = False
    with sqlite3.connect(DB) as connection:
        connection.row_factory = sqlite3.Row
        profile = connection.execute("SELECT * FROM providerprofile WHERE provider_key='toapis'").fetchone()
        models = connection.execute("SELECT * FROM providermodelprofile WHERE provider_profile_id=?", (profile["id"],)).fetchall()
        checks["modelsAccessible"] = bool(profile["preflight_image_model_accessible"] and profile["preflight_video_model_accessible"])
        checks["pricingReviewed"] = len(models) == 2 and all(row["pricing_review_status"] == "REVIEWED" for row in models)
        checks["pricingHashMatched"] = all(row["pricing_snapshot_hash"] == EXPECTED_HASH for row in models)
        checks["pricingFresh"] = all(parsed(row["pricing_reviewed_at"]) and parsed(row["pricing_reviewed_at"]) >= datetime.now(timezone.utc) - timedelta(days=7) for row in models)
        balance_time = parsed(profile["account_balance_reviewed_at"])
        checks["balanceReviewValid"] = bool(
            profile["account_balance_sufficient"] and balance_time
            and balance_time >= datetime.now(timezone.utc) - timedelta(hours=24)
            and profile["account_balance_pricing_snapshot_hash"] == EXPECTED_HASH
            and Decimal(profile["account_balance_confirmed_units"] or "0") >= maximum
        )
        checks["liveDisabled"] = not bool(profile["live_orchestration_enabled"])
        checks["noActiveRuns"] = connection.execute("SELECT COUNT(*) FROM providerverificationrun WHERE status IN ('PENDING','RUNNING')").fetchone()[0] == 0
        checks["noUnfinishedTasks"] = connection.execute("SELECT COUNT(*) FROM generationtask WHERE provider_id='toapis' AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED','STALE_RESULT')").fetchone()[0] == 0
        checks["imageCanaryPassed"] = connection.execute("SELECT COUNT(*) FROM providerverificationrun WHERE verification_type='LIVE_CANARY' AND status='PASSED'").fetchone()[0] >= 1
        video = connection.execute("SELECT actual_cost FROM providerverificationrun WHERE id=4 AND verification_type='LIVE_VIDEO_CANARY' AND status='PASSED'").fetchone()
        checks["videoCanaryPassed"] = video is not None
        checks["videoBillingConsoleReviewed"] = bool(video and video["actual_cost"] is not None)
        asset80 = connection.execute("SELECT * FROM asset WHERE id=80").fetchone()
        asset81 = connection.execute("SELECT * FROM asset WHERE id=81").fetchone()
        checks["videoAssetVerified"] = bool(asset80 and asset80["sha256"] == "6d2adedbf02ee4965a289722fbcded199ba7f84e3386cecd2aca27a914c31b43" and asset80["frame_count"] == 25)
        checks["tailAssetVerified"] = bool(asset81 and asset81["source_asset_id"] == 80 and asset81["sha256"] == "8b08a871e8f639ed05a7a6a4e32d46b35a10381acb0d22ab6fc8ff285aca161e")
    for key, value in checks.items():
        print(f"{key}={str(value).lower()}")
    for line in (
        "imageRequests=2", "videoRequests=2", "videoDurationSecondsEach=4", "totalVideoSeconds=8",
        "imageBilling=12.6", "videoBilling=160", "estimatedBillingUnits=172.6",
        f"maximumBillingUnits={maximum}", "billingUnit=TOAPIS_CREDIT", "audio=false",
        "resolution=720p", "autoApprovalMeaning=WORKFLOW_VERIFICATION_APPROVAL",
    ):
        print(line)
    print(f"ready={str(all(checks.values())).lower()}")
    print("networkCalled=false")
    print("databaseUpdated=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
