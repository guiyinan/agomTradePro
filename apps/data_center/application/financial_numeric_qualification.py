"""Typed application boundary for qualification-aware financial verification.

These candidate ports define a numeric proof primitive only. A verification
result does not replace a write or publication unit-of-work fence, and callers
must recheck qualification state under the transaction that commits use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from apps.data_center.domain.entities import FinancialFact
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogEntry,
    FinancialNumericCatalogOwnerEvent,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)


class FinancialNumericVerificationPurpose(StrEnum):
    """Identify why one exact financial value is being verified."""

    CURRENT_READ = "current_read"
    CURRENT_WRITE = "current_write"
    CURRENT_PUBLICATION = "current_publication"
    POINT_IN_TIME_READ = "point_in_time_read"


def _utc_clock(value: object, *, field_name: str) -> datetime:
    """Require an explicit aware UTC instant and normalize its timezone object."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field_name} must be an explicit UTC datetime")
    try:
        offset = value.utcoffset()
        if offset != timedelta(0):
            raise ValueError(f"{field_name} must be UTC")
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} must be an explicit UTC datetime") from error


@dataclass(frozen=True, slots=True)
class FinancialNumericVerificationContext:
    """Require a caller-sampled UTC knowledge instant and typed use purpose.

    The verifier never substitutes ``fact.fetched_at`` for ``known_at``.
    Current callers must supply their server UTC clock; PIT callers supply the
    historical decision instant. The purpose is forwarded to the authoritative
    catalog resolver, which reconstructs approval and revocation as known at
    the supplied instant.
    """

    known_at: datetime
    purpose: FinancialNumericVerificationPurpose

    def __post_init__(self) -> None:
        """Reject missing, local-time, and untyped verification contexts."""

        object.__setattr__(self, "known_at", _utc_clock(self.known_at, field_name="known_at"))
        if type(self.purpose) is not FinancialNumericVerificationPurpose:
            raise TypeError("purpose must be a FinancialNumericVerificationPurpose")


@dataclass(frozen=True, slots=True)
class FinancialNumericSourceQualificationResolution:
    """Resolved qualification with its actual persisted entry and Owner events.

    Infrastructure constructs this only from the unique database entry and
    its persisted Owner-event and document-capture rows. The nested entry
    carries actual IDs, hashes, actor snapshots, and record/event clocks; none
    are synthesized from the qualification payload or caller context.
    """

    entry: FinancialNumericCatalogEntry

    def __post_init__(self) -> None:
        """Require the exact typed entry and its matching stored apply event."""

        if type(self.entry) is not FinancialNumericCatalogEntry:
            raise TypeError("entry must be a FinancialNumericCatalogEntry snapshot")
        qualification = self.entry.qualification
        matching_events = tuple(
            event
            for event in self.entry.owner_events
            if event.qualification_identity == qualification.identity
            and event.qualification_sha256 == qualification.content_hash
            and event.entry_id == self.entry.entry_id
        )
        apply_events = tuple(event for event in matching_events if event.action == "apply")
        revoke_events = tuple(event for event in matching_events if event.action == "revoke")
        if len(matching_events) != len(self.entry.owner_events) or len(apply_events) != 1:
            raise ValueError("entry snapshot must contain one matching persisted apply event")
        if len(revoke_events) > 1:
            raise ValueError("entry snapshot cannot contain multiple revoke events")

    @property
    def qualification(self) -> FinancialNumericSourceQualification:
        """Return the qualification decoded from the exact catalog row."""

        return self.entry.qualification

    @property
    def recorded_at(self) -> datetime:
        """Return the persisted catalog entry recording clock."""

        return self.entry.recorded_at

    @property
    def capture_recorded_at(self) -> datetime:
        """Return the persisted retained-document capture recording clock."""

        return self.entry.capture_recorded_at

    @property
    def apply_event(self) -> FinancialNumericCatalogOwnerEvent:
        """Return the unique persisted apply event, including its DB identity."""

        return next(event for event in self.entry.owner_events if event.action == "apply")

    @property
    def approved_at(self) -> datetime:
        """Return the apply event's actual event clock for Domain eligibility."""

        return self.apply_event.event_at

    @property
    def approved_recorded_at(self) -> datetime:
        """Return the apply event's separate database recording clock."""

        return self.apply_event.recorded_at

    @property
    def revoke_event(self) -> FinancialNumericCatalogOwnerEvent | None:
        """Return the matching persisted revoke event included at the query cutoff."""

        return next(
            (event for event in self.entry.owner_events if event.action == "revoke"),
            None,
        )

    @property
    def revoked_at(self) -> datetime | None:
        """Return the revoke event clock when that event is in the resolved snapshot."""

        event = self.revoke_event
        return None if event is None else event.event_at

    @property
    def revoked_recorded_at(self) -> datetime | None:
        """Return the revoke event's database recording clock when present."""

        event = self.revoke_event
        return None if event is None else event.recorded_at


class FinancialNumericCatalogEntrySnapshotReadPort(Protocol):
    """Read actual catalog and Owner rows after authoritative qualification lookup."""

    def read_exact_entry(
        self,
        qualification: FinancialNumericSourceQualification,
        *,
        known_at: datetime,
    ) -> FinancialNumericCatalogEntry | None:
        """Return one exact persisted entry snapshot as known at the same cutoff.

        The snapshot adds database row/event identities and record clocks to
        the qualification resolver result. It has no approval authority and
        must be built from persisted capture, entry, and Owner-event rows.
        """
        ...


class FinancialNumericSourceQualificationCatalogPort(Protocol):
    """Resolve one qualified native contract for exact row context and clocks."""

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        verification_context: FinancialNumericVerificationContext,
    ) -> FinancialNumericSourceQualificationResolution | None:
        """Return authenticated records effective and knowable for this request.

        ``source_response_completed_at`` and ``source_context`` must come from
        the unique row and response metadata independently verified by the raw
        body reader. ``verification_context.known_at`` is a separate policy
        knowledge cutoff. Return ``None`` if the retained documentation capture
        or authenticated Owner apply event is absent, mismatched, or unknown at
        that cutoff. The resolver must reconstruct revocation at that same
        cutoff, not use only today's active flag.
        """
        ...


class ContextualFinancialNumericEvidenceVerifier(Protocol):
    """Verify one native fact only when the caller supplies explicit context."""

    def verify(
        self,
        fact: FinancialFact,
        context: FinancialNumericVerificationContext,
    ) -> bool:
        """Return true for a proven exact claim, not for downstream commit safety."""
        ...


__all__ = [
    "ContextualFinancialNumericEvidenceVerifier",
    "FinancialNumericCatalogEntrySnapshotReadPort",
    "FinancialNumericSourceQualificationCatalogPort",
    "FinancialNumericSourceQualificationResolution",
    "FinancialNumericVerificationContext",
    "FinancialNumericVerificationPurpose",
]
