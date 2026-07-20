import json

import pytest
from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.entities import (
    BudgetPeriodType,
    GenerationKind,
    GenerationUsageRecord,
    Project,
    ProviderAdapterType,
    ProviderModelGenerationType,
    Shot,
    UnknownCostPolicy,
    UsageCostSource,
    UsageRecordStatus,
    UsageRecordType,
)
from app.models.schemas import (
    LiveVerificationRequest,
    ProjectBudgetPolicyUpdate,
    ProviderModelProfileCreate,
    ProviderProfileCreate,
)
from app.services import provider_management, task_service


def _request(
    session: Session,
    *,
    provider_id: str = "real-provider",
    pricing: dict[str, object] | None = None,
    model: str = "model-1",
) -> int:
    project = Project(name="Usage", description="")
    session.add(project)
    session.commit()
    session.refresh(project)
    shot = Shot(project_id=project.id or 0, title="Shot", description="", duration_seconds=4.0, sort_order=0)
    session.add(shot)
    session.commit()
    session.refresh(shot)
    snapshot = {
        "provider_key": provider_id,
        "provider_model_key": model,
        "pricing": pricing or {},
        "currency": "USD",
    }
    request = task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot.id or 0,
        kind=GenerationKind.KEYFRAME,
        provider_name=provider_id,
        effective_provider_id=provider_id,
        model=model,
        prompt_snapshot="prompt",
        pricing_snapshot_json=json.dumps(snapshot),
    )
    return request.id or 0


def test_provider_profile_rejects_secret_config_fields(session: Session) -> None:
    payload = ProviderProfileCreate(
        name="Unsafe",
        provider_key="unsafe",
        adapter_type=ProviderAdapterType.MAPPED_ASYNC_HTTP,
        base_url="https://provider.example",
        config={"api_key": "must-not-be-here"},
    )

    with pytest.raises(AppError) as exc:
        provider_management.create_provider_profile(session, payload)

    assert exc.value.code == "PROVIDER_CONFIG_SECRET_FIELD"


def test_unknown_estimate_keeps_cost_null_instead_of_zero(session: Session) -> None:
    request = session.get(task_service.GenerationRequest, _request(session, pricing={}))
    assert request is not None

    record = provider_management.create_estimate_for_request(session, request)

    assert record.status == UsageRecordStatus.UNKNOWN
    assert record.estimated_cost is None
    assert record.cost_source == UsageCostSource.UNKNOWN


def test_usage_summary_does_not_double_count_task_attempt_estimate(session: Session) -> None:
    request = session.get(task_service.GenerationRequest, _request(session, pricing={"rules": [{"unit": "REQUEST", "price": "0.25"}]}))
    assert request is not None
    task_service.create_task_attempt(session, generation_request=request, provider_id="real-provider")

    records = session.exec(select(GenerationUsageRecord)).all()
    estimate_records = [item for item in records if item.record_type == UsageRecordType.ESTIMATE]
    summary = provider_management.usage_summary(session, request.project_id)

    assert len(estimate_records) == 2
    assert summary["currencies"] == [{"currency": "USD", "estimated_total": "0.25", "actual_total": "0"}]


def test_budget_hard_limit_uses_current_request_once(session: Session) -> None:
    request = session.get(task_service.GenerationRequest, _request(session, pricing={"rules": [{"unit": "REQUEST", "price": "0.25"}]}))
    assert request is not None
    provider_management.update_budget(
        session,
        request.project_id,
        ProjectBudgetPolicyUpdate(
            currency="USD",
            hard_limit="0.20",
            period_type=BudgetPeriodType.PROJECT_TOTAL,
            unknown_cost_policy=UnknownCostPolicy.ALLOW_WITH_WARNING,
            enabled=True,
        ),
    )

    with pytest.raises(AppError) as exc:
        provider_management.check_budget_before_task(session, request)

    assert exc.value.code == "BUDGET_HARD_LIMIT_EXCEEDED"


def test_fake_provider_bypasses_budget_hard_limit(session: Session) -> None:
    request = session.get(
        task_service.GenerationRequest,
        _request(session, provider_id="fake-http", pricing={"rules": [{"unit": "REQUEST", "price": "99"}]}),
    )
    assert request is not None
    provider_management.update_budget(
        session,
        request.project_id,
        ProjectBudgetPolicyUpdate(currency="USD", hard_limit="0.01", enabled=True),
    )

    assert provider_management.check_budget_before_task(session, request) == []


def test_live_verification_defaults_to_blocked_without_network(session: Session) -> None:
    profile = provider_management.create_provider_profile(
        session,
        ProviderProfileCreate(
            name="Vendor",
            provider_key="vendor",
            adapter_type=ProviderAdapterType.MAPPED_ASYNC_HTTP,
            base_url="https://provider.example",
            config={},
        ),
    )
    model = provider_management.create_provider_model(
        session,
        profile["id"],
        ProviderModelProfileCreate(
            model_key="video-1",
            generation_type=ProviderModelGenerationType.VIDEO,
            pricing={"rules": [{"unit": "REQUEST", "price": "1"}]},
        ),
    )

    run = provider_management.verify_live(
        session,
        profile["id"],
        LiveVerificationRequest(confirm_live=False, model_profile_id=model["id"], max_cost="1"),
    )

    assert run["status"] == "BLOCKED"
    assert run["error_code"] == "BLOCKED_LIVE_VERIFICATION"
    assert run["summary"]["network_performed"] is False
