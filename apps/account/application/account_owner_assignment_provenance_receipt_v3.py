"""Creation-only issuance and closed reads for Account claimant receipt v3."""

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
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
    validate_account_owner_assignment_provenance_receipt_v3_binding,
    validate_account_owner_assignment_provenance_receipt_v3_root,
    validate_account_owner_assignment_provenance_receipt_v3_successor,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)


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


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentProvenanceReceiptV3:
    """Bind one receipt first winner to its authenticated human claimant."""

    receipt: AccountOwnerAssignmentProvenanceReceiptV3
    issued_by: AccountOwnerAssignmentServerActor

    def __post_init__(self) -> None:
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV3:
            raise TypeError("receipt must be an exact v3 provenance receipt")
        self.receipt.__post_init__()
        if type(self.issued_by) is not AccountOwnerAssignmentServerActor:
            raise TypeError("issued_by must be an exact authenticated actor")
        self.issued_by.__post_init__()
        if self.receipt.claimant != self.issued_by.to_domain():
            raise ValueError("persisted v3 receipt actor seal is invalid")


@dataclass(frozen=True, slots=True)
class IssueAccountOwnerAssignmentProvenanceReceiptV3Command:
    """Select only one receipt identity and exact durable Binding-v2 seal."""

    receipt_id: str
    receipt_version: str
    binding_id: str
    binding_version: str
    expected_binding_content_hash: str
    expected_creation_root_content_hash: str

    def __post_init__(self) -> None:
        for name in ("receipt_id", "receipt_version", "binding_id", "binding_version"):
            _token(getattr(self, name), name)
        _digest(self.expected_binding_content_hash, "expected_binding_content_hash")
        _digest(
            self.expected_creation_root_content_hash,
            "expected_creation_root_content_hash",
        )


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentProvenanceReceiptV3Command:
    """Select one exact immutable receipt at a historical point in time."""

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
class GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command:
    """Carry the complete expected closed-current receipt head."""

    expected_receipt: AccountOwnerAssignmentProvenanceReceiptV3
    as_of: datetime

    def __post_init__(self) -> None:
        if type(self.expected_receipt) is not AccountOwnerAssignmentProvenanceReceiptV3:
            raise TypeError("expected_receipt must be an exact v3 receipt")
        self.expected_receipt.__post_init__()
        _aware(self.as_of, "as_of")


class ExactCanonicalAccountCreationBindingV2Provider(Protocol):
    """Read only one exact durable Binding-v2 seal."""

    def get_exact(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None: ...


class ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider(Protocol):
    """Read only an exact-current allocated Physical-v3 creation root."""

    def get_exact(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None: ...

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None: ...


class CurrentAccountOwnerClaimantProvider(Protocol):
    """Resolve the currently authenticated human claimant at one cutoff."""

    def get_current(self, *, as_of: datetime) -> AccountOwnerAssignmentServerActor | None: ...


class AccountOwnerAssignmentProvenanceReceiptV3Repository(Protocol):
    """Persist first winners and logical heads with predecessor CAS."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None: ...

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None: ...

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3: ...

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None: ...


@dataclass(frozen=True, slots=True)
class _IssuanceInputs:
    binding: CanonicalAccountCreationBindingV2
    root: AllocatedPhysicalAccountRowObservationV3
    actor: AccountOwnerAssignmentServerActor


class IssueAccountOwnerAssignmentProvenanceReceiptV3:
    """Winner-first, double-read, CAS issuance from Binding-v2 and Physical-v3."""

    def __init__(
        self,
        *,
        binding_provider: ExactCanonicalAccountCreationBindingV2Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        claimant_provider: CurrentAccountOwnerClaimantProvider,
        repository: AccountOwnerAssignmentProvenanceReceiptV3Repository,
        validity_period: timedelta,
    ) -> None:
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._bindings = binding_provider
        self._roots = root_provider
        self._claimants = claimant_provider
        self._repository = repository
        self._validity_period = validity_period

    def execute(
        self, command: IssueAccountOwnerAssignmentProvenanceReceiptV3Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV3:
        """Issue or replay one creation claim under a single server cutoff."""

        if type(command) is not IssueAccountOwnerAssignmentProvenanceReceiptV3Command:
            raise TypeError("command must be an exact v3 issue command")
        command.__post_init__()
        with self._repository.atomic():
            cutoff = self._clock(self._repository.now())
            winner_value = self._repository.get_winner(
                receipt_id=command.receipt_id,
                receipt_version=command.receipt_version,
                as_of=cutoff,
            )
            winner = self._optional_record(winner_value)
            if winner is not None:
                self._validate_historical_winner(winner, command, cutoff)
                return winner.receipt
            first = self._read_inputs(command, cutoff)
            head_value = self._repository.get_current_head(
                receipt_id=command.receipt_id, as_of=cutoff
            )
            try:
                final = self._read_inputs(command, cutoff)
            except AccountOwnerAssignmentUnavailable as error:
                raise AccountOwnerAssignmentConflict(
                    "v3 issuance inputs changed during issuance"
                ) from error
            if final != first:
                raise AccountOwnerAssignmentConflict("v3 issuance inputs changed during issuance")
            head = self._optional_record(head_value)
            predecessor = head.receipt if head is not None else None
            recorded_at = self._clock(self._repository.now())
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentCorruption("repository clock moved backwards")
            valid_until = min(
                final.root.valid_until,
                final.binding.allocation.valid_until,
                cutoff + self._validity_period,
            )
            if recorded_at >= valid_until:
                raise AccountOwnerAssignmentUnavailable("creation evidence expired before issuance")
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
            try:
                if predecessor is None:
                    validate_account_owner_assignment_provenance_receipt_v3_root(receipt)
                else:
                    validate_account_owner_assignment_provenance_receipt_v3_successor(
                        predecessor, receipt
                    )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentCorruption("v3 receipt chain is invalid") from error
            expected = PersistedAccountOwnerAssignmentProvenanceReceiptV3(receipt, final.actor)
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
                raise AccountOwnerAssignmentConflict("concurrent v3 first winner differs")
            return persisted.receipt

    def _read_inputs(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV3Command,
        as_of: datetime,
    ) -> _IssuanceInputs:
        binding = _require_binding(
            self._bindings.get_exact(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                expected_content_hash=command.expected_binding_content_hash,
                as_of=as_of,
            ),
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_binding_content_hash,
            as_of=as_of,
        )
        root = _read_root(self._roots, binding, as_of)
        actor = _require_claimant(self._claimants.get_current(as_of=as_of))
        if actor.user_id != binding.allocation.requested_row_user_id:
            raise AccountOwnerAssignmentUnavailable(
                "current claimant does not own the creation allocation"
            )
        return _IssuanceInputs(binding, root, actor)

    @staticmethod
    def _build(
        command: IssueAccountOwnerAssignmentProvenanceReceiptV3Command,
        inputs: _IssuanceInputs,
        *,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> AccountOwnerAssignmentProvenanceReceiptV3:
        binding, root, actor = inputs.binding, inputs.root, inputs.actor
        physical = root.physical_observation
        return AccountOwnerAssignmentProvenanceReceiptV3(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            binding=binding,
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            underlying_unified_account_namespace=binding.underlying_unified_account_namespace_claim,
            underlying_unified_account_id=binding.underlying_unified_account_id_claim,
            allocation_identity_hash=binding.allocation.identity_hash,
            allocation_content_hash=binding.allocation.content_hash,
            creation_root_identity_hash=root.identity_hash,
            creation_root_content_hash=root.content_hash,
            binding_identity_hash=binding.identity_hash,
            binding_content_hash=binding.content_hash,
            account_claim_hash=binding.account_claim_hash,
            underlying_claim_hash=binding.underlying_claim_hash,
            physical_observation_content_hash=physical.content_hash,
            physical_source_content_hash=physical.source_content_hash,
            physical_raw_observation_content_hash=physical.raw_observation_content_hash,
            assigned_owner_user_id=actor.user_id,
            claimant=actor.to_domain(),
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_historical_winner(
        self,
        winner: PersistedAccountOwnerAssignmentProvenanceReceiptV3,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV3Command,
        cutoff: datetime,
    ) -> None:
        receipt = winner.receipt
        if receipt.recorded_at > cutoff:
            raise AccountOwnerAssignmentCorruption("repository returned a future v3 winner")
        actor = _require_claimant(self._claimants.get_current(as_of=cutoff))
        if actor != winner.issued_by:
            raise AccountOwnerAssignmentConflict("v3 receipt belongs to another claimant")
        binding = _require_binding(
            self._bindings.get_exact(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                expected_content_hash=command.expected_binding_content_hash,
                as_of=cutoff,
            ),
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_binding_content_hash,
            as_of=cutoff,
        )
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.binding != binding
            or receipt.binding_content_hash != command.expected_binding_content_hash
            or receipt.creation_root_content_hash != command.expected_creation_root_content_hash
        ):
            raise AccountOwnerAssignmentConflict("v3 receipt identity has another first winner")
        stable = self._build(
            command,
            _IssuanceInputs(binding, binding.creation_root, winner.issued_by),
            issued_at=receipt.issued_at,
            recorded_at=receipt.recorded_at,
            valid_until=receipt.valid_until,
            supersedes_content_hash=receipt.supersedes_content_hash,
        )
        if stable != receipt:
            raise AccountOwnerAssignmentConflict("v3 receipt identity has another first winner")
        try:
            validate_account_owner_assignment_provenance_receipt_v3_binding(receipt, binding)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("v3 winner binding seal is invalid") from error

    @staticmethod
    def _record(value: object) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3:
        if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV3:
            raise AccountOwnerAssignmentCorruption("repository record type substitution")
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "repository returned invalid v3 receipt"
            ) from error
        return value

    @classmethod
    def _optional_record(
        cls, value: object | None
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV3 | None:
        return None if value is None else cls._record(value)

    @staticmethod
    def _clock(value: object) -> datetime:
        try:
            _aware(value, "repository clock")
        except ValueError as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error
        return value  # type: ignore[return-value]


class GetExactAccountOwnerAssignmentProvenanceReceiptV3:
    """Read exact PIT evidence only while Binding-v2 and Physical-v3 remain exact."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV3Repository,
        binding_provider: ExactCanonicalAccountCreationBindingV2Provider,
    ) -> None:
        self._repository = repository
        self._bindings = binding_provider

    def execute(
        self, command: GetExactAccountOwnerAssignmentProvenanceReceiptV3Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV3 | None:
        """Return exact evidence without any predecessor or prior-version fallback."""

        if type(command) is not GetExactAccountOwnerAssignmentProvenanceReceiptV3Command:
            raise TypeError("command must be an exact v3 PIT command")
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        receipt = IssueAccountOwnerAssignmentProvenanceReceiptV3._record(value).receipt
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentCorruption("exact v3 receipt selector substitution")
        if command.as_of < receipt.recorded_at:
            return None
        try:
            binding = _read_receipt_binding(self._bindings, receipt, command.as_of)
        except AccountOwnerAssignmentUnavailable:
            return None
        try:
            validate_account_owner_assignment_provenance_receipt_v3_binding(receipt, binding)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("v3 receipt binding seal is invalid") from error
        return receipt


class GetCurrentAccountOwnerAssignmentProvenanceReceiptV3:
    """Read only the closed logical head with exact-current upstream evidence."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV3Repository,
        binding_provider: ExactCanonicalAccountCreationBindingV2Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
    ) -> None:
        self._repository = repository
        self._roots = root_provider
        self._exact = GetExactAccountOwnerAssignmentProvenanceReceiptV3(
            repository=repository,
            binding_provider=binding_provider,
        )

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV3 | None:
        """Return expected head or none; never fall back from a replaced/expired head."""

        if type(command) is not GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command:
            raise TypeError("command must be an exact v3 current command")
        command.__post_init__()
        expected = command.expected_receipt
        exact = self._exact.execute(
            GetExactAccountOwnerAssignmentProvenanceReceiptV3Command(
                expected.receipt_id,
                expected.receipt_version,
                expected.content_hash,
                command.as_of,
            )
        )
        if exact != expected:
            return None
        if not expected.is_current_at(command.as_of):
            return None
        try:
            _read_root(self._roots, expected.binding, command.as_of)
        except AccountOwnerAssignmentUnavailable:
            return None
        head = self._repository.get_current_head(
            receipt_id=expected.receipt_id, as_of=command.as_of
        )
        if (
            head is None
            or IssueAccountOwnerAssignmentProvenanceReceiptV3._record(head).receipt != expected
        ):
            return None
        return exact


def _require_binding(
    value: CanonicalAccountCreationBindingV2 | None,
    *,
    binding_id: str,
    binding_version: str,
    expected_content_hash: str,
    as_of: datetime,
) -> CanonicalAccountCreationBindingV2:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact durable Binding-v2 is unavailable")
    if type(value) is not CanonicalAccountCreationBindingV2:
        raise AccountOwnerAssignmentCorruption("Binding-v2 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Binding-v2 is invalid") from error
    if (
        value.binding_id != binding_id
        or value.binding_version != binding_version
        or value.content_hash != expected_content_hash
    ):
        raise AccountOwnerAssignmentCorruption("Binding-v2 selector substitution")
    if not value.is_knowable_at(as_of):
        raise AccountOwnerAssignmentUnavailable("exact durable Binding-v2 is unavailable")
    return value


def _read_receipt_binding(
    provider: ExactCanonicalAccountCreationBindingV2Provider,
    receipt: AccountOwnerAssignmentProvenanceReceiptV3,
    as_of: datetime,
) -> CanonicalAccountCreationBindingV2:
    binding = receipt.binding
    return _require_binding(
        provider.get_exact(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            expected_content_hash=receipt.binding_content_hash,
            as_of=as_of,
        ),
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        expected_content_hash=receipt.binding_content_hash,
        as_of=as_of,
    )


def _read_root(
    provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
    binding: CanonicalAccountCreationBindingV2,
    as_of: datetime,
) -> AllocatedPhysicalAccountRowObservationV3:
    expected = binding.creation_root
    value = provider.get_exact_current(
        observation_id=expected.observation_id,
        observation_version=expected.observation_version,
        expected_content_hash=binding.creation_root_content_hash,
        as_of=as_of,
    )
    if value is None:
        raise AccountOwnerAssignmentUnavailable("exact-current Physical-v3 is unavailable")
    if type(value) is not AllocatedPhysicalAccountRowObservationV3:
        raise AccountOwnerAssignmentCorruption("Physical-v3 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("Physical-v3 is invalid") from error
    if value != expected or value.content_hash != binding.creation_root_content_hash:
        raise AccountOwnerAssignmentCorruption("Physical-v3 selector substitution")
    if not value.is_knowable_at(as_of):
        raise AccountOwnerAssignmentUnavailable("exact-current Physical-v3 is unavailable")
    return value


def _require_claimant(
    value: AccountOwnerAssignmentServerActor | None,
) -> AccountOwnerAssignmentServerActor:
    if value is None:
        raise AccountOwnerAssignmentUnavailable("current human claimant is unavailable")
    if type(value) is not AccountOwnerAssignmentServerActor:
        raise AccountOwnerAssignmentCorruption("claimant type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("claimant is invalid") from error
    if value.role != "account_owner_claimant" or value.is_staff:
        raise AccountOwnerAssignmentUnavailable("current human claimant is not eligible")
    return value


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV3Repository",
    "CurrentAccountOwnerClaimantProvider",
    "ExactCanonicalAccountCreationBindingV2Provider",
    "ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV3",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV3Command",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV3",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV3Command",
    "IssueAccountOwnerAssignmentProvenanceReceiptV3",
    "IssueAccountOwnerAssignmentProvenanceReceiptV3Command",
    "PersistedAccountOwnerAssignmentProvenanceReceiptV3",
]
