import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from app.models.entities import WorkerHeartbeat, WorkerStatus, WorkerType, utcnow

logger = logging.getLogger(__name__)


def safe_heartbeat(
    session_factory: Any,
    *,
    worker_id: str,
    worker_type: WorkerType,
    status: WorkerStatus,
    current_task_id: int | None = None,
    processed_count: int | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> None:
    try:
        with session_factory() as session:
            record_heartbeat(
                session,
                worker_id=worker_id,
                worker_type=worker_type,
                status=status,
                current_task_id=current_task_id,
                processed_count=processed_count,
                last_error_code=last_error_code,
                last_error_message=last_error_message,
                metadata=metadata,
                now=now,
            )
    except Exception as exc:
        logger.warning("worker heartbeat failed worker_id=%s worker_type=%s error=%s", worker_id, worker_type, exc)


def record_heartbeat(
    session: Session,
    *,
    worker_id: str,
    worker_type: WorkerType,
    status: WorkerStatus,
    current_task_id: int | None = None,
    processed_count: int | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> WorkerHeartbeat:
    current_time = now or utcnow()
    heartbeat = session.exec(
        select(WorkerHeartbeat).where(
            WorkerHeartbeat.worker_id == worker_id,
            WorkerHeartbeat.worker_type == worker_type,
        )
    ).first()
    if heartbeat is None:
        heartbeat = WorkerHeartbeat(
            worker_id=worker_id,
            worker_type=worker_type,
            status=status,
            started_at=current_time,
        )
    heartbeat.status = status
    heartbeat.last_seen_at = current_time
    heartbeat.current_task_id = current_task_id
    if processed_count is not None:
        heartbeat.processed_count = processed_count
    if last_error_code is not None:
        heartbeat.last_error_code = last_error_code
    if last_error_message is not None:
        heartbeat.last_error_message = last_error_message[:1000]
    if metadata is not None:
        heartbeat.metadata_json = json.dumps(metadata, ensure_ascii=True, sort_keys=True)
    session.add(heartbeat)
    session.commit()
    session.refresh(heartbeat)
    return heartbeat


def status_summary(session: Session, *, stale_after_seconds: int, now: datetime | None = None) -> dict[str, object]:
    current_time = now or utcnow()
    rows = list(session.exec(select(WorkerHeartbeat).order_by(col(WorkerHeartbeat.last_seen_at).desc())).all())
    return {
        "stale_after_seconds": stale_after_seconds,
        "generation": _type_summary(rows, WorkerType.GENERATION, current_time, stale_after_seconds),
        "result": _type_summary(rows, WorkerType.RESULT, current_time, stale_after_seconds),
        "render": _type_summary(rows, WorkerType.RENDER, current_time, stale_after_seconds),
    }


def _type_summary(
    rows: list[WorkerHeartbeat],
    worker_type: WorkerType,
    now: datetime,
    stale_after_seconds: int,
) -> dict[str, object]:
    typed = [row for row in rows if row.worker_type == worker_type]
    workers = [_worker_payload(row, now=now, stale_after_seconds=stale_after_seconds) for row in typed]
    return {
        "worker_type": worker_type,
        "online_count": sum(1 for worker in workers if worker["online"]),
        "total_count": len(workers),
        "stale_after_seconds": stale_after_seconds,
        "workers": workers,
    }


def _worker_payload(row: WorkerHeartbeat, *, now: datetime, stale_after_seconds: int) -> dict[str, object]:
    last_seen = row.last_seen_at
    if last_seen.tzinfo is None and now.tzinfo is not None:
        last_seen = last_seen.replace(tzinfo=now.tzinfo)
    online = now - last_seen <= timedelta(seconds=stale_after_seconds)
    return {
        "worker_id": row.worker_id,
        "worker_type": row.worker_type,
        "status": row.status,
        "online": online,
        "started_at": row.started_at,
        "last_seen_at": row.last_seen_at,
        "current_task_id": row.current_task_id,
        "processed_count": row.processed_count,
        "last_error_code": row.last_error_code,
        "last_error_message": row.last_error_message,
    }
