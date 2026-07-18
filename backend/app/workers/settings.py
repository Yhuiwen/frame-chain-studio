import os
import secrets
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSettings:
    worker_id: str
    lease_seconds: int = 30
    poll_interval_seconds: int = 1
    retry_delay_seconds: int = 5
    max_unknown_polls: int = 3
    batch_size: int = 10


def load_worker_settings() -> WorkerSettings:
    worker_id = os.getenv("FCS_WORKER_ID")
    if not worker_id:
        worker_id = f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(4)}"
    return WorkerSettings(
        worker_id=worker_id,
        lease_seconds=int(os.getenv("FCS_WORKER_LEASE_SECONDS", "30")),
        poll_interval_seconds=int(os.getenv("FCS_WORKER_POLL_INTERVAL_SECONDS", "1")),
        retry_delay_seconds=int(os.getenv("FCS_WORKER_RETRY_DELAY_SECONDS", "5")),
        max_unknown_polls=int(os.getenv("FCS_WORKER_MAX_UNKNOWN_POLLS", "3")),
        batch_size=int(os.getenv("FCS_WORKER_BATCH_SIZE", "10")),
    )
