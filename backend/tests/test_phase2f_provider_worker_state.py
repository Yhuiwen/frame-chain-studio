from datetime import timedelta
from typing import Any, cast

import pytest
from sqlmodel import Session

from app.core.errors import AppError
from app.models.entities import Asset, AssetType, GenerationKind, Project, Shot, ShotStatus, WorkerStatus, WorkerType, utcnow
from app.models.schemas import GenerationStartRequest
from app.providers.async_base import AsyncGenerationProvider
from app.providers.models import (
    ProviderCapabilities,
    ProviderCancelResult,
    ProviderJobResult,
    ProviderSubmitResult,
    RemoteJobStatus,
)
from app.providers.registry import ProviderRegistry
from app.services import provider_resolution, studio, worker_status


class DummyProvider(AsyncGenerationProvider):
    def __init__(self, capabilities: ProviderCapabilities) -> None:
        self._capabilities = capabilities

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def submit_image(self, request):
        return ProviderSubmitResult(remote_job_id="remote-image", remote_status=RemoteJobStatus.QUEUED)

    async def submit_video(self, request):
        return ProviderSubmitResult(remote_job_id="remote-video", remote_status=RemoteJobStatus.QUEUED)

    async def get_job(self, remote_job_id: str):
        return ProviderJobResult(remote_job_id=remote_job_id, normalized_status=RemoteJobStatus.RUNNING)

    async def cancel_job(self, remote_job_id: str):
        return ProviderCancelResult(remote_job_id=remote_job_id, accepted=True)


def test_project_defaults_resolve_effective_provider_snapshot(session: Session) -> None:
    project = Project(name="Demo", image_provider_id="p1", image_model="img-v1", default_seed=123)
    session.add(project)
    session.commit()
    session.refresh(project)
    shot = Shot(project_id=project.id or 0, title="S1", prompt="city")
    session.add(shot)
    session.commit()
    session.refresh(shot)
    registry = ProviderRegistry()
    registry.register(
        DummyProvider(
            ProviderCapabilities(
                provider_id="p1",
                display_name="P1",
                text_to_image=True,
                supports_seed=True,
                supported_aspect_ratios=["16:9"],
            )
        )
    )

    resolved = provider_resolution.resolve_generation(
        session,
        project=project,
        shot=shot,
        kind=GenerationKind.KEYFRAME,
        payload=GenerationStartRequest(),
        registry=registry,
    )

    assert resolved.provider_id == "p1"
    assert resolved.model == "img-v1"
    assert resolved.seed == 123
    assert resolved.generation_mode.value == "TEXT_TO_IMAGE"
    assert resolved.request_payload(shot)["provider_id"] == "p1"


def test_first_last_frame_requires_capability_unless_fallback_allowed(session: Session) -> None:
    project = Project(name="Demo", video_provider_id="p2")
    session.add(project)
    session.commit()
    session.refresh(project)
    shot = Shot(project_id=project.id or 0, title="S1", status=ShotStatus.KEYFRAME_APPROVED)
    session.add(shot)
    session.commit()
    session.refresh(shot)
    start = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.START_FRAME, path="s.png", mime_type="image/png")
    keyframe = Asset(project_id=project.id or 0, shot_id=shot.id, type=AssetType.KEYFRAME, path="k.png", mime_type="image/png")
    session.add(start)
    session.add(keyframe)
    session.commit()
    session.refresh(start)
    shot.start_frame_asset_id = start.id
    session.add(shot)
    session.commit()
    registry = ProviderRegistry()
    registry.register(
        DummyProvider(
            ProviderCapabilities(provider_id="p2", display_name="P2", image_to_video=True, max_reference_images=2)
        )
    )

    with pytest.raises(AppError) as exc_info:
        provider_resolution.resolve_generation(
            session,
            project=project,
            shot=shot,
            kind=GenerationKind.VIDEO,
            payload=GenerationStartRequest(),
            registry=registry,
        )
    assert exc_info.value.code == "PROVIDER_CAPABILITY_UNSUPPORTED"

    resolved = provider_resolution.resolve_generation(
        session,
        project=project,
        shot=shot,
        kind=GenerationKind.VIDEO,
        payload=GenerationStartRequest(allow_capability_fallback=True),
        registry=registry,
    )
    assert resolved.generation_mode.value == "START_FRAME_ONLY"


def test_worker_heartbeat_summary_marks_stale_workers_offline(session: Session) -> None:
    now = utcnow()
    worker_status.record_heartbeat(
        session,
        worker_id="gen-1",
        worker_type=WorkerType.GENERATION,
        status=WorkerStatus.IDLE,
        now=now,
    )
    worker_status.record_heartbeat(
        session,
        worker_id="result-1",
        worker_type=WorkerType.RESULT,
        status=WorkerStatus.ERROR,
        last_error_code="BOOM",
        now=now - timedelta(seconds=60),
    )

    summary = worker_status.status_summary(session, stale_after_seconds=30, now=now)
    generation = cast(dict[str, Any], summary["generation"])
    result = cast(dict[str, Any], summary["result"])

    assert generation["online_count"] == 1
    assert result["online_count"] == 0
    assert result["workers"][0]["last_error_code"] == "BOOM"


def test_project_detail_returns_shot_actions_for_many_shots(session: Session) -> None:
    project = studio.create_project(session, payload=type("Payload", (), {"name": "Demo", "description": ""})())
    for index in range(20):
        session.add(Shot(project_id=project.id or 0, title=f"Shot {index + 1}", sort_order=index))
    session.commit()

    _, shots, _, _, tasks, _ = studio.project_detail(session, project.id or 0)

    assert len(shots) == 20
    assert tasks == []
    assert shots[0]["actions"] == {
        "can_generate_keyframe": True,
        "can_generate_video": False,
        "reasons": ["VIDEO_REQUIRES_KEYFRAME_APPROVED"],
    }
