from app.core.errors import AppError
from app.models.entities import ReliableTaskStatus


ACTIVE_TASK_STATUSES = {
    ReliableTaskStatus.QUEUED,
    ReliableTaskStatus.SUBMITTING,
    ReliableTaskStatus.RUNNING,
    ReliableTaskStatus.RETRY_WAIT,
    ReliableTaskStatus.CANCELLING,
}
TERMINAL_TASK_STATUSES = {
    ReliableTaskStatus.SUCCEEDED,
    ReliableTaskStatus.FAILED,
    ReliableTaskStatus.CANCELLED,
}
LEASEABLE_TASK_STATUSES = {
    ReliableTaskStatus.QUEUED,
    ReliableTaskStatus.SUBMITTING,
    ReliableTaskStatus.RUNNING,
    ReliableTaskStatus.RETRY_WAIT,
}

ALLOWED_TASK_TRANSITIONS: dict[ReliableTaskStatus, set[ReliableTaskStatus]] = {
    ReliableTaskStatus.QUEUED: {ReliableTaskStatus.SUBMITTING, ReliableTaskStatus.CANCELLED},
    ReliableTaskStatus.SUBMITTING: {
        ReliableTaskStatus.RUNNING,
        ReliableTaskStatus.RETRY_WAIT,
        ReliableTaskStatus.FAILED,
        ReliableTaskStatus.CANCELLING,
        ReliableTaskStatus.CANCELLED,
    },
    ReliableTaskStatus.RUNNING: {
        ReliableTaskStatus.RUNNING,
        ReliableTaskStatus.RETRY_WAIT,
        ReliableTaskStatus.RESULT_READY,
        ReliableTaskStatus.SUCCEEDED,
        ReliableTaskStatus.FAILED,
        ReliableTaskStatus.CANCELLING,
        ReliableTaskStatus.CANCELLED,
    },
    ReliableTaskStatus.RESULT_READY: {
        ReliableTaskStatus.SUCCEEDED,
        ReliableTaskStatus.FAILED,
        ReliableTaskStatus.CANCELLED,
    },
    ReliableTaskStatus.RETRY_WAIT: {
        ReliableTaskStatus.QUEUED,
        ReliableTaskStatus.SUBMITTING,
        ReliableTaskStatus.CANCELLED,
        ReliableTaskStatus.FAILED,
    },
    ReliableTaskStatus.CANCELLING: {
        ReliableTaskStatus.CANCELLED,
        ReliableTaskStatus.FAILED,
        ReliableTaskStatus.RUNNING,
    },
    ReliableTaskStatus.SUCCEEDED: set(),
    ReliableTaskStatus.FAILED: set(),
    ReliableTaskStatus.CANCELLED: set(),
}


def ensure_task_transition_allowed(current: ReliableTaskStatus, target: ReliableTaskStatus) -> None:
    if current == target:
        return
    if target not in ALLOWED_TASK_TRANSITIONS[current]:
        raise AppError(
            "INVALID_TASK_STATE_TRANSITION",
            f"Cannot transition task from {current.value} to {target.value}.",
            status_code=409,
        )
