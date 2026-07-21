import csv
import io
import json
import os
from decimal import Decimal, InvalidOperation
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session, col, select

from app.core.errors import AppError
from app.core.redaction import redact_sensitive
from app.models.entities import (
    BudgetPeriodType,
    GenerationKind,
    GenerationRequest,
    GenerationTask,
    GenerationTaskStatus,
    GenerationUsageRecord,
    Project,
    ProjectBudgetPolicy,
    PricingReviewStatus,
    ProviderAdapterType,
    ProviderModelGenerationType,
    ProviderModelProfile,
    ProviderProfile,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    UnknownCostPolicy,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
    utcnow,
)
from app.models.schemas import (
    LiveVerificationRequest,
    ProjectBudgetPolicyUpdate,
    ProviderModelProfileCreate,
    ProviderModelProfileUpdate,
    ProviderProfileCreate,
    ProviderProfileUpdate,
)
from app.providers.config_loader import load_registry_from_env
from app.providers.http import MappedAsyncHttpProvider
from app.providers.models import MappedHttpProviderConfig, ProviderCapabilities
from app.providers.registry import ProviderRegistry
from app.providers.toapis import TOAPIS_BASE_URL, ToApisProvider


SAFE_CONFIG_KEYS = {
    "submit_path",
    "poll_path",
    "cancel_path",
    "upload_path",
    "submit_method",
    "poll_method",
    "cancel_method",
    "upload_method",
    "status_aliases",
    "mapping",
    "headers",
    "timeout_seconds",
    "poll_interval_seconds",
    "upload_file_field",
    "upload_response_url_path",
    "upload_response_file_id_path",
}
SENSITIVE_KEYS = {"secret", "token", "cookie", "authorization", "api_key", "apikey", "password"}
USAGE_WHITELIST = {"billed_seconds", "generated_images", "input_images", "output_pixels", "provider_cost", "currency", "provider_request_id"}


def list_provider_profiles(session: Session, *, include_archived: bool = False) -> list[dict[str, Any]]:
    statement = select(ProviderProfile)
    if not include_archived:
        statement = statement.where(col(ProviderProfile.archived_at).is_(None))
    profiles = session.exec(statement.order_by(col(ProviderProfile.provider_key))).all()
    return [provider_profile_payload(session, item) for item in profiles]


def create_provider_profile(session: Session, payload: ProviderProfileCreate) -> dict[str, Any]:
    config = validate_provider_config(payload.config)
    _validate_base_url(payload.base_url, allow_local=payload.adapter_type == ProviderAdapterType.FAKE)
    profile = ProviderProfile(
        name=payload.name,
        provider_key=payload.provider_key,
        adapter_type=payload.adapter_type,
        display_name=payload.display_name or payload.name,
        description=payload.description,
        base_url=payload.base_url,
        secret_env_var=payload.secret_env_var,
        enabled=payload.enabled,
        config_json=dumps(config),
    )
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return provider_profile_payload(session, profile)


def get_provider_profile_or_404(session: Session, provider_id: int) -> ProviderProfile:
    profile = session.get(ProviderProfile, provider_id)
    if profile is None:
        raise AppError("PROVIDER_PROFILE_NOT_FOUND", f"ProviderProfile {provider_id} was not found.", 404)
    return profile


def update_provider_profile(session: Session, provider_id: int, payload: ProviderProfileUpdate) -> dict[str, Any]:
    profile = get_provider_profile_or_404(session, provider_id)
    updates = payload.model_dump(exclude_unset=True)
    if "config" in updates and updates["config"] is not None:
        profile.config_json = dumps(validate_provider_config(updates.pop("config")))
        profile.config_revision += 1
    if "base_url" in updates and updates["base_url"] is not None:
        _validate_base_url(str(updates["base_url"]), allow_local=profile.adapter_type == ProviderAdapterType.FAKE)
    for key, value in updates.items():
        setattr(profile, key, value)
        if key not in {"enabled"}:
            profile.config_revision += 1
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return provider_profile_payload(session, profile)


def archive_provider_profile(session: Session, provider_id: int) -> dict[str, Any]:
    profile = get_provider_profile_or_404(session, provider_id)
    profile.archived_at = profile.archived_at or utcnow()
    profile.enabled = False
    profile.updated_at = utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return provider_profile_payload(session, profile)


def list_provider_models(session: Session, provider_id: int) -> list[dict[str, Any]]:
    get_provider_profile_or_404(session, provider_id)
    models = session.exec(
        select(ProviderModelProfile)
        .where(ProviderModelProfile.provider_profile_id == provider_id)
        .order_by(col(ProviderModelProfile.generation_type), col(ProviderModelProfile.model_key))
    ).all()
    return [provider_model_payload(item) for item in models]


def create_provider_model(session: Session, provider_id: int, payload: ProviderModelProfileCreate) -> dict[str, Any]:
    get_provider_profile_or_404(session, provider_id)
    model = ProviderModelProfile(
        provider_profile_id=provider_id,
        model_key=payload.model_key,
        remote_model=payload.remote_model,
        display_name=payload.display_name or payload.model_key,
        generation_type=payload.generation_type,
        enabled=payload.enabled,
        capabilities_json=dumps(payload.capabilities),
        limits_json=dumps(payload.limits),
        pricing_json=dumps(validate_pricing(payload.pricing)),
        billing_unit=payload.billing_unit.upper(),
        pricing_version=payload.pricing_version,
        pricing_source=payload.pricing_source,
        pricing_review_status=payload.pricing_review_status,
        currency=payload.currency.upper(),
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return provider_model_payload(model)


def update_provider_model(session: Session, model_id: int, payload: ProviderModelProfileUpdate) -> dict[str, Any]:
    model = session.get(ProviderModelProfile, model_id)
    if model is None:
        raise AppError("PROVIDER_MODEL_NOT_FOUND", f"ProviderModelProfile {model_id} was not found.", 404)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "capabilities":
            model.capabilities_json = dumps(value or {})
        elif key == "limits":
            model.limits_json = dumps(value or {})
        elif key == "pricing":
            model.pricing_json = dumps(validate_pricing(value or {}))
            model.pricing_review_status = PricingReviewStatus.PENDING
            model.pricing_snapshot_hash = None
            model.pricing_reviewed_at = None
            model.pricing_reviewed_by = None
        elif key == "billing_unit" and value:
            model.billing_unit = str(value).upper()
            model.pricing_review_status = PricingReviewStatus.PENDING
            model.pricing_snapshot_hash = None
        elif key == "currency" and value:
            model.currency = str(value).upper()
        else:
            setattr(model, key, value)
    model.updated_at = utcnow()
    session.add(model)
    session.commit()
    session.refresh(model)
    return provider_model_payload(model)


def archive_provider_model(session: Session, model_id: int) -> dict[str, Any]:
    return update_provider_model(session, model_id, ProviderModelProfileUpdate(enabled=False))


def validate_provider_profile(session: Session, provider_id: int) -> dict[str, Any]:
    profile = get_provider_profile_or_404(session, provider_id)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        validate_provider_config(loads_dict(profile.config_json))
    except AppError as exc:
        errors.append(exc.message)
    try:
        _validate_base_url(profile.base_url, allow_local=profile.adapter_type == ProviderAdapterType.FAKE)
    except AppError as exc:
        errors.append(exc.message)
    secret_configured = bool(profile.secret_env_var and os.getenv(profile.secret_env_var))
    if profile.secret_env_var and not secret_configured:
        warnings.append("secret_env_var_not_configured")
    models = list_provider_models(session, profile.id or 0)
    if not models:
        warnings.append("no_model_profiles")
    return {
        "provider_profile_id": profile.id,
        "configuration_valid": not errors,
        "secret_configured": secret_configured,
        "contract_verified": latest_contract_passed(session, profile.id or 0),
        "live_verified": latest_live_passed(session, profile.id or 0),
        "warnings": warnings,
        "errors": errors,
    }


def verify_contract(session: Session, provider_id: int) -> dict[str, Any]:
    profile = get_provider_profile_or_404(session, provider_id)
    validation = validate_provider_profile(session, provider_id)
    toapis_errors: list[str] = []
    if profile.adapter_type == ProviderAdapterType.TOAPIS:
        if profile.provider_key != "toapis":
            toapis_errors.append("provider_key_must_be_toapis")
        if profile.base_url.rstrip("/") != TOAPIS_BASE_URL:
            toapis_errors.append("base_url_must_be_official_toapis_v1")
        if profile.secret_env_var != "TOAPIS_API_KEY":
            toapis_errors.append("secret_env_var_must_be_TOAPIS_API_KEY")
        models = list_provider_models(session, provider_id)
        keys = {item["model_key"] for item in models if item["enabled"]}
        if not {"toapis-seedream-5", "toapis-viduq3-pro"}.issubset(keys):
            toapis_errors.append("required_model_profiles_missing")
    status = ProviderVerificationStatus.PASSED if validation["configuration_valid"] and not toapis_errors else ProviderVerificationStatus.FAILED
    run = ProviderVerificationRun(
        provider_profile_id=profile.id or 0,
        verification_type=ProviderVerificationType.CONTRACT,
        status=status,
        started_at=utcnow(),
        completed_at=utcnow(),
        summary_json=dumps({"validation": validation, "offline": True, "adapter": profile.adapter_type.value, "contract_errors": toapis_errors}),
        error_code=None if status == ProviderVerificationStatus.PASSED else "CONTRACT_FAILED",
        error_message="" if status == ProviderVerificationStatus.PASSED else "Provider contract validation failed.",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return verification_payload(run)


def verify_live(session: Session, provider_id: int, payload: LiveVerificationRequest) -> dict[str, Any]:
    profile = get_provider_profile_or_404(session, provider_id)
    blocked: list[str] = []
    max_cost = _decimal_or_none(payload.max_billing_units or payload.max_cost)
    if not payload.confirm_live:
        blocked.append("confirm_live_required")
    if not payload.execute_paid:
        blocked.append("execute_paid_required")
    if not profile.secret_env_var or not os.getenv(profile.secret_env_var):
        blocked.append("secret_not_configured")
    if max_cost is None or max_cost <= Decimal("0"):
        blocked.append("positive_max_billing_units_required")
    if max_cost is not None and max_cost > Decimal("500"):
        blocked.append("max_billing_units_exceeds_safety_limit")
    if payload.canary_image_only and max_cost is not None and max_cost > Decimal("10"):
        blocked.append("canary_max_billing_units_exceeds_limit")
    if payload.canary_image_only and payload.canary_video_first_last:
        blocked.append("canary_modes_are_mutually_exclusive")
    if payload.canary_video_first_last and max_cost is not None and not Decimal("20") <= max_cost <= Decimal("25"):
        blocked.append("video_canary_budget_must_be_20_to_25")
    if profile.provider_key != "toapis":
        blocked.append("toapis_provider_required")
    if payload.billing_unit != "TOAPIS_CREDIT":
        blocked.append("billing_unit_mismatch")
    estimate: str | None = None
    if not blocked:
        from app.services import live_orchestration
        try:
            gate = live_orchestration.validate_live_orchestration_gate(
                session, profile=profile, expected_snapshot_hash=payload.pricing_snapshot_hash,
                check_active_verification=True, required_billing_units=max_cost,
            )
            models = live_orchestration._models(session, profile.id or 0)
            estimate = (
                str(live_orchestration._reviewed_rule_price(models[live_orchestration.IMAGE_MODEL_KEY], live_orchestration.IMAGE_UNIT))
                if payload.canary_image_only else
                str(live_orchestration._reviewed_rule_price(models[live_orchestration.VIDEO_MODEL_KEY], live_orchestration.VIDEO_UNIT))
                if payload.canary_video_first_last else live_orchestration.two_shot_estimate(models)
            )
            if max_cost is None or Decimal(estimate) > max_cost:
                blocked.append("budget_below_estimate")
            if payload.pricing_snapshot_hash != gate["pricing_snapshot_hash"]:
                blocked.append("pricing_snapshot_mismatch")
        except AppError as exc:
            session.rollback()
            blocked.append(exc.code.lower())
    run = ProviderVerificationRun(
        provider_profile_id=profile.id or 0,
        model_profile_id=payload.model_profile_id,
        verification_type=(
            ProviderVerificationType.LIVE_CANARY if payload.canary_image_only else
            ProviderVerificationType.LIVE_VIDEO_CANARY if payload.canary_video_first_last else
            ProviderVerificationType.LIVE_CHAIN
        ),
        status=ProviderVerificationStatus.BLOCKED if blocked else ProviderVerificationStatus.RUNNING,
        started_at=utcnow(),
        completed_at=utcnow() if blocked else None,
        max_cost=str(max_cost) if max_cost is not None else None,
        workflow_version=(
            "toapis-image-canary-v1" if payload.canary_image_only else
            "toapis-video-canary-v1" if payload.canary_video_first_last else "toapis-two-shot-v1"
        ),
        current_stage="BLOCKED" if blocked else "CREATED",
        pricing_snapshot_hash=payload.pricing_snapshot_hash,
        billing_unit=payload.billing_unit,
        estimated_billing_units=estimate,
        reserved_billing_units=estimate,
        auto_approve_for_verification=payload.auto_approve_for_verification,
        canary_image_only=payload.canary_image_only,
        summary_json=dumps({"blocked": blocked, "network_performed": False, "approval_semantics": "WORKFLOW_VERIFICATION_APPROVAL"}),
        error_code="BLOCKED_LIVE_VERIFICATION" if blocked else None,
        error_message="Live verification creation was blocked by a safety gate." if blocked else "",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return verification_payload(run)


def load_registry_with_db(session: Session) -> ProviderRegistry:
    registry = load_registry_from_env()
    for profile in session.exec(
        select(ProviderProfile).where(
            col(ProviderProfile.enabled).is_(True),
            col(ProviderProfile.archived_at).is_(None),
        )
    ).all():
        if profile.adapter_type == ProviderAdapterType.FAKE:
            continue
        if profile.adapter_type == ProviderAdapterType.TOAPIS:
            api_key = os.getenv(profile.secret_env_var) if profile.secret_env_var else None
            if api_key:
                # Callers must pass the durable live-orchestration gate before invoking TOAPIS.
                # Keeping this instance usable avoids caching a stale startup-time flag.
                registry.register(ToApisProvider(api_key, base_url=profile.base_url, allow_live_submit=True))
            else:
                registry.register_configuration_error(profile.provider_key, profile.display_name, "TOAPIS_API_KEY is not configured.")
        else:
            config = db_profile_to_http_config(session, profile)
            registry.register(MappedAsyncHttpProvider(config))
    return registry


def db_profile_to_http_config(session: Session, profile: ProviderProfile) -> MappedHttpProviderConfig:
    config = loads_dict(profile.config_json)
    models = session.exec(select(ProviderModelProfile).where(ProviderModelProfile.provider_profile_id == profile.id)).all()
    caps = _capabilities_from_models(profile, models)
    payload = {
        **config,
        "provider_id": profile.provider_key,
        "display_name": profile.display_name or profile.name,
        "base_url": profile.base_url,
        "capabilities": caps.model_dump(),
    }
    return MappedHttpProviderConfig.model_validate(payload)


def snapshot_for_provider(session: Session, provider_key: str, model_key: str | None) -> dict[str, Any]:
    profile = session.exec(select(ProviderProfile).where(ProviderProfile.provider_key == provider_key)).first()
    if profile is None:
        return {"provider_key": provider_key, "provider_model_key": model_key, "pricing": {}, "capabilities": {}, "revision": None}
    model = _find_model(session, profile.id or 0, model_key)
    return {
        "provider_profile_id": profile.id,
        "provider_key": profile.provider_key,
        "provider_model_profile_id": model.id if model else None,
        "provider_model_key": model.model_key if model else model_key,
        "revision": profile.config_revision,
        "pricing": loads_dict(model.pricing_json) if model else {},
        "currency": model.currency if model else "USD",
        "billing_unit": model.billing_unit if model else "USD",
        "pricing_version": model.pricing_version if model else "",
        "pricing_snapshot_hash": model.pricing_snapshot_hash if model else None,
        "provider_live_enable_snapshot": profile.live_orchestration_enabled,
        "contract_review_reference": profile.contract_reference,
        "preflight_checked_at": profile.preflight_checked_at.isoformat() if profile.preflight_checked_at else None,
        "capabilities": loads_dict(model.capabilities_json) if model else {},
        "limits": loads_dict(model.limits_json) if model else {},
    }


def create_estimate_for_request(session: Session, request: GenerationRequest) -> GenerationUsageRecord:
    existing = session.exec(
        select(GenerationUsageRecord).where(
            GenerationUsageRecord.generation_request_id == request.id,
            GenerationUsageRecord.record_type == UsageRecordType.ESTIMATE,
            col(GenerationUsageRecord.generation_task_id).is_(None),
        )
    ).first()
    if existing:
        return existing
    snapshot = loads_dict(request.pricing_snapshot_json)
    pricing = loads_dict(json.dumps(snapshot.get("pricing") or {}))
    currency = str(snapshot.get("currency") or "USD").upper()
    billing_unit = str(snapshot.get("billing_unit") or currency).upper()
    units = estimated_units(request)
    cost = estimate_cost(units, pricing)
    status = UsageRecordStatus.ESTIMATED if cost is not None else UsageRecordStatus.UNKNOWN
    source = UsageCostSource.FAKE_PROVIDER if request.effective_provider_id in {"mock", "fake-http"} and cost == Decimal("0") else (
        UsageCostSource.PRICING_RULE if cost is not None else UsageCostSource.UNKNOWN
    )
    record = GenerationUsageRecord(
        project_id=request.project_id,
        shot_id=request.shot_id,
        generation_request_id=request.id,
        provider_profile_id=_int_or_none(snapshot.get("provider_profile_id")),
        provider_model_profile_id=_int_or_none(snapshot.get("provider_model_profile_id")),
        attempt_number=1,
        record_type=UsageRecordType.ESTIMATE,
        status=status,
        currency=currency,
        billing_unit=billing_unit,
        estimated_units_json=dumps(units),
        estimated_cost=format_decimal(cost) if cost is not None else None,
        cost_source=source,
    )
    session.add(record)
    session.flush()
    return record


def ensure_task_usage_estimate(session: Session, task: GenerationTask) -> None:
    request = session.get(GenerationRequest, task.generation_request_id)
    if request is None:
        return
    existing = session.exec(
        select(GenerationUsageRecord).where(
            GenerationUsageRecord.generation_task_id == task.id,
            GenerationUsageRecord.attempt_number == task.attempt_number,
            GenerationUsageRecord.record_type == UsageRecordType.ESTIMATE,
        )
    ).first()
    if existing:
        return
    base = create_estimate_for_request(session, request)
    task_record = GenerationUsageRecord(
        project_id=task.project_id,
        shot_id=task.shot_id,
        generation_request_id=request.id,
        generation_task_id=task.id,
        provider_profile_id=base.provider_profile_id,
        provider_model_profile_id=base.provider_model_profile_id,
        attempt_number=task.attempt_number,
        record_type=UsageRecordType.ESTIMATE,
        status=base.status,
        currency=base.currency,
        billing_unit=base.billing_unit,
        estimated_units_json=base.estimated_units_json,
        estimated_cost=base.estimated_cost,
        cost_source=base.cost_source,
    )
    session.add(task_record)
    session.flush()


def record_actual_from_provider(session: Session, task: GenerationTask, metadata: dict[str, Any] | None = None) -> None:
    existing = session.exec(
        select(GenerationUsageRecord).where(
            GenerationUsageRecord.generation_task_id == task.id,
            GenerationUsageRecord.attempt_number == task.attempt_number,
            GenerationUsageRecord.record_type == UsageRecordType.PROVIDER_REPORTED,
        )
    ).first()
    if existing:
        return
    request = session.get(GenerationRequest, task.generation_request_id)
    provider_usage = sanitize_provider_usage(metadata or {})
    snapshot = loads_dict(request.pricing_snapshot_json if request else "{}")
    currency = str(provider_usage.get("currency") or snapshot.get("currency") or "USD").upper()
    billing_unit = str(snapshot.get("billing_unit") or currency).upper()
    actual_cost = _decimal_or_none(provider_usage.get("provider_cost"))
    units = {key: value for key, value in provider_usage.items() if key in {"billed_seconds", "generated_images", "input_images", "output_pixels"}}
    if actual_cost is None and units:
        actual_cost = estimate_cost(units, loads_dict(json.dumps(snapshot.get("pricing") or {})))
    if actual_cost is None and task.provider_id in {"mock", "fake-http"}:
        actual_cost = Decimal("0")
        source = UsageCostSource.FAKE_PROVIDER
        status = UsageRecordStatus.ACTUAL
    elif actual_cost is None:
        source = UsageCostSource.UNKNOWN
        status = UsageRecordStatus.UNKNOWN
    else:
        source = UsageCostSource.PROVIDER_RESPONSE if provider_usage.get("provider_cost") is not None else UsageCostSource.PRICING_RULE
        status = UsageRecordStatus.ACTUAL
    record = GenerationUsageRecord(
        project_id=task.project_id,
        shot_id=task.shot_id,
        generation_request_id=task.generation_request_id,
        generation_task_id=task.id,
        provider_profile_id=_int_or_none(snapshot.get("provider_profile_id")),
        provider_model_profile_id=_int_or_none(snapshot.get("provider_model_profile_id")),
        attempt_number=task.attempt_number,
        record_type=UsageRecordType.PROVIDER_REPORTED,
        status=status,
        currency=currency,
        billing_unit=billing_unit,
        actual_units_json=dumps(units),
        actual_cost=format_decimal(actual_cost) if actual_cost is not None else None,
        cost_source=source,
        provider_usage_json=dumps(provider_usage),
    )
    session.add(record)
    session.flush()


def budget_for_project(session: Session, project_id: int) -> dict[str, Any]:
    project = session.get(Project, project_id)
    if project is None:
        raise AppError("PROJECT_NOT_FOUND", f"Project {project_id} was not found.", 404)
    policy = session.exec(
        select(ProjectBudgetPolicy).where(
            ProjectBudgetPolicy.project_id == project_id,
            ProjectBudgetPolicy.period_type == BudgetPeriodType.PROJECT_TOTAL,
        )
    ).first()
    if policy is None:
        return {
            "id": None,
            "project_id": project_id,
            "currency": "USD",
            "billing_unit": "USD",
            "warning_limit": None,
            "hard_limit": None,
            "per_request_limit": None,
            "period_type": BudgetPeriodType.PROJECT_TOTAL,
            "unknown_cost_policy": UnknownCostPolicy.ALLOW_WITH_WARNING,
            "enabled": False,
            "created_at": None,
            "updated_at": None,
        }
    return policy.model_dump()


def update_budget(session: Session, project_id: int, payload: ProjectBudgetPolicyUpdate) -> dict[str, Any]:
    if session.get(Project, project_id) is None:
        raise AppError("PROJECT_NOT_FOUND", f"Project {project_id} was not found.", 404)
    policy = session.exec(
        select(ProjectBudgetPolicy).where(
            ProjectBudgetPolicy.project_id == project_id,
            ProjectBudgetPolicy.period_type == payload.period_type,
        )
    ).first()
    if policy is None:
        policy = ProjectBudgetPolicy(project_id=project_id)
    policy.currency = payload.currency.upper()
    policy.billing_unit = payload.billing_unit.upper()
    policy.warning_limit = payload.warning_limit
    policy.hard_limit = payload.hard_limit
    policy.per_request_limit = payload.per_request_limit
    policy.period_type = payload.period_type
    policy.unknown_cost_policy = payload.unknown_cost_policy
    policy.enabled = payload.enabled
    policy.updated_at = utcnow()
    session.add(policy)
    session.commit()
    session.refresh(policy)
    return policy.model_dump()


def check_budget_before_task(session: Session, request: GenerationRequest) -> list[str]:
    policy = session.exec(
        select(ProjectBudgetPolicy).where(
            ProjectBudgetPolicy.project_id == request.project_id,
            col(ProjectBudgetPolicy.enabled).is_(True),
            ProjectBudgetPolicy.period_type == BudgetPeriodType.PROJECT_TOTAL,
        )
    ).first()
    if policy is None or request.effective_provider_id in {"mock", "fake-http"}:
        return []
    estimate = create_estimate_for_request(session, request)
    if estimate.billing_unit != policy.billing_unit:
        raise AppError("BILLING_UNIT_MISMATCH", "Budget billing unit does not match the Provider estimate.", 409)
    if estimate.estimated_cost is None:
        if policy.unknown_cost_policy == UnknownCostPolicy.BLOCK:
            raise AppError("BUDGET_UNKNOWN_COST_BLOCKED", "Budget policy blocks requests with unknown estimated cost.", 409)
        return ["estimated_cost_unknown"]
    estimate_cost_value = Decimal(estimate.estimated_cost)
    if policy.per_request_limit and estimate_cost_value > Decimal(policy.per_request_limit):
        raise AppError("BUDGET_PER_REQUEST_LIMIT_EXCEEDED", "Estimated request cost exceeds per-request limit.", 409)
    committed = committed_estimated_total(
        session,
        request.project_id,
        policy.billing_unit,
        exclude_generation_request_id=request.id,
    )
    projected = committed + estimate_cost_value
    if policy.hard_limit and projected > Decimal(policy.hard_limit):
        raise AppError("BUDGET_HARD_LIMIT_EXCEEDED", "Estimated project cost exceeds hard budget limit.", 409)
    if policy.warning_limit and projected > Decimal(policy.warning_limit):
        return ["budget_warning_limit_exceeded"]
    return []


def usage_summary(session: Session, project_id: int) -> dict[str, Any]:
    records = session.exec(select(GenerationUsageRecord).where(GenerationUsageRecord.project_id == project_id)).all()
    currencies: dict[str, dict[str, Decimal]] = {}
    unknown = 0
    pending: dict[str, Decimal] = {}
    for record in records:
        bucket = currencies.setdefault(record.currency, {"estimated_total": Decimal("0"), "actual_total": Decimal("0")})
        if record.estimated_cost and record.record_type == UsageRecordType.ESTIMATE and record.generation_task_id is None:
            bucket["estimated_total"] += Decimal(record.estimated_cost)
            if record.status == UsageRecordStatus.ESTIMATED:
                pending[record.currency] = pending.get(record.currency, Decimal("0")) + Decimal(record.estimated_cost)
        if record.actual_cost:
            bucket["actual_total"] += Decimal(record.actual_cost)
        if record.status == UsageRecordStatus.UNKNOWN:
            unknown += 1
    requests = session.exec(select(GenerationRequest).where(GenerationRequest.project_id == project_id)).all()
    return {
        "currencies": [
            {"currency": currency, "estimated_total": format_decimal(values["estimated_total"]), "actual_total": format_decimal(values["actual_total"])}
            for currency, values in sorted(currencies.items())
        ],
        "unknown_cost_count": unknown,
        "pending_estimate_total": {currency: format_decimal(value) for currency, value in sorted(pending.items())},
        "request_count": len(requests),
        "image_request_count": len([item for item in requests if item.kind == GenerationKind.KEYFRAME]),
        "video_request_count": len([item for item in requests if item.kind == GenerationKind.VIDEO]),
        "failed_request_count": len([item for item in requests if item.status == GenerationTaskStatus.FAILED]),
        "cancelled_request_count": 0,
        "provider_breakdown": _breakdown(records, "provider_profile_id"),
        "model_breakdown": _breakdown(records, "provider_model_profile_id"),
        "period_start": None,
        "period_end": None,
    }


def usage_records(session: Session, project_id: int) -> list[dict[str, Any]]:
    records = session.exec(
        select(GenerationUsageRecord).where(GenerationUsageRecord.project_id == project_id).order_by(col(GenerationUsageRecord.created_at))
    ).all()
    return [usage_payload(item) for item in records]


def request_usage(session: Session, request_id: int) -> list[dict[str, Any]]:
    records = session.exec(
        select(GenerationUsageRecord).where(GenerationUsageRecord.generation_request_id == request_id).order_by(col(GenerationUsageRecord.created_at))
    ).all()
    return [usage_payload(item) for item in records]


def usage_csv(session: Session, project_id: int) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["created_at", "shot_id", "request_id", "task_id", "provider", "model", "attempt", "generation_type", "status", "estimated_cost", "actual_cost", "currency", "cost_source"])
    for record in usage_records(session, project_id):
        writer.writerow([
            _csv_cell(record["created_at"]),
            _csv_cell(record["shot_id"]),
            _csv_cell(record["generation_request_id"]),
            _csv_cell(record["generation_task_id"]),
            _csv_cell(record["provider_profile_id"]),
            _csv_cell(record["provider_model_profile_id"]),
            _csv_cell(record["attempt_number"]),
            _csv_cell(record["record_type"]),
            _csv_cell(record["status"]),
            _csv_cell(record["estimated_cost"]),
            _csv_cell(record["actual_cost"]),
            _csv_cell(record["currency"]),
            _csv_cell(record["cost_source"]),
        ])
    return "\ufeff" + output.getvalue()


def provider_profile_payload(session: Session, profile: ProviderProfile) -> dict[str, Any]:
    validation = {
        "secret_configured": bool(profile.secret_env_var and os.getenv(profile.secret_env_var)),
        "configuration_valid": True,
        "contract_verified": latest_contract_passed(session, profile.id or 0),
        "live_verified": latest_live_passed(session, profile.id or 0),
    }
    return {**profile.model_dump(exclude={"config_json"}), "config": loads_dict(profile.config_json), **validation}


def provider_model_payload(model: ProviderModelProfile) -> dict[str, Any]:
    return {
        **model.model_dump(exclude={"capabilities_json", "limits_json", "pricing_json"}),
        "capabilities": loads_dict(model.capabilities_json),
        "limits": loads_dict(model.limits_json),
        "pricing": loads_dict(model.pricing_json),
    }


def usage_payload(record: GenerationUsageRecord) -> dict[str, Any]:
    return {
        **record.model_dump(exclude={"estimated_units_json", "actual_units_json", "provider_usage_json"}),
        "estimated_units": loads_dict(record.estimated_units_json),
        "actual_units": loads_dict(record.actual_units_json),
        "provider_usage": loads_dict(record.provider_usage_json),
    }


def verification_payload(run: ProviderVerificationRun) -> dict[str, Any]:
    return {**run.model_dump(exclude={"summary_json"}), "summary": loads_dict(run.summary_json)}


def validate_provider_config(config: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in config.items():
        lowered = key.lower()
        if any(token in lowered for token in SENSITIVE_KEYS):
            raise AppError("PROVIDER_CONFIG_SECRET_FIELD", "Provider config must not contain secret fields.", 400)
        if key not in SAFE_CONFIG_KEYS:
            raise AppError("PROVIDER_CONFIG_FIELD_NOT_ALLOWED", f"Provider config field is not allowed: {key}.", 400)
        cleaned[key] = _reject_sensitive_value(value)
    return cleaned


def validate_pricing(pricing: dict[str, Any]) -> dict[str, Any]:
    rules = pricing.get("rules", [])
    if not isinstance(rules, list):
        raise AppError("INVALID_PRICING_RULES", "pricing.rules must be a list.", 400)
    for rule in rules:
        if not isinstance(rule, dict) or "unit" not in rule or "price" not in rule:
            raise AppError("INVALID_PRICING_RULE", "Each pricing rule requires unit and price.", 400)
        _decimal_or_error(rule["price"], "INVALID_PRICING_PRICE")
    return pricing


def estimated_units(request: GenerationRequest) -> dict[str, Any]:
    input_ids = loads_list(request.input_asset_ids)
    reference_ids = []
    structured = loads_dict(request.structured_payload_json)
    if isinstance(structured.get("reference_asset_ids"), list):
        reference_ids = [item for item in structured["reference_asset_ids"] if isinstance(item, int)]
    if request.kind == GenerationKind.KEYFRAME:
        return {"IMAGE_COUNT": 1, "INPUT_IMAGE": len(reference_ids), "REQUEST": 1}
    return {
        "VIDEO_SECOND": str(request.duration_seconds or 0),
        "INPUT_IMAGE": len(input_ids) + len(reference_ids),
        "REQUEST": 1,
    }


def get_verification_run(session: Session, run_id: int) -> dict[str, Any]:
    run = session.get(ProviderVerificationRun, run_id)
    if run is None:
        raise AppError("PROVIDER_VERIFICATION_RUN_NOT_FOUND", "Provider verification run was not found.", 404)
    return verification_payload(run)


def estimate_cost(units: dict[str, Any], pricing: dict[str, Any]) -> Decimal | None:
    rules = pricing.get("rules", [])
    if not isinstance(rules, list) or not rules:
        return None
    total = Decimal("0")
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        unit = str(rule.get("unit") or "")
        if unit not in units:
            continue
        total += _decimal_or_error(rule.get("price"), "INVALID_PRICING_PRICE") * _decimal_or_error(units[unit], "INVALID_USAGE_UNIT")
    return total


def committed_estimated_total(
    session: Session,
    project_id: int,
    billing_unit: str,
    *,
    exclude_generation_request_id: int | None = None,
) -> Decimal:
    statement = select(GenerationUsageRecord).where(
        GenerationUsageRecord.project_id == project_id,
        GenerationUsageRecord.billing_unit == billing_unit,
        GenerationUsageRecord.record_type == UsageRecordType.ESTIMATE,
        col(GenerationUsageRecord.generation_task_id).is_(None),
    )
    if exclude_generation_request_id is not None:
        statement = statement.where(GenerationUsageRecord.generation_request_id != exclude_generation_request_id)
    records = session.exec(statement).all()
    return sum((Decimal(item.estimated_cost) for item in records if item.estimated_cost), Decimal("0"))


def sanitize_provider_usage(metadata: dict[str, Any]) -> dict[str, Any]:
    return redact_sensitive({key: metadata[key] for key in USAGE_WHITELIST if key in metadata})


def latest_contract_passed(session: Session, provider_id: int) -> bool:
    run = session.exec(
        select(ProviderVerificationRun)
        .where(
            ProviderVerificationRun.provider_profile_id == provider_id,
            ProviderVerificationRun.verification_type == ProviderVerificationType.CONTRACT,
        )
        .order_by(col(ProviderVerificationRun.created_at).desc(), col(ProviderVerificationRun.id).desc())
    ).first()
    return bool(run and run.status == ProviderVerificationStatus.PASSED)


def latest_live_passed(session: Session, provider_id: int) -> bool:
    run = session.exec(
        select(ProviderVerificationRun)
        .where(
            ProviderVerificationRun.provider_profile_id == provider_id,
            col(ProviderVerificationRun.verification_type).in_([ProviderVerificationType.LIVE_IMAGE, ProviderVerificationType.LIVE_VIDEO, ProviderVerificationType.LIVE_CHAIN]),
        )
        .order_by(col(ProviderVerificationRun.created_at).desc(), col(ProviderVerificationRun.id).desc())
    ).first()
    return bool(run and run.status == ProviderVerificationStatus.PASSED)


def _capabilities_from_models(profile: ProviderProfile, models: Sequence[ProviderModelProfile]) -> ProviderCapabilities:
    image_models = [item for item in models if item.enabled and item.generation_type == ProviderModelGenerationType.IMAGE]
    video_models = [item for item in models if item.enabled and item.generation_type == ProviderModelGenerationType.VIDEO]
    merged = {}
    for model in models:
        merged.update(loads_dict(model.capabilities_json))
        merged.update(loads_dict(model.limits_json))
    return ProviderCapabilities(
        provider_id=profile.provider_key,
        display_name=profile.display_name or profile.name,
        text_to_image=bool(image_models),
        image_to_video=bool(video_models),
        first_last_frame_video=bool(merged.get("first_last_frame_video")),
        supports_seed=bool(merged.get("seed")),
        supports_cancel=bool(merged.get("cancel")),
        supports_negative_prompt=True,
        max_reference_images=int(merged.get("max_reference_images") or 0),
        max_duration_seconds=merged.get("max_duration_seconds") if isinstance(merged.get("max_duration_seconds"), (int, float)) else None,
        supported_aspect_ratios=[item for item in merged.get("supported_aspect_ratios", []) if isinstance(item, str)] if isinstance(merged.get("supported_aspect_ratios"), list) else [],
    )


def _find_model(session: Session, provider_profile_id: int, model_key: str | None) -> ProviderModelProfile | None:
    statement = select(ProviderModelProfile).where(ProviderModelProfile.provider_profile_id == provider_profile_id)
    if model_key:
        statement = statement.where(ProviderModelProfile.model_key == model_key)
    return session.exec(statement.order_by(col(ProviderModelProfile.id))).first()


def _validate_base_url(url: str, *, allow_local: bool) -> None:
    if not url:
        return
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError("INVALID_PROVIDER_BASE_URL", "Provider base_url must be an HTTP(S) URL.", 400)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} and not allow_local:
        raise AppError("LOCAL_PROVIDER_URL_NOT_ALLOWED", "Local Provider endpoints require an explicit fake/local adapter.", 400)


def _reject_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in value:
            if any(token in str(key).lower() for token in SENSITIVE_KEYS):
                raise AppError("PROVIDER_CONFIG_SECRET_FIELD", "Provider config must not contain secret fields.", 400)
        return {key: _reject_sensitive_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_reject_sensitive_value(item) for item in value]
    return value


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in {None, ""}:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_or_error(value: Any, code: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AppError(code, "Invalid decimal value.", 400) from exc


def format_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.00000001")).normalize(), "f")


def _breakdown(records: Sequence[GenerationUsageRecord], field: str) -> list[dict[str, Any]]:
    buckets: dict[str, int] = {}
    for record in records:
        key = str(getattr(record, field) or "unknown")
        buckets[key] = buckets.get(key, 0) + 1
    return [{"key": key, "record_count": count} for key, count in sorted(buckets.items())]


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def dumps(value: Any) -> str:
    return json.dumps(redact_sensitive(value), ensure_ascii=True, sort_keys=True)


def loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []
