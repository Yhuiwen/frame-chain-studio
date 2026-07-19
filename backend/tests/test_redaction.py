from typing import Any
from urllib.parse import parse_qsl, urlsplit

from app.core.redaction import REDACTED_VALUE, redact_sensitive


def test_redacts_nested_sensitive_values_without_mutating_input() -> None:
    payload: dict[str, Any] = {
        "Authorization": "Bearer abc",
        "safe": "value",
        "nested": {"api_key": "secret", "model": "demo"},
        "items": [{"Cookie": "session"}, {"name": "kept"}],
    }

    redacted = redact_sensitive(payload)

    assert redacted["Authorization"] == REDACTED_VALUE
    assert redacted["nested"]["api_key"] == REDACTED_VALUE
    assert redacted["items"][0]["Cookie"] == REDACTED_VALUE
    assert redacted["safe"] == "value"
    assert redacted["nested"]["model"] == "demo"
    assert payload["Authorization"] == "Bearer abc"
    assert payload["nested"]["api_key"] == "secret"


def test_redacts_sensitive_url_query_values() -> None:
    payload = {
        "url": "https://cdn.example.test/file.png?X-Amz-Signature=secret&token=abc&safe=kept",
        "safe_url": "https://cdn.example.test/file.png?width=1280",
    }

    redacted = redact_sensitive(payload)

    assert "secret" not in redacted["url"]
    assert "token=abc" not in redacted["url"]
    assert "safe=kept" in redacted["url"]
    query = dict(parse_qsl(urlsplit(redacted["url"]).query))
    assert query["X-Amz-Signature"] == REDACTED_VALUE
    assert query["token"] == REDACTED_VALUE
    assert redacted["safe_url"] == payload["safe_url"]
