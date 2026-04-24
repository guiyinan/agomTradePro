"""Repository provider for audit application orchestration."""

from __future__ import annotations

from apps.audit.infrastructure.repositories import DjangoAuditRepository


def get_audit_repository() -> DjangoAuditRepository:
    """Return the configured audit repository implementation."""

    return DjangoAuditRepository()
