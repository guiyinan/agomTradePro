"""Explicit composition root for same-alias calendar Audit event/outbox use cases."""

from __future__ import annotations

from typing import Protocol

from apps.audit.application.calendar_publication_audit import (
    CalendarPublicationAuditOutboxWriter,
)
from apps.audit.application.calendar_publication_integrity import (
    CalendarPublicationAuditIntegrityReader,
)
from apps.audit.application.calendar_publication_replay_verifier import (
    CalendarPublicationAuditReplayReader,
)
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from core.exceptions import InvalidInputError


class CalendarPublicationAuditCoordinator(
    CalendarPublicationAuditOutboxWriter,
    CalendarPublicationAuditReplayReader,
    CalendarPublicationAuditIntegrityReader,
    Protocol,
):
    """One alias-bound adapter serving only the calendar Audit App ports."""

    pass


def build_calendar_publication_audit_coordinator(
    *,
    using: str,
) -> CalendarPublicationAuditCoordinator:
    """Build the existing canonical coordinator for an explicit database alias."""

    if type(using) is not str or not using or using.strip() != using:
        raise InvalidInputError(
            "calendar Audit composition requires an explicit database alias",
            code="CALENDAR_PUBLICATION_AUDIT_ALIAS_INVALID",
        )
    coordinator = DjangoSystemAuditEventOutboxCoordinator(using=using)
    if coordinator.database_alias != using:
        raise InvalidInputError(
            "calendar Audit coordinator was composed on another database alias",
            code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
        )
    return coordinator


__all__ = [
    "CalendarPublicationAuditCoordinator",
    "build_calendar_publication_audit_coordinator",
]
