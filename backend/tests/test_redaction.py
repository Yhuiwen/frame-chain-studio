from typing import Any

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
