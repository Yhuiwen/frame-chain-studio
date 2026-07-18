from datetime import datetime

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.models.entities import GenerationTask, ReliableTaskStatus
from app.services.task_service import db_time, loads_json_list

RESULT_CANDIDATE_STATUSES = {
    ReliableTaskStatus.PROCESSING_RESULT,
    ReliableTaskStatus.RESULT_READY,
}
RESULT_PRIORITY = {
    ReliableTaskStatus.PROCESSING_RESULT: 0,
    ReliableTaskStatus.RESULT_READY: 1,
}


def find_due_result_task_ids(
    session: Session,
    *,
    limit: int,
    now: datetime | None = None,
) -> list[int]:
    current_time = db_time(now)
    candidates = list(
        session.exec(
            select(GenerationTask)
            .where(
                col(GenerationTask.status).in_([status.value for status in RESULT_CANDIDATE_STATUSES]),
                or_(col(GenerationTask.locked_until).is_(None), col(GenerationTask.locked_until) <= current_time),
                or_(
                    col(GenerationTask.next_result_retry_at).is_(None),
                    col(GenerationTask.next_result_retry_at) <= current_time,
                ),
            )
            .limit(limit * 4)
        ).all()
    )
    candidates = [task for task in candidates if loads_json_list(task.result_urls_json)]
    candidates.sort(key=lambda task: (RESULT_PRIORITY[task.status], task.created_at))
    return [task.id or 0 for task in candidates[:limit]]
