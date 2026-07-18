from datetime import datetime

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models.entities import GenerationTask, ReliableTaskStatus
from app.services.task_service import db_time

WORKER_CANDIDATE_STATUSES = {
    ReliableTaskStatus.CANCELLING,
    ReliableTaskStatus.SUBMITTING,
    ReliableTaskStatus.RUNNING,
    ReliableTaskStatus.RETRY_WAIT,
    ReliableTaskStatus.QUEUED,
}
TASK_PRIORITY = {
    ReliableTaskStatus.CANCELLING: 0,
    ReliableTaskStatus.SUBMITTING: 1,
    ReliableTaskStatus.RUNNING: 2,
    ReliableTaskStatus.RETRY_WAIT: 3,
    ReliableTaskStatus.QUEUED: 4,
}


def find_due_task_ids(
    session: Session,
    *,
    configured_provider_ids: set[str],
    limit: int,
    now: datetime | None = None,
) -> list[int]:
    if not configured_provider_ids:
        return []
    current_time = db_time(now)
    candidates = list(
        session.exec(
            select(GenerationTask)
            .where(
                col(GenerationTask.status).in_([status.value for status in WORKER_CANDIDATE_STATUSES]),
                col(GenerationTask.provider_id).in_(configured_provider_ids),
                or_(col(GenerationTask.locked_until).is_(None), col(GenerationTask.locked_until) <= current_time),
                or_(col(GenerationTask.next_retry_at).is_(None), col(GenerationTask.next_retry_at) <= current_time),
                or_(col(GenerationTask.next_poll_at).is_(None), col(GenerationTask.next_poll_at) <= current_time),
            )
            .limit(limit * 4)
        ).all()
    )
    candidates.sort(key=lambda task: (TASK_PRIORITY[task.status], task.created_at))
    return [task.id or 0 for task in candidates[:limit]]
