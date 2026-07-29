"""Agent Runtime audit-boundary security tests."""

from apps.agent_runtime.application.services.audit_service import _masked_dict


def test_audit_payload_masks_nested_credentials_and_dsn() -> None:
    """Nested secrets and credential-bearing URLs are removed before persistence."""

    payload = _masked_dict(
        {
            "token": "raw-token",
            "nested": {
                "endpoint": "postgresql://user:secret@database.internal/runtime",
                "safe": "kept",
            },
        }
    )

    rendered = str(payload)
    assert "raw-token" not in rendered
    assert "secret" not in rendered
    assert payload["nested"]["safe"] == "kept"
