import pytest

from app.core.errors import AppError
from app.domain.task_state_machine import ALLOWED_TASK_TRANSITIONS, ensure_task_transition_allowed
from app.models.entities import ReliableTaskStatus


def test_all_declared_task_transitions_are_allowed() -> None:
    for current, targets in ALLOWED_TASK_TRANSITIONS.items():
        for target in targets:
            ensure_task_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ReliableTaskStatus.QUEUED, ReliableTaskStatus.SUCCEEDED),
        (ReliableTaskStatus.RETRY_WAIT, ReliableTaskStatus.SUCCEEDED),
        (ReliableTaskStatus.SUCCEEDED, ReliableTaskStatus.RUNNING),
        (ReliableTaskStatus.FAILED, ReliableTaskStatus.QUEUED),
        (ReliableTaskStatus.CANCELLED, ReliableTaskStatus.QUEUED),
    ],
)
def test_rejects_illegal_and_terminal_recovery_transitions(
    current: ReliableTaskStatus,
    target: ReliableTaskStatus,
) -> None:
    with pytest.raises(AppError) as exc:
        ensure_task_transition_allowed(current, target)
    assert exc.value.code == "INVALID_TASK_STATE_TRANSITION"


def test_same_status_transition_is_idempotent() -> None:
    ensure_task_transition_allowed(ReliableTaskStatus.RUNNING, ReliableTaskStatus.RUNNING)
