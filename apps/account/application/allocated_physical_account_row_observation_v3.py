"""ID/hash-only creation-root workflows for allocated Physical-v3 evidence."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationAllocation,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)


class AllocatedPhysicalAccountRowObservationV3Unavailable(RuntimeError):
    """One exact-current creation-root input is unavailable."""


class AllocatedPhysicalAccountRowObservationV3Conflict(RuntimeError):
    """A first winner, head, or root CAS differs."""


class AllocatedPhysicalAccountRowObservationV3Corruption(RuntimeError):
    """A trusted provider or repository substituted evidence."""


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
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            f"{field_name} must be timezone-aware"
        )
    return value


@dataclass(frozen=True, slots=True)
class CaptureAllocatedPhysicalAccountRowObservationV3Command:
    """Select exact allocation and Physical-v2 inputs without row facts."""

    observation_id: str
    observation_version: str
    allocation_id: str
    allocation_version: str
    expected_allocation_content_hash: str
    physical_observation_id: str
    physical_observation_version: str
    expected_physical_content_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "observation_id",
            "observation_version",
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


@dataclass(frozen=True, slots=True)
class GetExactAllocatedPhysicalAccountRowObservationV3Command:
    """Exact identity/hash historical PIT selector."""

    observation_id: str
    observation_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.observation_id, "observation_id")
        _token(self.observation_version, "observation_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class GetCurrentAllocatedPhysicalAccountRowObservationV3Command:
    """ID/hash-only selector for one exact creation-root logical head."""

    observation_id: str
    observation_version: str
    expected_content_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        _token(self.observation_id, "observation_id")
        _token(self.observation_version, "observation_version")
        _digest(self.expected_content_hash, "expected_content_hash")
        _aware(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class AllocatedPhysicalAccountRowObservationV3Recorder:
    """Fixed automated service projecting one allocation-anchored creation root."""

    service_id: str
    role: str = "allocated_physical_creation_projector"
    kind: str = "service"
    is_automated: bool = True

    def __post_init__(self) -> None:
        _token(self.service_id, "service_id")
        if (
            self.role,
            self.kind,
            self.is_automated,
        ) != (
            "allocated_physical_creation_projector",
            "service",
            True,
        ):
            raise ValueError("creation-root recorder authority is fixed")


@dataclass(frozen=True, slots=True)
class PersistedAllocatedPhysicalAccountRowObservationV3:
    """Pair one immutable creation root with its server service recorder."""

    observation: AllocatedPhysicalAccountRowObservationV3
    recorded_by: AllocatedPhysicalAccountRowObservationV3Recorder

    def __post_init__(self) -> None:
        if type(self.observation) is not AllocatedPhysicalAccountRowObservationV3:
            raise TypeError("observation must be an exact AllocatedPhysicalAccountRowObservationV3")
        AllocatedPhysicalAccountRowObservationV3.__post_init__(self.observation)
        if type(self.recorded_by) is not AllocatedPhysicalAccountRowObservationV3Recorder:
            raise TypeError(
                "recorded_by must be an exact AllocatedPhysicalAccountRowObservationV3Recorder"
            )
        self.recorded_by.__post_init__()


class ExactCurrentUnconsumedCanonicalAllocationProvider(Protocol):
    """Load one exact-current allocation not yet consumed by a durable binding."""

    def get_exact_current_unconsumed(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None: ...


class ExactFinalPhysicalAccountRowObservationV2Provider(Protocol):
    """Load one exact-final Physical-v2 creation root."""

    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None: ...


class AllocatedPhysicalAccountRowObservationV3Repository(Protocol):
    """Store creation roots under first-winner, head, and root-CAS semantics."""

    def atomic(self) -> AbstractContextManager[None]: ...

    def now(self) -> datetime: ...

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None: ...

    def get_current_head(
        self,
        *,
        allocation_content_hash: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        physical_content_hash: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None: ...

    def append(
        self,
        record: PersistedAllocatedPhysicalAccountRowObservationV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3: ...

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None: ...


class CaptureAllocatedPhysicalAccountRowObservationV3:
    """Create or replay one exact allocation-anchored Physical-v3 root."""

    def __init__(
        self,
        *,
        allocation_provider: ExactCurrentUnconsumedCanonicalAllocationProvider,
        physical_provider: ExactFinalPhysicalAccountRowObservationV2Provider,
        repository: AllocatedPhysicalAccountRowObservationV3Repository,
        recorder: AllocatedPhysicalAccountRowObservationV3Recorder,
        validity_period: timedelta,
    ) -> None:
        if type(recorder) is not AllocatedPhysicalAccountRowObservationV3Recorder:
            raise TypeError(
                "recorder must be exact AllocatedPhysicalAccountRowObservationV3Recorder"
            )
        recorder.__post_init__()
        if type(validity_period) is not timedelta or validity_period <= timedelta(0):
            raise ValueError("validity_period must be an exact positive timedelta")
        self._allocation_provider = allocation_provider
        self._physical_provider = physical_provider
        self._repository = repository
        self._recorder = recorder
        self._validity_period = validity_period

    def execute(
        self,
        command: CaptureAllocatedPhysicalAccountRowObservationV3Command,
    ) -> AllocatedPhysicalAccountRowObservationV3:
        """Capture after same-cutoff allocation and Physical-v2 double reads."""

        if type(command) is not CaptureAllocatedPhysicalAccountRowObservationV3Command:
            raise TypeError(
                "command must be an exact CaptureAllocatedPhysicalAccountRowObservationV3Command"
            )
        command.__post_init__()
        cutoff = _aware(self._repository.now(), "repository cutoff")
        winner = self._repository.get_winner(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            as_of=cutoff,
        )
        if winner is not None:
            return self._validate_replay(winner, command, cutoff)
        first_allocation = self._read_allocation(command, cutoff)
        first_physical = self._read_physical(command, cutoff)
        with self._repository.atomic():
            recorded_at = _aware(self._repository.now(), "repository recorded_at")
            if recorded_at < cutoff:
                raise AllocatedPhysicalAccountRowObservationV3Corruption(
                    "repository clock moved backwards"
                )
            winner = self._repository.get_winner(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                as_of=recorded_at,
            )
            if winner is not None:
                return self._validate_replay(winner, command, recorded_at)
            final_allocation = self._read_allocation(command, recorded_at)
            final_physical = self._read_physical(command, recorded_at)
            if final_allocation != first_allocation or final_physical != first_physical:
                raise AllocatedPhysicalAccountRowObservationV3Conflict(
                    "creation-root inputs changed during capture"
                )
            physical = final_physical
            head = self._repository.get_current_head(
                allocation_content_hash=first_allocation.content_hash,
                account_namespace=physical.account_namespace,
                account_id=physical.account_id,
                underlying_unified_account_namespace=(
                    physical.underlying_unified_account_namespace
                ),
                underlying_unified_account_id=physical.underlying_unified_account_id,
                physical_content_hash=physical.content_hash,
                as_of=recorded_at,
            )
            if head is not None:
                raise AllocatedPhysicalAccountRowObservationV3Conflict(
                    "creation-root anchor already has a head"
                )
            ttl_valid_until = cutoff + self._validity_period
            candidate = AllocatedPhysicalAccountRowObservationV3(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                allocation=final_allocation,
                physical_observation=final_physical,
                recorded_at=recorded_at,
                ttl_valid_until=ttl_valid_until,
                valid_until=min(
                    final_allocation.valid_until,
                    final_physical.valid_until,
                    ttl_valid_until,
                ),
            )
            record = PersistedAllocatedPhysicalAccountRowObservationV3(
                observation=candidate,
                recorded_by=self._recorder,
            )
            persisted = self._repository.append(
                record,
                expected_predecessor_hash=None,
                recorded_at=recorded_at,
            )
            checked = _record(persisted)
            if checked != record:
                raise AllocatedPhysicalAccountRowObservationV3Conflict(
                    "concurrent creation-root first winner differs"
                )
            return checked.observation

    def _read_allocation(
        self,
        command: CaptureAllocatedPhysicalAccountRowObservationV3Command,
        cutoff: datetime,
    ) -> CanonicalAccountCreationAllocation:
        value = self._allocation_provider.get_exact_current_unconsumed(
            allocation_id=command.allocation_id,
            allocation_version=command.allocation_version,
            expected_content_hash=command.expected_allocation_content_hash,
            as_of=cutoff,
        )
        if value is None:
            raise AllocatedPhysicalAccountRowObservationV3Unavailable(
                "allocation is not exact-current-unconsumed"
            )
        allocation = _allocation(value)
        if (
            allocation.allocation_id != command.allocation_id
            or allocation.allocation_version != command.allocation_version
            or allocation.content_hash != command.expected_allocation_content_hash
            or not allocation.allocated_at <= cutoff < allocation.valid_until
        ):
            raise AllocatedPhysicalAccountRowObservationV3Corruption(
                "allocation selector substitution"
            )
        return allocation

    def _read_physical(
        self,
        command: CaptureAllocatedPhysicalAccountRowObservationV3Command,
        cutoff: datetime,
    ) -> PhysicalAccountRowObservationV2:
        value = self._physical_provider.get_exact_final(
            observation_id=command.physical_observation_id,
            observation_version=command.physical_observation_version,
            expected_content_hash=command.expected_physical_content_hash,
            as_of=cutoff,
        )
        if value is None:
            raise AllocatedPhysicalAccountRowObservationV3Unavailable(
                "exact-final Physical-v2 root is unavailable"
            )
        physical = _physical(value)
        if (
            physical.observation_id != command.physical_observation_id
            or physical.observation_version != command.physical_observation_version
            or physical.content_hash != command.expected_physical_content_hash
            or not physical.is_current_at(cutoff)
        ):
            raise AllocatedPhysicalAccountRowObservationV3Corruption(
                "Physical-v2 selector substitution"
            )
        return physical

    def _validate_replay(
        self,
        value: object,
        command: CaptureAllocatedPhysicalAccountRowObservationV3Command,
        cutoff: datetime,
    ) -> AllocatedPhysicalAccountRowObservationV3:
        record = _record(value)
        observation = record.observation
        if (
            observation.observation_id != command.observation_id
            or observation.observation_version != command.observation_version
            or observation.allocation.allocation_id != command.allocation_id
            or observation.allocation.allocation_version != command.allocation_version
            or observation.allocation.content_hash != command.expected_allocation_content_hash
            or observation.physical_observation.observation_id != command.physical_observation_id
            or observation.physical_observation.observation_version
            != command.physical_observation_version
            or observation.physical_observation.content_hash
            != command.expected_physical_content_hash
            or record.recorded_by != self._recorder
        ):
            raise AllocatedPhysicalAccountRowObservationV3Conflict(
                "creation-root identity first winner differs"
            )
        physical = observation.physical_observation
        head = self._repository.get_current_head(
            allocation_content_hash=observation.allocation.content_hash,
            account_namespace=physical.account_namespace,
            account_id=physical.account_id,
            underlying_unified_account_namespace=(physical.underlying_unified_account_namespace),
            underlying_unified_account_id=physical.underlying_unified_account_id,
            physical_content_hash=physical.content_hash,
            as_of=cutoff,
        )
        if head is None or _record(head) != record:
            raise AllocatedPhysicalAccountRowObservationV3Conflict(
                "creation-root first winner is not the logical head"
            )
        return observation


class GetExactAllocatedPhysicalAccountRowObservationV3:
    """Read exact identity/hash creation-root evidence at one PIT."""

    def __init__(self, repository: AllocatedPhysicalAccountRowObservationV3Repository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetExactAllocatedPhysicalAccountRowObservationV3Command,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None:
        if type(command) is not GetExactAllocatedPhysicalAccountRowObservationV3Command:
            raise TypeError(
                "command must be an exact GetExactAllocatedPhysicalAccountRowObservationV3Command"
            )
        command.__post_init__()
        value = self._repository.get_exact_by_hash(
            observation_id=command.observation_id,
            observation_version=command.observation_version,
            expected_content_hash=command.expected_content_hash,
            as_of=command.as_of,
        )
        if value is None:
            return None
        observation = _record(value).observation
        if (
            observation.observation_id != command.observation_id
            or observation.observation_version != command.observation_version
            or observation.content_hash != command.expected_content_hash
        ):
            raise AllocatedPhysicalAccountRowObservationV3Corruption(
                "exact creation-root selector substitution"
            )
        return observation if observation.is_knowable_at(command.as_of) else None


class GetCurrentAllocatedPhysicalAccountRowObservationV3:
    """Return only one exact unexpired creation-root logical head."""

    def __init__(self, repository: AllocatedPhysicalAccountRowObservationV3Repository) -> None:
        self._repository = repository

    def execute(
        self,
        command: GetCurrentAllocatedPhysicalAccountRowObservationV3Command,
    ) -> AllocatedPhysicalAccountRowObservationV3 | None:
        if type(command) is not GetCurrentAllocatedPhysicalAccountRowObservationV3Command:
            raise TypeError(
                "command must be an exact GetCurrentAllocatedPhysicalAccountRowObservationV3Command"
            )
        command.__post_init__()
        expected = GetExactAllocatedPhysicalAccountRowObservationV3(self._repository).execute(
            GetExactAllocatedPhysicalAccountRowObservationV3Command(
                observation_id=command.observation_id,
                observation_version=command.observation_version,
                expected_content_hash=command.expected_content_hash,
                as_of=command.as_of,
            )
        )
        if expected is None:
            return None
        physical = expected.physical_observation
        head = self._repository.get_current_head(
            allocation_content_hash=expected.allocation.content_hash,
            account_namespace=physical.account_namespace,
            account_id=physical.account_id,
            underlying_unified_account_namespace=(physical.underlying_unified_account_namespace),
            underlying_unified_account_id=physical.underlying_unified_account_id,
            physical_content_hash=physical.content_hash,
            as_of=command.as_of,
        )
        if head is None or _record(head).observation != expected:
            return None
        return expected if expected.is_knowable_at(command.as_of) else None


def _allocation(value: object) -> CanonicalAccountCreationAllocation:
    if type(value) is not CanonicalAccountCreationAllocation:
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            "allocation provider type substitution"
        )
    try:
        CanonicalAccountCreationAllocation.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            "allocation provider returned invalid evidence"
        ) from error
    return value


def _physical(value: object) -> PhysicalAccountRowObservationV2:
    if type(value) is not PhysicalAccountRowObservationV2:
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            "Physical-v2 provider type substitution"
        )
    try:
        PhysicalAccountRowObservationV2.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            "Physical-v2 provider returned invalid evidence"
        ) from error
    return value


def _record(value: object) -> PersistedAllocatedPhysicalAccountRowObservationV3:
    if type(value) is not PersistedAllocatedPhysicalAccountRowObservationV3:
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            "repository record type substitution"
        )
    try:
        PersistedAllocatedPhysicalAccountRowObservationV3.__post_init__(value)
    except (TypeError, ValueError) as error:
        raise AllocatedPhysicalAccountRowObservationV3Corruption(
            "repository returned invalid creation-root evidence"
        ) from error
    return value


__all__ = [
    "AllocatedPhysicalAccountRowObservationV3Conflict",
    "AllocatedPhysicalAccountRowObservationV3Corruption",
    "AllocatedPhysicalAccountRowObservationV3Repository",
    "AllocatedPhysicalAccountRowObservationV3Recorder",
    "AllocatedPhysicalAccountRowObservationV3Unavailable",
    "CaptureAllocatedPhysicalAccountRowObservationV3",
    "CaptureAllocatedPhysicalAccountRowObservationV3Command",
    "ExactCurrentUnconsumedCanonicalAllocationProvider",
    "ExactFinalPhysicalAccountRowObservationV2Provider",
    "GetCurrentAllocatedPhysicalAccountRowObservationV3",
    "GetCurrentAllocatedPhysicalAccountRowObservationV3Command",
    "GetExactAllocatedPhysicalAccountRowObservationV3",
    "GetExactAllocatedPhysicalAccountRowObservationV3Command",
    "PersistedAllocatedPhysicalAccountRowObservationV3",
]
