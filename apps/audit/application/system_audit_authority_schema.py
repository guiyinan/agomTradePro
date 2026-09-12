"""Versioned scope schema identifiers for system-audit authority bundles."""

from __future__ import annotations

from typing import Final

SYSTEM_AUDIT_SCOPE_SCHEMA_V1: Final[str] = "account.owner_tenant_authority.v1"
SYSTEM_AUDIT_SCOPE_SCHEMA_V2: Final[str] = "account.owner_tenant_authority.v2"
SYSTEM_AUDIT_SCOPE_SCHEMA_V3: Final[str] = "account.owner_tenant_authority.v3"
SYSTEM_AUDIT_SCOPE_SCHEMAS: Final[frozenset[str]] = frozenset(
    {
        SYSTEM_AUDIT_SCOPE_SCHEMA_V1,
        SYSTEM_AUDIT_SCOPE_SCHEMA_V2,
        SYSTEM_AUDIT_SCOPE_SCHEMA_V3,
    }
)


def validate_system_audit_scope_schema(value: object) -> str:
    """Return one supported scope schema or reject an unknown schema."""

    if type(value) is not str or value not in SYSTEM_AUDIT_SCOPE_SCHEMAS:
        raise ValueError("scope_schema must be a supported owner/tenant authority schema")
    return value


__all__ = [
    "SYSTEM_AUDIT_SCOPE_SCHEMA_V1",
    "SYSTEM_AUDIT_SCOPE_SCHEMA_V2",
    "SYSTEM_AUDIT_SCOPE_SCHEMA_V3",
    "SYSTEM_AUDIT_SCOPE_SCHEMAS",
    "validate_system_audit_scope_schema",
]
