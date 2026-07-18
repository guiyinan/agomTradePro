"""OpenAPI contracts for custom authentication classes."""

from apps.account.interface.openapi import TerminalInternalAuthenticationScheme
from apps.audit.interface.openapi import AuditIngestTokenAuthenticationScheme
from apps.realtime.interface.openapi import RealtimeTokenAuthenticationScheme


def test_terminal_internal_authentication_has_openapi_scheme():
    extension = TerminalInternalAuthenticationScheme(target=None)

    assert extension.name == "agomInternalSignature"
    definition = extension.get_security_definition(auto_schema=None)
    assert definition["type"] == "apiKey"
    assert definition["in"] == "header"
    assert definition["name"] == "X-Agom-Internal-Signature"
    assert "X-Agom-Internal-Timestamp" in definition["description"]


def test_realtime_token_authentication_uses_distinct_openapi_scheme():
    extension = RealtimeTokenAuthenticationScheme(target=None)

    assert extension.name == "realtimeTokenAuth"
    definition = extension.get_security_definition(auto_schema=None)
    assert definition["name"] == "Authorization"
    assert "Token <value>" in definition["description"]


def test_audit_ingest_token_authentication_uses_distinct_openapi_scheme():
    extension = AuditIngestTokenAuthenticationScheme(target=None)

    assert extension.name == "auditIngestTokenAuth"
    definition = extension.get_security_definition(auto_schema=None)
    assert definition["name"] == "Authorization"
    assert "Token <value>" in definition["description"]
