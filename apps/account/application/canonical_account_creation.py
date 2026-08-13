"""ID-only workflows for canonical Account allocation and first-row binding."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
    CanonicalAccountCreationBinding,
    CanonicalAccountCreationRequester,
    CanonicalAccountCreationServiceRecorder,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)


class CanonicalAccountCreationUnavailable(RuntimeError):
    """A required exact owner artifact is absent or no longer usable."""


class CanonicalAccountCreationConflict(RuntimeError):
    """A first-winner, idempotency, or one-time binding anchor conflicts."""


class CanonicalAccountCreationCorruption(RuntimeError):
    """A trusted dependency substituted malformed or mismatched evidence."""


def _token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _digest(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalAccountCreationCorruption(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True, slots=True)
class AllocateCanonicalAccountCreationCommand:
    """Caller selector without an Account ID, user identity, or clock."""

    allocation_id: str
    allocation_version: str
    request_fingerprint_hash: str
    requested_raw_account_type: str

    def __post_init__(self) -> None:
        for field_name in (
            "allocation_id",
            "allocation_version",
            "requested_raw_account_type",
        ):
            _token(getattr(self, field_name), field_name)
        _digest(self.request_fingerprint_hash, "request_fingerprint_hash")


@dataclass(frozen=True, slots=True)
class BindCanonicalAccountCreationCommand:
    """Bind exact allocation and Physical-v2 identities without row facts."""

    binding_id: str
    binding_version: str
    allocation_id: str
    allocation_version: str
    expected_allocation_content_hash: str
    physical_observation_id: str
    physical_observation_version: str
    expected_physical_content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "binding_id",
            "binding_version",
            "allocation_id",
            "allocation_version",
            "physical_observation_id",
            "physical_observation_version",
        ):
            _token(getattr(self, field_name), field_name)
        _digest(
            self.expected_allocation_content_hash,
            "expected_allocation_content_hash",
        )
        _digest(self.expected_physical_content_hash, "expected_physical_content_hash")


class CanonicalAccountIdGenerator(Protocol):
    """Generate an opaque Account-owned canonical identity."""

    def generate(self) -> str: ...


class ExactFinalPhysicalAccountRowObservationV2Provider(Protocol):
    """Read an exact final Physical-v2 root, including pre-binding evidence."""

    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None: ...


class CanonicalAccountCreationRepository(Protocol):
    """Persist allocations and one-time bindings with all uniqueness anchors."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_allocation_winner(
        self, *, allocation_id: str, allocation_version: str, as_of: datetime
    ) -> CanonicalAccountCreationAllocation | None: ...

    def get_allocation_by_request(
        self,
        *,
        requester_actor_id: str,
        requester_user_id: int,
        request_fingerprint_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None: ...

    def get_exact_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None: ...

    def get_current_unconsumed_allocation(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None: ...

    def append_allocation(
        self, allocation: CanonicalAccountCreationAllocation, *, recorded_at: datetime
    ) -> CanonicalAccountCreationAllocation: ...

    def get_binding_winner(
        self, *, binding_id: str, binding_version: str, as_of: datetime
    ) -> CanonicalAccountCreationBinding | None: ...

    def get_binding_by_any_anchor(
        self,
        *,
        allocation_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBinding | None: ...

    def get_exact_binding(
        self,
        *,
        binding_id: str,
        binding_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationBinding | None: ...

    def append_binding(
        self,
        binding: CanonicalAccountCreationBinding,
        *,
        expected_allocation_content_hash: str,
        expected_account_claim_hash: str,
        expected_underlying_claim_hash: str,
        expected_physical_content_hash: str,
        recorded_at: datetime,
    ) -> CanonicalAccountCreationBinding: ...


class AllocateCanonicalAccountCreation:
    """Allocate an opaque Account ID using server identity, clock, and generator."""

    def __init__(
        self,
        *,
        repository: CanonicalAccountCreationRepository,
        requester: CanonicalAccountCreationRequester,
        account_id_generator: CanonicalAccountIdGenerator,
        allocator: CanonicalAccountCreationServiceRecorder,
        validity_period: timedelta,
    ) -> None:
        if type(requester) is not CanonicalAccountCreationRequester:
            raise TypeError("requester must be exact CanonicalAccountCreationRequester")
        requester.__post_init__()
        if type(allocator) is not CanonicalAccountCreationServiceRecorder:
            raise TypeError("allocator must be exact CanonicalAccountCreationServiceRecorder")
        allocator.__post_init__()
        if allocator.role != "canonical_account_identity_allocator":
            raise ValueError("allocator service role is invalid")
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be a positive timedelta")
        self._repository = repository
        self._requester = requester
        self._account_id_generator = account_id_generator
        self._allocator = allocator
        self._validity_period = validity_period

    def execute(
        self, command: AllocateCanonicalAccountCreationCommand
    ) -> CanonicalAccountCreationAllocation:
        """Return the request first-winner without accepting a caller Account ID."""

        if type(command) is not AllocateCanonicalAccountCreationCommand:
            raise TypeError("command must be exact AllocateCanonicalAccountCreationCommand")
        command.__post_init__()
        cutoff = _aware(self._repository.now(), "repository cutoff")
        with self._repository.atomic():
            request_winner = self._repository.get_allocation_by_request(
                requester_actor_id=self._requester.actor_id,
                requester_user_id=self._requester.user_id,
                request_fingerprint_hash=command.request_fingerprint_hash,
                as_of=cutoff,
            )
            if request_winner is not None:
                return self._validate_request_replay(request_winner, command)
            identity_winner = self._repository.get_allocation_winner(
                allocation_id=command.allocation_id,
                allocation_version=command.allocation_version,
                as_of=cutoff,
            )
            if identity_winner is not None:
                raise CanonicalAccountCreationConflict("allocation identity is already claimed")
            canonical_account_id = self._account_id_generator.generate()
            _token(canonical_account_id, "generated canonical_account_id")
            candidate = CanonicalAccountCreationAllocation(
                allocation_id=command.allocation_id,
                allocation_version=command.allocation_version,
                canonical_account_namespace="account",
                canonical_account_id=canonical_account_id,
                requested_row_user_id=self._requester.user_id,
                requested_raw_account_type=command.requested_raw_account_type,
                intended_underlying_unified_account_namespace="simulated-account-row",
                request_fingerprint_hash=command.request_fingerprint_hash,
                requested_by=self._requester,
                allocated_at=cutoff,
                valid_until=cutoff + self._validity_period,
                recorded_by=self._allocator,
            )
            persisted = self._repository.append_allocation(candidate, recorded_at=cutoff)
            checked = _allocation(persisted)
            if checked == candidate:
                return checked
            return self._validate_request_replay(checked, command)

    def _validate_request_replay(
        self,
        value: object,
        command: AllocateCanonicalAccountCreationCommand,
    ) -> CanonicalAccountCreationAllocation:
        checked = _allocation(value)
        if (
            checked.requested_by != self._requester
            or checked.request_fingerprint_hash != command.request_fingerprint_hash
            or checked.requested_raw_account_type != command.requested_raw_account_type
        ):
            raise CanonicalAccountCreationConflict("allocation request first-winner differs")
        return checked


class BindCanonicalAccountCreation:
    """Atomically consume an exact allocation with one exact Physical-v2 root."""

    def __init__(
        self,
        *,
        repository: CanonicalAccountCreationRepository,
        physical_provider: ExactFinalPhysicalAccountRowObservationV2Provider,
        binder: CanonicalAccountCreationServiceRecorder,
    ) -> None:
        if type(binder) is not CanonicalAccountCreationServiceRecorder:
            raise TypeError("binder must be exact CanonicalAccountCreationServiceRecorder")
        binder.__post_init__()
        if binder.role != "canonical_account_creation_binder":
            raise ValueError("binder service role is invalid")
        self._repository = repository
        self._physical_provider = physical_provider
        self._binder = binder

    def execute(
        self, command: BindCanonicalAccountCreationCommand
    ) -> CanonicalAccountCreationBinding:
        """Bind first-winner anchors after same-cutoff exact source double reads."""

        if type(command) is not BindCanonicalAccountCreationCommand:
            raise TypeError("command must be exact BindCanonicalAccountCreationCommand")
        command.__post_init__()
        cutoff = _aware(self._repository.now(), "repository cutoff")
        first_allocation = self._read_allocation(command, cutoff)
        first_physical = self._read_physical(command, cutoff)
        with self._repository.atomic():
            winner = self._repository.get_binding_winner(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                as_of=cutoff,
            )
            if winner is not None:
                return self._validate_binding_replay(winner, command)
            anchor = self._repository.get_binding_by_any_anchor(
                allocation_content_hash=command.expected_allocation_content_hash,
                account_namespace=first_allocation.canonical_account_namespace,
                account_id=first_allocation.canonical_account_id,
                underlying_unified_account_namespace=(
                    first_physical.underlying_unified_account_namespace
                ),
                underlying_unified_account_id=(first_physical.underlying_unified_account_id),
                physical_content_hash=command.expected_physical_content_hash,
                as_of=cutoff,
            )
            if anchor is not None:
                raise CanonicalAccountCreationConflict("creation binding anchor is consumed")
            final_allocation = self._read_allocation(command, cutoff)
            final_physical = self._read_physical(command, cutoff)
            if final_allocation != first_allocation or final_physical != first_physical:
                raise CanonicalAccountCreationConflict("creation binding source drifted")
            recorded_at = _aware(self._repository.now(), "binding recorded_at")
            candidate = CanonicalAccountCreationBinding(
                binding_id=command.binding_id,
                binding_version=command.binding_version,
                allocation=final_allocation,
                physical_observation=final_physical,
                account_namespace_claim=final_allocation.canonical_account_namespace,
                account_id_claim=final_allocation.canonical_account_id,
                underlying_unified_account_namespace_claim=(
                    final_physical.underlying_unified_account_namespace
                ),
                underlying_unified_account_id_claim=(final_physical.underlying_unified_account_id),
                recorded_by=self._binder,
                recorded_at=recorded_at,
                valid_until=min(final_allocation.valid_until, final_physical.valid_until),
            )
            persisted = self._repository.append_binding(
                candidate,
                expected_allocation_content_hash=final_allocation.content_hash,
                expected_account_claim_hash=candidate.account_claim_hash,
                expected_underlying_claim_hash=candidate.underlying_claim_hash,
                expected_physical_content_hash=final_physical.content_hash,
                recorded_at=recorded_at,
            )
            checked = _binding(persisted)
            if checked != candidate:
                raise CanonicalAccountCreationConflict("binding append first-winner differs")
            return checked

    def _read_allocation(
        self, command: BindCanonicalAccountCreationCommand, cutoff: datetime
    ) -> CanonicalAccountCreationAllocation:
        value = self._repository.get_current_unconsumed_allocation(
            allocation_id=command.allocation_id,
            allocation_version=command.allocation_version,
            expected_content_hash=command.expected_allocation_content_hash,
            as_of=cutoff,
        )
        if value is None:
            raise CanonicalAccountCreationUnavailable("allocation is not current-unconsumed")
        checked = _allocation(value)
        if (
            checked.allocation_id != command.allocation_id
            or checked.allocation_version != command.allocation_version
            or checked.content_hash != command.expected_allocation_content_hash
        ):
            raise CanonicalAccountCreationCorruption("allocation selector substitution")
        return checked

    def _read_physical(
        self, command: BindCanonicalAccountCreationCommand, cutoff: datetime
    ) -> PhysicalAccountRowObservationV2:
        value = self._physical_provider.get_exact_final(
            observation_id=command.physical_observation_id,
            observation_version=command.physical_observation_version,
            expected_content_hash=command.expected_physical_content_hash,
            as_of=cutoff,
        )
        if value is None:
            raise CanonicalAccountCreationUnavailable("Physical-v2 root is unavailable")
        checked = _physical(value)
        if (
            checked.observation_id != command.physical_observation_id
            or checked.observation_version != command.physical_observation_version
            or checked.content_hash != command.expected_physical_content_hash
        ):
            raise CanonicalAccountCreationCorruption("Physical-v2 selector substitution")
        return checked

    def _validate_binding_replay(
        self, value: object, command: BindCanonicalAccountCreationCommand
    ) -> CanonicalAccountCreationBinding:
        checked = _binding(value)
        if (
            checked.binding_id != command.binding_id
            or checked.binding_version != command.binding_version
            or checked.allocation.allocation_id != command.allocation_id
            or checked.allocation.allocation_version != command.allocation_version
            or checked.allocation.content_hash != command.expected_allocation_content_hash
            or checked.physical_observation.observation_id != command.physical_observation_id
            or checked.physical_observation.observation_version
            != command.physical_observation_version
            or checked.physical_observation.content_hash != command.expected_physical_content_hash
        ):
            raise CanonicalAccountCreationConflict("binding identity first-winner differs")
        return checked


def _allocation(value: object) -> CanonicalAccountCreationAllocation:
    if type(value) is not CanonicalAccountCreationAllocation:
        raise CanonicalAccountCreationCorruption("allocation type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationCorruption("allocation is corrupt") from error
    return value


def _physical(value: object) -> PhysicalAccountRowObservationV2:
    if type(value) is not PhysicalAccountRowObservationV2:
        raise CanonicalAccountCreationCorruption("Physical-v2 type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationCorruption("Physical-v2 is corrupt") from error
    return value


def _binding(value: object) -> CanonicalAccountCreationBinding:
    if type(value) is not CanonicalAccountCreationBinding:
        raise CanonicalAccountCreationCorruption("binding type substitution")
    try:
        value.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountCreationCorruption("binding is corrupt") from error
    return value


__all__ = [
    "AllocateCanonicalAccountCreation",
    "AllocateCanonicalAccountCreationCommand",
    "BindCanonicalAccountCreation",
    "BindCanonicalAccountCreationCommand",
    "CanonicalAccountCreationConflict",
    "CanonicalAccountCreationCorruption",
    "CanonicalAccountCreationRepository",
    "CanonicalAccountCreationUnavailable",
    "CanonicalAccountIdGenerator",
    "ExactFinalPhysicalAccountRowObservationV2Provider",
]
