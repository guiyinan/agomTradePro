"""ID/hash-only issuance and permanent reads for durable creation bindings v2."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_creation_consumption import (
    CanonicalAccountCreationConsumptionClaim,
    resolve_canonical_account_creation_consumption_claim_identity,
)


class CanonicalAccountCreationBindingV2Unavailable(RuntimeError):
    """One exact live issuance input is unavailable."""


class CanonicalAccountCreationBindingV2Conflict(RuntimeError):
    """A durable identity or one-time mapping anchor has another winner."""


class CanonicalAccountCreationBindingV2Corruption(RuntimeError):
    """A trusted provider or repository substituted malformed evidence."""


def _token(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime:
        raise TypeError(f"{name} must be an exact datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _repository_time(value: object, name: str) -> datetime:
    try:
        return _aware(value, name)
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption(f"{name} is invalid") from error


@dataclass(frozen=True, slots=True)
class BindCanonicalAccountCreationV2Command:
    """Exact immutable selectors without actors, clocks, or nested evidence."""

    binding_id: str
    binding_version: str
    allocation_id: str
    allocation_version: str
    expected_allocation_content_hash: str
    creation_root_observation_id: str
    creation_root_observation_version: str
    expected_creation_root_content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "binding_version",
            "allocation_id",
            "allocation_version",
            "creation_root_observation_id",
            "creation_root_observation_version",
        ):
            _token(getattr(self, name), name)
        _digest(self.expected_allocation_content_hash, "expected_allocation_content_hash")
        _digest(self.expected_creation_root_content_hash, "expected_creation_root_content_hash")


@dataclass(frozen=True, slots=True)
class PersistedCanonicalAccountCreationBindingV2:
    """One repository-restored atomic Binding-v2 and consumption-claim pair."""

    binding: CanonicalAccountCreationBindingV2
    claim: CanonicalAccountCreationConsumptionClaim

    def __post_init__(self) -> None:
        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
        self.binding.__post_init__()
        if type(self.claim) is not CanonicalAccountCreationConsumptionClaim:
            raise TypeError("claim must be an exact CanonicalAccountCreationConsumptionClaim")
        self.claim.__post_init__()
        if self.claim.consumer_generation != "v2" or self.claim.consumer != self.binding:
            raise ValueError("consumption claim does not bind the exact Binding-v2")


@dataclass(frozen=True, slots=True)
class GetExactCanonicalAccountCreationBindingV2Command:
    """Permanent PIT selector using recording knowledge time only."""

    binding_id: str
    binding_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.binding_id, "binding_id")
        _token(self.binding_version, "binding_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


class ExactCurrentUnconsumedAllocationProvider(Protocol):
    def get_current_unconsumed_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None: ...


class ExactFinalAllocatedPhysicalAccountRowObservationV3Provider(Protocol):
    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None: ...


class CanonicalAccountCreationBindingV2Repository(Protocol):
    def atomic(self) -> AbstractContextManager[None]: ...
    def now(self) -> datetime: ...
    def get_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> PersistedCanonicalAccountCreationBindingV2 | None: ...
    def get_consumption_claim_by_any_anchor(
        self,
        *,
        claim_id: str,
        claim_version: str,
        allocation_identity_hash: str,
        allocation_content_hash: str,
        consumer_identity_hash: str,
        consumer_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_v2_content_hash: str,
        physical_v3_root_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationConsumptionClaim | None: ...
    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None: ...
    def append_with_consumption_claim(
        self,
        binding: CanonicalAccountCreationBindingV2,
        claim: CanonicalAccountCreationConsumptionClaim,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_creation_root_content_hash: str,
        expected_consumption_claim_content_hash: str,
        recorded_at: datetime,
    ) -> tuple[
        CanonicalAccountCreationBindingV2,
        CanonicalAccountCreationConsumptionClaim,
    ]: ...


class BindCanonicalAccountCreationV2:
    """Atomically issue one durable mapping and its allocation-consumption claim."""

    def __init__(
        self,
        *,
        allocation_provider: ExactCurrentUnconsumedAllocationProvider,
        creation_root_provider: ExactFinalAllocatedPhysicalAccountRowObservationV3Provider,
        repository: CanonicalAccountCreationBindingV2Repository,
        binder: CanonicalAccountCreationServiceRecorder,
    ) -> None:
        if type(binder) is not CanonicalAccountCreationServiceRecorder:
            raise TypeError("binder must be exact CanonicalAccountCreationServiceRecorder")
        binder.__post_init__()
        if binder.role != "canonical_account_creation_binder":
            raise ValueError("binder role is invalid")
        self._allocation_provider = allocation_provider
        self._creation_root_provider = creation_root_provider
        self._repository = repository
        self._binder = binder

    def execute(
        self, command: BindCanonicalAccountCreationV2Command
    ) -> CanonicalAccountCreationBindingV2:
        """Append or replay one exact durable Binding-v2/claim first-winner pair."""
        if type(command) is not BindCanonicalAccountCreationV2Command:
            raise TypeError("command must be exact BindCanonicalAccountCreationV2Command")
        command.__post_init__()
        cutoff = _repository_time(self._repository.now(), "repository cutoff")
        winner = self._repository.get_winner(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            as_of=cutoff,
        )
        if winner is not None:
            return self._validate_replay(winner, command, as_of=cutoff)
        first = self._read(command, cutoff)
        with self._repository.atomic():
            recorded_at = _repository_time(self._repository.now(), "repository recorded_at")
            if recorded_at < cutoff:
                raise CanonicalAccountCreationBindingV2Corruption(
                    "repository clock moved backwards"
                )
            winner = self._repository.get_winner(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                as_of=recorded_at,
            )
            if winner is not None:
                return self._validate_replay(winner, command, as_of=recorded_at)
            final = self._read(command, recorded_at)
            if first != final:
                raise CanonicalAccountCreationBindingV2Conflict("issuance inputs changed")
            allocation, root = final
            candidate = self._build(command, allocation, root, recorded_at=recorded_at)
            claim = self._build_claim(candidate)
            anchor = self._repository.get_consumption_claim_by_any_anchor(
                claim_id=claim.claim_id,
                claim_version=claim.claim_version,
                allocation_identity_hash=allocation.identity_hash,
                allocation_content_hash=allocation.content_hash,
                consumer_identity_hash=candidate.identity_hash,
                consumer_content_hash=candidate.content_hash,
                account_namespace=claim.account_namespace,
                account_id=claim.account_id,
                underlying_unified_account_namespace=(claim.underlying_unified_account_namespace),
                underlying_unified_account_id=claim.underlying_unified_account_id,
                physical_v2_content_hash=claim.physical_v2_content_hash,
                physical_v3_root_content_hash=root.content_hash,
                as_of=recorded_at,
            )
            if anchor is not None:
                _claim(anchor)
                raise CanonicalAccountCreationBindingV2Conflict(
                    "canonical creation consumption anchor is already claimed"
                )
            persisted = self._repository.append_with_consumption_claim(
                candidate,
                claim,
                expected_allocation_content_hash=allocation.content_hash,
                expected_account_claim_hash=candidate.account_claim_hash,
                expected_underlying_claim_hash=candidate.underlying_claim_hash,
                expected_creation_root_content_hash=root.content_hash,
                expected_consumption_claim_content_hash=claim.content_hash,
                recorded_at=recorded_at,
            )
            checked_binding, checked_claim = _persisted_tuple(persisted)
            if checked_binding != candidate or checked_claim != claim:
                raise CanonicalAccountCreationBindingV2Conflict(
                    "Binding-v2/consumption-claim append winner differs"
                )
            return checked_binding

    def _validate_replay(
        self,
        winner: PersistedCanonicalAccountCreationBindingV2,
        command: BindCanonicalAccountCreationV2Command,
        *,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2:
        persisted = _persisted(winner)
        checked = persisted.binding
        claim = persisted.claim
        allocation = checked.allocation
        root = checked.creation_root
        expected_claim_id, expected_claim_version = (
            resolve_canonical_account_creation_consumption_claim_identity(
                allocation,
                consumer_generation="v2",
            )
        )
        if checked.recorded_at > as_of or claim.recorded_at > as_of:
            raise CanonicalAccountCreationBindingV2Corruption(
                "repository returned a future Binding-v2/claim winner"
            )
        if (
            checked.binding_id != command.binding_id
            or checked.binding_version != command.binding_version
            or claim.claim_id != expected_claim_id
            or claim.claim_version != expected_claim_version
            or allocation.allocation_id != command.allocation_id
            or allocation.allocation_version != command.allocation_version
            or allocation.content_hash != command.expected_allocation_content_hash
            or root.observation_id != command.creation_root_observation_id
            or root.observation_version != command.creation_root_observation_version
            or root.content_hash != command.expected_creation_root_content_hash
            or checked.recorded_by != self._binder
            or claim.consumer_generation != "v2"
            or claim.consumer != checked
            or claim.allocation != allocation
            or claim.account_namespace != checked.account_namespace_claim
            or claim.account_id != checked.account_id_claim
            or claim.underlying_unified_account_namespace
            != checked.underlying_unified_account_namespace_claim
            or claim.underlying_unified_account_id != checked.underlying_unified_account_id_claim
            or claim.physical_v2_content_hash != checked.physical_observation_content_hash
            or claim.physical_v3_root_content_hash != root.content_hash
            or claim.recorded_at != checked.recorded_at
        ):
            raise CanonicalAccountCreationBindingV2Conflict(
                "Binding-v2/consumption-claim identity winner differs"
            )
        return checked

    def _read(
        self, command: BindCanonicalAccountCreationV2Command, cutoff: datetime
    ) -> tuple[CanonicalAccountCreationAllocation, AllocatedPhysicalAccountRowObservationV3]:
        allocation = _allocation(
            self._allocation_provider.get_current_unconsumed_allocation(
                allocation_id=command.allocation_id,
                allocation_version=command.allocation_version,
                expected_content_hash=command.expected_allocation_content_hash,
                as_of=cutoff,
            )
        )
        root = _root(
            self._creation_root_provider.get_exact_final(
                observation_id=command.creation_root_observation_id,
                observation_version=command.creation_root_observation_version,
                expected_content_hash=command.expected_creation_root_content_hash,
                as_of=cutoff,
            )
        )
        if (
            allocation.allocation_id != command.allocation_id
            or allocation.allocation_version != command.allocation_version
            or allocation.content_hash != command.expected_allocation_content_hash
        ):
            raise CanonicalAccountCreationBindingV2Corruption("allocation selector substitution")
        if (
            root.observation_id != command.creation_root_observation_id
            or root.observation_version != command.creation_root_observation_version
            or root.content_hash != command.expected_creation_root_content_hash
        ):
            raise CanonicalAccountCreationBindingV2Corruption("creation root selector substitution")
        if allocation != root.allocation:
            raise CanonicalAccountCreationBindingV2Corruption(
                "creation root allocation substitution"
            )
        return allocation, root

    def _build(
        self,
        command: BindCanonicalAccountCreationV2Command,
        allocation: CanonicalAccountCreationAllocation,
        root: AllocatedPhysicalAccountRowObservationV3,
        *,
        recorded_at: datetime,
    ) -> CanonicalAccountCreationBindingV2:
        physical = root.physical_observation
        try:
            return CanonicalAccountCreationBindingV2(
                command.binding_id,
                command.binding_version,
                allocation,
                root,
                physical.account_namespace,
                physical.account_id,
                physical.underlying_unified_account_namespace,
                physical.underlying_unified_account_id,
                root.identity_hash,
                root.content_hash,
                physical.content_hash,
                physical.source_content_hash,
                physical.raw_observation_content_hash,
                self._binder,
                recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise CanonicalAccountCreationBindingV2Corruption(
                "durable binding candidate is invalid"
            ) from error

    def _build_claim(
        self,
        binding: CanonicalAccountCreationBindingV2,
    ) -> CanonicalAccountCreationConsumptionClaim:
        physical = binding.creation_root.physical_observation
        claim_id, claim_version = resolve_canonical_account_creation_consumption_claim_identity(
            binding.allocation,
            consumer_generation="v2",
        )
        try:
            return CanonicalAccountCreationConsumptionClaim(
                claim_id=claim_id,
                claim_version=claim_version,
                allocation=binding.allocation,
                consumer_generation="v2",
                consumer=binding,
                account_namespace=binding.account_namespace_claim,
                account_id=binding.account_id_claim,
                underlying_unified_account_namespace=(
                    binding.underlying_unified_account_namespace_claim
                ),
                underlying_unified_account_id=(binding.underlying_unified_account_id_claim),
                physical_v2_content_hash=physical.content_hash,
                physical_v3_root_content_hash=binding.creation_root.content_hash,
                recorded_at=binding.recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise CanonicalAccountCreationBindingV2Corruption(
                "consumption claim candidate is invalid"
            ) from error


class GetExactCanonicalAccountCreationBindingV2:
    """Read permanent exact evidence by recorded knowledge time, never TTL currentness."""

    def __init__(self, repository: CanonicalAccountCreationBindingV2Repository) -> None:
        self._repository = repository

    def execute(
        self, command: GetExactCanonicalAccountCreationBindingV2Command
    ) -> CanonicalAccountCreationBindingV2 | None:
        if type(command) is not GetExactCanonicalAccountCreationBindingV2Command:
            raise TypeError(
                "command must be exact GetExactCanonicalAccountCreationBindingV2Command"
            )
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        checked = _binding(value)
        if (
            checked.binding_id != command.binding_id
            or checked.binding_version != command.binding_version
            or checked.content_hash != command.expected_content_hash
        ):
            raise CanonicalAccountCreationBindingV2Corruption("exact binding selector substitution")
        return checked if checked.recorded_at <= command.as_of else None


def _allocation(value: object) -> CanonicalAccountCreationAllocation:
    if value is None:
        raise CanonicalAccountCreationBindingV2Unavailable("allocation is unavailable")
    if type(value) is not CanonicalAccountCreationAllocation:
        raise CanonicalAccountCreationBindingV2Corruption("allocation type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("allocation is corrupt") from error
    return value


def _root(value: object) -> AllocatedPhysicalAccountRowObservationV3:
    if value is None:
        raise CanonicalAccountCreationBindingV2Unavailable("creation root is unavailable")
    if type(value) is not AllocatedPhysicalAccountRowObservationV3:
        raise CanonicalAccountCreationBindingV2Corruption("creation root type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("creation root is corrupt") from error
    return value


def _binding(value: object) -> CanonicalAccountCreationBindingV2:
    if type(value) is not CanonicalAccountCreationBindingV2:
        raise CanonicalAccountCreationBindingV2Corruption("binding type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("binding is corrupt") from error
    return value


def _claim(value: object) -> CanonicalAccountCreationConsumptionClaim:
    if type(value) is not CanonicalAccountCreationConsumptionClaim:
        raise CanonicalAccountCreationBindingV2Corruption("claim type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("claim is corrupt") from error
    return value


def _persisted(value: object) -> PersistedCanonicalAccountCreationBindingV2:
    if type(value) is not PersistedCanonicalAccountCreationBindingV2:
        raise CanonicalAccountCreationBindingV2Corruption("winner pair type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("winner pair is corrupt") from error
    return value


def _persisted_tuple(
    value: object,
) -> tuple[CanonicalAccountCreationBindingV2, CanonicalAccountCreationConsumptionClaim]:
    if type(value) is not tuple or len(value) != 2:
        raise CanonicalAccountCreationBindingV2Corruption("append pair type substitution")
    binding = _binding(value[0])
    claim = _claim(value[1])
    try:
        PersistedCanonicalAccountCreationBindingV2(binding, claim)
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationBindingV2Corruption("append pair is corrupt") from error
    return binding, claim


__all__ = [
    "BindCanonicalAccountCreationV2",
    "BindCanonicalAccountCreationV2Command",
    "CanonicalAccountCreationBindingV2Conflict",
    "CanonicalAccountCreationBindingV2Corruption",
    "CanonicalAccountCreationBindingV2Repository",
    "CanonicalAccountCreationBindingV2Unavailable",
    "ExactCurrentUnconsumedAllocationProvider",
    "ExactFinalAllocatedPhysicalAccountRowObservationV3Provider",
    "GetExactCanonicalAccountCreationBindingV2",
    "GetExactCanonicalAccountCreationBindingV2Command",
    "PersistedCanonicalAccountCreationBindingV2",
]
