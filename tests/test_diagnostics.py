"""Only safe upstream validation details cross the MCP boundary."""

from wallapop_mcp.diagnostics import diagnostic_message, safe_error_payload


def test_error_payload_keeps_validation_field_but_drops_tokens_and_links():
    payload = {
        "status": {"code": "INVALID_ATTRIBUTE", "message": "invalid color"},
        "errors": [{"field": "color", "message": "not supported"}],
        "access_token": "super-secret",
        "request_url": "https://example.test/?sig=secret",
    }
    safe = safe_error_payload(payload)
    assert safe == {
        "status": {"code": "INVALID_ATTRIBUTE", "message": "invalid color"},
        "errors": [{"field": "color", "message": "not supported"}],
    }
    assert diagnostic_message(safe) == "not supported" or diagnostic_message(safe) == "invalid color"


def test_signed_url_inside_message_is_redacted():
    safe = safe_error_payload({"message": "see https://example.test/?sig=secret"})
    assert safe == {"message": "see [URL redacted]"}


def test_named_secret_inside_message_is_redacted():
    safe = safe_error_payload({"message": "invalid access_token=shortsecret"})
    assert safe == {"message": "invalid [credential redacted]"}


def test_nested_validation_data_is_kept_without_unknown_fields():
    safe = safe_error_payload({"data": {"errors": [{"field": "model", "message": "invalid"}], "token": "secret"}})
    assert safe == {"data": {"errors": [{"field": "model", "message": "invalid"}]}}
