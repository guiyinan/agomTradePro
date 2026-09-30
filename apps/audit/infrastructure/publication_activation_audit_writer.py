"""Caller-owned audit adapter for the feature-off publication activation path."""

from __future__ import annotations

from datetime import datetime

from apps.audit.application.data_publication_audit import (
    AppendDataPublicationAuditObservationUseCase,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.audit.infrastructure.system_audit_event_outbox_coordinator import (
    DjangoSystemAuditEventOutboxCoordinator,
)
from apps.data_center.application.publication_activation import (
    PublicationActivationAuditWriter,
    PublicationActivationRequest,
)
from apps.data_center.domain.control_plane import CanonicalPublication, PublicationMember
from core.integration.data_center_audit import (
    DataPublicationAuditObservation,
    SystemAuditEventOutboxCommit,
)


class _CallerOwnedScopeProvider:
    """Reject accidental use of the scope resolving API on this adapter."""

    def get_scope(self, *, as_of: datetime) -> AuditScopeRef:
        """Require activation to provide its already-fenced scope explicitly."""

        del as_of
        raise RuntimeError("publication activation audit requires the caller-owned path")


class DjangoPublicationActivationAuditWriter(PublicationActivationAuditWriter):
    """Write the required event and outbox row in activation's outer UOW."""

    def __init__(
        self,
        coordinator: DjangoSystemAuditEventOutboxCoordinator,
    ) -> None:
        if not isinstance(coordinator, DjangoSystemAuditEventOutboxCoordinator):
            raise TypeError("publication activation requires the canonical audit coordinator")
        self._coordinator = coordinator
        self._use_case = AppendDataPublicationAuditObservationUseCase(
            coordinator,
            _CallerOwnedScopeProvider(),
        )

    @property
    def database_alias(self) -> str:
        """Return the alias shared by publication and audit persistence."""

        return self._coordinator.database_alias

    def append_required(
        self,
        *,
        request: PublicationActivationRequest,
        publication: CanonicalPublication,
        members: tuple[PublicationMember, ...],
        observation: DataPublicationAuditObservation,
    ) -> SystemAuditEventOutboxCommit:
        """Append one exact activation observation with no nested transaction."""

        del request, publication, members
        return self._use_case.execute_in_caller_transaction(observation)


__all__ = ["DjangoPublicationActivationAuditWriter"]
