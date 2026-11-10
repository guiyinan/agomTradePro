"""Use cases for append-only official-exchange disclosure facts."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from apps.data_center.domain.security_disclosure_event import (
    PersistedSecurityDisclosureEvent,
    PersistedSecurityDisclosureListingCoverage,
    SecurityDisclosureEvent,
    SecurityDisclosureEventAppendResult,
    SecurityDisclosureEventReadScope,
    SecurityDisclosureEventType,
    SecurityDisclosureExchange,
    SecurityDisclosureListingCoverageAppendResult,
    SecurityDisclosureListingCoverageProof,
    SecurityDisclosureListingCoverageReadScope,
    SecurityDisclosureListingCoverageSnapshot,
    SecurityDisclosureListingCoverageStatus,
    SecurityDisclosureListingEntry,
    SecurityDisclosureSource,
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


class SecurityDisclosureListingCoverageRepositoryPort(Protocol):
    """Infrastructure port for immutable, exact SZSE listing-window proofs."""

    def append(
        self,
        proof: SecurityDisclosureListingCoverageProof,
    ) -> SecurityDisclosureListingCoverageAppendResult:
        """Persist one completed two-pass proof or return its exact first winner."""

    def get_known_at(
        self,
        scope: SecurityDisclosureListingCoverageReadScope,
    ) -> PersistedSecurityDisclosureListingCoverage | None:
        """Return the newest exact-window proof durably recorded by the cutoff."""

    def get_by_episode(
        self,
        proof: SecurityDisclosureListingCoverageProof,
    ) -> PersistedSecurityDisclosureListingCoverage | None:
        """Return the exact already-retained proof episode and observation clocks."""


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


class AppendSecurityDisclosureListingCoverageUseCase:
    """Persist completed official-list evidence after event PDFs were ingested."""

    def __init__(self, repository: SecurityDisclosureListingCoverageRepositoryPort) -> None:
        """Bind the Data Center-owned append-only proof repository."""

        self._repository = repository

    def execute(
        self,
        proof: SecurityDisclosureListingCoverageProof,
    ) -> SecurityDisclosureListingCoverageAppendResult:
        """Append one exact typed listing proof without refreshing an existing winner."""

        if type(proof) is not SecurityDisclosureListingCoverageProof:
            raise DataValidationError(
                "Security disclosure listing proof is invalid.",
                code="SECURITY_DISCLOSURE_LISTING_PROOF_INVALID",
            )
        return self._repository.append(proof)

    def get_by_episode(
        self,
        proof: SecurityDisclosureListingCoverageProof,
    ) -> PersistedSecurityDisclosureListingCoverage | None:
        """Return the exact previously retained proof episode, if present."""

        if type(proof) is not SecurityDisclosureListingCoverageProof:
            raise DataValidationError(
                "Security disclosure listing proof is invalid.",
                code="SECURITY_DISCLOSURE_LISTING_PROOF_INVALID",
            )
        return self._repository.get_by_episode(proof)


class QuerySecurityDisclosureListingCoverageUseCase:
    """Read one exact historical listing window without claiming current coverage."""

    def __init__(
        self,
        *,
        coverage_repository: SecurityDisclosureListingCoverageRepositoryPort,
        event_repository: SecurityDisclosureEventRepositoryPort,
    ) -> None:
        """Bind the exact-window proof and PIT event readers owned by Data Center."""

        self._coverage_repository = coverage_repository
        self._event_repository = event_repository

    def execute(
        self,
        scope: SecurityDisclosureListingCoverageReadScope,
    ) -> SecurityDisclosureListingCoverageSnapshot:
        """Return COMPLETE only for a known proof with every listed PDF classified."""

        if type(scope) is not SecurityDisclosureListingCoverageReadScope:
            raise DataValidationError(
                "Security disclosure listing scope is invalid.",
                code="SECURITY_DISCLOSURE_LISTING_SCOPE_INVALID",
            )
        proof = self._coverage_repository.get_known_at(scope)
        if proof is None:
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=None,
                events=(),
                coverage_status=SecurityDisclosureListingCoverageStatus.MISSING,
                reason_code="LISTING_PROOF_NOT_KNOWN_AT_CUTOFF",
            )

        # A proof only describes its first durable knowledge instant; later cutoffs need recheck.
        if proof.recorded_at != scope.as_of:
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=proof,
                events=(),
                coverage_status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
                reason_code="LISTING_PROOF_OUTSIDE_EXACT_KNOWN_CUTOFF",
            )

        all_events = self._event_repository.list_known_at(
            SecurityDisclosureEventReadScope(
                as_of=scope.as_of,
                exchange=proof.proof.exchange,
                asset_code=scope.asset_code,
            )
        )
        expected_ids = set(proof.proof.source_document_ids)
        listed_events = tuple(
            item for item in all_events if item.event.source_event_id in expected_ids
        )
        represented_ids = {item.event.source_event_id for item in listed_events}
        if self._has_unlisted_in_window_event(all_events, expected_ids, scope):
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=proof,
                events=listed_events,
                coverage_status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
                reason_code="EVENT_NOT_IN_LISTING_MANIFEST",
            )
        if any(
            item.event.event_type is SecurityDisclosureEventType.UNKNOWN for item in listed_events
        ):
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=proof,
                events=listed_events,
                coverage_status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
                reason_code="LISTED_EVENT_CLASSIFICATION_UNKNOWN",
            )
        if any(
            sum(item.event.source_event_id == source_id for item in listed_events) > 1
            for source_id in expected_ids
        ):
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=proof,
                events=listed_events,
                coverage_status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
                reason_code="LISTED_DOCUMENT_REVISION_AMBIGUOUS",
            )
        if expected_ids - represented_ids:
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=proof,
                events=listed_events,
                coverage_status=SecurityDisclosureListingCoverageStatus.PARTIAL,
                reason_code="LISTED_EVENT_NOT_REPRESENTED",
            )
        entries_by_document_id = {entry.source_document_id: entry for entry in proof.proof.entries}
        if any(
            not self._matches_listing_entry(
                item,
                entries_by_document_id[item.event.source_event_id],
                asset_code=scope.asset_code,
            )
            for item in listed_events
        ):
            return SecurityDisclosureListingCoverageSnapshot(
                scope=scope,
                proof=proof,
                events=listed_events,
                coverage_status=SecurityDisclosureListingCoverageStatus.UNKNOWN,
                reason_code="LISTED_EVENT_IDENTITY_MISMATCH",
            )
        return SecurityDisclosureListingCoverageSnapshot(
            scope=scope,
            proof=proof,
            events=listed_events,
            coverage_status=SecurityDisclosureListingCoverageStatus.COMPLETE,
            reason_code="LISTING_WINDOW_COMPLETE",
        )

    @staticmethod
    def _has_unlisted_in_window_event(
        events: tuple[PersistedSecurityDisclosureEvent, ...],
        expected_ids: set[str],
        scope: SecurityDisclosureListingCoverageReadScope,
    ) -> bool:
        """Reject unlisted events when date precision cannot safely bound the window."""

        for item in events:
            if item.event.source_event_id in expected_ids:
                continue
            announced_at = item.event.announced_at
            if type(announced_at) is datetime:
                utc_date = announced_at.astimezone(UTC).date()
                earliest_ambiguous_date = (
                    scope.start_on - timedelta(days=1) if scope.start_on > date.min else date.min
                )
                latest_ambiguous_date = (
                    scope.end_on + timedelta(days=1) if scope.end_on < date.max else date.max
                )
                # Any real exchange timezone is within one UTC calendar day of the source date.
                if earliest_ambiguous_date <= utc_date <= latest_ambiguous_date:
                    return True
                continue
            if type(announced_at) is not date:
                return True
            if scope.start_on <= announced_at <= scope.end_on:
                return True
        return False

    @staticmethod
    def _matches_listing_entry(
        item: PersistedSecurityDisclosureEvent,
        entry: SecurityDisclosureListingEntry,
        *,
        asset_code: str,
    ) -> bool:
        """Require exact listed PDF, security, URL, and date precision agreement."""

        event = item.event
        return (
            event.source is SecurityDisclosureSource.SZSE_OFFICIAL
            and event.exchange is SecurityDisclosureExchange.SZSE
            and event.asset_code == asset_code
            and event.source_security_code == event.asset_code[:6]
            and event.source_event_id == entry.source_document_id
            and event.source_url == entry.source_url
            and type(event.announced_at) is date
            and event.announced_at == entry.published_on
        )


__all__ = [
    "AppendSecurityDisclosureListingCoverageUseCase",
    "AppendSecurityDisclosureEventUseCase",
    "QuerySecurityDisclosureListingCoverageUseCase",
    "QuerySecurityDisclosureEventsUseCase",
    "SecurityDisclosureEventRepositoryPort",
    "SecurityDisclosureListingCoverageRepositoryPort",
]
