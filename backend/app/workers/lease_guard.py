import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlmodel import Session

from app.services import task_service


class LeaseLostError(RuntimeError):
    pass


SessionFactory = Callable[[], AbstractContextManager[Session]]
T = TypeVar("T")


@dataclass(frozen=True)
class TaskLeaseGuardConfig:
    task_id: int
    worker_id: str
    lease_seconds: int
    session_factory: SessionFactory
    heartbeat: Callable[[], None] | None = None


class TaskLeaseGuard:
    def __init__(self, config: TaskLeaseGuardConfig) -> None:
        self.config = config
        self.interval_seconds = max(1.0, config.lease_seconds / 3)
        self._lost = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    async def __aenter__(self) -> "TaskLeaseGuard":
        self._task = asyncio.create_task(self._renew_loop())
        return self

    async def __aexit__(self, *_args: object) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _renew_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
                return
            except TimeoutError:
                pass
            if self.config.heartbeat is not None:
                self.config.heartbeat()
            with self.config.session_factory() as session:
                renewed = task_service.renew_task_lease(
                    session,
                    self.config.task_id,
                    worker_id=self.config.worker_id,
                    lease_seconds=self.config.lease_seconds,
                )
            if renewed is None:
                self._lost.set()
                return

    def ensure_owned(self) -> None:
        if self._lost.is_set():
            raise LeaseLostError("Task lease was lost.")
        with self.config.session_factory() as session:
            if not task_service.task_lease_is_owned(
                session,
                self.config.task_id,
                worker_id=self.config.worker_id,
            ):
                self._lost.set()
                raise LeaseLostError("Task lease was lost.")

    async def run_cancellable(self, operation: Awaitable[T]) -> T:
        op_task: asyncio.Future[T] = asyncio.ensure_future(operation)
        lost_task = asyncio.create_task(self._lost.wait())
        try:
            wait_tasks: set[asyncio.Future[Any]] = {op_task, lost_task}
            done, _ = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)
            if lost_task in done and self._lost.is_set():
                op_task.cancel()
                raise LeaseLostError("Task lease was lost.")
            return await op_task
        finally:
            lost_task.cancel()
            if not op_task.done():
                op_task.cancel()
