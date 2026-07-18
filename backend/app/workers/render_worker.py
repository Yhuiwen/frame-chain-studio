import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from app.models.entities import WorkerStatus, WorkerType
from app.services import worker_status
from app.workers.execution_service import SessionFactory
from app.workers.render_service import RenderProcessingService, acquire_render_lease, release_render_lease

logger = logging.getLogger(__name__)


class RenderWorker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        worker_id: str,
        lease_seconds: int,
        poll_interval_seconds: int = 1,
        processing_service: RenderProcessingService | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.processing_service = processing_service or RenderProcessingService(session_factory=session_factory)
        self._stop_event = asyncio.Event()

    async def run_once(self, *, now: datetime | None = None) -> int:
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.worker_id,
            worker_type=WorkerType.RENDER,
            status=WorkerStatus.IDLE,
            now=now,
        )
        with self.session_factory() as session:
            render = acquire_render_lease(
                session,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                now=now,
            )
        if render is None or render.id is None:
            return 0
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.worker_id,
            worker_type=WorkerType.RENDER,
            status=WorkerStatus.BUSY,
            current_task_id=None,
            metadata={"render_id": render.id},
            now=now,
        )
        try:
            logger.info("render worker claim render_id=%s worker_id=%s", render.id, self.worker_id)
            did_work = self.processing_service.process_render_once(render.id)
            return 1 if did_work else 0
        except Exception as exc:
            logger.warning("render worker failed render_id=%s worker_id=%s error=%s", render.id, self.worker_id, exc)
            worker_status.safe_heartbeat(
                self.session_factory,
                worker_id=self.worker_id,
                worker_type=WorkerType.RENDER,
                status=WorkerStatus.ERROR,
                last_error_code=exc.__class__.__name__,
                last_error_message=str(exc),
                metadata={"render_id": render.id},
                now=now,
            )
            return 1
        finally:
            with self.session_factory() as session:
                release_render_lease(session, render.id, worker_id=self.worker_id)
            worker_status.safe_heartbeat(
                self.session_factory,
                worker_id=self.worker_id,
                worker_type=WorkerType.RENDER,
                status=WorkerStatus.IDLE,
                now=now,
            )

    async def run_until_idle(self, *, now: Callable[[], datetime] | None = None) -> int:
        total = 0
        while True:
            processed = await self.run_once(now=now() if now else None)
            if processed == 0:
                return total
            total += processed

    async def run_forever(self) -> None:
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.worker_id,
            worker_type=WorkerType.RENDER,
            status=WorkerStatus.STARTING,
        )
        try:
            while not self._stop_event.is_set():
                processed = await self.run_once()
                if processed == 0:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
                    except TimeoutError:
                        pass
        finally:
            worker_status.safe_heartbeat(
                self.session_factory,
                worker_id=self.worker_id,
                worker_type=WorkerType.RENDER,
                status=WorkerStatus.STOPPED,
            )

    def stop(self) -> None:
        worker_status.safe_heartbeat(
            self.session_factory,
            worker_id=self.worker_id,
            worker_type=WorkerType.RENDER,
            status=WorkerStatus.STOPPING,
        )
        self._stop_event.set()
