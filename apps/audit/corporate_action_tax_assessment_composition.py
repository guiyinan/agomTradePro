"""Expose the existing atomic Audit coordinator through a narrow public owner port."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from apps.audit.application.system_audit_event_outbox import (
    ExactSystemAuditOutboxWinner,
    SystemAuditEventOutboxCommit,
)
from apps.audit.domain.system_audit_event import AuditScopeRef, SystemAuditEvent
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from core.exceptions import InvalidInputError


class TaxAssessmentAuditCoordinatorPort(Protocol):
    """Alias-bound existing event/Outbox capabilities for one caller-owned transaction."""

    @property
    def database_alias(self) -> str:
        """Return the common database alias."""
        ...

    def caller_owned_atomic(self) -> AbstractContextManager[None]:
        """Bind existing private append capabilities to the outer transaction."""
        ...

    def lock_streams(self, stream_ids: tuple[str, ...]) -> None:
        """Lock streams in stable order before reading or appending."""
        ...

    def get_winner_targeted(
        self, *, event_id: str, event_version: str, as_of: datetime, lock: bool = False
    ) -> SystemAuditEvent | None:
        """Read one exact event identity."""
        ...

    def get_current_head_targeted(
        self,
        *,
        stream_id: str,
        as_of: datetime,
        scope: AuditScopeRef | None = None,
        lock: bool = False,
    ) -> SystemAuditEvent | None:
        """Read the exact scoped stream head."""
        ...

    def get_exact_outbox_winner_targeted(
        self, event: SystemAuditEvent
    ) -> ExactSystemAuditOutboxWinner | None:
        """Read the original exact Outbox pair without repairing missing evidence."""
        ...

    def append_and_enqueue_targeted(
        self,
        event: SystemAuditEvent,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
        scope: AuditScopeRef | None = None,
        identity_winner: SystemAuditEvent | None = None,
        stream_head: SystemAuditEvent | None = None,
    ) -> SystemAuditEventOutboxCommit:
        """Append the event and exact Outbox payload in the bound transaction."""
        ...


def build_tax_assessment_audit_coordinator(*, using: str) -> TaxAssessmentAuditCoordinatorPort:
    """Compose the existing Audit implementation without issuing any user authority."""
    if (
        type(using) is not str
        or not using
        or using != using.strip()
        or any(c.isspace() for c in using)
    ):
        raise InvalidInputError("Tax assessment Audit requires an explicit database alias.")
    return DjangoSystemAuditEventOutboxCoordinator(using=using)


__all__ = ["TaxAssessmentAuditCoordinatorPort", "build_tax_assessment_audit_coordinator"]
