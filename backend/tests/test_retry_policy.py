from datetime import datetime, timedelta

from app.domain.retry_policy import RetryPolicyConfig, decide_error, exponential_delay, retry_after_delay
from app.models.entities import ReliableTaskStatus, TaskErrorCode


def test_retryable_errors_use_exponential_backoff_without_jitter() -> None:
    config = RetryPolicyConfig(base_seconds=2, max_seconds=30, jitter_ratio=0)

    assert exponential_delay(retry_count=0, config=config) == 2
    assert exponential_delay(retry_count=1, config=config) == 4
    assert exponential_delay(retry_count=8, config=config) == 30


def test_retry_after_numeric_and_http_date_are_clamped() -> None:
    now = datetime(2026, 7, 18, 12, 0, 0)

    assert retry_after_delay("8", now=now, max_seconds=30) == 8
    assert retry_after_delay("120", now=now, max_seconds=30) == 30
    assert retry_after_delay("Sat, 18 Jul 2026 12:00:05 GMT", now=now, max_seconds=30) == 5
    assert retry_after_delay("not-a-date", now=now, max_seconds=30) is None
    assert retry_after_delay((now - timedelta(seconds=1)).isoformat(), now=now, max_seconds=30) is None


def test_decide_error_classifies_retryable_and_terminal_errors() -> None:
    retryable = decide_error(
        TaskErrorCode.REMOTE_SERVER_ERROR,
        retry_count=1,
        config=RetryPolicyConfig(base_seconds=3, max_seconds=30, jitter_ratio=0),
    )
    assert retryable.retryable is True
    assert retryable.retry_after_seconds == 6
    assert retryable.terminal_status is None

    cancelled = decide_error(TaskErrorCode.CANCELLED)
    assert cancelled.retryable is False
    assert cancelled.terminal_status == ReliableTaskStatus.CANCELLED

    unknown = decide_error("VENDOR_ODDITY")
    assert unknown.error_code == TaskErrorCode.UNKNOWN_ERROR.value
    assert unknown.terminal_status == ReliableTaskStatus.FAILED
