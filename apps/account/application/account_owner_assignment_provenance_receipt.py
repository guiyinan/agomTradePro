"""ID-only issuance and inactive reads for Account assignment provenance."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.domain.account_owner_assignment_provenance_receipt import (
    ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_KINDS,
    AccountOwnerAssignmentProvenanceReceipt,
    validate_account_owner_assignment_provenance_receipt_row,
    validate_account_owner_assignment_provenance_receipt_successor,
)
from apps.account.domain.physical_account_row_observation import (
    PhysicalAccountRowObservation,
)

_ARTIFACT_BY_KIND: dict[str, str] = {
    "creation": "account_creation_receipt",
    "migration": "account_legacy_default_assignment_receipt",
    "manual_reclaim": "account_owner_reclaim_receipt",
}
_ROLE_BY_KIND: dict[str, str] = {
    "creation": "account_owner_claimant",
    "migration": "legacy_assignment_reviewer",
    "manual_reclaim": "account_owner_claimant",
}


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class AccountOwnerAssignmentProvenanceReceiptUnavailable(AccountOwnerAssignmentUnavailable):
    """Required exact-current row or receipt is unavailable."""


class AccountOwnerAssignmentProvenanceReceiptConflict(AccountOwnerAssignmentConflict):
    """A first winner or logical provenance chain conflicts."""


class AccountOwnerAssignmentProvenanceReceiptCorruption(AccountOwnerAssignmentCorruption):
    """A provider or repository substituted provenance evidence."""


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentProvenanceReceipt:
    """Pair one immutable receipt with its authenticated issuing actor."""

    receipt: AccountOwnerAssignmentProvenanceReceipt
    issued_by: AccountOwnerAssignmentServerActor

    def __post_init__(self) -> None:
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceipt:
            raise TypeError("receipt must be exact AccountOwnerAssignmentProvenanceReceipt")
        AccountOwnerAssignmentProvenanceReceipt.__post_init__(self.receipt)
        if type(self.issued_by) is not AccountOwnerAssignmentServerActor:
            raise TypeError("issued_by must be exact AccountOwnerAssignmentServerActor")
        AccountOwnerAssignmentServerActor.__post_init__(self.issued_by)
        if self.receipt.claimant != self.issued_by.to_domain():
            raise ValueError("persisted receipt actor seal is invalid")


@dataclass(frozen=True, slots=True)
class IssueAccountOwnerAssignmentProvenanceReceiptCommand:
    """ID-only selector for one explicit claimant-side issuance operation."""

    receipt_id: str
    receipt_version: str
    provenance_kind: str
    row_observation_id: str
    row_observation_version: str

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "receipt_version",
            "provenance_kind",
            "row_observation_id",
            "row_observation_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if self.provenance_kind not in ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_KINDS:
            raise ValueError("provenance_kind is invalid")


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentProvenanceReceiptCommand:
    """Exact receipt identity, hash, and historical PIT selector."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.receipt_id, "receipt_id")
        _require_token(self.receipt_version, "receipt_version")
        _require_hash(self.expected_content_hash, "expected_content_hash")
        _require_aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand:
    """Closed full-receipt selector for an inactive logical head."""

    receipt: AccountOwnerAssignmentProvenanceReceipt
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceipt:
            raise TypeError("receipt must be exact AccountOwnerAssignmentProvenanceReceipt")
        AccountOwnerAssignmentProvenanceReceipt.__post_init__(self.receipt)
        _require_aware(self.as_of, "as_of")


class ExactCurrentPhysicalAccountRowObservationProvider(Protocol):
    """Load one exact-current Account-owned physical-row observation."""

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservation | None:
        """Return the exact observation at one Account server cutoff."""

        ...


class AccountOwnerAssignmentProvenanceReceiptRepository(Protocol):
    """Actor-bound first-winner store with logical-head CAS reads."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open one issuance transaction."""

        ...

    def now(self) -> datetime:
        """Return the authoritative Account server clock."""

        ...

    def get_winner(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        """Return one immutable receipt identity first winner."""

        ...

    def get_current_head(
        self,
        *,
        receipt_id: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        """Return the final recorded head even when that head is expired."""

        ...

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
        """Append under first-winner and predecessor-CAS semantics."""

        ...

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceipt | None:
        """Return exact immutable receipt evidence knowable at a PIT."""

        ...


class IssueAccountOwnerAssignmentProvenanceReceipt:
    """Issue or replay one actor-bound inactive provenance receipt."""

    def __init__(
        self,
        *,
        row_provider: ExactCurrentPhysicalAccountRowObservationProvider,
        repository: AccountOwnerAssignmentProvenanceReceiptRepository,
        actor: AccountOwnerAssignmentServerActor,
        validity_period: timedelta,
    ) -> None:
        if type(actor) is not AccountOwnerAssignmentServerActor:
            raise TypeError("actor must be exact AccountOwnerAssignmentServerActor")
        AccountOwnerAssignmentServerActor.__post_init__(actor)
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._row_provider = row_provider
        self._repository = repository
        self._actor = actor
        self._validity_period = validity_period

    def execute(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptCommand,
    ) -> AccountOwnerAssignmentProvenanceReceipt:
        """Double-read one exact row and CAS-append its explicit receipt."""

        if type(command) is not IssueAccountOwnerAssignmentProvenanceReceiptCommand:
            raise TypeError(
                "command must be exact IssueAccountOwnerAssignmentProvenanceReceiptCommand"
            )
        IssueAccountOwnerAssignmentProvenanceReceiptCommand.__post_init__(command)
        self._require_actor_for_kind(command.provenance_kind)
        with self._repository.atomic():
            cutoff = self._repository.now()
            try:
                _require_aware(cutoff, "repository cutoff")
            except ValueError as error:
                raise AccountOwnerAssignmentProvenanceReceiptCorruption(str(error)) from error
            first = self._read_row(command, cutoff)
            winner = self._repository.get_winner(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                as_of=cutoff,
            )
            head = self._repository.get_current_head(
                receipt_id=command.receipt_id,
                as_of=cutoff,
            )
            final = self._read_row(command, cutoff)
            if final != first:
                raise AccountOwnerAssignmentProvenanceReceiptConflict(
                    "physical row changed during issuance"
                )
            if winner is not None:
                checked = self._require_record(winner)
                self._validate_winner(checked, command, final, head, cutoff)
                return checked.receipt
            predecessor = self._require_record(head).receipt if head is not None else None
            valid_until = min(final.valid_until, cutoff + self._validity_period)
            if cutoff >= valid_until:
                raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                    "physical row expired before receipt issuance"
                )
            receipt = self._build_receipt(
                command,
                final,
                issued_at=cutoff,
                recorded_at=cutoff,
                valid_until=valid_until,
                supersedes_content_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
            )
            self._validate_row(receipt, final)
            if predecessor is not None:
                try:
                    validate_account_owner_assignment_provenance_receipt_successor(
                        predecessor,
                        receipt,
                    )
                except (TypeError, ValueError) as error:
                    raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                        "provenance receipt successor is invalid"
                    ) from error
            record = PersistedAccountOwnerAssignmentProvenanceReceipt(
                receipt,
                self._actor,
            )
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=(
                    predecessor.content_hash if predecessor is not None else None
                ),
                recorded_at=cutoff,
            )
            checked = self._require_record(persisted)
            if checked != record:
                raise AccountOwnerAssignmentProvenanceReceiptConflict(
                    "concurrent provenance receipt first winner differs"
                )
            return checked.receipt

    def _require_actor_for_kind(self, provenance_kind: str) -> None:
        expected_role = _ROLE_BY_KIND[provenance_kind]
        if self._actor.role != expected_role:
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "authenticated actor has the wrong claimant role"
            )
        if provenance_kind == "migration" and self._actor.is_staff is not True:
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "migration issuance requires a human staff reviewer"
            )

    def _read_row(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptCommand,
        cutoff: datetime,
    ) -> PhysicalAccountRowObservation:
        value = self._row_provider.get_exact_current(
            observation_id=command.row_observation_id,
            observation_version=command.row_observation_version,
            as_of=cutoff,
        )
        if value is None:
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "exact current physical row is unavailable"
            )
        if type(value) is not PhysicalAccountRowObservation:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "physical row type substitution"
            )
        PhysicalAccountRowObservation.__post_init__(value)
        if (
            value.observation_id != command.row_observation_id
            or value.observation_version != command.row_observation_version
        ):
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "physical row identity substitution"
            )
        if not value.is_knowable_at(cutoff) or not value.is_active:
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "exact current physical row is unavailable"
            )
        if value.activation_available or not value.must_not_execute:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "physical row execution state substitution"
            )
        if command.provenance_kind == "creation" and value.row_user_id != self._actor.user_id:
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "creation claimant does not match the exact physical row user"
            )
        return value

    def _build_receipt(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptCommand,
        row: PhysicalAccountRowObservation,
        *,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> AccountOwnerAssignmentProvenanceReceipt:
        migration = command.provenance_kind == "migration"
        return AccountOwnerAssignmentProvenanceReceipt(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            provenance_kind=command.provenance_kind,
            artifact_type=_ARTIFACT_BY_KIND[command.provenance_kind],
            assignment_state="legacy_default" if migration else "authoritative",
            assigned_owner_user_id=None if migration else self._actor.user_id,
            account_namespace=row.account_namespace,
            account_id=row.account_id,
            underlying_unified_account_namespace=(row.underlying_unified_account_namespace),
            underlying_unified_account_id=row.underlying_unified_account_id,
            row_observation_owner=row.owner,
            row_observation_artifact_type=row.artifact_type,
            row_observation_id=row.observation_id,
            row_observation_version=row.observation_version,
            row_observation_identity_hash=row.identity_hash,
            row_observation_content_hash=row.content_hash,
            row_observation_valid_until=row.valid_until,
            claimant=self._actor.to_domain(),
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            supersedes_content_hash=supersedes_content_hash,
        )

    @staticmethod
    def _validate_row(
        receipt: AccountOwnerAssignmentProvenanceReceipt,
        row: PhysicalAccountRowObservation,
    ) -> None:
        try:
            validate_account_owner_assignment_provenance_receipt_row(receipt, row)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "issued receipt does not bind the exact physical row"
            ) from error

    def _validate_winner(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceipt,
        command: IssueAccountOwnerAssignmentProvenanceReceiptCommand,
        row: PhysicalAccountRowObservation,
        head: PersistedAccountOwnerAssignmentProvenanceReceipt | None,
        cutoff: datetime,
    ) -> None:
        receipt = record.receipt
        if not receipt.is_knowable_at(cutoff):
            raise AccountOwnerAssignmentProvenanceReceiptUnavailable(
                "persisted provenance receipt is unavailable"
            )
        if record.issued_by != self._actor:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance receipt belongs to another actor"
            )
        stable = self._build_receipt(
            command,
            row,
            issued_at=receipt.issued_at,
            recorded_at=receipt.recorded_at,
            valid_until=receipt.valid_until,
            supersedes_content_hash=receipt.supersedes_content_hash,
        )
        if stable != receipt:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance receipt identity has another first winner"
            )
        if head is None or self._require_record(head) != record:
            raise AccountOwnerAssignmentProvenanceReceiptConflict(
                "provenance receipt is no longer the logical current head"
            )
        self._validate_row(receipt, row)

    @staticmethod
    def _require_record(value: object) -> PersistedAccountOwnerAssignmentProvenanceReceipt:
        if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceipt:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "repository record type substitution"
            )
        PersistedAccountOwnerAssignmentProvenanceReceipt.__post_init__(value)
        return value


class GetExactAccountOwnerAssignmentProvenanceReceipt:
    """Read exact inactive provenance by identity, hash, and PIT."""

    def __init__(self, repository: AccountOwnerAssignmentProvenanceReceiptRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactAccountOwnerAssignmentProvenanceReceiptCommand,
    ) -> AccountOwnerAssignmentProvenanceReceipt | None:
        """Return only exact immutable receipt evidence knowable at the PIT."""

        if type(command) is not GetExactAccountOwnerAssignmentProvenanceReceiptCommand:
            raise TypeError(
                "command must be exact GetExactAccountOwnerAssignmentProvenanceReceiptCommand"
            )
        GetExactAccountOwnerAssignmentProvenanceReceiptCommand.__post_init__(command)
        value = self._repository.get_exact_by_hash(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        receipt = IssueAccountOwnerAssignmentProvenanceReceipt._require_record(value).receipt
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "exact provenance receipt identity substitution"
            )
        if not receipt.is_knowable_at(command.as_of):
            return None
        if receipt.activation_available or not receipt.must_not_execute:
            raise AccountOwnerAssignmentProvenanceReceiptCorruption(
                "provenance receipt execution state substitution"
            )
        return receipt


class GetCurrentAccountOwnerAssignmentProvenanceReceipt:
    """Read one closed-selector inactive receipt at its final logical head."""

    def __init__(self, repository: AccountOwnerAssignmentProvenanceReceiptRepository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand,
    ) -> AccountOwnerAssignmentProvenanceReceipt | None:
        """Reject selector substitutions and never fall back from expiry."""

        if type(command) is not GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand:
            raise TypeError(
                "command must be exact GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand"
            )
        GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand.__post_init__(command)
        expected = command.receipt
        receipt = GetExactAccountOwnerAssignmentProvenanceReceipt(self._repository).execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptCommand(
                receipt_id=expected.receipt_id,
                receipt_version=expected.receipt_version,
                expected_content_hash=expected.content_hash,
                as_of=command.as_of,
            )
        )
        if receipt is None or receipt != expected:
            return None
        head = self._repository.get_current_head(
            receipt_id=expected.receipt_id,
            as_of=command.as_of,
        )
        if (
            head is None
            or IssueAccountOwnerAssignmentProvenanceReceipt._require_record(head).receipt
            != expected
        ):
            return None
        return receipt


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptConflict",
    "AccountOwnerAssignmentProvenanceReceiptCorruption",
    "AccountOwnerAssignmentProvenanceReceiptRepository",
    "AccountOwnerAssignmentProvenanceReceiptUnavailable",
    "ExactCurrentPhysicalAccountRowObservationProvider",
    "GetCurrentAccountOwnerAssignmentProvenanceReceipt",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptCommand",
    "GetExactAccountOwnerAssignmentProvenanceReceipt",
    "GetExactAccountOwnerAssignmentProvenanceReceiptCommand",
    "IssueAccountOwnerAssignmentProvenanceReceipt",
    "IssueAccountOwnerAssignmentProvenanceReceiptCommand",
    "PersistedAccountOwnerAssignmentProvenanceReceipt",
]
