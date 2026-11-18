"""Audit-owned construction of the canonical event/outbox public port."""

from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCoordinator
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from core.exceptions import InvalidInputError


def build_system_audit_event_outbox_coordinator(
    *,
    using: str,
) -> SystemAuditEventOutboxCoordinator:
    """Build the existing implementation without exposing persistence to its consumers."""

    if type(using) is not str or not using or using != using.strip():
        raise InvalidInputError(
            "Audit database alias is invalid", code="SYSTEM_AUDIT_ALIAS_INVALID"
        )
    coordinator = DjangoSystemAuditEventOutboxCoordinator(using=using)
    if coordinator.database_alias != using:
        raise InvalidInputError("Audit database alias differs", code="SYSTEM_AUDIT_ALIAS_MISMATCH")
    return coordinator
