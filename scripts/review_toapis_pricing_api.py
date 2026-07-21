from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.main import app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pricing-version", required=True)
    parser.add_argument("--image-price", required=True)
    parser.add_argument("--image-unit", required=True)
    parser.add_argument("--video-price", required=True)
    parser.add_argument("--video-unit", required=True)
    parser.add_argument("--billing-unit", required=True)
    parser.add_argument("--image-model", required=True)
    parser.add_argument("--video-model", required=True)
    parser.add_argument("--contract-reference", required=True)
    args = parser.parse_args()
    payload = {
        "acknowledged": True,
        "pricing_version": args.pricing_version,
        "image_price": args.image_price,
        "image_unit": args.image_unit,
        "video_price": args.video_price,
        "video_unit": args.video_unit,
        "billing_unit": args.billing_unit,
        "image_model": args.image_model,
        "video_model": args.video_model,
        "pricing_source_kind": "OFFICIAL_PUBLIC_MODEL_GUIDE",
        "contract_reference": args.contract_reference,
    }
    with TestClient(app) as client:
        response = client.post("/api/provider-profiles/toapis/pricing-review", json=payload)
    if response.status_code != 200:
        error = response.json()
        detail = error.get("error", {}) if isinstance(error, dict) else {}
        print(str(detail.get("code") or "PRICING_REVIEW_FAILED"), file=sys.stderr)
        return 1
    print(json.dumps(response.json(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
