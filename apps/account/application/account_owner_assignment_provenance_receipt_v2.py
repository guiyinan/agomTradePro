"""ID/hash-only issuance and closed reads for inactive Account provenance v2."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentServerActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
    validate_account_owner_assignment_provenance_receipt_v2_root,
    validate_account_owner_assignment_provenance_receipt_v2_row,
    validate_account_owner_assignment_provenance_receipt_v2_successor,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)

_KINDS = ("creation", "migration", "manual_reclaim")
_ROLES = {
    "creation": "account_owner_claimant",
    "migration": "legacy_assignment_reviewer",
    "manual_reclaim": "account_owner_claimant",
}


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _aware(value: object, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class AccountOwnerAssignmentProvenanceReceiptV2Unavailable(ValueError):
    """The exact-current physical v2 row or receipt is unavailable."""


class AccountOwnerAssignmentProvenanceReceiptV2Conflict(ValueError):
    """A first winner, actor seal, or logical head conflicts."""


class AccountOwnerAssignmentProvenanceReceiptV2Corruption(ValueError):
    """A provider or repository substituted sealed v2 evidence."""


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentProvenanceReceiptV2:
    """Bind one claimant receipt to its authenticated human issuer."""

    receipt: AccountOwnerAssignmentProvenanceReceiptV2
    issued_by: AccountOwnerAssignmentServerActor

    def __post_init__(self) -> None:
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV2:
            raise TypeError("receipt must be an exact v2 provenance receipt")
        AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(self.receipt)
        if type(self.issued_by) is not AccountOwnerAssignmentServerActor:
            raise TypeError("issued_by must be an exact authenticated actor")
        AccountOwnerAssignmentServerActor.__post_init__(self.issued_by)
        if self.receipt.claimant != self.issued_by.to_domain():
            raise ValueError("persisted v2 receipt actor seal is invalid")


@dataclass(frozen=True, slots=True)
class IssueAccountOwnerAssignmentProvenanceReceiptV2Command:
    """Identity/hash-only selector; no row facts, owner claim, or clock is accepted."""

    receipt_id: str
    receipt_version: str
    provenance_kind: str
    row_observation_id: str
    row_observation_version: str
    expected_row_observation_content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "receipt_version",
            "provenance_kind",
            "row_observation_id",
            "row_observation_version",
        ):
            _token(getattr(self, name), name)
        if self.provenance_kind not in _KINDS:
            raise ValueError("provenance_kind is invalid")
        _digest(
            self.expected_row_observation_content_hash,
            "expected_row_observation_content_hash",
        )


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentProvenanceReceiptV2Command:
    """Exact receipt identity/hash and historical point-in-time selector."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.receipt_id, "receipt_id")
        _token(self.receipt_version, "receipt_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command:
    """Closed full-receipt selector for the final current claimant head."""

    expected_receipt: AccountOwnerAssignmentProvenanceReceiptV2
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_receipt) is not AccountOwnerAssignmentProvenanceReceiptV2:
            raise TypeError("expected_receipt must be an exact v2 receipt")
        AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(self.expected_receipt)
        _aware(self.as_of, "as_of")


class ExactCurrentPhysicalAccountRowObservationV2Provider(Protocol):
    """Expose only an exact live Account physical-row v2 owner record."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None:
        """Return one exact identity/hash row only when it is the live head."""

        ...


class AccountOwnerAssignmentProvenanceReceiptV2Repository(Protocol):
    """Store actor-bound first winners with logical-head CAS semantics."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one receipt issuance transaction."""

        ...

    def now(self) -> datetime:
        """Return the authoritative server clock."""

        ...

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None:
        """Return an immutable receipt identity first winner."""

        ...

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None:
        """Return the final recorded receipt head, including terminal heads."""

        ...

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
        """Append under first-winner and predecessor-CAS semantics."""

        ...

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None:
        """Return exact immutable receipt evidence knowable at one PIT."""

        ...


class IssueAccountOwnerAssignmentProvenanceReceiptV2:
    """Double-read one full exact-current physical v2 row and CAS-append a claim."""

    def __init__(
        self,
        *,
        row_provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
        repository: AccountOwnerAssignmentProvenanceReceiptV2Repository,
        actor: AccountOwnerAssignmentServerActor,
        validity_period: timedelta,
    ) -> None:
        if type(actor) is not AccountOwnerAssignmentServerActor:
            raise TypeError("actor must be an exact authenticated actor")
        AccountOwnerAssignmentServerActor.__post_init__(actor)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._provider = row_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self, command: IssueAccountOwnerAssignmentProvenanceReceiptV2Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV2:
        """Issue or replay one actor-bound claimant receipt from an exact v2 row."""

        if type(command) is not IssueAccountOwnerAssignmentProvenanceReceiptV2Command:
            raise TypeError("command must be an exact v2 issue command")
        IssueAccountOwnerAssignmentProvenanceReceiptV2Command.__post_init__(command)
        self._require_actor(command.provenance_kind)
        with self._repository.atomic():
            cutoff = self._repository.now()
            self._require_clock(cutoff)
            first = self._read_row(command, cutoff)
            winner = self._repository.get_winner(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(receipt_id=command.receipt_id, as_of=cutoff)
            final = self._read_row(command, cutoff)
            if final != first:
                raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                    "physical v2 row changed during issuance"
                )
            if winner is not None:
                record = self._record(winner)
                self._validate_winner(record, command, final, head, cutoff)
                return record.receipt
            predecessor = self._record(head).receipt if head is not None else None
            recorded_at = self._repository.now()
            self._require_clock(recorded_at)
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                    "repository clock moved backwards"
                )
            valid_until = min(final.valid_until, cutoff + self._validity_period)
            if recorded_at >= valid_until:
                raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
                    "physical v2 row expired before issuance"
                )
            receipt = self._build(
                command,
                final,
                issued_at=cutoff,
                recorded_at=recorded_at,
                valid_until=valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            self._validate_row(receipt, final)
            try:
                if predecessor is None:
                    validate_account_owner_assignment_provenance_receipt_v2_root(receipt)
                else:
                    validate_account_owner_assignment_provenance_receipt_v2_successor(
                        predecessor, receipt
                    )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                    "v2 receipt chain is invalid"
                ) from error
            expected = PersistedAccountOwnerAssignmentProvenanceReceiptV2(receipt, self._actor)
            persisted = self._record(
                self._repository.append(
                    expected,
                    expected_predecessor_hash=(
                        predecessor.content_hash if predecessor is not None else None
                    ),
                    recorded_at=recorded_at,
                )
            )
            if persisted != expected:
                raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                    "concurrent v2 receipt first winner differs"
                )
            return persisted.receipt

    def _require_actor(self, kind: str) -> None:
        if self._actor.role != _ROLES[kind]:
            raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
                "authenticated actor has the wrong role"
            )
        if kind == "migration" and not self._actor.is_staff:
            raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
                "migration requires a human staff reviewer"
            )

    def _read_row(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV2Command,
        cutoff: datetime,
    ) -> PhysicalAccountRowObservationV2:
        value = self._provider.get_exact_current(
            observation_id=command.row_observation_id,
            observation_version=command.row_observation_version,
            expected_content_hash=command.expected_row_observation_content_hash,
            as_of=cutoff,
        )
        row = _require_current_row(
            value,
            observation_id=command.row_observation_id,
            observation_version=command.row_observation_version,
            expected_content_hash=command.expected_row_observation_content_hash,
            as_of=cutoff,
        )
        if command.provenance_kind == "creation" and row.row_user_id != self._actor.user_id:
            raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
                "creation claimant does not match the exact physical v2 row user"
            )
        return row

    def _build(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV2Command,
        row: PhysicalAccountRowObservationV2,
        *,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> AccountOwnerAssignmentProvenanceReceiptV2:
        migration = command.provenance_kind == "migration"
        return AccountOwnerAssignmentProvenanceReceiptV2(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            provenance_kind=command.provenance_kind,
            assignment_state="legacy_default_claim" if migration else "claimed_owner",
            assigned_owner_user_id=None if migration else self._actor.user_id,
            account_namespace=row.account_namespace,
            account_id=row.account_id,
            underlying_unified_account_namespace=row.underlying_unified_account_namespace,
            underlying_unified_account_id=row.underlying_unified_account_id,
            row_observation_owner=row.owner,
            row_observation_artifact_type=row.artifact_type,
            row_observation_schema=row.schema,
            row_observation_id=row.observation_id,
            row_observation_version=row.observation_version,
            row_observation_identity_hash=row.identity_hash,
            row_observation_content_hash=row.content_hash,
            row_observation_supersedes_content_hash=row.supersedes_content_hash,
            row_observation_recorded_at=row.recorded_at,
            row_observation_valid_until=row.valid_until,
            source_content_hash=row.source_content_hash,
            raw_observation_content_hash=row.raw_observation_content_hash,
            row_is_active=row.is_active,
            row_is_present=row.is_present,
            row_is_tombstone=row.is_tombstone,
            row_user_id=row.row_user_id,
            claimant=self._actor.to_domain(),
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_winner(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV2,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV2Command,
        row: PhysicalAccountRowObservationV2,
        head: PersistedAccountOwnerAssignmentProvenanceReceiptV2 | None,
        cutoff: datetime,
    ) -> None:
        receipt = record.receipt
        if not receipt.is_current_at(cutoff):
            raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
                "persisted v2 receipt is unavailable"
            )
        if record.issued_by != self._actor:
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                "v2 receipt belongs to another actor"
            )
        stable = self._build(
            command,
            row,
            issued_at=receipt.issued_at,
            recorded_at=receipt.recorded_at,
            valid_until=receipt.valid_until,
            supersedes_content_hash=receipt.supersedes_content_hash,
        )
        if stable != receipt:
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                "v2 receipt identity has another first winner"
            )
        if head is None or self._record(head) != record:
            raise AccountOwnerAssignmentProvenanceReceiptV2Conflict(
                "v2 receipt is no longer the logical head"
            )
        self._validate_row(receipt, row)

    @staticmethod
    def _validate_row(
        receipt: AccountOwnerAssignmentProvenanceReceiptV2,
        row: PhysicalAccountRowObservationV2,
    ) -> None:
        try:
            validate_account_owner_assignment_provenance_receipt_v2_row(receipt, row)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                "v2 receipt does not bind the exact physical row"
            ) from error

    @staticmethod
    def _record(value: object) -> PersistedAccountOwnerAssignmentProvenanceReceiptV2:
        if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV2:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                "repository record type substitution"
            )
        try:
            PersistedAccountOwnerAssignmentProvenanceReceiptV2.__post_init__(value)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                "repository returned invalid v2 receipt"
            ) from error
        return value

    @staticmethod
    def _require_clock(value: object) -> None:
        try:
            _aware(value, "repository clock")
        except ValueError as error:
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(str(error)) from error


class GetExactAccountOwnerAssignmentProvenanceReceiptV2:
    """Read exact claimant evidence only while its physical v2 row is current."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV2Repository,
        row_provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
    ) -> None:
        self._repository = repository
        self._provider = row_provider

    def execute(
        self, command: GetExactAccountOwnerAssignmentProvenanceReceiptV2Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV2 | None:
        """Revalidate the exact-current upstream row; never fall back to v1."""

        if type(command) is not GetExactAccountOwnerAssignmentProvenanceReceiptV2Command:
            raise TypeError("command must be an exact v2 PIT command")
        GetExactAccountOwnerAssignmentProvenanceReceiptV2Command.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        receipt = IssueAccountOwnerAssignmentProvenanceReceiptV2._record(value).receipt
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
                "exact v2 receipt selector substitution"
            )
        if not receipt.is_current_at(command.as_of):
            return None
        try:
            row = _read_receipt_row(self._provider, receipt, command.as_of)
        except AccountOwnerAssignmentProvenanceReceiptV2Unavailable:
            return None
        IssueAccountOwnerAssignmentProvenanceReceiptV2._validate_row(receipt, row)
        return receipt


class GetCurrentAccountOwnerAssignmentProvenanceReceiptV2:
    """Read a closed final head without falling back from terminal upstream state."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV2Repository,
        row_provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
    ) -> None:
        self._repository = repository
        self._provider = row_provider

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV2 | None:
        """Return only the expected receipt at both receipt and physical-row heads."""

        if type(command) is not GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command:
            raise TypeError("command must be an exact v2 current command")
        GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command.__post_init__(command)
        expected = command.expected_receipt
        exact = GetExactAccountOwnerAssignmentProvenanceReceiptV2(
            repository=self._repository, row_provider=self._provider
        ).execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptV2Command(
                expected.receipt_id,
                expected.receipt_version,
                expected.content_hash,
                command.as_of,
            )
        )
        if exact != expected:
            return None
        head = self._repository.get_current_head(
            receipt_id=expected.receipt_id, as_of=command.as_of
        )
        if (
            head is None
            or IssueAccountOwnerAssignmentProvenanceReceiptV2._record(head).receipt != expected
        ):
            return None
        return exact


def _read_receipt_row(
    provider: ExactCurrentPhysicalAccountRowObservationV2Provider,
    receipt: AccountOwnerAssignmentProvenanceReceiptV2,
    as_of: datetime,
) -> PhysicalAccountRowObservationV2:
    value = provider.get_exact_current(
        observation_id=receipt.row_observation_id,
        observation_version=receipt.row_observation_version,
        expected_content_hash=receipt.row_observation_content_hash,
        as_of=as_of,
    )
    return _require_current_row(
        value,
        observation_id=receipt.row_observation_id,
        observation_version=receipt.row_observation_version,
        expected_content_hash=receipt.row_observation_content_hash,
        as_of=as_of,
    )


def _require_current_row(
    value: PhysicalAccountRowObservationV2 | None,
    *,
    observation_id: str,
    observation_version: str,
    expected_content_hash: str,
    as_of: datetime,
) -> PhysicalAccountRowObservationV2:
    if value is None:
        raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
            "exact-current physical v2 row is unavailable"
        )
    if type(value) is not PhysicalAccountRowObservationV2:
        raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
            "physical v2 row type substitution"
        )
    try:
        PhysicalAccountRowObservationV2.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
            "physical v2 row is invalid"
        ) from error
    if (
        value.observation_id != observation_id
        or value.observation_version != observation_version
        or value.content_hash != expected_content_hash
    ):
        raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
            "physical v2 row selector substitution"
        )
    if not value.is_current_at(as_of):
        raise AccountOwnerAssignmentProvenanceReceiptV2Unavailable(
            "exact-current physical v2 row is unavailable"
        )
    if value.activation_available or not value.must_not_execute:
        raise AccountOwnerAssignmentProvenanceReceiptV2Corruption(
            "physical v2 row execution state substitution"
        )
    return value


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV2Conflict",
    "AccountOwnerAssignmentProvenanceReceiptV2Corruption",
    "AccountOwnerAssignmentProvenanceReceiptV2Repository",
    "AccountOwnerAssignmentProvenanceReceiptV2Unavailable",
    "ExactCurrentPhysicalAccountRowObservationV2Provider",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV2",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV2Command",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV2",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV2Command",
    "IssueAccountOwnerAssignmentProvenanceReceiptV2",
    "IssueAccountOwnerAssignmentProvenanceReceiptV2Command",
    "PersistedAccountOwnerAssignmentProvenanceReceiptV2",
]
