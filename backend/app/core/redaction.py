from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
SENSITIVE_QUERY_KEYS = {
    "api_key",
    "key",
    "token",
    "access_token",
    "sig",
    "signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
    "credential",
    "expires",
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
    if isinstance(value, str):
        return _redact_url(value)
    return value


def _redact_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.query:
        return value
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key.lower() in SENSITIVE_QUERY_KEYS for key, _ in pairs):
        return value
    redacted_pairs = [
        (key, REDACTED_VALUE if key.lower() in SENSITIVE_QUERY_KEYS else item)
        for key, item in pairs
    ]
    return urlunsplit(parsed._replace(query=urlencode(redacted_pairs)))
