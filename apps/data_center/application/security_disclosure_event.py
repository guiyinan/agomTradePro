"""Use cases for append-only official-exchange disclosure facts."""

from __future__ import annotations

import logging
from typing import Protocol

from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
)
from core.exceptions import DataValidationError

logger = logging.getLogger(__name__)


class SecurityDisclosureEventRepositoryPort(Protocol):
    """Infrastructure port for immutable source disclosure facts."""

    def append(
        self,
        event: SecurityDisclosureEvent,
        source_document_body: bytes,
    ) -> SecurityDisclosureEventAppendResult:
        """Persist one verified source document or return its exact first winner."""

    def list_known_at(
        self,
        scope: SecurityDisclosureEventReadScope,
    ) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        """Read source revisions available to the public by one candidate cutoff."""


class AppendSecurityDisclosureEventUseCase:
    """Validate a typed source document and append its exact event revision."""

    def __init__(self, repository: SecurityDisclosureEventRepositoryPort) -> None:
        """Bind the owning Data Center repository."""

        self._repository = repository

    def execute(
        self,
        event: SecurityDisclosureEvent,
        source_document_body: bytes,
    ) -> SecurityDisclosureEventAppendResult:
        """Append one event only when its original document bytes match the event hash."""

        if type(event) is not SecurityDisclosureEvent:
            raise DataValidationError(
                "Security disclosure event input is invalid.",
                code="SECURITY_DISCLOSURE_EVENT_INPUT_INVALID",
            )
        if not event.verifies_source_document(source_document_body):
            raise DataValidationError(
                "Source document bytes do not match the disclosure evidence hash.",
                code="SECURITY_DISCLOSURE_EVENT_SOURCE_BODY_MISMATCH",
            )
        if event.event_type is SecurityDisclosureEventType.UNKNOWN:
            logger.warning(
                "Unknown official disclosure type retained as UNKNOWN "
                "(source=%s, asset_code=%s, source_event_id=%s, raw_event_type=%s)",
                event.source.value,
                event.asset_code,
                event.source_event_id,
                event.raw_event_type,
            )
        return self._repository.append(event, source_document_body)


class QuerySecurityDisclosureEventsUseCase:
    """Read source events by public availability without dispatch or account writes."""

    def __init__(self, repository: SecurityDisclosureEventRepositoryPort) -> None:
        """Bind the owning Data Center repository."""

        self._repository = repository

    def execute(
        self,
        scope: SecurityDisclosureEventReadScope,
    ) -> tuple[PersistedSecurityDisclosureEvent, ...]:
        """Return every matching revision available by the supplied knowledge cutoff."""

        if type(scope) is not SecurityDisclosureEventReadScope:
            raise DataValidationError(
                "Security disclosure event read scope is invalid.",
                code="SECURITY_DISCLOSURE_EVENT_SCOPE_INVALID",
            )
        return self._repository.list_known_at(scope)


__all__ = [
    "AppendSecurityDisclosureEventUseCase",
    "QuerySecurityDisclosureEventsUseCase",
    "SecurityDisclosureEventRepositoryPort",
]
