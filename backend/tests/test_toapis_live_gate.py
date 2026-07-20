from datetime import timedelta
import httpx
import pytest
from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.entities import (
    PricingReviewStatus, ProviderAdapterType, ProviderModelGenerationType,
    ProviderModelProfile, ProviderProfile, ProviderVerificationRun,
    ProviderVerificationStatus, ProviderVerificationType, utcnow,
)
from app.models.schemas import ToApisAccountBalanceRequest, ToApisLiveEnableRequest, ToApisPricingReviewRequest
from app.services import live_orchestration


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def setup_toapis(session: Session) -> ProviderProfile:
    profile = ProviderProfile(name="TOAPIS", provider_key="toapis", adapter_type=ProviderAdapterType.TOAPIS, display_name="TOAPIS", base_url="https://toapis.com/v1", secret_env_var="TOAPIS_API_KEY")
    session.add(profile)
    session.flush()
    session.add(ProviderModelProfile(provider_profile_id=profile.id or 0, model_key="toapis-seedream-5", remote_model="doubao-seedream-5-0", generation_type=ProviderModelGenerationType.IMAGE, pricing_json='{"rules":[{"unit":"IMAGE_REQUEST","price":"6.3"}]}', billing_unit="TOAPIS_CREDIT", pricing_version="toapis-public-2026-07", pricing_review_status=PricingReviewStatus.PENDING))
    session.add(ProviderModelProfile(provider_profile_id=profile.id or 0, model_key="toapis-viduq3-pro", remote_model="viduq3-pro", generation_type=ProviderModelGenerationType.VIDEO, pricing_json='{"rules":[{"unit":"VIDEO_SECOND","price":"20"}]}', billing_unit="TOAPIS_CREDIT", pricing_version="toapis-public-2026-07", pricing_review_status=PricingReviewStatus.PENDING))
    session.add(ProviderVerificationRun(provider_profile_id=profile.id or 0, verification_type=ProviderVerificationType.CONTRACT, status=ProviderVerificationStatus.PASSED, started_at=utcnow(), completed_at=utcnow()))
    session.commit()
    return profile


def review_request(**changes: object) -> ToApisPricingReviewRequest:
    values = dict(pricing_version="toapis-public-2026-07", image_price="6.3", image_unit="IMAGE_REQUEST", video_price="20", video_unit="VIDEO_SECOND", billing_unit="TOAPIS_CREDIT", contract_reference="Public pricing reviewed 2026-07-20", acknowledged=True)
    values.update(changes)
    return ToApisPricingReviewRequest.model_validate(values)


def test_pricing_review_requires_exact_candidate(session: Session) -> None:
    setup_toapis(session)
    with pytest.raises(AppError) as caught:
        live_orchestration.review_pricing(session, review_request(image_price="6.4"))
    assert caught.value.code == "PRICING_SNAPSHOT_MISMATCH"
    state = live_orchestration.review_pricing(session, review_request())
    assert state["pricing_reviewed"] is True
    assert state["pricing_snapshot_hash"] == live_orchestration.candidate_snapshot_hash()


@pytest.mark.anyio
async def test_preflight_saves_only_target_summary(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_toapis(session)
    monkeypatch.setenv("TOAPIS_API_KEY", "test-secret")
    paths: list[str] = []
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": [{"id": "doubao-seedream-5-0"}, {"id": "viduq3-pro"}, {"id": "unrelated-private-model"}]})
    result = await live_orchestration.run_preflight(session, transport=httpx.MockTransport(handler))
    assert result["image_model_accessible"] is True and result["video_model_accessible"] is True
    assert result["targets"] == {"doubao-seedream-5-0": True, "viduq3-pro": True}
    assert paths == ["/v1/models"]
    assert not any(path in paths for path in ("/v1/uploads/images", "/v1/images/generations", "/v1/videos/generations"))


@pytest.mark.anyio
async def test_preflight_missing_video_and_auth(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_toapis(session)
    monkeypatch.setenv("TOAPIS_API_KEY", "test-secret")
    result = await live_orchestration.run_preflight(session, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "doubao-seedream-5-0"}]})))
    assert result["video_model_accessible"] is False
    with pytest.raises(AppError) as caught:
        await live_orchestration.run_preflight(session, transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"secret": "test-secret"})))
    assert caught.value.code == "AUTHENTICATION_ERROR"


def test_live_enable_full_gate_and_disable(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = setup_toapis(session)
    monkeypatch.setenv("TOAPIS_API_KEY", "test-secret")
    reviewed = live_orchestration.review_pricing(session, review_request())
    with pytest.raises(AppError) as caught:
        live_orchestration.enable_live(session, ToApisLiveEnableRequest(acknowledged=True, pricing_snapshot_hash=reviewed["pricing_snapshot_hash"], reason="test"))
    assert caught.value.code == "MODEL_ACCESS_NOT_VERIFIED"
    profile.preflight_checked_at = utcnow()
    profile.preflight_image_model_accessible = True
    profile.preflight_video_model_accessible = True
    profile.preflight_response_schema_valid = True
    session.add(profile)
    session.commit()
    live_orchestration.confirm_account_balance(session, ToApisAccountBalanceRequest(acknowledged=True, sufficient=True))
    enabled = live_orchestration.enable_live(session, ToApisLiveEnableRequest(acknowledged=True, pricing_snapshot_hash=reviewed["pricing_snapshot_hash"], reason="isolated verification"))
    assert enabled["live_orchestration_enabled"] is True
    assert live_orchestration.disable_live(session)["live_orchestration_enabled"] is False


def test_stale_pricing_disables_live(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = setup_toapis(session)
    monkeypatch.setenv("TOAPIS_API_KEY", "test-secret")
    live_orchestration.review_pricing(session, review_request())
    for model in session.exec(select(ProviderModelProfile)).all():
        model.pricing_reviewed_at = utcnow() - timedelta(days=8)
        session.add(model)
    profile.live_orchestration_enabled = True
    session.add(profile)
    session.commit()
    state = live_orchestration.pricing_review_state(session)
    assert state["pricing_reviewed"] is False
    assert profile.live_orchestration_enabled is False


def test_secret_missing_blocks_before_enable(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_toapis(session)
    monkeypatch.delenv("TOAPIS_API_KEY", raising=False)
    live_orchestration.review_pricing(session, review_request())
    with pytest.raises(AppError) as caught:
        live_orchestration.validate_live_orchestration_gate(session, require_enabled=False)
    assert caught.value.code == "SECRET_NOT_CONFIGURED"
