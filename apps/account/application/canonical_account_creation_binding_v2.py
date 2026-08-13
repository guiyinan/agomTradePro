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


class CanonicalAccountCreationBindingV2Unavailable(RuntimeError):
    """One exact live issuance input is unavailable."""


class CanonicalAccountCreationBindingV2Conflict(RuntimeError):
    """A durable identity or one-time mapping anchor has another winner."""


class CanonicalAccountCreationBindingV2Corruption(RuntimeError):
    """A trusted provider or repository substituted malformed evidence."""


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


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
    ) -> CanonicalAccountCreationBindingV2 | None: ...
    def get_by_any_anchor(
        self,
        *,
        allocation_content_hash: str,
        account_claim_hash: str,
        underlying_claim_hash: str,
        creation_root_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None: ...
    def get_exact_by_hash(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBindingV2 | None: ...
    def append(
        self,
        binding: CanonicalAccountCreationBindingV2,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_creation_root_content_hash: str,
        recorded_at: datetime,
    ) -> CanonicalAccountCreationBindingV2: ...


class BindCanonicalAccountCreationV2:
    """Issue one durable mapping after same-cutoff allocation/root double reads."""

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
        """Append or replay one exact four-anchor durable first winner."""
        if type(command) is not BindCanonicalAccountCreationV2Command:
            raise TypeError("command must be exact BindCanonicalAccountCreationV2Command")
        command.__post_init__()
        cutoff = _aware(self._repository.now(), "repository cutoff")
        winner = self._repository.get_winner(
            binding_id=command.binding_id,
            binding_version=command.binding_version,
            as_of=cutoff,
        )
        if winner is not None:
            return self._validate_replay(winner, command)
        first = self._read(command, cutoff)
        with self._repository.atomic():
            winner = self._repository.get_winner(
                binding_id=command.binding_id, binding_version=command.binding_version, as_of=cutoff
            )
            if winner is not None:
                return self._validate_replay(winner, command)
            final = self._read(command, cutoff)
            if first != final:
                raise CanonicalAccountCreationBindingV2Conflict("issuance inputs changed")
            allocation, root = final
            candidate = self._build(command, allocation, root, recorded_at=cutoff)
            anchor = self._repository.get_by_any_anchor(
                allocation_content_hash=allocation.content_hash,
                account_claim_hash=candidate.account_claim_hash,
                underlying_claim_hash=candidate.underlying_claim_hash,
                creation_root_content_hash=root.content_hash,
                as_of=cutoff,
            )
            if anchor is not None:
                raise CanonicalAccountCreationBindingV2Conflict(
                    "durable mapping anchor is consumed"
                )
            persisted = self._repository.append(
                candidate,
                expected_allocation_content_hash=allocation.content_hash,
                expected_account_claim_hash=candidate.account_claim_hash,
                expected_underlying_claim_hash=candidate.underlying_claim_hash,
                expected_creation_root_content_hash=root.content_hash,
                recorded_at=cutoff,
            )
            checked = _binding(persisted)
            if checked != candidate:
                raise CanonicalAccountCreationBindingV2Conflict("binding append winner differs")
            return checked

    def _validate_replay(
        self,
        winner: CanonicalAccountCreationBindingV2,
        command: BindCanonicalAccountCreationV2Command,
    ) -> CanonicalAccountCreationBindingV2:
        checked = _binding(winner)
        allocation = checked.allocation
        root = checked.creation_root
        if (
            checked.binding_id != command.binding_id
            or checked.binding_version != command.binding_version
            or allocation.allocation_id != command.allocation_id
            or allocation.allocation_version != command.allocation_version
            or allocation.content_hash != command.expected_allocation_content_hash
            or root.observation_id != command.creation_root_observation_id
            or root.observation_version != command.creation_root_observation_version
            or root.content_hash != command.expected_creation_root_content_hash
            or checked.recorded_by != self._binder
        ):
            raise CanonicalAccountCreationBindingV2Conflict("binding identity winner differs")
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
    value.__post_init__()
    return value


def _root(value: object) -> AllocatedPhysicalAccountRowObservationV3:
    if value is None:
        raise CanonicalAccountCreationBindingV2Unavailable("creation root is unavailable")
    if type(value) is not AllocatedPhysicalAccountRowObservationV3:
        raise CanonicalAccountCreationBindingV2Corruption("creation root type substitution")
    value.__post_init__()
    return value


def _binding(value: object) -> CanonicalAccountCreationBindingV2:
    if type(value) is not CanonicalAccountCreationBindingV2:
        raise CanonicalAccountCreationBindingV2Corruption("binding type substitution")
    value.__post_init__()
    return value


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
]
