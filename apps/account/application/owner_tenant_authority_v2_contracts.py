"""Typed persistence and live-source ports for owner decisions v2."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence_v4 import (
    GetCurrentAccountOwnerAssignmentEvidenceV4Command,
    GetExactAccountOwnerAssignmentEvidenceV4Command,
)
from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
)
from core.exceptions import AgomTradeProException


class OwnerTenantAuthorityV2Unavailable(AgomTradeProException):
    """A required current source or transaction cannot be proven."""

    default_code = "OWNER_TENANT_V2_UNAVAILABLE"
    default_status_code = 503


class OwnerTenantAuthorityV2Conflict(AgomTradeProException):
    """An immutable selector, root slot or revocation winner conflicts."""

    default_code = "OWNER_TENANT_V2_CONFLICT"
    default_status_code = 409


class OwnerTenantAuthorityV2Corruption(AgomTradeProException):
    """A persisted or provider value violates its sealed contract."""

    default_code = "OWNER_TENANT_V2_CORRUPTION"


def validate_owner_v2_time(value: object) -> datetime:
    """Require an exact aware timestamp without assigning source time."""
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("owner v2 timestamp must be timezone-aware")
    return value


def validate_owner_v2_authentication(
    authentication: CurrentAccountActorAuthorityV3,
    actor: AccountOwnerAssignmentActor,
    as_of: datetime,
) -> None:
    """Validate fresh real admin facts for one stable human, independent of role projection."""
    if type(authentication) is not CurrentAccountActorAuthorityV3:
        raise TypeError("authentication must be exact CurrentAccountActorAuthorityV3")
    if type(actor) is not AccountOwnerAssignmentActor:
        raise TypeError("actor must be exact AccountOwnerAssignmentActor")
    authentication.__post_init__()
    actor.__post_init__()
    cutoff = validate_owner_v2_time(as_of)
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
class PersistedOwnerTenantAuthorityV2:
    """Seal approval-time authentication without imposing its TTL on ownership."""

    authority: OwnerTenantAuthorityV2
    authentication: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Require valid authentication at both original approval and recording clocks."""
        if type(self.authority) is not OwnerTenantAuthorityV2:
            raise TypeError("authority must be exact OwnerTenantAuthorityV2")
        self.authority.__post_init__()
        for cutoff in (self.authority.approved_at, self.authority.recorded_at):
            validate_owner_v2_authentication(
                self.authentication, self.authority.approved_by, cutoff
            )


@dataclass(frozen=True, slots=True)
class PersistedOwnerTenantAuthorityV2Revocation:
    """Seal the fresh authentication used for one explicit immutable revocation."""

    revocation: OwnerTenantAuthorityV2Revocation
    authentication: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Require fresh same-actor authentication at event and recording clocks."""
        if type(self.revocation) is not OwnerTenantAuthorityV2Revocation:
            raise TypeError("revocation must be exact OwnerTenantAuthorityV2Revocation")
        self.revocation.__post_init__()
        for cutoff in (self.revocation.revoked_at, self.revocation.recorded_at):
            validate_owner_v2_authentication(
                self.authentication, self.revocation.revoked_by, cutoff
            )


@dataclass(frozen=True, slots=True)
class CurrentOwnerPhysicalRow:
    """Live row facts injected by the physical owner, not a creation or authority grant."""

    namespace: str
    row_pk: int
    user_id: int | None
    raw_account_type: str
    is_active: bool
    row_created_at: datetime
    row_updated_at: datetime
    observed_at: datetime

    def __post_init__(self) -> None:
        """Preserve nullable ownership and reject malformed source clocks and types."""
        for value in (self.namespace, self.raw_account_type):
            if type(value) is not str or not value or value.strip() != value:
                raise ValueError("physical identity must be exact nonempty text")
        for name in ("row_pk", "user_id"):
            identity: object = getattr(self, name)
            if name == "user_id" and identity is None:
                continue
            if type(identity) is not int or identity <= 0:
                raise ValueError("physical row identity must be an exact positive integer")
        if type(self.is_active) is not bool:
            raise TypeError("physical active state must be an exact boolean")
        for clock in (self.row_created_at, self.row_updated_at, self.observed_at):
            validate_owner_v2_time(clock)
        if not self.row_created_at <= self.row_updated_at <= self.observed_at:
            raise ValueError("physical source clock sequence is invalid")


class CurrentOwnerPhysicalRowReader(Protocol):
    """Lock and read a physical row in the decision repository's transaction."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the same transaction identity as the authority repository."""
        ...

    def read_locked(self, *, namespace: str, row_pk: int) -> CurrentOwnerPhysicalRow | None:
        """Return a new live observation, retaining its row lock until outer commit."""
        ...


class CurrentOwnerAssignmentV4Reader(Protocol):
    """Read the closed-current V4 graph only for initial decision approval.

    Composition must use the decision alias and retain locks on the complete
    assignment/receipt/policy/actor/creation graph until its outer transaction
    finishes. Repeated reads do not replace these locks.
    """

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4 | None:
        """Return the exact current assignment or fail closed."""
        ...


class HistoricalOwnerAssignmentV4Reader(Protocol):
    """Read durable historical V4 provenance, never reinterpret it as current."""

    def execute(
        self, command: GetExactAccountOwnerAssignmentEvidenceV4Command
    ) -> AccountOwnerAssignmentEvidenceV4 | None:
        """Return the exact assignment known at the original decision clock."""
        ...


class OwnerTenantAuthorityV2Repository(Protocol):
    """Persist one decision root and explicit revocation per immutable decision."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the transaction key shared by all live source readers."""
        ...

    def atomic(self) -> AbstractContextManager[None]:
        """Lock policy, identity, V4 assignment/creation and decision sources on one alias.

        Every injected current source must participate in this transaction and
        retain its source locks until the caller's outermost commit/rollback.
        """
        ...

    def now(self) -> datetime:
        """Return the authoritative server clock."""
        ...

    def get_winner(
        self, *, authority_id: str, authority_version: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Return one exact first winner known by the cutoff."""
        ...

    def get_head(
        self, *, authority_id: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Return the logical root even after expiry, without active fallback."""
        ...

    def get_assignment_head(
        self, *, assignment_content_hash: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2 | None:
        """Return the occupied decision root for this assignment, including expired roots."""
        ...

    def get_revocation(
        self, *, authority_content_hash: str, as_of: datetime
    ) -> PersistedOwnerTenantAuthorityV2Revocation | None:
        """Return the known immutable revocation, verifying all durable links."""
        ...

    def append_root(
        self, record: PersistedOwnerTenantAuthorityV2, *, recorded_at: datetime
    ) -> PersistedOwnerTenantAuthorityV2:
        """CAS both authority and assignment slots against the complete stored world."""
        ...

    def append_revocation(
        self,
        record: PersistedOwnerTenantAuthorityV2Revocation,
        *,
        expected_authority_content_hash: str,
        recorded_at: datetime,
    ) -> PersistedOwnerTenantAuthorityV2Revocation:
        """Append the unique revocation only for the exact sealed durable decision."""
        ...
