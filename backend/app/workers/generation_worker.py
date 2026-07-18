import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime

from sqlmodel import Session

from app.models.entities import WorkerStatus, WorkerType
from app.providers.registry import ProviderRegistry
from app.services import task_service, worker_status
from app.workers import task_selector
from app.workers.execution_service import ProviderExecutionService, SessionFactory
from app.workers.settings import WorkerSettings

logger = logging.getLogger(__name__)


class GenerationWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        registry: ProviderRegistry,
        settings: WorkerSettings,
        execution_service: ProviderExecutionService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.settings = settings
        self.execution_service = execution_service or ProviderExecutionService(
            session_factory=session_factory,
            registry=registry,
            settings=settings,
        )
        self._stop_event = asyncio.Event()

    async def run_once(self, *, now: datetime | None = None) -> int:
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.settings.worker_id,
            worker_type=WorkerType.GENERATION,
            status=WorkerStatus.IDLE,
            now=now,
        )
        configured = {info.provider_id for info in self.registry.list_capabilities() if info.configured}
        with self.session_factory() as session:
            task_ids = task_selector.find_due_task_ids(
                session,
                configured_provider_ids=configured,
                limit=self.settings.batch_size,
                now=now,
            )
        processed = 0
        for task_id in task_ids:
            with self.session_factory() as session:
                leased = task_service.acquire_task_lease(
                    session,
                    task_id,
                    worker_id=self.settings.worker_id,
                    lease_seconds=self.settings.lease_seconds,
                    now=now,
                )
            if leased is None:
                continue
            worker_status.safe_heartbeat(
                self.session_factory,
                worker_id=self.settings.worker_id,
                worker_type=WorkerType.GENERATION,
                status=WorkerStatus.BUSY,
                current_task_id=task_id,
                now=now,
            )
            try:
                logger.info(
                    "worker claim task_id=%s worker_id=%s provider_id=%s",
                    task_id,
                    self.settings.worker_id,
                    leased.provider_id,
                )
                did_work = await self.execution_service.process_task_once(task_id, now=now)
                processed += 1 if did_work else 0
            except Exception as exc:
                logger.warning(
                    "worker task failed task_id=%s worker_id=%s error=%s",
                    task_id,
                    self.settings.worker_id,
                    exc,
                )
                worker_status.safe_heartbeat(
                    self.session_factory,
                    worker_id=self.settings.worker_id,
                    worker_type=WorkerType.GENERATION,
                    status=WorkerStatus.ERROR,
                    current_task_id=task_id,
                    last_error_code=exc.__class__.__name__,
                    last_error_message=str(exc),
                    now=now,
                )
            finally:
                with self.session_factory() as session:
                    task_service.release_task_lease(session, task_id, worker_id=self.settings.worker_id)
                worker_status.safe_heartbeat(
                    self.session_factory,
                    worker_id=self.settings.worker_id,
                    worker_type=WorkerType.GENERATION,
                    status=WorkerStatus.IDLE,
                    processed_count=processed,
                    now=now,
                )
        return processed

    async def run_until_idle(self, *, now: Callable[[], datetime] | None = None) -> int:
        total = 0
        while True:
            current = now() if now else None
            processed = await self.run_once(now=current)
            if processed == 0:
                return total
            total += processed

    async def run_forever(self) -> None:
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.settings.worker_id,
            worker_type=WorkerType.GENERATION,
            status=WorkerStatus.STARTING,
        )
        try:
            while not self._stop_event.is_set():
                processed = await self.run_once()
                if processed == 0:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.poll_interval_seconds)
                    except TimeoutError:
                        pass
        finally:
            worker_status.safe_heartbeat(
                self.session_factory,
                worker_id=self.settings.worker_id,
                worker_type=WorkerType.GENERATION,
                status=WorkerStatus.STOPPED,
            )

    def stop(self) -> None:
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.settings.worker_id,
            worker_type=WorkerType.GENERATION,
            status=WorkerStatus.STOPPING,
        )
        self._stop_event.set()


def session_factory_from_sessionmaker(factory: Callable[[], AbstractContextManager[Session]]) -> SessionFactory:
    return factory
