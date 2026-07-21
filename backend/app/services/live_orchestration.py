from __future__ import annotations

from datetime import timedelta, timezone
import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.entities import (
    PricingReviewStatus,
    ProviderModelProfile,
    ProviderProfile,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    utcnow,
)
from app.models.schemas import ToApisAccountBalanceRequest, ToApisLiveEnableRequest, ToApisPricingReviewRequest
from app.services import provider_management
from app.services.toapis_pricing import TOAPIS_PRICING_CONTRACT

PROVIDER_KEY = "toapis"
PRICING_VERSION = TOAPIS_PRICING_CONTRACT.version
BILLING_UNIT = TOAPIS_PRICING_CONTRACT.billing_unit
IMAGE_MODEL_KEY = TOAPIS_PRICING_CONTRACT.image.model_key
VIDEO_MODEL_KEY = TOAPIS_PRICING_CONTRACT.video.model_key
IMAGE_REMOTE_MODEL = TOAPIS_PRICING_CONTRACT.image.remote_model
VIDEO_REMOTE_MODEL = TOAPIS_PRICING_CONTRACT.video.remote_model
IMAGE_PRICE = str(TOAPIS_PRICING_CONTRACT.image.price)
VIDEO_PRICE = str(TOAPIS_PRICING_CONTRACT.video.price)
IMAGE_UNIT = TOAPIS_PRICING_CONTRACT.image.unit
VIDEO_UNIT = TOAPIS_PRICING_CONTRACT.video.unit


def get_toapis_profile(session: Session) -> ProviderProfile:
    profile = session.exec(select(ProviderProfile).where(ProviderProfile.provider_key == PROVIDER_KEY)).first()
    if profile is None:
        raise AppError("PROVIDER_PROFILE_NOT_FOUND", "TOAPIS ProviderProfile was not found.", 404)
    return profile


def pricing_review_state(session: Session) -> dict[str, Any]:
    profile = get_toapis_profile(session)
    models = _models(session, profile.id or 0)
    _mark_stale_if_needed(session, profile, models)
    image = models[IMAGE_MODEL_KEY]
    video = models[VIDEO_MODEL_KEY]
    pricing_reviewed = all(item.pricing_review_status == PricingReviewStatus.REVIEWED for item in (image, video))
    estimate = two_shot_estimate(models) if pricing_reviewed else None
    breakdown = two_shot_breakdown(models) if pricing_reviewed else []
    snapshot_hash = image.pricing_snapshot_hash if image.pricing_snapshot_hash == video.pricing_snapshot_hash else None
    return {
        "provider_key": PROVIDER_KEY,
        "pricing_version": PRICING_VERSION,
        "billing_unit": BILLING_UNIT,
        "image": _model_pricing_payload(image),
        "video": _model_pricing_payload(video),
        "pricing_snapshot_hash": snapshot_hash,
        "pricing_reviewed": pricing_reviewed,
        "contract_reviewed_at": profile.contract_reviewed_at,
        "contract_reference": profile.contract_reference,
        "live_orchestration_enabled": profile.live_orchestration_enabled,
        "preflight": {
            "checked_at": profile.preflight_checked_at,
            "image_model_accessible": profile.preflight_image_model_accessible,
            "video_model_accessible": profile.preflight_video_model_accessible,
            "response_schema_valid": profile.preflight_response_schema_valid,
            "balance_check": "MANUAL_CONFIRMATION_REQUIRED",
        },
        "account_balance_reviewed_at": profile.account_balance_reviewed_at,
        "account_balance_sufficient": profile.account_balance_sufficient,
        "account_balance_pricing_snapshot_hash": profile.account_balance_pricing_snapshot_hash,
        "account_balance_confirmed_units": profile.account_balance_confirmed_units,
        "account_balance_evidence_type": profile.account_balance_evidence_type,
        "estimated_two_shot_billing_units": estimate,
        "estimated_two_shot_breakdown": breakdown,
        "recommended_test_ceiling": str(TOAPIS_PRICING_CONTRACT.recommended_ceiling),
    }


def review_pricing(session: Session, payload: ToApisPricingReviewRequest) -> dict[str, Any]:
    expected = (
        PRICING_VERSION, IMAGE_PRICE, IMAGE_UNIT, VIDEO_PRICE, VIDEO_UNIT, BILLING_UNIT,
        IMAGE_REMOTE_MODEL, VIDEO_REMOTE_MODEL, TOAPIS_PRICING_CONTRACT.source_kind,
        TOAPIS_PRICING_CONTRACT.contract_reference,
    )
    actual = (
        payload.pricing_version, str(payload.image_price), payload.image_unit, str(payload.video_price),
        payload.video_unit, payload.billing_unit, payload.image_model, payload.video_model,
        payload.pricing_source_kind, payload.contract_reference,
    )
    if not payload.acknowledged:
        raise AppError("PRICING_REVIEW_ACKNOWLEDGEMENT_REQUIRED", "Pricing review acknowledgement is required.", 409)
    if actual != expected:
        raise AppError("PRICING_SNAPSHOT_MISMATCH", "Submitted pricing does not match the current candidate snapshot.", 409)
    profile = get_toapis_profile(session)
    models = _models(session, profile.id or 0)
    reviewed_at = utcnow()
    snapshot_hash = candidate_snapshot_hash()
    for model_key, model in models.items():
        contract_model = TOAPIS_PRICING_CONTRACT.image if model_key == IMAGE_MODEL_KEY else TOAPIS_PRICING_CONTRACT.video
        model.billing_unit = BILLING_UNIT
        model.pricing_version = PRICING_VERSION
        model.pricing_json = json.dumps(
            {"rules": [{"unit": contract_model.unit, "price": str(contract_model.price)}]},
            separators=(",", ":"),
        )
        model.pricing_source = "TOAPIS official public model guide; reference pricing may vary by user group or promotion."
        model.pricing_source_kind = TOAPIS_PRICING_CONTRACT.source_kind
        model.pricing_source_checked_at = reviewed_at
        model.pricing_source_reference = contract_model.source_reference
        model.pricing_assumptions_json = TOAPIS_PRICING_CONTRACT.assumptions_json(image=model_key == IMAGE_MODEL_KEY)
        model.pricing_review_status = PricingReviewStatus.REVIEWED
        model.pricing_reviewed_at = reviewed_at
        model.pricing_reviewed_by = "LOCAL_OPERATOR"
        model.pricing_snapshot_hash = snapshot_hash
        model.updated_at = reviewed_at
        session.add(model)
    profile.contract_reviewed_at = reviewed_at
    profile.contract_reviewed_by = "LOCAL_OPERATOR"
    profile.contract_reference = payload.contract_reference
    profile.live_orchestration_enabled = False
    profile.account_balance_sufficient = False
    profile.account_balance_reviewed_at = None
    profile.account_balance_pricing_snapshot_hash = None
    profile.account_balance_confirmed_units = None
    profile.account_balance_evidence_type = None
    profile.updated_at = reviewed_at
    session.add(profile)
    session.add(ProviderVerificationRun(
        provider_profile_id=profile.id or 0, verification_type=ProviderVerificationType.CONTRACT,
        status=ProviderVerificationStatus.PASSED, started_at=reviewed_at, completed_at=reviewed_at,
        summary_json=json.dumps({"action": "TOAPIS_PRICING_REVIEWED", "pricing_version": PRICING_VERSION, "billing_unit": BILLING_UNIT, "pricing_snapshot_hash": snapshot_hash}),
    ))
    session.commit()
    return pricing_review_state(session)


async def run_preflight(session: Session, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    profile = get_toapis_profile(session)
    api_key = os.getenv(profile.secret_env_var) if profile.secret_env_var else None
    if not api_key:
        raise AppError("SECRET_NOT_CONFIGURED", "TOAPIS_API_KEY is not configured.", 409)
    try:
        async with httpx.AsyncClient(timeout=get_settings().toapis_http_timeout_seconds, transport=transport, trust_env=False) as client:
            response = await client.get(f"{profile.base_url.rstrip('/')}/models?type=all", headers={"Authorization": f"Bearer {api_key}"}, follow_redirects=False)
    except httpx.TimeoutException as exc:
        _persist_preflight_failure(session, profile)
        raise AppError("PREFLIGHT_TIMEOUT", "TOAPIS model-access preflight timed out.", 503) from exc
    except httpx.NetworkError as exc:
        _persist_preflight_failure(session, profile)
        raise AppError("PREFLIGHT_NETWORK_ERROR", "TOAPIS model-access preflight failed.", 503) from exc
    if response.status_code == 401:
        _persist_preflight_failure(session, profile)
        raise AppError("AUTHENTICATION_ERROR", "TOAPIS model-access preflight authentication failed.", 401)
    if response.status_code == 429:
        _persist_preflight_failure(session, profile)
        raise AppError("RATE_LIMITED", "TOAPIS model-access preflight was rate limited.", 429)
    if response.status_code >= 400:
        _persist_preflight_failure(session, profile)
        raise AppError("PREFLIGHT_FAILED", "TOAPIS model-access preflight failed.", 502)
    if len(response.content) > get_settings().toapis_preflight_max_response_bytes:
        _persist_preflight_failure(session, profile)
        raise AppError("PREFLIGHT_RESPONSE_TOO_LARGE", "TOAPIS model list response exceeded the safety limit.", 502)
    try:
        raw = response.json()
    except ValueError as exc:
        _persist_preflight_failure(session, profile)
        raise AppError("PREFLIGHT_INVALID_RESPONSE", "TOAPIS model list returned invalid JSON.", 502) from exc
    items = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(items, dict):
        items = items.get("data") or items.get("models")
    if not isinstance(items, list) or len(items) > 10_000:
        _persist_preflight_failure(session, profile)
        raise AppError("PREFLIGHT_INVALID_RESPONSE", "TOAPIS model list schema is invalid or too large.", 502)
    ids = {str(item.get("id") or item.get("model") or item.get("name")) for item in items if isinstance(item, dict)}
    checked_at = utcnow()
    profile.preflight_checked_at = checked_at
    profile.preflight_image_model_accessible = IMAGE_REMOTE_MODEL in ids
    profile.preflight_video_model_accessible = VIDEO_REMOTE_MODEL in ids
    profile.preflight_response_schema_valid = True
    profile.live_orchestration_enabled = False
    profile.updated_at = checked_at
    session.add(profile)
    session.commit()
    return {
        "models_checked": True,
        "image_model_accessible": profile.preflight_image_model_accessible,
        "video_model_accessible": profile.preflight_video_model_accessible,
        "checked_at": checked_at,
        "response_schema_valid": True,
        "targets": {IMAGE_REMOTE_MODEL: profile.preflight_image_model_accessible, VIDEO_REMOTE_MODEL: profile.preflight_video_model_accessible},
        "balance_check": "MANUAL_CONFIRMATION_REQUIRED",
    }


def _persist_preflight_failure(session: Session, profile: ProviderProfile) -> None:
    """Persist only a sanitized failed summary; never retain the response body."""
    profile.preflight_checked_at = utcnow()
    profile.preflight_image_model_accessible = False
    profile.preflight_video_model_accessible = False
    profile.preflight_response_schema_valid = False
    profile.live_orchestration_enabled = False
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()


def confirm_account_balance(session: Session, payload: ToApisAccountBalanceRequest) -> dict[str, Any]:
    if not payload.acknowledged or not payload.sufficient:
        raise AppError("ACCOUNT_BALANCE_CONFIRMATION_REQUIRED", "A positive manual account-balance confirmation is required.", 409)
    if payload.evidence_type != "TOKEN_BALANCE_READ_ONLY":
        raise AppError("BALANCE_EVIDENCE_TYPE_INVALID", "TOAPIS balance evidence type is invalid.", 409)
    state = pricing_review_state(session)
    current_hash = state.get("pricing_snapshot_hash")
    if not state.get("pricing_reviewed") or payload.pricing_snapshot_hash != current_hash:
        raise AppError("PRICING_SNAPSHOT_MISMATCH", "Balance evidence must bind the current reviewed pricing snapshot.", 409)
    confirmed_units = _positive_decimal(payload.confirmed_billing_units, "BALANCE_CONFIRMED_UNITS_INVALID")
    profile = get_toapis_profile(session)
    profile.account_balance_reviewed_at = utcnow()
    profile.account_balance_sufficient = True
    profile.account_balance_pricing_snapshot_hash = str(current_hash)
    profile.account_balance_confirmed_units = str(confirmed_units)
    profile.account_balance_evidence_type = payload.evidence_type
    profile.account_balance_note = payload.note or "Confirmed sufficient in TOAPIS console by local operator."
    profile.live_orchestration_enabled = False
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    return pricing_review_state(session)


def enable_live(session: Session, payload: ToApisLiveEnableRequest) -> dict[str, Any]:
    if not payload.acknowledged:
        raise AppError("LIVE_ENABLE_ACKNOWLEDGEMENT_REQUIRED", "Live enable acknowledgement is required.", 409)
    profile = get_toapis_profile(session)
    validate_live_orchestration_gate(session, profile=profile, expected_snapshot_hash=payload.pricing_snapshot_hash, require_enabled=False)
    profile.live_orchestration_enabled = True
    profile.live_enabled_at = utcnow()
    profile.live_enabled_by = "LOCAL_OPERATOR"
    profile.live_enable_reason = payload.reason
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    return pricing_review_state(session)


def disable_live(session: Session) -> dict[str, Any]:
    profile = get_toapis_profile(session)
    profile.live_orchestration_enabled = False
    profile.live_enabled_at = None
    profile.live_enabled_by = None
    profile.live_enable_reason = None
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    return pricing_review_state(session)


def validate_live_orchestration_gate(
    session: Session,
    *,
    profile: ProviderProfile | None = None,
    expected_snapshot_hash: str | None = None,
    require_enabled: bool = True,
    exclude_verification_run_id: int | None = None,
    check_active_verification: bool = False,
    required_billing_units: Decimal | None = None,
) -> dict[str, Any]:
    profile = profile or get_toapis_profile(session)
    if not profile.enabled:
        raise AppError("PROVIDER_DISABLED", "TOAPIS Provider is disabled.", 409)
    if not profile.secret_env_var or not os.getenv(profile.secret_env_var):
        raise AppError("SECRET_NOT_CONFIGURED", "TOAPIS_API_KEY is not configured.", 409)
    if not provider_management.latest_contract_passed(session, profile.id or 0) or not profile.contract_reviewed_at:
        raise AppError("CONTRACT_NOT_REVIEWED", "TOAPIS contract review is required.", 409)
    models = _models(session, profile.id or 0)
    _mark_stale_if_needed(session, profile, models)
    if any(item.pricing_review_status == PricingReviewStatus.STALE for item in models.values()):
        raise AppError("PRICING_SNAPSHOT_STALE", "TOAPIS pricing snapshot is stale.", 409)
    if any(item.pricing_review_status != PricingReviewStatus.REVIEWED for item in models.values()):
        raise AppError("PRICING_NOT_REVIEWED", "TOAPIS model pricing has not been reviewed.", 409)
    units = {item.billing_unit for item in models.values()}
    if units != {BILLING_UNIT}:
        raise AppError("MODEL_PRICING_UNIT_MISMATCH", "TOAPIS model billing units do not match.", 409)
    hashes = {item.pricing_snapshot_hash for item in models.values()}
    if len(hashes) != 1 or None in hashes or (expected_snapshot_hash and expected_snapshot_hash not in hashes):
        raise AppError("PRICING_SNAPSHOT_MISMATCH", "TOAPIS pricing snapshot hash does not match.", 409)
    if not profile.preflight_checked_at or not profile.preflight_image_model_accessible or not profile.preflight_video_model_accessible:
        raise AppError("MODEL_ACCESS_NOT_VERIFIED", "TOAPIS model access preflight has not passed.", 409)
    balance_cutoff = utcnow() - timedelta(hours=get_settings().toapis_balance_review_max_age_hours)
    balance_reviewed_at = profile.account_balance_reviewed_at
    if balance_reviewed_at and balance_reviewed_at.tzinfo is None:
        balance_reviewed_at = balance_reviewed_at.replace(tzinfo=timezone.utc)
    confirmed_units = _decimal_or_none(profile.account_balance_confirmed_units)
    current_hash = next(iter(hashes))
    balance_valid = bool(
        profile.account_balance_sufficient and balance_reviewed_at and balance_reviewed_at >= balance_cutoff
        and profile.account_balance_pricing_snapshot_hash == current_hash
        and profile.account_balance_evidence_type == "TOKEN_BALANCE_READ_ONLY"
        and confirmed_units is not None
        and (required_billing_units is None or confirmed_units >= required_billing_units)
    )
    if not balance_valid:
        raise AppError("ACCOUNT_BALANCE_NOT_CONFIRMED", "TOAPIS account balance has not been confirmed.", 409)
    if check_active_verification:
        active_query = select(ProviderVerificationRun).where(
            ProviderVerificationRun.provider_profile_id == profile.id,
            col(ProviderVerificationRun.verification_type).in_([
                ProviderVerificationType.LIVE_CHAIN, ProviderVerificationType.LIVE_CANARY,
                ProviderVerificationType.LIVE_VIDEO_CANARY,
            ]),
            col(ProviderVerificationRun.status).in_([ProviderVerificationStatus.PENDING, ProviderVerificationStatus.RUNNING]),
        )
        if exclude_verification_run_id is not None:
            active_query = active_query.where(ProviderVerificationRun.id != exclude_verification_run_id)
        active = session.exec(active_query).first()
        if active:
            raise AppError("LIVE_VERIFICATION_ALREADY_RUNNING", "A TOAPIS live verification is already active.", 409)
    if require_enabled and not profile.live_orchestration_enabled:
        raise AppError("LIVE_ORCHESTRATION_DISABLED", "TOAPIS live orchestration is disabled.", 409)
    return {"pricing_snapshot_hash": current_hash, "billing_unit": BILLING_UNIT, "profile": profile}


def _positive_decimal(value: str | None, code: str) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None or parsed <= 0:
        raise AppError(code, "A positive billing amount is required.", 409)
    return parsed


def _decimal_or_none(value: str | None) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


def candidate_snapshot_hash() -> str:
    return TOAPIS_PRICING_CONTRACT.snapshot_hash()


def two_shot_breakdown(models: dict[str, ProviderModelProfile]) -> list[dict[str, str | int]]:
    image_price = _reviewed_rule_price(models[IMAGE_MODEL_KEY], IMAGE_UNIT)
    video_price = _reviewed_rule_price(models[VIDEO_MODEL_KEY], VIDEO_UNIT)
    return [
        {"model_key": IMAGE_MODEL_KEY, "unit": IMAGE_UNIT, "quantity": 2, "unit_price": str(image_price), "subtotal": str(image_price * 2)},
        {"model_key": VIDEO_MODEL_KEY, "unit": VIDEO_UNIT, "quantity": 8, "unit_price": str(video_price), "subtotal": str(video_price * 8)},
    ]


def two_shot_estimate(models: dict[str, ProviderModelProfile]) -> str:
    return str(sum((Decimal(item["subtotal"]) for item in two_shot_breakdown(models)), Decimal("0")))


def _reviewed_rule_price(model: ProviderModelProfile, unit: str) -> Decimal:
    if model.pricing_review_status != PricingReviewStatus.REVIEWED or not model.pricing_snapshot_hash:
        raise AppError("PRICING_NOT_REVIEWED", "TOAPIS model pricing has not been reviewed.", 409)
    rules = provider_management.loads_dict(model.pricing_json).get("rules")
    if not isinstance(rules, list):
        raise AppError("PRICING_SCHEMA_INVALID", "TOAPIS model pricing schema is invalid.", 409)
    matches = [item.get("price") for item in rules if isinstance(item, dict) and item.get("unit") == unit]
    if len(matches) != 1:
        raise AppError("PRICING_SCHEMA_INVALID", "TOAPIS model pricing rule is missing or ambiguous.", 409)
    try:
        price = Decimal(str(matches[0]))
    except (InvalidOperation, ValueError) as exc:
        raise AppError("PRICING_SCHEMA_INVALID", "TOAPIS model price is invalid.", 409) from exc
    if price <= 0:
        raise AppError("PRICING_SCHEMA_INVALID", "Unknown TOAPIS cost cannot be treated as zero.", 409)
    return price


def _models(session: Session, profile_id: int) -> dict[str, ProviderModelProfile]:
    items = session.exec(select(ProviderModelProfile).where(ProviderModelProfile.provider_profile_id == profile_id)).all()
    models = {item.model_key: item for item in items if item.model_key in {IMAGE_MODEL_KEY, VIDEO_MODEL_KEY}}
    if set(models) != {IMAGE_MODEL_KEY, VIDEO_MODEL_KEY}:
        raise AppError("REQUIRED_MODEL_PROFILES_MISSING", "Required TOAPIS model profiles are missing.", 409)
    return models


def _mark_stale_if_needed(session: Session, profile: ProviderProfile, models: dict[str, ProviderModelProfile]) -> None:
    cutoff = utcnow() - timedelta(days=get_settings().toapis_pricing_snapshot_max_age_days)
    changed = False
    for model in models.values():
        reviewed_at = model.pricing_reviewed_at
        if reviewed_at and reviewed_at.tzinfo is None:
            reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        if model.pricing_review_status == PricingReviewStatus.REVIEWED and (not reviewed_at or reviewed_at < cutoff):
            model.pricing_review_status = PricingReviewStatus.STALE
            session.add(model)
            changed = True
    if changed:
        profile.live_orchestration_enabled = False
        profile.account_balance_sufficient = False
        session.add(profile)
        session.commit()


def _model_pricing_payload(model: ProviderModelProfile) -> dict[str, Any]:
    return {
        "model_key": model.model_key, "remote_model": model.remote_model,
        "pricing": provider_management.loads_dict(model.pricing_json), "billing_unit": model.billing_unit,
        "pricing_version": model.pricing_version, "pricing_review_status": model.pricing_review_status,
        "pricing_reviewed_at": model.pricing_reviewed_at, "pricing_snapshot_hash": model.pricing_snapshot_hash,
        "pricing_source": model.pricing_source, "pricing_source_kind": model.pricing_source_kind,
        "pricing_source_checked_at": model.pricing_source_checked_at,
        "pricing_source_reference": model.pricing_source_reference,
        "pricing_assumptions": provider_management.loads_dict(model.pricing_assumptions_json),
        "pricing_reviewed_by": model.pricing_reviewed_by,
    }
