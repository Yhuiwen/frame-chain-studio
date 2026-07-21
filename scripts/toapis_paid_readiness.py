from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
from app.services.toapis_pricing import TOAPIS_PRICING_CONTRACT  # noqa: E402

OFFICIAL_BASE_URL = "https://toapis.com/v1"
IMAGE_MODEL = TOAPIS_PRICING_CONTRACT.image.remote_model
VIDEO_MODEL = TOAPIS_PRICING_CONTRACT.video.remote_model


def _get_json(path: str, api_key: str) -> dict[str, Any]:
    request = Request(
        f"{OFFICIAL_BASE_URL}{path}",
        method="GET",
        headers={"Authorization": f"Bearer {api_key}", "User-Agent": "frame-chain-studio-readiness/1"},
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS host
            content = response.read(2 * 1024 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("READ_ONLY_TOAPIS_REQUEST_FAILED") from exc
    if len(content) > 2 * 1024 * 1024:
        raise RuntimeError("READ_ONLY_TOAPIS_RESPONSE_TOO_LARGE")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("READ_ONLY_TOAPIS_RESPONSE_INVALID") from exc
    if not isinstance(value, dict):
        raise RuntimeError("READ_ONLY_TOAPIS_RESPONSE_INVALID")
    return value


def _database_path(repo_root: Path) -> Path:
    configured = os.getenv("FCS_DATABASE_URL", "sqlite:///./data/frame_chain.db")
    prefix = "sqlite:///"
    if not configured.startswith(prefix):
        raise RuntimeError("READINESS_REQUIRES_LOCAL_SQLITE")
    raw = Path(configured.removeprefix(prefix))
    return raw.resolve() if raw.is_absolute() else (repo_root / "backend" / raw).resolve()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def _pricing_state(connection: sqlite3.Connection, expected_hash: str) -> tuple[bool, bool, Decimal | None]:
    rows = connection.execute(
        """SELECT remote_model, pricing_json, pricing_review_status, pricing_reviewed_at,
                  pricing_snapshot_hash, pricing_version, billing_unit, pricing_source_kind,
                  pricing_source_checked_at, pricing_source_reference, pricing_assumptions_json
           FROM providermodelprofile
           WHERE remote_model IN (?, ?) ORDER BY remote_model""",
        (IMAGE_MODEL, VIDEO_MODEL),
    ).fetchall()
    if len(rows) != 2:
        return False, False, None
    matched = all(row[4] == expected_hash for row in rows) and expected_hash == TOAPIS_PRICING_CONTRACT.snapshot_hash()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    fresh = all(
        row[2] == "REVIEWED"
        and (_parse_time(row[3]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        and row[5] == TOAPIS_PRICING_CONTRACT.version
        and row[6] == TOAPIS_PRICING_CONTRACT.billing_unit
        and row[7] == TOAPIS_PRICING_CONTRACT.source_kind
        and (_parse_time(row[8]) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        for row in rows
    )
    contract_by_model = {IMAGE_MODEL: TOAPIS_PRICING_CONTRACT.image, VIDEO_MODEL: TOAPIS_PRICING_CONTRACT.video}
    for row in rows:
        contract_model = contract_by_model[row[0]]
        expected_assumptions = contract_model.assumptions.model_dump(mode="json")
        try:
            actual_assumptions = json.loads(row[10] or "{}")
        except json.JSONDecodeError:
            actual_assumptions = {}
        fresh = fresh and row[9] == contract_model.source_reference and actual_assumptions == expected_assumptions
    prices: dict[str, Decimal] = {}
    try:
        model_rows = connection.execute(
            """SELECT remote_model, pricing_json FROM providermodelprofile
               WHERE remote_model IN (?, ?)""",
            (IMAGE_MODEL, VIDEO_MODEL),
        ).fetchall()
        for model, raw in model_rows:
            rules = json.loads(raw or "{}").get("rules", [])
            wanted = "IMAGE_REQUEST" if model == IMAGE_MODEL else "VIDEO_SECOND"
            matches = [Decimal(str(rule["price"])) for rule in rules if isinstance(rule, dict) and rule.get("unit") == wanted]
            if len(matches) != 1:
                return matched, fresh, None
            prices[model] = matches[0]
    except (json.JSONDecodeError, InvalidOperation, KeyError, TypeError):
        return matched, fresh, None
    return matched, fresh, prices[IMAGE_MODEL] * 2 + prices[VIDEO_MODEL] * 8


def _credit_balance(raw: dict[str, Any]) -> tuple[bool, bool, Decimal | None]:
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if not isinstance(data, dict):
        return False, False, None
    unlimited = data.get("unlimited_quota") is True
    if unlimited:
        return True, True, None
    value = data.get("remain_credits")
    try:
        return True, False, Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return True, False, None


def _anchor_ready(repo_root: Path) -> bool:
    path = repo_root / ".run" / "toapis-verification-anchor.png"
    try:
        if path.stat().st_size >= 1024 * 1024:
            return False
        with Image.open(path) as image:
            image.load()
            return image.mode == "RGB" and image.size == (1280, 720) and not image.getexif()
    except (FileNotFoundError, UnidentifiedImageError, OSError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--billing-unit", required=True)
    parser.add_argument("--pricing-snapshot-hash", required=True)
    parser.add_argument("--max-billing-units", required=True)
    parser.add_argument("--balance-evidence-precheck", action="store_true")
    args = parser.parse_args()
    try:
        maximum = Decimal(args.max_billing_units)
    except InvalidOperation:
        maximum = Decimal("0")

    key = os.getenv("TOAPIS_API_KEY")
    process_configured = bool(key)
    models_checked = image_accessible = video_accessible = False
    token_active = token_unlimited = balance_readable = balance_sufficient = False
    model_gets = token_gets = user_gets = 0

    if key:
        try:
            models = _get_json("/models?type=all", key)
            model_gets = 1
            items = models.get("data")
            if isinstance(items, list):
                ids = {item.get("id") for item in items if isinstance(item, dict)}
                models_checked = True
                image_accessible = IMAGE_MODEL in ids
                video_accessible = VIDEO_MODEL in ids
        except RuntimeError:
            pass
        try:
            token_raw = _get_json("/balance", key)
            token_gets = 1
            token_active, token_unlimited, token_credits = _credit_balance(token_raw)
            balance_readable = token_active and (token_unlimited or token_credits is not None)
            if token_unlimited:
                balance_sufficient = True
            elif token_credits is not None:
                balance_sufficient = token_credits >= maximum
        except RuntimeError:
            pass

    repo_root = REPO_ROOT
    anchor_ready = _anchor_ready(repo_root)
    active_runs = 0
    live_enabled = False
    pricing_matched = pricing_fresh = False
    estimated: Decimal | None = None
    unfinished_tasks = 0
    balance_review_valid = False
    try:
        with sqlite3.connect(_database_path(repo_root)) as connection:
            connection.row_factory = sqlite3.Row
            profile = connection.execute(
                """SELECT id, live_orchestration_enabled, account_balance_sufficient,
                          account_balance_reviewed_at, account_balance_pricing_snapshot_hash,
                          account_balance_confirmed_units, account_balance_evidence_type
                   FROM providerprofile WHERE provider_key='toapis'"""
            ).fetchone()
            if profile:
                live_enabled = bool(profile["live_orchestration_enabled"])
                reviewed_at = _parse_time(profile["account_balance_reviewed_at"])
                try:
                    confirmed = Decimal(str(profile["account_balance_confirmed_units"]))
                except InvalidOperation:
                    confirmed = Decimal("0")
                balance_review_valid = bool(
                    profile["account_balance_sufficient"] and reviewed_at
                    and reviewed_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                    and profile["account_balance_pricing_snapshot_hash"] == args.pricing_snapshot_hash
                    and profile["account_balance_evidence_type"] == "TOKEN_BALANCE_READ_ONLY"
                    and confirmed >= maximum
                )
                active_runs = connection.execute(
                    "SELECT COUNT(*) FROM providerverificationrun WHERE provider_profile_id=? AND status IN ('PENDING','RUNNING')",
                    (profile["id"],),
                ).fetchone()[0]
            unfinished_tasks = connection.execute(
                "SELECT COUNT(*) FROM generationtask WHERE provider_id='toapis' AND status NOT IN ('SUCCEEDED','FAILED','CANCELLED','STALE_RESULT')"
            ).fetchone()[0]
            pricing_matched, pricing_fresh, estimated = _pricing_state(connection, args.pricing_snapshot_hash)
    except (OSError, sqlite3.Error, RuntimeError):
        pass

    if maximum <= TOAPIS_PRICING_CONTRACT.recommended_ceiling and maximum <= Decimal("10"):
        estimated = TOAPIS_PRICING_CONTRACT.image.price
    canary = maximum <= Decimal("10")
    ready = all(
        (
            process_configured,
            models_checked,
            image_accessible,
            canary or video_accessible,
            token_active,
            balance_readable,
            balance_sufficient,
            args.billing_unit == "TOAPIS_CREDIT",
            estimated is not None and maximum >= estimated > 0,
            maximum <= Decimal("500"),
            pricing_matched,
            pricing_fresh,
            active_runs == 0,
            unfinished_tasks == 0,
            not live_enabled,
            canary or anchor_ready,
            args.balance_evidence_precheck or balance_review_valid,
        )
    )
    values = {
        "ProcessConfigured": process_configured,
        "modelsChecked": models_checked,
        "imageModelAccessible": image_accessible,
        "videoModelAccessible": video_accessible,
        "tokenActive": token_active,
        "tokenUnlimited": token_unlimited,
        "balanceReadable": balance_readable,
        "balanceSufficient": balance_sufficient,
        "estimatedBillingUnits": str(estimated) if estimated is not None else "UNKNOWN",
        "maximumBillingUnits": str(maximum),
        "pricingSnapshotHashMatched": pricing_matched,
        "pricingSnapshotFresh": pricing_fresh,
        "activeVerificationRuns": active_runs,
        "liveOrchestrationEnabled": live_enabled,
        "accountBalanceReviewValid": balance_review_valid,
        "ready": ready,
        "modelListGets": model_gets,
        "tokenBalanceGets": token_gets,
        "userBalanceGets": user_gets,
        "uploads": 0,
        "imageSubmits": 0,
        "videoSubmits": 0,
        "generationPolls": 0,
        "unfinishedPaidTasks": unfinished_tasks,
    }
    for name, value in values.items():
        rendered = str(value).lower() if isinstance(value, bool) else value
        print(f"{name}={rendered}")
    if not balance_readable or not balance_sufficient:
        print("MANUAL_BALANCE_CONFIRMATION_REQUIRED")
    if not pricing_fresh:
        print("MANUAL_PRICING_REVIEW_REQUIRED")
    if ready:
        command = (
            ".\\scripts\\e2e-real-provider.ps1 -ConfirmLive -ExecutePaid "
            + ("-CanaryImageOnly " if canary else "")
            + f"-BillingUnit TOAPIS_CREDIT -MaxBillingUnits {maximum} "
            + f"-PricingSnapshotHash {args.pricing_snapshot_hash} "
            + ("" if canary else "-InitialAnchorPath .\\.run\\toapis-verification-anchor.png -AutoApproveForVerification ")
            + f"-PollIntervalSeconds 10 -TimeoutMinutes {20 if canary else 45}"
        )
        print(f"suggestedCommand={command}")
        print("THIS COMMAND CREATES PAID REMOTE TASKS.")
        print("It has not been executed.")
        print("Explicit operator authorization is still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
