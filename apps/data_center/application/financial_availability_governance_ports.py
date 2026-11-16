"""Application ports for C2 source rereads and local Owner-event UOWs."""

from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from apps.data_center.domain.financial_availability_governance import (
    FinancialAvailabilityGovernanceRecord,
    FinancialAvailabilityOwnerEventIdentity,
    FinancialAvailabilityRecordKind,
    StatutorySourceCaptureReference,
)


def _require_utc(value: object, name: str) -> datetime:
    """Require one representable UTC datetime at the application boundary."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{name} must be an explicit aware UTC datetime")
    offset = value.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{name} must be an explicit aware UTC datetime")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{name} is not representable in UTC") from error


@dataclass(frozen=True, slots=True)
class FinancialAvailabilitySourceRead:
    """Exact retained source bytes and actual storage clocks visible at cutoff."""

    reference: StatutorySourceCaptureReference
    body: bytes = field(repr=False)
    checked_at: datetime
    known_at: datetime

    def __post_init__(self) -> None:
        """Verify bytes and require every source fact to be knowable at cutoff."""

        if type(self.reference) is not StatutorySourceCaptureReference:
            raise TypeError("reference must be an exact StatutorySourceCaptureReference")
        self.reference.__post_init__()
        if type(self.body) is not bytes or not self.body:
            raise ValueError("source body must be non-empty exact bytes")
        if (
            len(self.body) != self.reference.body_size_bytes
            or hashlib.sha256(self.body).hexdigest() != self.reference.body_sha256
        ):
            raise ValueError("source bytes differ from exact retained statutory identity")
        checked = _require_utc(self.checked_at, "checked_at")
        cutoff = _require_utc(self.known_at, "known_at")
        if checked < cutoff:
            raise ValueError("source bytes were checked before the requested known_at")
        if (
            max(
                self.reference.first_seen_at,
                self.reference.capture_observed_at,
                self.reference.revision_recorded_at,
                self.reference.capture_recorded_at,
            )
            > cutoff
        ):
            raise ValueError("source identity was not knowable at the requested cutoff")


class LockedFinancialAvailabilityPrincipal(Protocol):
    """Authenticated Django User and C2 Permission held under one database UOW."""

    @property
    def user_id(self) -> int:
        """Return the primary key read from the locked authenticated User row."""

    @property
    def permission_id(self) -> int:
        """Return the primary key for the exact data_center C2 Permission row."""

    @property
    def permission_app_label(self) -> str:
        """Return the verified Django content type app label."""

    @property
    def permission_codename(self) -> str:
        """Return the verified dedicated permission codename."""

    @property
    def database_alias(self) -> str:
        """Return the alias holding User, Permission and required grant locks."""

    @property
    def verified_at(self) -> datetime:
        """Return the server time after standard Django ``has_perm`` succeeds."""

    def assert_live(self) -> None:
        """Raise unless authorization was revalidated and its required locks remain."""


@dataclass(frozen=True, slots=True)
class FinancialAvailabilitySessionRequestProof:
    """Untrusted session selector derived from an authenticated Django request.

    Infrastructure must reload the session and active User, clear permission
    caches, run standard ``has_perm`` semantics, and lock the required User,
    Permission and non-superuser grant rows. Active superusers use Django's
    normal permission semantics. This proof cannot itself grant authority.
    """

    user_id: int
    session_key: str = field(repr=False, compare=False)
    request_authenticated_at: datetime
    request_user_database_alias: str
    database_alias: str

    def __post_init__(self) -> None:
        """Reject malformed request claims before Infrastructure access."""

        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive exact Django User ID")
        if (
            type(self.session_key) is not str
            or not self.session_key
            or len(self.session_key) > 40
            or self.session_key.strip() != self.session_key
        ):
            raise ValueError("session_key must be one exact request credential")
        _require_utc(self.request_authenticated_at, "request_authenticated_at")
        for name, value in (
            ("request_user_database_alias", self.request_user_database_alias),
            ("database_alias", self.database_alias),
        ):
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError(f"{name} must be one exact database alias")
        if self.request_user_database_alias != self.database_alias:
            raise ValueError("authenticated User and C2 configuration must share one alias")


class FinancialAvailabilityPermissionAuthorizerPort(Protocol):
    """Hold the actual session, User, permission and applicable-grant UOW."""

    @property
    def database_alias(self) -> str:
        """Return the alias holding the locked session and permission facts."""

    def lock_authorized_principal(
        self,
        proof: FinancialAvailabilitySessionRequestProof,
    ) -> AbstractContextManager[LockedFinancialAvailabilityPrincipal]:
        """Reload authentication and enforce standard Django ``has_perm`` semantics.

        The returned principal must bind app label
        ``data_center`` and codename
        ``manage_financial_availability_governance``. The implementation must
        not trust a request boolean, team label, cached permission result, or
        caller-provided actor identity.
        """


class FinancialAvailabilitySourceReaderPort(Protocol):
    """Read one exact retained statutory capture without fetching/fallback."""

    @property
    def database_alias(self) -> str:
        """Return the alias containing statutory revision and capture rows."""

    def read_exact_capture(
        self,
        *,
        issuer: str,
        document_id: str,
        source_version: str,
        capture_id: UUID,
        known_at: datetime,
    ) -> FinancialAvailabilitySourceRead | None:
        """Reload native revision/capture rows and body, visible at explicit cutoff."""


class FinancialAvailabilityGovernanceRepositoryPort(Protocol):
    """Append/read immutable C2 rule and policy version rows on one alias."""

    @property
    def database_alias(self) -> str:
        """Return the alias used by the configuration and local event tables."""

    def atomic(self) -> AbstractContextManager[None]:
        """Join the caller's READ COMMITTED UOW without changing its isolation."""

    def now(self) -> datetime:
        """Return ``clock_timestamp()`` from this database alias in UTC."""

    def require_caller_owned_current_uow(self) -> None:
        """Require the single caller-owned PostgreSQL READ COMMITTED transaction."""

    def lock_current_scopes(
        self,
        scopes: tuple[tuple[FinancialAvailabilityRecordKind, str], ...],
    ) -> None:
        """Acquire shared scope locks before current selection and row locks."""

    def lock_change_scope(
        self,
        *,
        kind: FinancialAvailabilityRecordKind,
        exchange: str,
    ) -> None:
        """Acquire the matching exclusive scope lock before apply or revoke."""

    def append_record(
        self,
        record: FinancialAvailabilityGovernanceRecord,
    ) -> FinancialAvailabilityGovernanceRecord:
        """Append and return a DB-clock-stamped new record version."""

    def get_exact(
        self,
        *,
        record_id: str,
        record_version: str,
        expected_content_sha256: str,
        known_at: datetime,
    ) -> FinancialAvailabilityGovernanceRecord | None:
        """Read one exact row after rehashing its payload and source foreign key."""

    def list_for_effective_date(
        self,
        *,
        kind: FinancialAvailabilityRecordKind,
        exchange: str,
        effective_on: date,
        known_at: datetime,
    ) -> tuple[FinancialAvailabilityGovernanceRecord, ...]:
        """Return every exact-scope candidate visible at cutoff without choosing."""

    def list_scope_for_current_update(
        self,
        *,
        kind: FinancialAvailabilityRecordKind,
        exchange: str,
    ) -> tuple[FinancialAvailabilityGovernanceRecord, ...]:
        """Lock and re-decode every immutable row in one current scope."""


class FinancialAvailabilityOwnerEventRepositoryPort(Protocol):
    """Append/read local apply/revoke rows; these are not SystemAudit/outbox."""

    @property
    def database_alias(self) -> str:
        """Return the alias holding the configuration and event tables."""

    def append_apply_event(
        self,
        *,
        record: FinancialAvailabilityGovernanceRecord,
        principal: LockedFinancialAvailabilityPrincipal,
        reason: str,
        known_at: datetime,
    ) -> FinancialAvailabilityOwnerEventIdentity:
        """Verify source at explicit cutoff, then append using DB event clocks."""

    def append_revoke_event(
        self,
        *,
        record: FinancialAvailabilityGovernanceRecord,
        apply_event: FinancialAvailabilityOwnerEventIdentity,
        principal: LockedFinancialAvailabilityPrincipal,
        reason: str,
    ) -> FinancialAvailabilityOwnerEventIdentity:
        """Append a revocation linked to one exact apply event, without row mutation."""

    def list_complete_history(
        self,
        *,
        record_id: str,
        record_version: str,
    ) -> tuple[FinancialAvailabilityOwnerEventIdentity, ...]:
        """Read and rehash the complete append-only event stream for one row."""

    def list_complete_history_for_update(
        self,
        *,
        record_id: str,
        record_version: str,
    ) -> tuple[FinancialAvailabilityOwnerEventIdentity, ...]:
        """Lock and rehash every event in one current lifecycle stream."""


@dataclass(frozen=True, slots=True)
class GetFinancialAvailabilityGovernanceQuery:
    """Explicit scope and point-in-time selector with no current-time default."""

    kind: FinancialAvailabilityRecordKind
    exchange: str
    effective_on: date
    known_at: datetime

    def __post_init__(self) -> None:
        """Validate exact kind, exchange, date and aware UTC knowledge cutoff."""

        if type(self.kind) is not FinancialAvailabilityRecordKind:
            raise ValueError("kind must be an exact financial availability record kind")
        if (
            type(self.exchange) is not str
            or not self.exchange
            or self.exchange.strip() != self.exchange
        ):
            raise ValueError("exchange must be explicit canonical text")
        if type(self.effective_on) is not date:
            raise ValueError("effective_on must be an exact date")
        _require_utc(self.known_at, "known_at")


__all__ = [
    "FinancialAvailabilityGovernanceRepositoryPort",
    "FinancialAvailabilityOwnerEventRepositoryPort",
    "FinancialAvailabilityPermissionAuthorizerPort",
    "FinancialAvailabilitySessionRequestProof",
    "FinancialAvailabilitySourceRead",
    "FinancialAvailabilitySourceReaderPort",
    "GetFinancialAvailabilityGovernanceQuery",
    "LockedFinancialAvailabilityPrincipal",
]
