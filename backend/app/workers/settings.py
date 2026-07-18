import os
import secrets
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerSettings:
    worker_id: str
    lease_seconds: int = 30
    poll_interval_seconds: int = 1
    retry_base_seconds: float = 2
    retry_max_seconds: float = 300
    retry_jitter_ratio: float = 0.2
    max_unknown_polls: int = 3
    batch_size: int = 10
    submission_timeout_seconds: int = 120
    job_timeout_seconds: int = 1800
    cancellation_timeout_seconds: int = 120

    def __post_init__(self) -> None:
        if self.retry_base_seconds <= 0:
            raise ValueError("retry_base_seconds must be positive")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("retry_max_seconds must be >= retry_base_seconds")
        if not 0 <= self.retry_jitter_ratio <= 1:
            raise ValueError("retry_jitter_ratio must be between 0 and 1")
        if min(self.submission_timeout_seconds, self.job_timeout_seconds, self.cancellation_timeout_seconds) < 0:
            raise ValueError("timeout values cannot be negative")


def load_worker_settings() -> WorkerSettings:
    worker_id = os.getenv("FCS_WORKER_ID")
    if not worker_id:
        worker_id = f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(4)}"
    return WorkerSettings(
        worker_id=worker_id,
        lease_seconds=int(os.getenv("FCS_WORKER_LEASE_SECONDS", "30")),
        poll_interval_seconds=int(os.getenv("FCS_WORKER_POLL_INTERVAL_SECONDS", "1")),
        retry_base_seconds=float(os.getenv("FCS_WORKER_RETRY_BASE_SECONDS", "2")),
        retry_max_seconds=float(os.getenv("FCS_WORKER_RETRY_MAX_SECONDS", "300")),
        retry_jitter_ratio=float(os.getenv("FCS_WORKER_RETRY_JITTER_RATIO", "0.2")),
        max_unknown_polls=int(os.getenv("FCS_WORKER_MAX_UNKNOWN_POLLS", "3")),
        batch_size=int(os.getenv("FCS_WORKER_BATCH_SIZE", "10")),
        submission_timeout_seconds=int(os.getenv("FCS_WORKER_SUBMISSION_TIMEOUT_SECONDS", "120")),
        job_timeout_seconds=int(os.getenv("FCS_WORKER_JOB_TIMEOUT_SECONDS", "1800")),
        cancellation_timeout_seconds=int(os.getenv("FCS_WORKER_CANCELLATION_TIMEOUT_SECONDS", "120")),
    )
