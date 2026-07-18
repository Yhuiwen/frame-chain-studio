from typing import Any

from app.core.redaction import redact_sensitive
from app.models.entities import TaskErrorCode


def truncate_text(value: str, limit: int = 1000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


class ProviderError(Exception):
    error_code = TaskErrorCode.UNKNOWN_ERROR
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.message = truncate_text(message)
        self.http_status = http_status
        self.details = redact_sensitive(details or {})
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.message)

    def to_task_error_code(self) -> TaskErrorCode:
        return self.error_code

    def as_details(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "details": self.details,
        }


class ProviderConfigurationError(ProviderError):
    error_code = TaskErrorCode.CONFIGURATION_ERROR


class ProviderAuthenticationError(ProviderError):
    error_code = TaskErrorCode.AUTHENTICATION_ERROR


class ProviderRateLimitError(ProviderError):
    error_code = TaskErrorCode.RATE_LIMITED
    retryable = True


class ProviderRemoteServerError(ProviderError):
    error_code = TaskErrorCode.REMOTE_SERVER_ERROR
    retryable = True


class ProviderNetworkError(ProviderError):
    error_code = TaskErrorCode.NETWORK_ERROR
    retryable = True


class ProviderTimeoutError(ProviderError):
    error_code = TaskErrorCode.REQUEST_TIMEOUT
    retryable = True


class ProviderInvalidResponseError(ProviderError):
    error_code = TaskErrorCode.INVALID_REMOTE_RESPONSE


class ProviderUnsupportedCapabilityError(ProviderError):
    error_code = TaskErrorCode.CONFIGURATION_ERROR


class ProviderJobNotFoundError(ProviderError):
    error_code = TaskErrorCode.INVALID_REMOTE_RESPONSE


class ProviderCancellationError(ProviderError):
    error_code = TaskErrorCode.UNKNOWN_ERROR
