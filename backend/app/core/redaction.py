from copy import deepcopy
from typing import Any


REDACTED_VALUE = "***REDACTED***"
SENSITIVE_KEYS = {
    "authorization",
    "api_key",
    "apikey",
    "x-api-key",
    "token",
    "access_token",
    "refresh_token",
    "cookie",
    "set-cookie",
    "password",
    "secret",
    "client_secret",
}


def redact_sensitive(value: Any) -> Any:
    candidate = deepcopy(value)
    return _redact(candidate)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED_VALUE if str(key).lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
