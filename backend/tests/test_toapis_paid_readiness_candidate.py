from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

import pytest

from app.services.toapis_pricing import TOAPIS_PRICING_CONTRACT


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "toapis_paid_readiness.py"


def load_script():
    spec = importlib.util.spec_from_file_location("toapis_paid_readiness_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_database(
    path: Path,
    *,
    live: bool = False,
    active: bool = False,
    unfinished: bool = False,
    stale_pricing: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    pricing_reviewed_at = "2000-01-01T00:00:00+00:00" if stale_pricing else now
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE providerprofile (id INTEGER PRIMARY KEY, provider_key TEXT, live_orchestration_enabled INTEGER,
              account_balance_sufficient INTEGER, account_balance_reviewed_at TEXT, account_balance_pricing_snapshot_hash TEXT,
              account_balance_confirmed_units TEXT, account_balance_evidence_type TEXT);
            CREATE TABLE providermodelprofile (remote_model TEXT, pricing_json TEXT, pricing_review_status TEXT,
              pricing_reviewed_at TEXT, pricing_snapshot_hash TEXT, pricing_version TEXT, billing_unit TEXT,
              pricing_source_kind TEXT, pricing_source_checked_at TEXT, pricing_source_reference TEXT,
              pricing_assumptions_json TEXT);
            CREATE TABLE providerverificationrun (provider_profile_id INTEGER, status TEXT);
            CREATE TABLE generationtask (provider_id TEXT, status TEXT);
            """
        )
        pricing_hash = TOAPIS_PRICING_CONTRACT.snapshot_hash()
        db.execute(
            "INSERT INTO providerprofile VALUES (1,'toapis',?,?,?,?,?,?)",
            (live, True, now, pricing_hash, "110", "TOKEN_BALANCE_READ_ONLY"),
        )
        for model in (TOAPIS_PRICING_CONTRACT.image, TOAPIS_PRICING_CONTRACT.video):
            db.execute(
                "INSERT INTO providermodelprofile VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    model.remote_model,
                    json.dumps({"rules": [{"unit": model.unit, "price": str(model.price)}]}),
                    "REVIEWED",
                    pricing_reviewed_at,
                    pricing_hash,
                    TOAPIS_PRICING_CONTRACT.version,
                    TOAPIS_PRICING_CONTRACT.billing_unit,
                    TOAPIS_PRICING_CONTRACT.source_kind,
                    pricing_reviewed_at,
                    model.source_reference,
                    json.dumps(model.assumptions.model_dump(mode="json")),
                ),
            )
        if active:
            db.execute("INSERT INTO providerverificationrun VALUES (1,'RUNNING')")
        if unfinished:
            db.execute("INSERT INTO generationtask VALUES ('toapis','RUNNING')")


def run_short(
    monkeypatch,
    capsys,
    tmp_path: Path,
    *,
    maximum: str = "110",
    pricing_hash: str | None = None,
    live: bool = False,
    active: bool = False,
    unfinished: bool = False,
    stale_pricing: bool = False,
    missing_image: bool = False,
    missing_video: bool = False,
    available_credits: str | None = None,
):
    db_path = tmp_path / "readiness.db"
    make_database(
        db_path,
        live=live,
        active=active,
        unfinished=unfinished,
        stale_pricing=stale_pricing,
    )
    before = sha256(db_path.read_bytes()).hexdigest()
    module = load_script()
    secret = "obviously-fake-readiness-key"
    monkeypatch.setenv("TOAPIS_API_KEY", secret)
    monkeypatch.setenv("FCS_DATABASE_URL", f"sqlite:///{db_path}")
    models = []
    if not missing_image:
        models.append(TOAPIS_PRICING_CONTRACT.image.remote_model)
    if not missing_video:
        models.append(TOAPIS_PRICING_CONTRACT.video.remote_model)

    def fake_get_json(path: str, _key: str) -> dict[str, object]:
        if path.startswith("/models"):
            return {"data": [{"id": value} for value in models]}
        if available_credits is None:
            return {"data": {"unlimited_quota": True}}
        return {"data": {"unlimited_quota": False, "remain_credits": available_credits}}

    monkeypatch.setattr(module, "_get_json", fake_get_json)
    expected = pricing_hash or TOAPIS_PRICING_CONTRACT.snapshot_hash()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--candidate",
            "SHORT_CONTINUITY_CANARY",
            "--billing-unit",
            "TOAPIS_CREDIT",
            "--pricing-snapshot-hash",
            expected,
            "--max-billing-units",
            maximum,
            "--balance-evidence-precheck",
        ],
    )
    code = module.main()
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
    assert sha256(db_path.read_bytes()).hexdigest() == before
    return code, captured.out


def test_short_mock_readiness_is_ready_and_side_effect_free(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    code, output = run_short(monkeypatch, capsys, tmp_path)
    assert code == 0
    for expected in (
        "candidate=SHORT_CONTINUITY_CANARY",
        "estimatedBillingUnits=92.6",
        "maximumBillingUnits=110",
        "imageTasksMax=2",
        "videoTasksMax=2",
        "videoDurationSecondsEach=2",
        "totalVideoSeconds=4",
        "maxAttemptsPerTask=1",
        "automaticRetryAllowed=false",
        "ready=true",
        "paidCommandPreviewAvailable=false",
        "paidCommandPreviewExecuted=false",
        "paidCommandPreviewReason=SHORT_PAID_EXECUTION_ENTRY_NOT_IMPLEMENTED",
    ):
        assert expected in output


@pytest.mark.parametrize(
    "kwargs",
    [
        {"maximum": "90"},
        {"pricing_hash": "0" * 64},
        {"live": True},
        {"active": True},
        {"unfinished": True},
        {"stale_pricing": True},
        {"missing_image": True},
        {"missing_video": True},
        {"available_credits": "92.5"},
    ],
)
def test_short_readiness_blocks_failed_gates(
    monkeypatch, capsys, tmp_path: Path, kwargs: dict[str, Any]
) -> None:
    _code, output = run_short(monkeypatch, capsys, tmp_path, **kwargs)
    assert "ready=false" in output


def test_unknown_candidate_exits_nonzero_without_network(monkeypatch, capsys) -> None:
    module = load_script()
    called = False

    def forbidden(*_args):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(module, "_get_json", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--candidate",
            "UNKNOWN",
            "--billing-unit",
            "TOAPIS_CREDIT",
            "--pricing-snapshot-hash",
            "0" * 64,
            "--max-billing-units",
            "110",
        ],
    )
    assert module.main() != 0
    assert called is False
    assert "TOAPIS_VERIFICATION_CANDIDATE_INVALID" in capsys.readouterr().err
