from __future__ import annotations

from fastapi.testclient import TestClient
from pathlib import Path
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.errors import AppError
from app.db import get_session
from app.main import app
from app.models.entities import (
    Asset,
    AssetStatus,
    AssetType,
    GenerationTask,
    GenerationTaskType,
    HumanVisualStatus,
    Project,
    ProviderVerificationRun,
    ProviderVerificationStatus,
    ProviderVerificationType,
    ProviderVisualReview,
    Shot,
    VisualAnalysisStatus,
    VisualContinuityReport,
    VisualReviewDecision,
)
from app.services import provider_visual_review


def run_fixture(
    session: Session,
    *,
    technical: ProviderVerificationStatus = ProviderVerificationStatus.PASSED,
    legacy_human: HumanVisualStatus | None = None,
    automatic: VisualAnalysisStatus = VisualAnalysisStatus.PASSED,
) -> tuple[ProviderVerificationRun, Asset, Asset]:
    project = Project(name="review-project")
    session.add(project)
    session.flush()
    shot_1 = Shot(project_id=project.id or 0, title="shot 1", sort_order=1)
    shot_2 = Shot(project_id=project.id or 0, title="shot 2", sort_order=2)
    session.add(shot_1)
    session.add(shot_2)
    session.flush()

    video_1 = asset(session, project.id or 0, shot_1.id, AssetType.VIDEO, "video-1")
    tail_1 = asset(
        session,
        project.id or 0,
        shot_1.id,
        AssetType.TAIL_FRAME,
        "tail-1",
        source_asset_id=video_1.id,
    )
    inherited = asset(
        session,
        project.id or 0,
        shot_2.id,
        AssetType.START_FRAME,
        "inherited",
        source_asset_id=tail_1.id,
    )
    inherited.path = tail_1.path
    session.add(inherited)
    video_2 = asset(session, project.id or 0, shot_2.id, AssetType.VIDEO, "video-2")
    render = asset(session, project.id or 0, None, AssetType.PROJECT_RENDER, "render")
    shot_1.approved_video_asset_id = video_1.id
    shot_1.locked_tail_frame_asset_id = tail_1.id
    shot_2.start_frame_asset_id = inherited.id
    shot_2.approved_video_asset_id = video_2.id
    session.add(shot_1)
    session.add(shot_2)
    run = ProviderVerificationRun(
        provider_profile_id=1,
        verification_type=ProviderVerificationType.LIVE_CHAIN,
        status=technical,
        verification_project_id=project.id,
        shot_1_id=shot_1.id,
        shot_2_id=shot_2.id,
        final_render_asset_id=render.id,
        auto_approve_for_verification=True,
    )
    session.add(run)
    session.flush()
    if legacy_human is not None:
        session.add(
            VisualContinuityReport(
                project_id=project.id or 0,
                shot_id=shot_1.id,
                video_asset_id=video_1.id or 0,
                analysis_version="visual-continuity-v1",
                config_hash="a" * 64,
                report_hash="b" * 64,
                technical_status=VisualAnalysisStatus.PASSED,
                automatic_visual_status=automatic,
                human_visual_status=legacy_human,
                rejection_reasons_json=(
                    '["CHARACTER_STYLE_DRIFT"]'
                    if legacy_human == HumanVisualStatus.REJECTED
                    else "[]"
                ),
            )
        )
    session.commit()
    return run, render, video_1


def asset(
    session: Session,
    project_id: int,
    shot_id: int | None,
    asset_type: AssetType,
    digest_seed: str,
    *,
    source_asset_id: int | None = None,
) -> Asset:
    item = Asset(
        project_id=project_id,
        shot_id=shot_id,
        type=asset_type,
        status=AssetStatus.APPROVED,
        path=f"storage/{digest_seed}",
        mime_type="video/mp4"
        if asset_type in {AssetType.VIDEO, AssetType.PROJECT_RENDER}
        else "image/png",
        source_asset_id=source_asset_id,
        sha256=(digest_seed.encode().hex() + "0" * 64)[:64],
    )
    session.add(item)
    session.flush()
    return item


@pytest.mark.parametrize(
    ("technical", "human", "expected"),
    [
        (ProviderVerificationStatus.PASSED, None, "BLOCKED"),
        (ProviderVerificationStatus.FAILED, VisualReviewDecision.APPROVED, "BLOCKED"),
        (ProviderVerificationStatus.PASSED, VisualReviewDecision.APPROVED, "READY"),
        (ProviderVerificationStatus.PASSED, VisualReviewDecision.REJECTED, "BLOCKED"),
    ],
)
def test_production_statuses_are_independent(
    session: Session,
    technical: ProviderVerificationStatus,
    human: VisualReviewDecision | None,
    expected: str,
) -> None:
    run, render, _video = run_fixture(session, technical=technical)
    if human is not None:
        provider_visual_review.create_review(
            session,
            run_id=run.id or 0,
            asset_id=render.id or 0,
            decision=human,
            reason_codes=["SUBJECT_SCALE_DRIFT"] if human == VisualReviewDecision.REJECTED else [],
            notes="operator evidence",
            idempotency_key=f"review-{human.value}",
        )
    payload = provider_visual_review.readiness_payload(session, run.id or 0)
    assert payload["technical_status"] == technical.value
    assert payload["production_status"] == expected
    saved_run = session.get(ProviderVerificationRun, run.id)
    assert saved_run is not None
    assert saved_run.status == technical


def test_legacy_run6_equivalent_stays_passed_rejected_and_blocked(session: Session) -> None:
    run, _render, _video = run_fixture(
        session,
        legacy_human=HumanVisualStatus.REJECTED,
        automatic=VisualAnalysisStatus.FAILED,
    )
    payload = provider_visual_review.readiness_payload(session, run.id or 0)
    assert payload["technical_status"] == "PASSED"
    assert payload["lineage_status"] == "PASSED"
    assert payload["human_visual_status"] == "REJECTED"
    assert payload["production_status"] == "BLOCKED"
    assert payload["legacy_review_evidence"] is True
    assert payload["current_visual_review"] is None
    assert payload["workflow_approval_only"] is True


def test_review_history_asset_binding_and_idempotency(session: Session) -> None:
    run, render, linked_video = run_fixture(session)
    task = GenerationTask(
        generation_request_id=999,
        project_id=render.project_id,
        shot_id=linked_video.shot_id or 0,
        task_type=GenerationTaskType.VIDEO_GENERATION,
        idempotency_key="unrelated-task",
    )
    session.add(task)
    session.commit()
    original_asset_status = render.status
    original_task_status = task.status
    first = provider_visual_review.create_review(
        session,
        run_id=run.id or 0,
        asset_id=render.id or 0,
        decision=VisualReviewDecision.APPROVED,
        reason_codes=[],
        notes=" approved ",
        idempotency_key="same-key",
    )
    replay = provider_visual_review.create_review(
        session,
        run_id=run.id or 0,
        asset_id=render.id or 0,
        decision=VisualReviewDecision.APPROVED,
        reason_codes=[],
        notes="approved",
        idempotency_key="same-key",
    )
    assert replay.id == first.id
    assert first.asset_sha256 == render.sha256
    with pytest.raises(AppError, match="another payload"):
        provider_visual_review.create_review(
            session,
            run_id=run.id or 0,
            asset_id=render.id or 0,
            decision=VisualReviewDecision.REJECTED,
            reason_codes=["SUBJECT_SCALE_DRIFT"],
            notes="changed",
            idempotency_key="same-key",
        )
    provider_visual_review.create_review(
        session,
        run_id=run.id or 0,
        asset_id=render.id or 0,
        decision=VisualReviewDecision.REJECTED,
        reason_codes=["SUBJECT_SCALE_DRIFT", "SUBJECT_SCALE_DRIFT"],
        notes="rejected",
        idempotency_key="second-key",
    )
    assert len(provider_visual_review.list_reviews(session, run.id or 0)) == 2
    assert (
        provider_visual_review.readiness_payload(session, run.id or 0)["human_visual_status"]
        == "REJECTED"
    )
    session.refresh(render)
    session.refresh(task)
    assert render.status == original_asset_status
    assert task.status == original_task_status
    # A review of another linked Asset is historical evidence, not approval of the selected render.
    provider_visual_review.create_review(
        session,
        run_id=run.id or 0,
        asset_id=linked_video.id or 0,
        decision=VisualReviewDecision.APPROVED,
        reason_codes=[],
        notes="old asset",
        idempotency_key="old-asset",
    )
    assert (
        provider_visual_review.readiness_payload(session, run.id or 0)["human_visual_status"]
        == "REJECTED"
    )


def test_validation_and_unrelated_asset_rejections(session: Session) -> None:
    run, render, _video = run_fixture(session)
    other_project = Project(name="other")
    session.add(other_project)
    session.flush()
    other = asset(session, other_project.id or 0, None, AssetType.PROJECT_RENDER, "other")
    same_project_unlinked = asset(
        session, render.project_id, None, AssetType.PROJECT_RENDER, "unlinked"
    )
    session.commit()
    for target, code in (
        (999999, "ASSET_NOT_FOUND"),
        (other.id, "ASSET_PROJECT_MISMATCH"),
        (same_project_unlinked.id, "ASSET_NOT_LINKED_TO_RUN"),
    ):
        with pytest.raises(AppError) as error:
            provider_visual_review.create_review(
                session,
                run_id=run.id or 0,
                asset_id=target or 0,
                decision=VisualReviewDecision.APPROVED,
                reason_codes=[],
                notes="",
                idempotency_key=None,
            )
        assert error.value.code == code
    with pytest.raises(AppError) as missing_reason:
        provider_visual_review.create_review(
            session,
            run_id=run.id or 0,
            asset_id=render.id or 0,
            decision=VisualReviewDecision.REJECTED,
            reason_codes=[],
            notes="",
            idempotency_key=None,
        )
    assert missing_reason.value.code == "VISUAL_REVIEW_REASON_REQUIRED"
    with pytest.raises(AppError) as other_notes:
        provider_visual_review.create_review(
            session,
            run_id=run.id or 0,
            asset_id=render.id or 0,
            decision=VisualReviewDecision.REJECTED,
            reason_codes=["OTHER"],
            notes=" ",
            idempotency_key=None,
        )
    assert other_notes.value.code == "VISUAL_REVIEW_NOTES_REQUIRED"
    with pytest.raises(AppError) as unknown_reason:
        provider_visual_review.create_review(
            session,
            run_id=run.id or 0,
            asset_id=render.id or 0,
            decision=VisualReviewDecision.REJECTED,
            reason_codes=["NOT_A_REASON"],
            notes="invalid",
            idempotency_key=None,
        )
    assert unknown_reason.value.code == "VISUAL_REVIEW_REASON_INVALID"


def test_lineage_failure_blocks_human_approval(session: Session) -> None:
    run, render, _video = run_fixture(session)
    shot_2 = session.get(Shot, run.shot_2_id)
    assert shot_2 is not None
    shot_2.start_frame_asset_id = None
    session.add(shot_2)
    session.commit()
    provider_visual_review.create_review(
        session,
        run_id=run.id or 0,
        asset_id=render.id or 0,
        decision=VisualReviewDecision.APPROVED,
        reason_codes=[],
        notes="visual only",
        idempotency_key="lineage-failed",
    )
    payload = provider_visual_review.readiness_payload(session, run.id or 0)
    assert payload["lineage_status"] == "FAILED"
    assert payload["human_visual_status"] == "APPROVED"
    assert payload["production_status"] == "BLOCKED"
    assert payload["production_blockers"] == ["LINEAGE_NOT_PASSED"]


def test_api_exposes_gates_and_safe_review_history(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api-review.db'}", connect_args={"check_same_thread": False}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as setup_session:
        run, render, _video = run_fixture(setup_session)
        run_id = run.id or 0
        render_id = render.id or 0
        before_tasks = len(setup_session.exec(select(GenerationTask)).all())

    def override_session():
        with Session(engine) as request_session:
            yield request_session

    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            created = client.post(
                f"/api/provider-verification-runs/{run_id}/visual-reviews",
                headers={"Idempotency-Key": "api-review"},
                json={
                    "asset_id": render_id,
                    "decision": "REJECTED",
                    "reason_codes": ["SUBJECT_SCALE_DRIFT"],
                    "notes": "visible drift",
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert body["reviewer_source"] == "HUMAN_OPERATOR"
            assert body["asset_url"] == f"/api/media/{render_id}"
            assert "path" not in body
            detail = client.get(f"/api/provider-verification-runs/{run_id}")
            assert detail.status_code == 200
            assert detail.json()["technical_status"] == "PASSED"
            assert detail.json()["human_visual_status"] == "REJECTED"
            assert detail.json()["production_status"] == "BLOCKED"
            history = client.get(f"/api/provider-verification-runs/{run_id}/visual-reviews")
            assert history.status_code == 200
            assert len(history.json()["history"]) == 1
    finally:
        app.dependency_overrides.clear()
    with Session(engine) as audit_session:
        assert len(audit_session.exec(select(GenerationTask)).all()) == before_tasks
        assert len(audit_session.exec(select(ProviderVisualReview)).all()) == 1
