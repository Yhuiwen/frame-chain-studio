from __future__ import annotations

from datetime import timedelta, timezone
from hashlib import sha256
import json
import os
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

PROVIDER_KEY = "toapis"
PRICING_VERSION = "toapis-public-2026-07"
BILLING_UNIT = "TOAPIS_CREDIT"
IMAGE_MODEL_KEY = "toapis-seedream-5"
VIDEO_MODEL_KEY = "toapis-viduq3-pro"
IMAGE_REMOTE_MODEL = "doubao-seedream-5-0"
VIDEO_REMOTE_MODEL = "viduq3-pro"
IMAGE_PRICE = "6.3"
VIDEO_PRICE = "20"
IMAGE_UNIT = "IMAGE_REQUEST"
VIDEO_UNIT = "VIDEO_SECOND"


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
    snapshot_hash = image.pricing_snapshot_hash if image.pricing_snapshot_hash == video.pricing_snapshot_hash else None
    return {
        "provider_key": PROVIDER_KEY,
        "pricing_version": PRICING_VERSION,
        "billing_unit": BILLING_UNIT,
        "image": _model_pricing_payload(image),
        "video": _model_pricing_payload(video),
        "pricing_snapshot_hash": snapshot_hash,
        "pricing_reviewed": all(item.pricing_review_status == PricingReviewStatus.REVIEWED for item in (image, video)),
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
        "estimated_two_shot_billing_units": "172.6",
        "recommended_test_ceiling": "200",
    }


def review_pricing(session: Session, payload: ToApisPricingReviewRequest) -> dict[str, Any]:
    expected = (PRICING_VERSION, IMAGE_PRICE, IMAGE_UNIT, VIDEO_PRICE, VIDEO_UNIT, BILLING_UNIT)
    actual = (payload.pricing_version, payload.image_price, payload.image_unit, payload.video_price, payload.video_unit, payload.billing_unit)
    if not payload.acknowledged:
        raise AppError("PRICING_REVIEW_ACKNOWLEDGEMENT_REQUIRED", "Pricing review acknowledgement is required.", 409)
    if actual != expected:
        raise AppError("PRICING_SNAPSHOT_MISMATCH", "Submitted pricing does not match the current candidate snapshot.", 409)
    profile = get_toapis_profile(session)
    models = _models(session, profile.id or 0)
    reviewed_at = utcnow()
    snapshot_hash = candidate_snapshot_hash()
    for model in models.values():
        model.billing_unit = BILLING_UNIT
        model.pricing_version = PRICING_VERSION
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
        raise AppError("PREFLIGHT_TIMEOUT", "TOAPIS model-access preflight timed out.", 503) from exc
    except httpx.NetworkError as exc:
        raise AppError("PREFLIGHT_NETWORK_ERROR", "TOAPIS model-access preflight failed.", 503) from exc
    if response.status_code == 401:
        raise AppError("AUTHENTICATION_ERROR", "TOAPIS model-access preflight authentication failed.", 401)
    if response.status_code == 429:
        raise AppError("RATE_LIMITED", "TOAPIS model-access preflight was rate limited.", 429)
    if response.status_code >= 400:
        raise AppError("PREFLIGHT_FAILED", "TOAPIS model-access preflight failed.", 502)
    try:
        raw = response.json()
    except ValueError as exc:
        raise AppError("PREFLIGHT_INVALID_RESPONSE", "TOAPIS model list returned invalid JSON.", 502) from exc
    items = raw.get("data") if isinstance(raw, dict) else None
    if isinstance(items, dict):
        items = items.get("data") or items.get("models")
    if not isinstance(items, list) or len(items) > 10_000:
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


def confirm_account_balance(session: Session, payload: ToApisAccountBalanceRequest) -> dict[str, Any]:
    if not payload.acknowledged or not payload.sufficient:
        raise AppError("ACCOUNT_BALANCE_CONFIRMATION_REQUIRED", "A positive manual account-balance confirmation is required.", 409)
    profile = get_toapis_profile(session)
    profile.account_balance_reviewed_at = utcnow()
    profile.account_balance_sufficient = True
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
    if not profile.account_balance_sufficient or not profile.account_balance_reviewed_at:
        raise AppError("ACCOUNT_BALANCE_NOT_CONFIRMED", "TOAPIS account balance has not been confirmed.", 409)
    active = session.exec(select(ProviderVerificationRun).where(
        ProviderVerificationRun.provider_profile_id == profile.id,
        ProviderVerificationRun.verification_type == ProviderVerificationType.LIVE_CHAIN,
        col(ProviderVerificationRun.status).in_([ProviderVerificationStatus.PENDING, ProviderVerificationStatus.RUNNING]),
    )).first()
    if active:
        raise AppError("LIVE_VERIFICATION_ALREADY_RUNNING", "A TOAPIS live verification is already active.", 409)
    if require_enabled and not profile.live_orchestration_enabled:
        raise AppError("LIVE_ORCHESTRATION_DISABLED", "TOAPIS live orchestration is disabled.", 409)
    return {"pricing_snapshot_hash": next(iter(hashes)), "billing_unit": BILLING_UNIT, "profile": profile}


def candidate_snapshot_hash() -> str:
    canonical = {
        "billing_unit": BILLING_UNIT,
        "image": {"model": IMAGE_REMOTE_MODEL, "price": IMAGE_PRICE, "unit": IMAGE_UNIT},
        "pricing_version": PRICING_VERSION,
        "video": {"model": VIDEO_REMOTE_MODEL, "price": VIDEO_PRICE, "unit": VIDEO_UNIT},
    }
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
        session.add(profile)
        session.commit()


def _model_pricing_payload(model: ProviderModelProfile) -> dict[str, Any]:
    return {
        "model_key": model.model_key, "remote_model": model.remote_model,
        "pricing": provider_management.loads_dict(model.pricing_json), "billing_unit": model.billing_unit,
        "pricing_version": model.pricing_version, "pricing_review_status": model.pricing_review_status,
        "pricing_reviewed_at": model.pricing_reviewed_at, "pricing_snapshot_hash": model.pricing_snapshot_hash,
    }
