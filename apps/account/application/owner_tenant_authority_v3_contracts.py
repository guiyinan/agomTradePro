"""Typed Application ports for the long-lived owner/tenant authority V3."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v5 import (
    GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    GetExactAccountOwnerAssignmentEvidenceV5Command,
)
from apps.account.application.single_owner_actor_authority import CurrentSingleOwnerParticipants
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v5 import (
    AccountOwnerAssignmentEvidenceV5,
)
from apps.account.domain.owner_tenant_authority_v3 import (
    OwnerTenantAuthorityV3,
    OwnerTenantAuthorityV3Revocation,
)
from core.exceptions import AgomTradeProException


class OwnerTenantAuthorityV3Unavailable(AgomTradeProException):
    """A required current source, durable winner, or transaction is unavailable."""

    default_code = "OWNER_TENANT_V3_UNAVAILABLE"
    default_status_code = 503


class OwnerTenantAuthorityV3Conflict(AgomTradeProException):
    """An immutable winner, chain head, or revocation first winner conflicts."""

    default_code = "OWNER_TENANT_V3_CONFLICT"
    default_status_code = 409


class OwnerTenantAuthorityV3Corruption(AgomTradeProException):
    """A persisted or injected value violates the Authority V3 contract."""

    default_code = "OWNER_TENANT_V3_CORRUPTION"


def validate_owner_v3_time(value: object) -> datetime:
    """Require an exact timezone-aware timestamp without creating a clock value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("owner v3 timestamp must be timezone-aware")
    return value


def validate_owner_v3_authentication(
    authentication: CurrentAccountActorAuthorityV3,
    actor: AccountOwnerAssignmentActor,
    as_of: datetime,
) -> None:
    """Validate fresh authenticated staff-admin facts for one sealed human actor."""

    if type(authentication) is not CurrentAccountActorAuthorityV3:
        raise TypeError("authentication must be exact CurrentAccountActorAuthorityV3")
    if type(actor) is not AccountOwnerAssignmentActor:
        raise TypeError("actor must be exact AccountOwnerAssignmentActor")
    authentication.__post_init__()
    actor.__post_init__()
    cutoff = validate_owner_v3_time(as_of)
    if (
        not authentication.is_authenticated
        or not authentication.is_active
        or not authentication.is_staff
        or authentication.rbac_role != "admin"
        or authentication.actor_id != actor.actor_id
        or authentication.user_id != actor.user_id
        or actor.kind != "human"
        or actor.is_staff is not authentication.is_staff
        or not authentication.recorded_at <= cutoff < authentication.valid_until
    ):
        raise ValueError("owner authentication is stale or does not match the real admin")


@dataclass(frozen=True, slots=True)
class PersistedOwnerTenantAuthorityV3:
    """Seal approval-time `CurrentAccountActorAuthorityV3` beside one Authority V3."""

    authority: OwnerTenantAuthorityV3
    authentication: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Require the same authenticated actor at approval and recording clocks."""

        if type(self.authority) is not OwnerTenantAuthorityV3:
            raise TypeError("authority must be exact OwnerTenantAuthorityV3")
        self.authority.__post_init__()
        for cutoff in (self.authority.approved_at, self.authority.recorded_at):
            validate_owner_v3_authentication(
                self.authentication,
                self.authority.approved_by,
                cutoff,
            )


@dataclass(frozen=True, slots=True)
class PersistedOwnerTenantAuthorityV3Revocation:
    """Seal fresh authenticated actor facts beside one immutable revocation."""

    revocation: OwnerTenantAuthorityV3Revocation
    authentication: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Require the same authenticated actor at revocation and recording clocks."""

        if type(self.revocation) is not OwnerTenantAuthorityV3Revocation:
            raise TypeError("revocation must be exact OwnerTenantAuthorityV3Revocation")
        self.revocation.__post_init__()
        for cutoff in (self.revocation.revoked_at, self.revocation.recorded_at):
            validate_owner_v3_authentication(
                self.authentication,
                self.revocation.revoked_by,
                cutoff,
            )


class CurrentOwnerAssignmentEvidenceV5Reader(Protocol):
    """Read one exact-current Evidence V5 through its public Application port."""

    def execute(
        self,
        command: GetCurrentAccountOwnerAssignmentEvidenceV5Command,
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Return the selected current Evidence V5 or no value."""
        ...


class HistoricalOwnerAssignmentEvidenceV5Reader(Protocol):
    """Read one exact historical Evidence V5 through its public Application port."""

    def execute(
        self,
        command: GetExactAccountOwnerAssignmentEvidenceV5Command,
    ) -> AccountOwnerAssignmentEvidenceV5 | None:
        """Return the selected Evidence V5 knowable at the requested cutoff."""
        ...


class CurrentOwnerTenantAuthorityParticipantsReader(Protocol):
    """Read current policy and authenticated actor facts as one source projection."""

    def get_current(self, *, as_of: datetime) -> CurrentSingleOwnerParticipants | None:
        """Return the current policy, actor, roles, and finite validity window."""
        ...


class OwnerTenantAuthorityV3Repository(Protocol):
    """Persist Authority V3 roots, successors, and one revocation per root."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository-owned transaction for one use case."""
        ...

    def now(self) -> datetime:
        """Return the authoritative timezone-aware repository clock."""
        ...

    def get_winner(
        self,
        *,
        authority_id: str,
        authority_version: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the exact immutable first winner knowable at the cutoff."""
        ...

    def get_head(
        self,
        *,
        authority_id: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the final logical Authority V3 head without active fallback."""
        ...

    def get_assignment_head(
        self,
        *,
        assignment_content_hash: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3 | None:
        """Return the occupied authority root for one exact Evidence V5 hash."""
        ...

    def get_revocation(
        self,
        *,
        authority_content_hash: str,
        as_of: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation | None:
        """Return the exact known revocation for one Authority V3 content hash."""
        ...

    def append(
        self,
        record: PersistedOwnerTenantAuthorityV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV3:
        """Append or replay one root/successor using predecessor CAS semantics."""
        ...

    def append_revocation(
        self,
        record: PersistedOwnerTenantAuthorityV3Revocation,
        *,
        expected_authority_content_hash: str,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV3Revocation:
        """Append or replay one revocation for the exact immutable authority."""
        ...


@dataclass(frozen=True, slots=True)
class CurrentOwnerTenantAuthorityV3:
    """Bind an Authority V3 to one fresh current policy/authentication observation."""

    authority: OwnerTenantAuthorityV3
    authentication: CurrentAccountActorAuthorityV3
    observed_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Keep the live observation bounded by every exact source validity window."""

        if type(self.authority) is not OwnerTenantAuthorityV3:
            raise TypeError("authority must be exact OwnerTenantAuthorityV3")
        self.authority.__post_init__()
        observed_at = validate_owner_v3_time(self.observed_at)
        valid_until = validate_owner_v3_time(self.valid_until)
        validate_owner_v3_authentication(
            self.authentication,
            self.authority.approved_by,
            observed_at,
        )
        if not self.authority.is_current_at(observed_at):
            raise ValueError("authority is not current at the observation clock")
        if (
            not observed_at
            < valid_until
            <= min(
                self.authority.valid_until,
                self.authority.assignment.valid_until,
                self.authority.policy.valid_until,
                self.authentication.valid_until,
            )
        ):
            raise ValueError("current authority observation exceeds its source validity")


__all__ = [
    "CurrentOwnerAssignmentEvidenceV5Reader",
    "CurrentOwnerTenantAuthorityParticipantsReader",
    "CurrentOwnerTenantAuthorityV3",
    "HistoricalOwnerAssignmentEvidenceV5Reader",
    "OwnerTenantAuthorityV3Conflict",
    "OwnerTenantAuthorityV3Corruption",
    "OwnerTenantAuthorityV3Repository",
    "OwnerTenantAuthorityV3Unavailable",
    "PersistedOwnerTenantAuthorityV3",
    "PersistedOwnerTenantAuthorityV3Revocation",
    "validate_owner_v3_authentication",
    "validate_owner_v3_time",
]
