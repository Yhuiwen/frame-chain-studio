from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextlib import AbstractContextManager
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import shutil

import httpx
import pytest
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel, create_engine, select

import fake_provider.app as fake_provider_app
from app.core.config import get_settings
from app.models.entities import (
    Asset,
    AssetType,
    GenerationKind,
    GenerationRequest,
    PricingReviewStatus,
    ProviderAdapterType,
    ProviderModelGenerationType,
    ProviderModelProfile,
    Project,
    ProviderProfile,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    Shot,
    utcnow,
)
from app.providers.async_base import AsyncGenerationProvider
from app.providers.models import (
    ImageGenerationRequest,
    ProviderCancelResult,
    ProviderCapabilities,
    ProviderJobResult,
    ProviderResultUrl,
    ProviderSubmitResult,
    RemoteJobStatus,
    VideoGenerationRequest,
)
from app.providers.registry import ProviderRegistry
from app.models.schemas import LiveVerificationRequest
from app.services import live_orchestration, provider_management, toapis_canary, toapis_verification, toapis_video_canary
from app.workers.generation_worker import GenerationWorker
from app.workers.render_service import RenderProcessingService
from app.workers.render_worker import RenderWorker
from app.workers.result_processing_service import ResultProcessingService, ResultWorkerSettings
from app.workers.result_worker import ResultWorker
from app.workers.settings import WorkerSettings


def test_paid_verification_prompts_are_frozen_and_safe() -> None:
    prompts = toapis_verification.SHOT_PROMPTS
    assert set(prompts) == {
        (1, GenerationKind.KEYFRAME),
        (1, GenerationKind.VIDEO),
        (2, GenerationKind.KEYFRAME),
        (2, GenerationKind.VIDEO),
    }
    for prompt in prompts.values():
        assert 1 <= len(prompt) <= 5000
        assert "TOAPIS_API_KEY" not in prompt
        assert "D:\\" not in prompt
        assert "watermark" in prompt.lower()


def configured_toapis(session: Session, monkeypatch: pytest.MonkeyPatch) -> ProviderProfile:
    monkeypatch.setenv("TOAPIS_API_KEY", "unit-test-secret")
    profile = ProviderProfile(
        name="TOAPIS", provider_key="toapis", adapter_type=ProviderAdapterType.TOAPIS,
        display_name="TOAPIS", base_url="https://toapis.com/v1", secret_env_var="TOAPIS_API_KEY",
        contract_reviewed_at=utcnow(), preflight_checked_at=utcnow(),
        preflight_image_model_accessible=True, preflight_video_model_accessible=True,
        preflight_response_schema_valid=True, account_balance_reviewed_at=utcnow(),
        account_balance_sufficient=True,
        account_balance_pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
        account_balance_confirmed_units="190",
        account_balance_evidence_type="TOKEN_BALANCE_READ_ONLY",
        live_orchestration_enabled=True,
    )
    session.add(profile)
    session.flush()
    snapshot_hash = live_orchestration.candidate_snapshot_hash()
    session.add(ProviderModelProfile(
        provider_profile_id=profile.id or 0, model_key=live_orchestration.IMAGE_MODEL_KEY,
        remote_model=live_orchestration.IMAGE_REMOTE_MODEL, generation_type=ProviderModelGenerationType.IMAGE,
        pricing_json='{"rules":[{"unit":"IMAGE_REQUEST","price":"6.3"}]}',
        billing_unit="TOAPIS_CREDIT", pricing_review_status=PricingReviewStatus.REVIEWED,
        pricing_reviewed_at=utcnow(), pricing_snapshot_hash=snapshot_hash,
        capabilities_json='{"text_to_image":true,"supported_aspect_ratios":["16:9"]}',
    ))
    session.add(ProviderModelProfile(
        provider_profile_id=profile.id or 0, model_key=live_orchestration.VIDEO_MODEL_KEY,
        remote_model=live_orchestration.VIDEO_REMOTE_MODEL, generation_type=ProviderModelGenerationType.VIDEO,
        pricing_json='{"rules":[{"unit":"VIDEO_SECOND","price":"20"}]}',
        billing_unit="TOAPIS_CREDIT", pricing_review_status=PricingReviewStatus.REVIEWED,
        pricing_reviewed_at=utcnow(), pricing_snapshot_hash=snapshot_hash,
        capabilities_json='{"image_to_video":true,"first_last_frame_video":true,"seed":true,"max_reference_images":2,"max_duration_seconds":16,"supported_aspect_ratios":["16:9"]}',
    ))
    session.add(ProviderVerificationRun(
        provider_profile_id=profile.id or 0, verification_type=ProviderVerificationType.CONTRACT,
        status=ProviderVerificationStatus.PASSED, started_at=utcnow(), completed_at=utcnow(),
    ))
    session.commit()
    return profile


def create_run(session: Session, profile: ProviderProfile) -> ProviderVerificationRun:
    payload = LiveVerificationRequest(
        confirm_live=True, execute_paid=True, billing_unit="TOAPIS_CREDIT",
        max_billing_units="172.6", pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
        auto_approve_for_verification=True,
    )
    result = provider_management.verify_live(session, profile.id or 0, payload)
    run = session.get(ProviderVerificationRun, int(result["id"]))
    assert run is not None
    return run


def install_anchor_fixture() -> None:
    settings = get_settings()
    settings.fixture_dir.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).parent / "fixtures" / "mock-keyframe.png"
    shutil.copyfile(source, settings.fixture_dir / "mock-keyframe.png")


def test_create_run_requires_independent_paid_gate(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session, profile.id or 0,
        LiveVerificationRequest(confirm_live=True, execute_paid=False, billing_unit="TOAPIS_CREDIT", max_billing_units="172.6", pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(), auto_approve_for_verification=True),
    )
    assert result["status"] == ProviderVerificationStatus.BLOCKED
    assert result["current_stage"] == "BLOCKED"
    assert session.exec(select(GenerationRequest)).all() == []


def test_advance_is_short_and_idempotent_while_waiting(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = configured_toapis(session, monkeypatch)
    install_anchor_fixture()
    run = create_run(session, profile)

    first = toapis_verification.advance(session, run.id or 0)
    assert first["stage"].value == "PROJECT_READY"
    second = toapis_verification.advance(session, run.id or 0)
    assert second["stage"].value == "SHOTS_READY"
    assert len(session.exec(select(Shot)).all()) == 2

    requested = toapis_verification.advance(session, run.id or 0)
    assert requested["stage"].value == "SHOT_1_KEYFRAME_REQUESTED"
    assert requested["image_requests_created"] == 1
    waiting = toapis_verification.advance(session, run.id or 0)
    assert waiting["stage"].value == "SHOT_1_KEYFRAME_REQUESTED"
    assert waiting["waiting_for"] == "GENERATION_TASK"
    requests = session.exec(select(GenerationRequest)).all()
    assert len(requests) == 1 and requests[0].kind == GenerationKind.KEYFRAME


def test_budget_below_estimate_is_blocked_before_run(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session, profile.id or 0,
        LiveVerificationRequest(confirm_live=True, execute_paid=True, billing_unit="TOAPIS_CREDIT", max_billing_units="172.5", pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(), auto_approve_for_verification=True),
    )
    assert result["status"] == ProviderVerificationStatus.BLOCKED
    assert "budget_below_estimate" in result["summary"]["blocked"]


@pytest.mark.parametrize(("ceiling", "expected"), [("6.2", "BLOCKED"), ("6.3", "RUNNING"), ("10", "RUNNING"), ("10.1", "BLOCKED")])
def test_image_canary_budget_boundary(
    session: Session, monkeypatch: pytest.MonkeyPatch, ceiling: str, expected: str,
) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session,
        profile.id or 0,
        LiveVerificationRequest(
            confirm_live=True,
            execute_paid=True,
            billing_unit="TOAPIS_CREDIT",
            max_billing_units=ceiling,
            pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
            canary_image_only=True,
        ),
    )
    assert result["status"].value == expected
    assert result["verification_type"] == ProviderVerificationType.LIVE_CANARY
    assert result["canary_image_only"] is True


@pytest.mark.parametrize(("ceiling", "expected"), [("19.9", "BLOCKED"), ("20", "RUNNING"), ("25", "RUNNING"), ("25.1", "BLOCKED")])
def test_video_canary_budget_boundary(
    session: Session, monkeypatch: pytest.MonkeyPatch, ceiling: str, expected: str,
) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session, profile.id or 0,
        LiveVerificationRequest(
            confirm_live=True, execute_paid=True, billing_unit="TOAPIS_CREDIT",
            max_billing_units=ceiling, pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
            canary_video_first_last=True,
        ),
    )
    assert result["status"].value == expected


def test_image_canary_creates_one_shot_and_one_image_request(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session,
        profile.id or 0,
        LiveVerificationRequest(
            confirm_live=True,
            execute_paid=True,
            billing_unit="TOAPIS_CREDIT",
            max_billing_units="10",
            pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
            canary_image_only=True,
        ),
    )
    run_id = int(result["id"])
    assert toapis_canary.advance(session, run_id)["stage"].value == "PROJECT_READY"
    assert toapis_canary.advance(session, run_id)["stage"].value == "SHOTS_READY"
    requested = toapis_canary.advance(session, run_id)
    assert requested["stage"].value == "CANARY_REQUESTED"
    assert requested["image_requests_created"] == 1
    assert requested["video_requests_created"] == 0
    assert len(session.exec(select(Shot)).all()) == 1
    requests = session.exec(select(GenerationRequest)).all()
    assert len(requests) == 1 and requests[0].kind == GenerationKind.KEYFRAME
    repeated = toapis_canary.advance(session, run_id)
    assert repeated["image_requests_created"] == 1


def test_video_canary_prepares_one_shot_two_frames_and_one_video_request(
    session: Session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session, profile.id or 0,
        LiveVerificationRequest(
            confirm_live=True, execute_paid=True, billing_unit="TOAPIS_CREDIT",
            max_billing_units="25", pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
            canary_video_first_last=True,
        ),
    )
    assert result["verification_type"] == ProviderVerificationType.LIVE_VIDEO_CANARY
    run_id = int(result["id"])
    assert toapis_video_canary.advance(session, run_id)["stage"].value == "PROJECT_READY"
    frames = toapis_video_canary.advance(session, run_id)
    assert frames["stage"].value == "FRAMES_READY"
    run = session.get(ProviderVerificationRun, run_id)
    assert run and run.initial_anchor_asset_id and run.end_frame_asset_id
    start = session.get(Asset, run.initial_anchor_asset_id)
    end = session.get(Asset, run.end_frame_asset_id)
    assert start and end and start.sha256 != end.sha256
    assert (start.width, start.height) == (end.width, end.height) == (2848, 1600)
    requested = toapis_video_canary.advance(session, run_id)
    assert requested["stage"].value == "VIDEO_REQUESTED"
    assert requested["image_requests_created"] == 0
    assert requested["video_requests_created"] == 1
    requests = session.exec(select(GenerationRequest)).all()
    assert len(requests) == 1 and requests[0].kind == GenerationKind.VIDEO
    assert requests[0].duration_seconds == 1


@pytest.mark.parametrize("ceiling", ["172.6", "190"])
def test_reviewed_budget_at_or_above_estimate_is_allowed(
    session: Session, monkeypatch: pytest.MonkeyPatch, ceiling: str,
) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session, profile.id or 0,
        LiveVerificationRequest(
            confirm_live=True, execute_paid=True, billing_unit="TOAPIS_CREDIT",
            max_billing_units=ceiling, pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
        ),
    )
    assert result["status"] == ProviderVerificationStatus.RUNNING
    assert profile.live_orchestration_enabled is True


@pytest.mark.parametrize(
    ("ceiling", "unit", "snapshot_hash", "reason"),
    [
        ("500.1", "TOAPIS_CREDIT", None, "max_billing_units_exceeds_safety_limit"),
        ("190", "USD", None, "billing_unit_mismatch"),
        ("190", "TOAPIS_CREDIT", "0" * 64, "pricing_snapshot_mismatch"),
    ],
)
def test_paid_run_rejects_unsafe_budget_unit_or_hash(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    ceiling: str,
    unit: str,
    snapshot_hash: str | None,
    reason: str,
) -> None:
    profile = configured_toapis(session, monkeypatch)
    result = provider_management.verify_live(
        session, profile.id or 0,
        LiveVerificationRequest(
            confirm_live=True, execute_paid=True, billing_unit=unit,
            max_billing_units=ceiling,
            pricing_snapshot_hash=snapshot_hash or live_orchestration.candidate_snapshot_hash(),
        ),
    )
    assert result["status"] == ProviderVerificationStatus.BLOCKED
    assert reason in result["summary"]["blocked"]


class FakeToApisProvider(AsyncGenerationProvider):
    def __init__(self) -> None:
        self.counter = 0
        self.upload_calls = 0
        self.image_submits = 0
        self.video_submits = 0
        self.video_requests: list[VideoGenerationRequest] = []
        self.jobs: dict[str, str] = {}

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id="toapis", display_name="Fake TOAPIS", text_to_image=True,
            image_to_video=True, first_last_frame_video=True, supports_seed=True,
            supports_negative_prompt=False, max_reference_images=2, max_duration_seconds=16,
            supported_aspect_ratios=["16:9"], supported_output_types=["png", "mp4"],
        )

    async def upload_asset(self, path: Path, *, client_request_id: str) -> ProviderResultUrl:
        assert path.is_file()
        self.upload_calls += 1
        return ProviderResultUrl(url=f"http://testserver/fake/v1/uploads/local-{self.upload_calls}")

    async def submit_image(self, request: ImageGenerationRequest) -> ProviderSubmitResult:
        self.image_submits += 1
        return self._submit("image")

    async def submit_video(self, request: VideoGenerationRequest) -> ProviderSubmitResult:
        self.video_submits += 1
        self.video_requests.append(request)
        return self._submit("video")

    def _submit(self, kind: str) -> ProviderSubmitResult:
        self.counter += 1
        job_id = f"verification-{kind}-{self.counter}"
        self.jobs[job_id] = kind
        fake_provider_app.JOBS[job_id] = {
            "id": job_id, "kind": kind, "scenario": "success", "status": "succeeded",
            "polls": 99, "running_polls": 1, "format": "A", "idempotency_key": job_id,
        }
        return ProviderSubmitResult(remote_job_id=job_id, remote_status=RemoteJobStatus.QUEUED)

    async def get_job(self, remote_job_id: str) -> ProviderJobResult:
        kind = self.jobs[remote_job_id]
        suffix = "png" if kind == "image" else "mp4"
        return ProviderJobResult(
            remote_job_id=remote_job_id, remote_status="completed",
            normalized_status=RemoteJobStatus.SUCCEEDED,
            result_urls=[ProviderResultUrl(url=f"http://testserver/fake/v1/results/{remote_job_id}.{suffix}")],
        )

    async def cancel_job(self, remote_job_id: str) -> ProviderCancelResult:
        return ProviderCancelResult(remote_job_id=remote_job_id, remote_status=RemoteJobStatus.CANCELLED, accepted=True)


@contextmanager
def verification_session_factory(
    tmp_path: Path,
) -> Generator[tuple[Callable[[], AbstractContextManager[Session]], Engine], None, None]:
    engine = create_engine(f"sqlite:///{tmp_path / 'verification.db'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def factory() -> Generator[Session, None, None]:
        with Session(engine) as db:
            yield db

    yield factory, engine


def result_resolver(host: str, _port: int | None) -> list[str]:
    return ["127.0.0.1"] if host == "testserver" else ["93.184.216.34"]


@pytest.mark.anyio
async def test_fake_provider_two_shot_chain_reaches_probeable_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.fixture_dir = Path(__file__).parent / "fixtures"
    settings.env = "test"
    settings.result_allowed_private_hosts = "testserver"
    fake_provider_app.test_reset()
    with verification_session_factory(tmp_path) as (factory, engine):
        with Session(engine) as db:
            profile = configured_toapis(db, monkeypatch)
            run = create_run(db, profile)
            run_id = run.id or 0
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)

        provider = FakeToApisProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        generation = GenerationWorker(
            session_factory=factory, registry=registry,
            settings=WorkerSettings(worker_id="verification-generation", poll_interval_seconds=1, retry_jitter_ratio=0),
        )
        result_settings = ResultWorkerSettings(worker_id="verification-result", retry_jitter_ratio=0, retry_base_seconds=1)
        result_worker = ResultWorker(
            session_factory=factory, settings=result_settings,
            processing_service=ResultProcessingService(
                session_factory=factory, settings=result_settings,
                downloader_transport=httpx.ASGITransport(app=fake_provider_app.app),
                downloader_resolver=result_resolver,
            ),
        )

        async def finish_generation() -> None:
            await generation.run_until_idle(now=lambda: utcnow())
            await generation.run_until_idle(now=lambda: utcnow() + timedelta(seconds=5))
            await result_worker.run_until_idle()

        await finish_generation()
        with Session(engine) as db:
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
        await finish_generation()
        with Session(engine) as db:
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
            continuity = toapis_verification.advance(db, run_id)
            assert continuity["stage"].value == "SHOT_2_START_FRAME_VERIFIED"
            shot_1 = db.get(Shot, continuity["shot_ids"][0])
            shot_2 = db.get(Shot, continuity["shot_ids"][1])
            assert shot_1 and shot_2 and shot_1.locked_tail_frame_asset_id
            inherited = db.get(Asset, shot_2.start_frame_asset_id)
            assert inherited and inherited.source_asset_id == shot_1.locked_tail_frame_asset_id
            toapis_verification.advance(db, run_id)
        await finish_generation()
        with Session(engine) as db:
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
        await finish_generation()
        with Session(engine) as db:
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)
            render_requested = toapis_verification.advance(db, run_id)
            assert render_requested["stage"].value == "RENDER_REQUESTED"

        render_worker = RenderWorker(
            session_factory=factory, worker_id="verification-render", lease_seconds=30,
            processing_service=RenderProcessingService(session_factory=factory),
        )
        assert await render_worker.run_until_idle() == 1
        with Session(engine) as db:
            toapis_verification.advance(db, run_id)
            passed = toapis_verification.advance(db, run_id)
            assert passed["stage"].value == "PASSED"
            assert passed["final_render_asset_id"] is not None
            assert passed["image_requests_created"] == 2
            assert passed["video_requests_created"] == 2
            assert len(db.exec(select(GenerationRequest)).all()) == 4
        assert provider.image_submits == 2
        assert provider.video_submits == 2
        assert len(provider.video_requests) == 2
        assert all(request.start_frame and request.end_frame for request in provider.video_requests)


@pytest.mark.anyio
async def test_fake_provider_image_canary_reaches_valid_asset_without_video(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "canary-storage"
    settings.fixture_dir = Path(__file__).parent / "fixtures"
    settings.env = "test"
    settings.result_allowed_private_hosts = "testserver"
    fake_provider_app.test_reset()
    with verification_session_factory(tmp_path) as (factory, engine):
        with Session(engine) as db:
            profile = configured_toapis(db, monkeypatch)
            result = provider_management.verify_live(
                db,
                profile.id or 0,
                LiveVerificationRequest(
                    confirm_live=True,
                    execute_paid=True,
                    billing_unit="TOAPIS_CREDIT",
                    max_billing_units="10",
                    pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
                    canary_image_only=True,
                ),
            )
            run_id = int(result["id"])
            for _ in range(3):
                toapis_canary.advance(db, run_id)

        provider = FakeToApisProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        generation = GenerationWorker(
            session_factory=factory,
            registry=registry,
            settings=WorkerSettings(worker_id="canary-generation", poll_interval_seconds=1, retry_jitter_ratio=0),
        )
        result_settings = ResultWorkerSettings(worker_id="canary-result", retry_jitter_ratio=0, retry_base_seconds=1)
        result_worker = ResultWorker(
            session_factory=factory,
            settings=result_settings,
            processing_service=ResultProcessingService(
                session_factory=factory,
                settings=result_settings,
                downloader_transport=httpx.ASGITransport(app=fake_provider_app.app),
                downloader_resolver=result_resolver,
            ),
        )
        await generation.run_until_idle(now=lambda: utcnow())
        await generation.run_until_idle(now=lambda: utcnow() + timedelta(seconds=5))
        await result_worker.run_until_idle()
        with Session(engine) as db:
            passed = toapis_canary.advance(db, run_id)
            assert passed["stage"].value == "PASSED"
            assert passed["image_requests_created"] == 1
            assert passed["video_requests_created"] == 0
            assert passed["final_render_asset_id"] is None
            assert len(db.exec(select(GenerationRequest)).all()) == 1
            run = db.get(ProviderVerificationRun, run_id)
            profile = live_orchestration.get_toapis_profile(db)
            assert run and run.status == ProviderVerificationStatus.PASSED
            assert profile.live_orchestration_enabled is False
        assert provider.image_submits == 1
        assert provider.video_submits == 0
        assert provider.upload_calls == 0


@pytest.mark.anyio
async def test_fake_provider_video_canary_runs_formal_result_and_tail_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "video-canary-storage"
    settings.fixture_dir = Path(__file__).parent / "fixtures"
    settings.env = "test"
    settings.result_allowed_private_hosts = "testserver"
    fake_provider_app.test_reset()
    with verification_session_factory(tmp_path) as (factory, engine):
        with Session(engine) as db:
            profile = configured_toapis(db, monkeypatch)
            created = provider_management.verify_live(
                db, profile.id or 0,
                LiveVerificationRequest(
                    confirm_live=True, execute_paid=True, billing_unit="TOAPIS_CREDIT",
                    max_billing_units="25", pricing_snapshot_hash=live_orchestration.candidate_snapshot_hash(),
                    canary_video_first_last=True,
                ),
            )
            run_id = int(created["id"])
            for _ in range(3):
                toapis_video_canary.advance(db, run_id)

        provider = FakeToApisProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        generation = GenerationWorker(
            session_factory=factory, registry=registry,
            settings=WorkerSettings(worker_id="video-canary-generation", poll_interval_seconds=1, retry_jitter_ratio=0),
        )
        result_settings = ResultWorkerSettings(worker_id="video-canary-result", retry_jitter_ratio=0, retry_base_seconds=1)
        result_worker = ResultWorker(
            session_factory=factory, settings=result_settings,
            processing_service=ResultProcessingService(
                session_factory=factory, settings=result_settings,
                downloader_transport=httpx.ASGITransport(app=fake_provider_app.app),
                downloader_resolver=result_resolver,
            ),
        )
        await generation.run_until_idle(now=lambda: utcnow())
        await generation.run_until_idle(now=lambda: utcnow() + timedelta(seconds=5))
        await result_worker.run_until_idle()
        with Session(engine) as db:
            passed = toapis_video_canary.advance(db, run_id)
            assert passed["stage"].value == "PASSED"
            run = db.get(ProviderVerificationRun, run_id)
            video = db.get(Asset, run.final_render_asset_id) if run else None
            tail = db.get(Asset, run.tail_frame_asset_id) if run else None
            assert video and video.type == AssetType.VIDEO and video.duration_seconds and video.duration_seconds > 0
            assert tail and tail.type == AssetType.TAIL_FRAME and Path(tail.path).is_file()
        assert provider.upload_calls == 2
        assert provider.image_submits == 0
        assert provider.video_submits == 1
        assert len(provider.video_requests) == 1
        request = provider.video_requests[0]
        assert request.duration_seconds == 1
        assert request.start_frame and request.end_frame


def test_concurrent_advance_does_not_duplicate_generation_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.fixture_dir = Path(__file__).parent / "fixtures"
    with verification_session_factory(tmp_path) as (factory, engine):
        with Session(engine) as db:
            profile = configured_toapis(db, monkeypatch)
            run_id = create_run(db, profile).id or 0
            toapis_verification.advance(db, run_id)
            toapis_verification.advance(db, run_id)

        def call_advance() -> str:
            with factory() as db:
                try:
                    return toapis_verification.advance(db, run_id)["stage"].value
                except Exception as exc:
                    return exc.__class__.__name__

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _index: call_advance(), range(2)))
        assert "SHOT_1_KEYFRAME_REQUESTED" in outcomes
        with Session(engine) as db:
            assert len(db.exec(select(GenerationRequest)).all()) == 1


def test_concurrent_first_advance_creates_one_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    settings.storage_dir = tmp_path / "storage"
    settings.fixture_dir = Path(__file__).parent / "fixtures"
    with verification_session_factory(tmp_path) as (factory, engine):
        with Session(engine) as db:
            profile = configured_toapis(db, monkeypatch)
            run_id = create_run(db, profile).id or 0

        def call_advance() -> None:
            with factory() as db:
                toapis_verification.advance(db, run_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _index: call_advance(), range(2)))
        with Session(engine) as db:
            assert len(db.exec(select(Project)).all()) == 1
            assert len(db.exec(select(Shot)).all()) in {0, 2}


def test_price_hash_change_fails_before_next_paid_request(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = configured_toapis(session, monkeypatch)
    install_anchor_fixture()
    run = create_run(session, profile)
    toapis_verification.advance(session, run.id or 0)
    toapis_verification.advance(session, run.id or 0)
    for model in session.exec(select(ProviderModelProfile)).all():
        model.pricing_snapshot_hash = "f" * 64
        session.add(model)
    session.commit()
    failed = toapis_verification.advance(session, run.id or 0)
    assert failed["status"] == ProviderVerificationStatus.FAILED
    saved = session.get(ProviderVerificationRun, run.id)
    assert saved and saved.failure_code == "PRICING_SNAPSHOT_MISMATCH"
    assert session.exec(select(GenerationRequest)).all() == []
