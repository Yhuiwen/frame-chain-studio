import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from app.providers.registry import ProviderRegistry
from app.services import task_service
from app.workers.execution_service import SessionFactory
from app.workers.result_processing_service import ResultProcessingService, ResultWorkerSettings
from app.workers.result_selector import find_due_result_task_ids

logger = logging.getLogger(__name__)


class ResultWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        settings: ResultWorkerSettings,
        processing_service: ResultProcessingService | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.processing_service = processing_service or ResultProcessingService(
            session_factory=session_factory,
            settings=settings,
        )
        self.registry = registry
        self._stop_event = asyncio.Event()

    async def run_once(self, *, now: datetime | None = None) -> int:
        with self.session_factory() as session:
            task_ids = find_due_result_task_ids(session, limit=self.settings.batch_size, now=now)
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
            try:
                logger.info("result worker claim task_id=%s worker_id=%s", task_id, self.settings.worker_id)
                did_work = await self.processing_service.process_task_once(task_id)
                processed += 1 if did_work else 0
            except Exception as exc:
                logger.warning("result worker task failed task_id=%s worker_id=%s error=%s", task_id, self.settings.worker_id, exc)
            finally:
                with self.session_factory() as session:
                    task_service.release_task_lease(session, task_id, worker_id=self.settings.worker_id)
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
        while not self._stop_event.is_set():
            processed = await self.run_once()
            if processed == 0:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.settings.poll_interval_seconds)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self._stop_event.set()
