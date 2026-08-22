from atlas_trader.infrastructure.logging import _redact_secrets


def test_sensitive_logging_fields_are_redacted() -> None:
    event = {
        "event_type": "api.failure",
        "authorization": "Bearer secret",
        "nobitex_token": "secret",
        "request": {"Authorization": "Bearer nested-secret"},
        "legacy": {"NOBITEX_API": "legacy-secret"},
        "vendor_access_token": "suffix-secret",
    }

    result = _redact_secrets(None, "error", event)

    assert result["authorization"] == "[REDACTED]"
    assert result["nobitex_token"] == "[REDACTED]"
    assert result["request"]["Authorization"] == "[REDACTED]"
    assert result["legacy"]["NOBITEX_API"] == "[REDACTED]"
    assert result["vendor_access_token"] == "[REDACTED]"
