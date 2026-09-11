"""Application orchestration for policy-bound Account owner receipt v4."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.account_owner_assignment_evidence import (
    AccountOwnerAssignmentConflict,
    AccountOwnerAssignmentCorruption,
    AccountOwnerAssignmentServerActor,
    AccountOwnerAssignmentUnavailable,
)
from apps.account.application.account_owner_assignment_provenance_receipt_v3 import (
    ExactCanonicalAccountCreationBindingV2Provider,
    ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
)
from apps.account.application.single_owner_actor_authority import (
    CurrentSingleOwnerParticipants,
)
from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
    validate_account_owner_assignment_provenance_receipt_v4_binding,
    validate_account_owner_assignment_provenance_receipt_v4_root,
    validate_account_owner_assignment_provenance_receipt_v4_successor,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
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


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class PersistedAccountOwnerAssignmentProvenanceReceiptV4:
    """Bind one v4 receipt to the real current staff authority that issued it."""

    receipt: AccountOwnerAssignmentProvenanceReceiptV4
    issued_by: AccountOwnerAssignmentServerActor
    authority: CurrentAccountActorAuthorityV3

    def __post_init__(self) -> None:
        """Validate exact receipt, actor, and authenticated authority facts."""

        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV4:
            raise TypeError("receipt must be an exact v4 provenance receipt")
        self.receipt.__post_init__()
        if type(self.issued_by) is not AccountOwnerAssignmentServerActor:
            raise TypeError("issued_by must be an exact authenticated server actor")
        self.issued_by.__post_init__()
        if type(self.authority) is not CurrentAccountActorAuthorityV3:
            raise TypeError("authority must be an exact current actor authority")
        self.authority.__post_init__()
        if self.issued_by.role != "account_owner_claimant":
            raise ValueError("v4 issuer must use the owner claimant role")
        if not self.issued_by.is_staff or self.receipt.claimant.is_staff is not True:
            raise ValueError("v4 issuer and claimant must preserve staff truth")
        if self.receipt.claimant != self.issued_by.to_domain():
            raise ValueError("persisted v4 receipt actor seal is invalid")
        if (
            self.authority.actor_id != self.issued_by.actor_id
            or self.authority.user_id != self.issued_by.user_id
            or self.authority.is_staff is not self.issued_by.is_staff
        ):
            raise ValueError("persisted v4 receipt authority actor seal is invalid")
        if (
            not self.authority.is_authenticated
            or not self.authority.is_active
            or not self.authority.is_staff
            or self.authority.rbac_role != "admin"
        ):
            raise ValueError("persisted v4 receipt authority is not current admin")
        if self.authority.recorded_at > self.receipt.issued_at:
            raise ValueError("authority recorded_at must precede receipt issued_at")
        if self.receipt.valid_until > self.authority.valid_until:
            raise ValueError("receipt valid_until exceeds authority valid_until")


@dataclass(frozen=True, slots=True)
class IssueAccountOwnerAssignmentProvenanceReceiptV4Command:
    """Select one receipt identity and exact durable Binding-v2/root seals."""

    receipt_id: str
    receipt_version: str
    binding_id: str
    binding_version: str
    expected_binding_content_hash: str
    expected_creation_root_content_hash: str

    def __post_init__(self) -> None:
        """Validate the six server-selected identity and hash selectors."""

        for name in ("receipt_id", "receipt_version", "binding_id", "binding_version"):
            _token(getattr(self, name), name)
        _digest(self.expected_binding_content_hash, "expected_binding_content_hash")
        _digest(
            self.expected_creation_root_content_hash,
            "expected_creation_root_content_hash",
        )


@dataclass(frozen=True, slots=True)
class GetExactAccountOwnerAssignmentProvenanceReceiptV4Command:
    """Select one immutable historical v4 receipt by exact hash."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact historical selectors and an aware cutoff."""

        _token(self.receipt_id, "receipt_id")
        _token(self.receipt_version, "receipt_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command:
    """Select one expected current v4 head without granting authority."""

    receipt_id: str
    receipt_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        """Validate exact current selectors and an aware cutoff."""

        _token(self.receipt_id, "receipt_id")
        _token(self.receipt_version, "receipt_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


class CurrentSingleOwnerParticipantsReader(Protocol):
    """Re-read current policy and authenticated same-owner roles per cutoff."""

    def get_current(self, *, as_of: datetime) -> CurrentSingleOwnerParticipants | None:
        """Return the exact current policy, authority, and role facts at ``as_of``."""
        ...


class AccountOwnerAssignmentProvenanceReceiptV4Repository(Protocol):
    """Persist first winners and logical v4 heads under predecessor CAS."""

    def atomic(self) -> AbstractContextManager[None]:
        """Open the repository unit of work used for one issuance or replay."""
        ...

    def now(self) -> datetime:
        """Return the repository's current timezone-aware clock value."""
        ...

    def get_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return the immutable first winner knowable at ``as_of``."""
        ...

    def get_current_head(
        self, *, receipt_id: str, as_of: datetime
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return the logical receipt head knowable at ``as_of``."""
        ...

    def append(
        self,
        record: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
        """Append an exact root or predecessor-checked successor receipt."""
        ...

    def get_exact_by_hash(
        self,
        *,
        receipt_id: str,
        receipt_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return only the requested historical identity and content hash."""
        ...


@dataclass(frozen=True, slots=True)
class _IssuanceInputs:
    """Validated sources used to construct one immutable receipt."""

    binding: CanonicalAccountCreationBindingV2
    root: AllocatedPhysicalAccountRowObservationV3
    participants: CurrentSingleOwnerParticipants


class IssueAccountOwnerAssignmentProvenanceReceiptV4:
    """Issue or replay one current policy-bound owner provenance receipt."""

    def __init__(
        self,
        *,
        binding_provider: ExactCanonicalAccountCreationBindingV2Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        participants_reader: CurrentSingleOwnerParticipantsReader,
        repository: AccountOwnerAssignmentProvenanceReceiptV4Repository,
        validity_period: timedelta,
    ) -> None:
        """Inject only public source readers and the immutable receipt repository."""

        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._bindings = binding_provider
        self._roots = root_provider
        self._participants = participants_reader
        self._repository = repository
        self._validity_period = validity_period

    def execute(
        self, command: IssueAccountOwnerAssignmentProvenanceReceiptV4Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV4:
        """Issue once with double reads and replay only after current revalidation."""

        if type(command) is not IssueAccountOwnerAssignmentProvenanceReceiptV4Command:
            raise TypeError("command must be an exact v4 issue command")
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
                receipt_id=command.receipt_id,
                as_of=cutoff,
            )
            head = self._optional_record(head_value)
            recorded_at = self._clock(self._repository.now())
            if recorded_at < cutoff:
                raise AccountOwnerAssignmentCorruption("repository clock moved backwards")
            try:
                final = self._read_inputs(command, recorded_at)
            except AccountOwnerAssignmentUnavailable as error:
                raise AccountOwnerAssignmentConflict(
                    "v4 issuance inputs changed during final revalidation"
                ) from error
            if not _same_inputs(first, final):
                raise AccountOwnerAssignmentConflict("v4 issuance inputs changed during issuance")
            predecessor = head.receipt if head is not None else None
            valid_until = min(
                final.participants.policy.valid_until,
                final.participants.authority.valid_until,
                final.participants.valid_until,
                final.root.valid_until,
                final.binding.allocation.valid_until,
                cutoff + self._validity_period,
            )
            if recorded_at >= valid_until:
                raise AccountOwnerAssignmentUnavailable(
                    "creation evidence expired before v4 issuance"
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
            try:
                if predecessor is None:
                    validate_account_owner_assignment_provenance_receipt_v4_root(receipt)
                else:
                    validate_account_owner_assignment_provenance_receipt_v4_successor(
                        predecessor, receipt
                    )
            except (TypeError, ValueError) as error:
                raise AccountOwnerAssignmentCorruption("v4 receipt chain is invalid") from error
            expected = PersistedAccountOwnerAssignmentProvenanceReceiptV4(
                receipt,
                _server_actor(final.participants.claimant),
                final.participants.authority,
            )
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
                raise AccountOwnerAssignmentConflict("concurrent v4 first winner differs")
            return persisted.receipt

    def _read_inputs(
        self,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV4Command,
        as_of: datetime,
    ) -> _IssuanceInputs:
        binding_value = self._bindings.get_exact(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_binding_content_hash,
            as_of=as_of,
        )
        binding = _require_binding(
            binding_value,
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_binding_content_hash,
            as_of=as_of,
        )
        if binding.creation_root_content_hash != command.expected_creation_root_content_hash:
            raise AccountOwnerAssignmentConflict(
                "creation root selector differs from exact Binding v2"
            )
        root = _read_root(self._roots, binding, as_of)
        participants_raw = self._participants.get_current(as_of=as_of)
        participants = _require_participants(participants_raw, as_of=as_of)
        if (
            participants.policy.account_namespace != binding.account_namespace_claim
            or participants.policy.account_id != binding.account_id_claim
        ):
            raise AccountOwnerAssignmentCorruption(
                "single-owner policy account scope differs from Binding v2"
            )
        if participants.claimant.user_id != binding.allocation.requested_row_user_id:
            raise AccountOwnerAssignmentUnavailable(
                "current claimant does not own the creation allocation"
            )
        return _IssuanceInputs(binding, root, participants)

    @staticmethod
    def _build(
        command: IssueAccountOwnerAssignmentProvenanceReceiptV4Command,
        inputs: _IssuanceInputs,
        *,
        issued_at: datetime,
        recorded_at: datetime,
        valid_until: datetime,
        supersedes_content_hash: str | None,
    ) -> AccountOwnerAssignmentProvenanceReceiptV4:
        binding, root, participants = inputs.binding, inputs.root, inputs.participants
        physical = root.physical_observation
        policy = participants.policy
        return AccountOwnerAssignmentProvenanceReceiptV4(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            policy=policy,
            policy_identity_hash=policy.identity_hash,
            policy_content_hash=policy.content_hash,
            binding=binding,
            account_namespace=binding.account_namespace_claim,
            account_id=binding.account_id_claim,
            underlying_unified_account_namespace=(
                binding.underlying_unified_account_namespace_claim
            ),
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
            assigned_owner_user_id=participants.claimant.user_id,
            claimant=participants.claimant,
            issued_at=issued_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            supersedes_content_hash=supersedes_content_hash,
        )

    def _validate_historical_winner(
        self,
        winner: PersistedAccountOwnerAssignmentProvenanceReceiptV4,
        command: IssueAccountOwnerAssignmentProvenanceReceiptV4Command,
        cutoff: datetime,
    ) -> None:
        receipt = winner.receipt
        if receipt.recorded_at > cutoff:
            raise AccountOwnerAssignmentCorruption("repository returned a future v4 winner")
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.binding.binding_id != command.binding_id
            or receipt.binding.binding_version != command.binding_version
            or receipt.binding_content_hash != command.expected_binding_content_hash
            or receipt.creation_root_content_hash != command.expected_creation_root_content_hash
        ):
            raise AccountOwnerAssignmentConflict("v4 receipt identity has another first winner")
        try:
            current = self._read_inputs(command, cutoff)
        except AccountOwnerAssignmentUnavailable as error:
            raise AccountOwnerAssignmentConflict(
                "v4 winner no longer has current policy or actor authority"
            ) from error
        current_issuer = _server_actor(current.participants.claimant)
        if (
            current.participants.policy != receipt.policy
            or current.participants.claimant != receipt.claimant
            or current_issuer != winner.issued_by
            or current.participants.authority != winner.authority
        ):
            raise AccountOwnerAssignmentConflict(
                "v4 winner no longer binds current actor or policy"
            )
        stable = self._build(
            command,
            current,
            issued_at=receipt.issued_at,
            recorded_at=receipt.recorded_at,
            valid_until=receipt.valid_until,
            supersedes_content_hash=receipt.supersedes_content_hash,
        )
        current_record = PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            stable,
            current_issuer,
            current.participants.authority,
        )
        if current_record != winner:
            raise AccountOwnerAssignmentConflict(
                "v4 winner no longer binds current actor or policy"
            )
        try:
            validate_account_owner_assignment_provenance_receipt_v4_binding(
                receipt, current.binding
            )
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("v4 winner binding seal is invalid") from error

    @staticmethod
    def _record(value: object) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4:
        if type(value) is not PersistedAccountOwnerAssignmentProvenanceReceiptV4:
            raise AccountOwnerAssignmentCorruption("repository record type substitution")
        try:
            value.__post_init__()
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(
                "repository returned invalid v4 receipt"
            ) from error
        return value

    @classmethod
    def _optional_record(
        cls, value: object | None
    ) -> PersistedAccountOwnerAssignmentProvenanceReceiptV4 | None:
        return None if value is None else cls._record(value)

    @staticmethod
    def _clock(value: object) -> datetime:
        try:
            return _aware(value, "repository clock")
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption(str(error)) from error


class GetExactAccountOwnerAssignmentProvenanceReceiptV4:
    """Read immutable history while preserving evidence semantics after expiry."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV4Repository,
        binding_provider: ExactCanonicalAccountCreationBindingV2Provider,
    ) -> None:
        """Inject the exact receipt repository and durable Binding-v2 reader."""

        self._repository = repository
        self._bindings = binding_provider

    def execute(
        self, command: GetExactAccountOwnerAssignmentProvenanceReceiptV4Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return exact historical evidence without requiring current authority."""

        if type(command) is not GetExactAccountOwnerAssignmentProvenanceReceiptV4Command:
            raise TypeError("command must be an exact v4 PIT command")
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = IssueAccountOwnerAssignmentProvenanceReceiptV4._record(value)
        receipt = record.receipt
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentCorruption("exact v4 receipt selector substitution")
        if command.as_of < receipt.recorded_at:
            return None
        try:
            binding = _require_binding(
                self._bindings.get_exact(
                    binding_id=receipt.binding.binding_id,
                    binding_version=receipt.binding.binding_version,
                    expected_content_hash=receipt.binding_content_hash,
                    as_of=command.as_of,
                ),
                binding_id=receipt.binding.binding_id,
                binding_version=receipt.binding.binding_version,
                expected_content_hash=receipt.binding_content_hash,
                as_of=command.as_of,
            )
        except AccountOwnerAssignmentUnavailable:
            return None
        try:
            validate_account_owner_assignment_provenance_receipt_v4_binding(receipt, binding)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("v4 receipt binding seal is invalid") from error
        return receipt


class GetCurrentAccountOwnerAssignmentProvenanceReceiptV4:
    """Read only the exact current head after policy, actor, root, and head re-reads."""

    def __init__(
        self,
        *,
        repository: AccountOwnerAssignmentProvenanceReceiptV4Repository,
        binding_provider: ExactCanonicalAccountCreationBindingV2Provider,
        root_provider: ExactCurrentAllocatedPhysicalAccountRowObservationV3Provider,
        participants_reader: CurrentSingleOwnerParticipantsReader,
    ) -> None:
        """Inject all current source readers required for a fail-closed read."""

        self._repository = repository
        self._bindings = binding_provider
        self._roots = root_provider
        self._participants = participants_reader

    def execute(
        self, command: GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command
    ) -> AccountOwnerAssignmentProvenanceReceiptV4 | None:
        """Return the exact current head only while every live source still agrees."""

        if type(command) is not GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command:
            raise TypeError("command must be an exact v4 current command")
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            receipt_id=command.receipt_id,
            receipt_version=command.receipt_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        record = IssueAccountOwnerAssignmentProvenanceReceiptV4._record(value)
        receipt = record.receipt
        if (
            receipt.receipt_id != command.receipt_id
            or receipt.receipt_version != command.receipt_version
            or receipt.content_hash != command.expected_content_hash
        ):
            raise AccountOwnerAssignmentCorruption("current v4 receipt selector substitution")
        if command.as_of < receipt.recorded_at:
            return None
        try:
            binding = _require_binding(
                self._bindings.get_exact(
                    binding_id=receipt.binding.binding_id,
                    binding_version=receipt.binding.binding_version,
                    expected_content_hash=receipt.binding_content_hash,
                    as_of=command.as_of,
                ),
                binding_id=receipt.binding.binding_id,
                binding_version=receipt.binding.binding_version,
                expected_content_hash=receipt.binding_content_hash,
                as_of=command.as_of,
            )
        except AccountOwnerAssignmentUnavailable:
            return None
        try:
            validate_account_owner_assignment_provenance_receipt_v4_binding(receipt, binding)
        except (TypeError, ValueError) as error:
            raise AccountOwnerAssignmentCorruption("v4 current binding seal is invalid") from error
        try:
            participants = _require_participants(
                self._participants.get_current(as_of=command.as_of),
                as_of=command.as_of,
            )
        except AccountOwnerAssignmentUnavailable:
            return None
        if (
            participants.policy != receipt.policy
            or participants.policy.identity_hash != receipt.policy_identity_hash
            or participants.policy.content_hash != receipt.policy_content_hash
        ):
            return None
        current_issuer = _server_actor(participants.claimant)
        if current_issuer != record.issued_by or participants.authority != record.authority:
            return None
        current_record = PersistedAccountOwnerAssignmentProvenanceReceiptV4(
            receipt, current_issuer, participants.authority
        )
        if current_record != record:
            return None
        try:
            root = _read_root(self._roots, binding, command.as_of)
        except AccountOwnerAssignmentUnavailable:
            return None
        if root != binding.creation_root:
            raise AccountOwnerAssignmentCorruption("current v4 Physical-v3 root substitution")
        if not receipt.is_current_at(command.as_of):
            return None
        head = IssueAccountOwnerAssignmentProvenanceReceiptV4._optional_record(
            self._repository.get_current_head(
                receipt_id=receipt.receipt_id,
                as_of=command.as_of,
            )
        )
        if head is None or head != record:
            return None
        return receipt


def _require_binding(
    value: object | None,
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


def _require_participants(
    value: object | None,
    *,
    as_of: datetime,
) -> CurrentSingleOwnerParticipants:
    """Validate every field of the unsealed participants reader projection."""

    if value is None:
        raise AccountOwnerAssignmentUnavailable("current single-owner participants are unavailable")
    if type(value) is not CurrentSingleOwnerParticipants:
        raise AccountOwnerAssignmentCorruption("participants type substitution")
    participants = value
    try:
        cutoff = _aware(as_of, "as_of")
        policy = participants.policy
        authority = participants.authority
        claimant = participants.claimant
        approver = participants.approver
        if type(policy) is not SingleOwnerAuthorityPolicyV1:
            raise TypeError("participants policy type substitution")
        policy.__post_init__()
        if type(authority) is not CurrentAccountActorAuthorityV3:
            raise TypeError("participants authority type substitution")
        authority.__post_init__()
        if type(claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("participants claimant type substitution")
        if type(approver) is not AccountOwnerAssignmentActor:
            raise TypeError("participants approver type substitution")
        claimant.__post_init__()
        approver.__post_init__()
        observed_at = _aware(participants.observed_at, "participants observed_at")
        valid_until = _aware(participants.valid_until, "participants valid_until")
    except (AttributeError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption("participants projection is corrupt") from error
    if observed_at != cutoff:
        raise AccountOwnerAssignmentCorruption("participants observation clock substitution")
    if authority.recorded_at > cutoff:
        raise AccountOwnerAssignmentCorruption("participants authority clock substitution")
    if not policy.is_current_at(cutoff):
        raise AccountOwnerAssignmentUnavailable("current single-owner policy is unavailable")
    if (
        not authority.is_authenticated
        or not authority.is_active
        or not authority.is_staff
        or authority.rbac_role != "admin"
        or cutoff >= authority.valid_until
    ):
        raise AccountOwnerAssignmentUnavailable("current actor authority is unavailable")
    if valid_until <= cutoff:
        raise AccountOwnerAssignmentUnavailable("current participant validity is unavailable")
    if valid_until > min(policy.valid_until, authority.valid_until):
        raise AccountOwnerAssignmentCorruption("participant validity exceeds its sources")
    try:
        validate_single_owner_participants(
            policy=policy,
            claimant=claimant,
            approver=approver,
            as_of=cutoff,
        )
    except (TypeError, ValueError) as error:
        raise AccountOwnerAssignmentCorruption(
            "participants roles or policy are corrupt"
        ) from error
    if (
        authority.actor_id != claimant.actor_id
        or authority.actor_id != approver.actor_id
        or authority.user_id != claimant.user_id
        or authority.user_id != approver.user_id
        or authority.is_staff is not claimant.is_staff
        or authority.is_staff is not approver.is_staff
    ):
        raise AccountOwnerAssignmentCorruption("participants authority actor substitution")
    return participants


def _server_actor(actor: AccountOwnerAssignmentActor) -> AccountOwnerAssignmentServerActor:
    return AccountOwnerAssignmentServerActor(
        actor_id=actor.actor_id,
        user_id=actor.user_id,
        role=actor.role,
        kind=actor.kind,
        is_staff=actor.is_staff,
    )


def _same_inputs(first: _IssuanceInputs, final: _IssuanceInputs) -> bool:
    """Compare source facts while allowing the reader's observation instant to advance."""

    return (
        first.binding == final.binding
        and first.root == final.root
        and first.participants.policy == final.participants.policy
        and first.participants.authority == final.participants.authority
        and first.participants.claimant == final.participants.claimant
        and first.participants.approver == final.participants.approver
        and first.participants.valid_until == final.participants.valid_until
    )


__all__ = [
    "AccountOwnerAssignmentProvenanceReceiptV4Repository",
    "CurrentSingleOwnerParticipantsReader",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV4",
    "GetCurrentAccountOwnerAssignmentProvenanceReceiptV4Command",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV4",
    "GetExactAccountOwnerAssignmentProvenanceReceiptV4Command",
    "IssueAccountOwnerAssignmentProvenanceReceiptV4",
    "IssueAccountOwnerAssignmentProvenanceReceiptV4Command",
    "PersistedAccountOwnerAssignmentProvenanceReceiptV4",
]
