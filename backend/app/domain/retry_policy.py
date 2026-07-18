from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from random import Random

from pydantic import BaseModel

from app.models.entities import ReliableTaskStatus, TaskErrorCode


class ErrorDecision(BaseModel):
    error_code: str
    retryable: bool
    retry_category: str | None = None
    retry_after_seconds: float | None = None
    terminal_status: ReliableTaskStatus | None = None
    user_message: str


@dataclass(frozen=True)
class RetryPolicyConfig:
    base_seconds: float = 2.0
    max_seconds: float = 300.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.base_seconds <= 0:
            raise ValueError("base_seconds must be positive")
        if self.max_seconds < self.base_seconds:
            raise ValueError("max_seconds must be >= base_seconds")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")


RETRYABLE_CODES = {
    TaskErrorCode.RATE_LIMITED,
    TaskErrorCode.REMOTE_SERVER_ERROR,
    TaskErrorCode.NETWORK_ERROR,
    TaskErrorCode.REQUEST_TIMEOUT,
}


def decide_error(
    error_code: TaskErrorCode | str,
    *,
    retry_after: str | None = None,
    retry_count: int = 0,
    now: datetime | None = None,
    config: RetryPolicyConfig | None = None,
    random_source: Callable[[], float] | None = None,
) -> ErrorDecision:
    try:
        resolved = error_code if isinstance(error_code, TaskErrorCode) else TaskErrorCode(error_code)
    except ValueError:
        resolved = TaskErrorCode.UNKNOWN_ERROR
    policy = config or RetryPolicyConfig()
    if resolved not in RETRYABLE_CODES:
        terminal = ReliableTaskStatus.CANCELLED if resolved == TaskErrorCode.CANCELLED else ReliableTaskStatus.FAILED
        return ErrorDecision(
            error_code=resolved.value,
            retryable=False,
            terminal_status=terminal,
            user_message=_message_for(resolved),
        )
    delay = retry_after_delay(retry_after, now=now, max_seconds=policy.max_seconds)
    if delay is None:
        delay = exponential_delay(
            retry_count=retry_count,
            config=policy,
            random_source=random_source,
        )
    return ErrorDecision(
        error_code=resolved.value,
        retryable=True,
        retry_category=resolved.value,
        retry_after_seconds=delay,
        user_message=_message_for(resolved),
    )


def exponential_delay(
    *,
    retry_count: int,
    config: RetryPolicyConfig,
    random_source: Callable[[], float] | None = None,
) -> float:
    base = min(config.max_seconds, config.base_seconds * (2 ** max(retry_count, 0)))
    if config.jitter_ratio == 0:
        return base
    source = random_source or Random().random
    factor = (1 - config.jitter_ratio) + (source() * config.jitter_ratio * 2)
    return min(config.max_seconds, base * factor)


def retry_after_delay(value: str | None, *, now: datetime | None, max_seconds: float) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
        seconds = (_db_time(parsed) - _db_time(now)).total_seconds()
    if seconds < 0:
        return None
    return min(max_seconds, seconds)


def _db_time(value: datetime | None) -> datetime:
    candidate = value or datetime.utcnow()
    if candidate.tzinfo is not None:
        return candidate.astimezone(timezone.utc).replace(tzinfo=None)
    return candidate


def _message_for(error_code: TaskErrorCode) -> str:
    messages = {
        TaskErrorCode.CONFIGURATION_ERROR: "Provider configuration is invalid.",
        TaskErrorCode.AUTHENTICATION_ERROR: "Provider authentication failed.",
        TaskErrorCode.RATE_LIMITED: "Provider is rate limited; retry is scheduled.",
        TaskErrorCode.REMOTE_SERVER_ERROR: "Provider server returned a temporary error.",
        TaskErrorCode.NETWORK_ERROR: "Network request failed.",
        TaskErrorCode.REQUEST_TIMEOUT: "Provider request timed out.",
        TaskErrorCode.JOB_TIMEOUT: "Remote job timed out.",
        TaskErrorCode.INVALID_REMOTE_RESPONSE: "Provider returned an invalid response.",
        TaskErrorCode.CANCELLED: "Task was cancelled.",
        TaskErrorCode.UNKNOWN_ERROR: "Unexpected task error.",
    }
    return messages.get(error_code, "Task failed.")
