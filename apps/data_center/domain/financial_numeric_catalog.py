"""Pure value objects and resolution rules for the financial numeric catalog.

These values express an exact source qualification and Owner-event timeline.
They are evidence only: retained body bytes, successful egress audit, provider
identity, and authenticated database events must be independently verified by
Infrastructure before constructing entries for the resolver. Resolution does
not by itself make any fact eligible for a decision or production.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceQualification,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_USERNAME_LENGTH = 150

FinancialNumericCatalogAction = Literal["apply", "revoke"]


class FinancialNumericCatalogResolutionPurpose(StrEnum):
    """Distinguish current use from an explicit historical knowledge query."""

    CURRENT_READ = "current_read"
    CURRENT_WRITE = "current_write"
    CURRENT_PUBLICATION = "current_publication"
    POINT_IN_TIME_READ = "point_in_time_read"


def _utc_datetime(value: object, *, field_name: str) -> datetime:
    """Require a representable UTC-aware event or knowledge timestamp."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    try:
        normalized = value.astimezone(UTC)
        offset = value.utcoffset()
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} must be representable in UTC") from error
    if offset != timedelta(0) or normalized.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return normalized


@dataclass(frozen=True, slots=True)
class FinancialNumericCatalogOwnerEvent:
    """One append-only event tied to the exact qualification and authenticated user.

    This object is not an authentication credential. Infrastructure must load
    the persisted user relation and append-only event row; a serialized copy
    supplied by a caller is never sufficient to authorize catalog resolution.
    """

    event_id: UUID
    entry_id: UUID
    action: FinancialNumericCatalogAction
    qualification_identity: str
    qualification_sha256: str
    actor_id: int
    actor_username: str
    event_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Reject incomplete identities, invalid actions, and contradictory clocks."""

        if type(self.event_id) is not UUID or type(self.entry_id) is not UUID:
            raise TypeError("catalog event and entry ids must be UUID values")
        if type(self.action) is not str or self.action not in {"apply", "revoke"}:
            raise ValueError("catalog event action must be apply or revoke")
        if (
            type(self.qualification_identity) is not str
            or not self.qualification_identity
            or len(self.qualification_identity) > 256
            or self.qualification_identity != self.qualification_identity.strip()
        ):
            raise ValueError("catalog event qualification identity is invalid")
        if (
            type(self.qualification_sha256) is not str
            or _SHA256.fullmatch(self.qualification_sha256) is None
        ):
            raise ValueError("catalog event qualification hash is invalid")
        if type(self.actor_id) is not int or self.actor_id <= 0:
            raise ValueError("catalog event actor id must be a positive integer")
        if (
            type(self.actor_username) is not str
            or not self.actor_username
            or len(self.actor_username) > _MAX_USERNAME_LENGTH
            or self.actor_username != self.actor_username.strip()
        ):
            raise ValueError("catalog event authenticated username is invalid")
        event_at = _utc_datetime(self.event_at, field_name="event_at")
        recorded_at = _utc_datetime(self.recorded_at, field_name="recorded_at")
        if event_at > recorded_at:
            raise ValueError("catalog event cannot be recorded before its event time")


@dataclass(frozen=True, slots=True)
class FinancialNumericCatalogEntry:
    """One immutable qualification row plus its separately persisted Owner events.

    Infrastructure may construct this object only after it has matched the
    qualification to retained capture metadata, read the original bytes back,
    verified the successful controlled-egress audit, and loaded the real user
    foreign keys. These constructor arguments alone do not prove those facts.
    """

    entry_id: UUID
    qualification: FinancialNumericSourceQualification
    recorded_at: datetime
    capture_recorded_at: datetime
    owner_events: tuple[FinancialNumericCatalogOwnerEvent, ...]

    def __post_init__(self) -> None:
        """Reject altered qualification identity, untyped events, or invalid clocks."""

        if type(self.entry_id) is not UUID:
            raise TypeError("catalog entry id must be a UUID")
        if type(self.qualification) is not FinancialNumericSourceQualification:
            raise TypeError("catalog entry requires a typed source qualification")
        recorded_at = _utc_datetime(self.recorded_at, field_name="catalog_recorded_at")
        capture_recorded_at = _utc_datetime(
            self.capture_recorded_at, field_name="capture_recorded_at"
        )
        if capture_recorded_at < self.qualification.document_capture.captured_at:
            raise ValueError("capture metadata cannot predate its response completion")
        if recorded_at < capture_recorded_at:
            raise ValueError("catalog entry cannot predate its exact document capture")
        if type(self.owner_events) is not tuple or any(
            type(event) is not FinancialNumericCatalogOwnerEvent for event in self.owner_events
        ):
            raise TypeError("catalog owner events must be a typed tuple")
        if len({event.event_id for event in self.owner_events}) != len(self.owner_events):
            raise ValueError("catalog entry contains a repeated Owner event id")
        if any(event.entry_id != self.entry_id for event in self.owner_events):
            raise ValueError("catalog Owner event points at a different entry")
        if any(event.recorded_at < recorded_at for event in self.owner_events):
            raise ValueError("catalog Owner event cannot predate its entry")
        if any(event.event_at < recorded_at for event in self.owner_events):
            raise ValueError("catalog Owner event time cannot predate its entry")
        if sum(event.action == "apply" for event in self.owner_events) > 1:
            raise ValueError("catalog entry contains more than one apply event")
        if sum(event.action == "revoke" for event in self.owner_events) > 1:
            raise ValueError("catalog entry contains more than one revoke event")
        apply_events = tuple(event for event in self.owner_events if event.action == "apply")
        revoke_events = tuple(event for event in self.owner_events if event.action == "revoke")
        if revoke_events and not apply_events:
            raise ValueError("catalog entry cannot be revoked before it is applied")
        if revoke_events and apply_events:
            applied = apply_events[0]
            revoked = revoke_events[0]
            if revoked.event_at < applied.event_at or revoked.recorded_at < applied.recorded_at:
                raise ValueError("catalog revoke event cannot predate the apply event")


def resolve_financial_numeric_source_qualification(
    entries: tuple[FinancialNumericCatalogEntry, ...],
    *,
    contract_identity: str,
    endpoint: str,
    source_response_completed_at: datetime,
    source_context: Mapping[str, object],
    known_at: datetime,
) -> FinancialNumericSourceQualification | None:
    """Resolve one exact applied qualification using independent source/knowledge clocks.

    ``source_response_completed_at`` is the acquisition clock from independently
    retained response evidence. It must not be replaced by the report period or
    by the time a later qualification was reviewed. ``known_at`` independently
    bounds capture, catalog, and event-record knowledge. Effective applicability
    is checked at response time; owner revocation only affects cutoffs at or
    after the persisted revoke event.

    The caller must pass only entries built after Infrastructure verified the
    database rows, authenticated user foreign keys, exact provider identity,
    successful egress audit, and retained body bytes. This function is a pure
    evidence resolver, not a production qualification or decision gate.
    """

    if type(entries) is not tuple or any(
        type(entry) is not FinancialNumericCatalogEntry for entry in entries
    ):
        return None
    if (
        type(contract_identity) is not str
        or not contract_identity
        or contract_identity != contract_identity.strip()
        or type(endpoint) is not str
        or not endpoint
        or endpoint != endpoint.strip()
        or not isinstance(source_context, Mapping)
        or any(type(key) is not str for key in source_context)
    ):
        return None
    try:
        response_at = _utc_datetime(
            source_response_completed_at,
            field_name="source_response_completed_at",
        )
        cutoff = _utc_datetime(known_at, field_name="known_at")
    except (TypeError, ValueError):
        return None
    if response_at > cutoff:
        return None

    resolved: list[FinancialNumericSourceQualification] = []
    for entry in entries:
        qualification = entry.qualification
        if (
            qualification.contract.identity != contract_identity
            or qualification.endpoint != endpoint
            or not qualification.matches_source_context(source_context)
            or entry.recorded_at > cutoff
            or entry.capture_recorded_at > cutoff
        ):
            continue
        qualification_hash = qualification.content_hash
        apply_events = tuple(event for event in entry.owner_events if event.action == "apply")
        if len(apply_events) != 1:
            continue
        apply_event = apply_events[0]
        if (
            apply_event.qualification_identity != qualification.identity
            or apply_event.qualification_sha256 != qualification_hash
            or apply_event.event_at > cutoff
            or apply_event.recorded_at > cutoff
        ):
            continue
        revoke_events = tuple(event for event in entry.owner_events if event.action == "revoke")
        revoke_at: datetime | None = None
        if revoke_events:
            revoke_event = revoke_events[0]
            if (
                revoke_event.qualification_identity != qualification.identity
                or revoke_event.qualification_sha256 != qualification_hash
            ):
                continue
            if revoke_event.recorded_at <= cutoff and revoke_event.event_at <= cutoff:
                revoke_at = revoke_event.event_at
        if qualification.is_eligible_at(
            known_at=cutoff,
            source_response_completed_at=response_at,
            recorded_at=entry.recorded_at,
            approved_at=apply_event.event_at,
            revoked_at=revoke_at,
        ):
            resolved.append(qualification)
    if len(resolved) != 1:
        return None
    return resolved[0]


__all__ = [
    "FinancialNumericCatalogAction",
    "FinancialNumericCatalogEntry",
    "FinancialNumericCatalogOwnerEvent",
    "FinancialNumericCatalogResolutionPurpose",
    "resolve_financial_numeric_source_qualification",
]
