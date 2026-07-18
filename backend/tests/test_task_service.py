from datetime import timedelta

import pytest
from sqlmodel import Session, create_engine, select

from app.core.errors import AppError
from app.models.entities import (
    GenerationKind,
    GenerationTaskType,
    Project,
    ReliableTaskStatus,
    Shot,
    TaskStateChange,
    utcnow,
)
from app.models.schemas import ProjectCreate, ShotCreate
from app.services import studio, task_service


def logical_request(session: Session):
    project = studio.create_project(session, ProjectCreate(name="Tasks"))
    shot = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 1"))
    return task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot.id or 0,
        kind=GenerationKind.KEYFRAME,
        provider_name="mock",
        prompt_snapshot="prompt",
    )


def test_create_first_task_attempt_sets_attempt_root_and_idempotency(session: Session) -> None:
    request = logical_request(session)

    task = task_service.create_task_attempt(session, generation_request=request)
    duplicate = task_service.create_task_attempt(session, generation_request=request)

    assert duplicate.id == task.id
    assert task.attempt_number == 1
    assert task.root_task_id == task.id
    assert task.retry_count == 0
    assert task.status == ReliableTaskStatus.QUEUED


def test_active_task_blocks_second_attempt_but_terminal_retry_creates_new_attempt(session: Session) -> None:
    request = logical_request(session)
    first = task_service.create_task_attempt(session, generation_request=request)

    with pytest.raises(AppError) as exc:
        task_service.create_task_attempt(session, generation_request=request, idempotency_key="different")
    assert exc.value.code == "ACTIVE_TASK_EXISTS"

    task_service.mark_task_running(session, first.id or 0)
    task_service.mark_task_failed(session, first.id or 0, error_message="failed")
    retry = task_service.create_task_attempt(
        session,
        generation_request=request,
        retry_of_task_id=first.id,
        idempotency_key="manual-retry",
    )

    assert retry.attempt_number == 2
    assert retry.retry_of_task_id == first.id
    assert retry.root_task_id == first.id


def test_different_shot_or_task_type_does_not_conflict(session: Session) -> None:
    project = studio.create_project(session, ProjectCreate(name="Parallel"))
    shot_one = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 1"))
    shot_two = studio.create_shot(session, project.id or 0, ShotCreate(title="Shot 2"))
    request_one = task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot_one.id or 0,
        kind=GenerationKind.KEYFRAME,
        provider_name="mock",
    )
    request_two = task_service.create_generation_request(
        session,
        project_id=project.id or 0,
        shot_id=shot_two.id or 0,
        kind=GenerationKind.VIDEO,
        provider_name="mock",
    )

    one = task_service.create_task_attempt(session, generation_request=request_one)
    two = task_service.create_task_attempt(
        session,
        generation_request=request_two,
        task_type=GenerationTaskType.VIDEO_GENERATION,
    )

    assert one.id != two.id


def test_transition_task_logs_once_and_checks_expected_current(session: Session) -> None:
    request = logical_request(session)
    task = task_service.create_task_attempt(session, generation_request=request)

    task_service.transition_task(
        session,
        task.id or 0,
        ReliableTaskStatus.SUBMITTING,
        expected_current=ReliableTaskStatus.QUEUED,
        reason_code="submit",
    )
    task_service.transition_task(session, task.id or 0, ReliableTaskStatus.SUBMITTING)

    changes = session.exec(select(TaskStateChange).where(TaskStateChange.task_id == task.id)).all()
    assert [change.to_status for change in changes] == [
        ReliableTaskStatus.QUEUED,
        ReliableTaskStatus.SUBMITTING,
    ]
    with pytest.raises(AppError) as exc:
        task_service.transition_task(
            session,
            task.id or 0,
            ReliableTaskStatus.RUNNING,
            expected_current=ReliableTaskStatus.QUEUED,
        )
    assert exc.value.code == "TASK_STATE_CHANGED"


def test_schedule_retry_and_retry_limit(session: Session) -> None:
    now = utcnow()
    request = logical_request(session)
    task = task_service.create_task_attempt(session, generation_request=request, max_attempts=2)
    task_service.mark_task_running(session, task.id or 0, now=now)

    retry_wait = task_service.schedule_retry(session, task.id or 0, delay_seconds=30, now=now)
    assert retry_wait.status == ReliableTaskStatus.RETRY_WAIT
    assert retry_wait.retry_count == 1
    assert retry_wait.next_retry_at == (now + timedelta(seconds=30)).replace(tzinfo=None)

    failed = task_service.schedule_retry(session, task.id or 0, delay_seconds=30, now=now)
    assert failed.status == ReliableTaskStatus.FAILED
    assert failed.retry_count == 2


def test_non_retryable_status_rejects_retry(session: Session) -> None:
    request = logical_request(session)
    task = task_service.create_task_attempt(session, generation_request=request)

    with pytest.raises(AppError) as exc:
        task_service.schedule_retry(session, task.id or 0, delay_seconds=1)
    assert exc.value.code == "TASK_NOT_RETRYABLE"


def test_lease_acquire_renew_release_and_expiry(session: Session) -> None:
    now = utcnow()
    request = logical_request(session)
    task = task_service.create_task_attempt(session, generation_request=request)

    acquired = task_service.acquire_task_lease(
        session,
        task.id or 0,
        worker_id="worker-a",
        lease_seconds=60,
        now=now,
    )
    assert acquired is not None
    assert acquired.locked_by == "worker-a"
    assert task_service.acquire_task_lease(
        session,
        task.id or 0,
        worker_id="worker-b",
        lease_seconds=60,
        now=now + timedelta(seconds=10),
    ) is None
    assert task_service.renew_task_lease(
        session,
        task.id or 0,
        worker_id="worker-a",
        lease_seconds=60,
        now=now + timedelta(seconds=20),
    ) is not None
    assert task_service.renew_task_lease(
        session,
        task.id or 0,
        worker_id="worker-b",
        lease_seconds=60,
        now=now + timedelta(seconds=20),
    ) is None
    expired_takeover = task_service.acquire_task_lease(
        session,
        task.id or 0,
        worker_id="worker-b",
        lease_seconds=60,
        now=now + timedelta(seconds=200),
    )
    assert expired_takeover is not None
    assert expired_takeover.locked_by == "worker-b"
    assert task_service.release_task_lease(session, task.id or 0, worker_id="worker-a") is None
    released = task_service.release_task_lease(session, task.id or 0, worker_id="worker-b")
    assert released is not None
    assert released.locked_by is None
    assert task_service.release_task_lease(session, task.id or 0, worker_id="worker-b") is not None


def test_terminal_task_cannot_be_leased(session: Session) -> None:
    request = logical_request(session)
    task = task_service.create_task_attempt(session, generation_request=request)
    task_service.mark_task_running(session, task.id or 0)
    task_service.mark_task_failed(session, task.id or 0, error_message="failed")

    assert task_service.acquire_task_lease(session, task.id or 0, worker_id="worker", lease_seconds=1) is None


def test_two_database_sessions_compete_for_one_lease(tmp_path) -> None:
    db_path = tmp_path / "lease.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    from sqlmodel import SQLModel

    SQLModel.metadata.create_all(engine)
    with Session(engine) as setup:
        project = Project(name="Lease", description="")
        setup.add(project)
        setup.commit()
        setup.refresh(project)
        shot = Shot(project_id=project.id or 0, title="Shot 1")
        setup.add(shot)
        setup.commit()
        setup.refresh(shot)
        request = task_service.create_generation_request(
            setup,
            project_id=project.id or 0,
            shot_id=shot.id or 0,
            kind=GenerationKind.KEYFRAME,
            provider_name="mock",
        )
        task = task_service.create_task_attempt(setup, generation_request=request)

    now = utcnow()
    with Session(engine) as first, Session(engine) as second:
        first_result = task_service.acquire_task_lease(
            first,
            task.id or 0,
            worker_id="worker-a",
            lease_seconds=60,
            now=now,
        )
        second_result = task_service.acquire_task_lease(
            second,
            task.id or 0,
            worker_id="worker-b",
            lease_seconds=60,
            now=now,
        )

    assert [first_result is not None, second_result is not None].count(True) == 1


def test_mark_succeeded_is_idempotent_and_detects_result_conflict(session: Session) -> None:
    request = logical_request(session)
    task = task_service.create_task_attempt(session, generation_request=request)
    task_service.mark_task_running(session, task.id or 0)
    completed = task_service.mark_task_succeeded(session, task.id or 0, result_asset_id=123)
    completed_at = completed.completed_at
    repeated = task_service.mark_task_succeeded(session, task.id or 0, result_asset_id=123)

    assert repeated.id == completed.id
    assert repeated.completed_at == completed_at
    assert repeated.locked_by is None
    with pytest.raises(AppError) as exc:
        task_service.mark_task_succeeded(session, task.id or 0, result_asset_id=456)
    assert exc.value.code == "TASK_RESULT_CONFLICT"
