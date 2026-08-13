from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3Conflict,
    AllocatedPhysicalAccountRowObservationV3Recorder,
    AllocatedPhysicalAccountRowObservationV3Unavailable,
    CaptureAllocatedPhysicalAccountRowObservationV3,
    CaptureAllocatedPhysicalAccountRowObservationV3Command,
    GetCurrentAllocatedPhysicalAccountRowObservationV3,
    GetCurrentAllocatedPhysicalAccountRowObservationV3Command,
    GetExactAllocatedPhysicalAccountRowObservationV3,
    GetExactAllocatedPhysicalAccountRowObservationV3Command,
    PersistedAllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation import CanonicalAccountCreationAllocation
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from tests.unit.account.test_canonical_account_creation import _allocation, _physical


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


class _AllocationProvider:
    def __init__(self, value: CanonicalAccountCreationAllocation | None) -> None:
        self.value = value
        self.calls = 0
        self.as_of_values: list[datetime] = []

    def get_exact_current_unconsumed(
        self,
        *,
        allocation_id: str,
        allocation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> CanonicalAccountCreationAllocation | None:
        self.calls += 1
        self.as_of_values.append(as_of)
        return self.value


class _PhysicalProvider:
    def __init__(self, value: PhysicalAccountRowObservationV2 | None) -> None:
        self.value = value
        self.calls = 0
        self.as_of_values: list[datetime] = []

    def get_exact_final(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PhysicalAccountRowObservationV2 | None:
        self.calls += 1
        self.as_of_values.append(as_of)
        return self.value


class _Repository:
    def __init__(self) -> None:
        self.clock = _at(7)
        self.record: PersistedAllocatedPhysicalAccountRowObservationV3 | None = None
        self.expected_predecessors: list[str | None] = []

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
        if self.record is None:
            return None
        value = self.record.observation
        return (
            self.record
            if (value.observation_id, value.observation_version)
            == (
                observation_id,
                observation_version,
            )
            else None
        )

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
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
        return self.record

    def append(
        self,
        record: PersistedAllocatedPhysicalAccountRowObservationV3,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3:
        self.expected_predecessors.append(expected_predecessor_hash)
        if self.record is None:
            self.record = record
        return self.record

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedAllocatedPhysicalAccountRowObservationV3 | None:
        winner = self.get_winner(
            observation_id=observation_id,
            observation_version=observation_version,
            as_of=as_of,
        )
        if winner is None or winner.observation.content_hash != expected_content_hash:
            return None
        return winner


class _AdvancingClockRepository(_Repository):
    def __init__(self) -> None:
        super().__init__()
        self.clocks = iter((_at(7), _at(8)))

    def now(self) -> datetime:
        return next(self.clocks)


def _command(
    allocation: CanonicalAccountCreationAllocation,
    physical: PhysicalAccountRowObservationV2,
) -> CaptureAllocatedPhysicalAccountRowObservationV3Command:
    return CaptureAllocatedPhysicalAccountRowObservationV3Command(
        observation_id="allocated-physical-row-7",
        observation_version="creation-root-v1",
        allocation_id=allocation.allocation_id,
        allocation_version=allocation.allocation_version,
        expected_allocation_content_hash=allocation.content_hash,
        physical_observation_id=physical.observation_id,
        physical_observation_version=physical.observation_version,
        expected_physical_content_hash=physical.content_hash,
    )


def _use_case(
    allocation_provider: _AllocationProvider,
    physical_provider: _PhysicalProvider,
    repository: _Repository,
) -> CaptureAllocatedPhysicalAccountRowObservationV3:
    return CaptureAllocatedPhysicalAccountRowObservationV3(
        allocation_provider=allocation_provider,
        physical_provider=physical_provider,
        repository=repository,
        recorder=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id="creation-root-recorder",
        ),
        validity_period=timedelta(days=7),
    )


def test_capture_double_reads_same_exact_inputs_and_appends_root_cas() -> None:
    allocation = _allocation()
    physical = _physical()
    allocations = _AllocationProvider(allocation)
    physicals = _PhysicalProvider(physical)
    repository = _Repository()

    result = _use_case(allocations, physicals, repository).execute(_command(allocation, physical))

    assert result.allocation is allocation
    assert result.physical_observation is physical
    assert allocations.calls == physicals.calls == 2
    assert repository.expected_predecessors == [None]


def test_capture_rereads_inputs_and_head_at_authoritative_recorded_clock() -> None:
    allocation = _allocation()
    physical = _physical()
    allocations = _AllocationProvider(allocation)
    physicals = _PhysicalProvider(physical)
    repository = _AdvancingClockRepository()

    result = _use_case(allocations, physicals, repository).execute(_command(allocation, physical))

    assert result.recorded_at == _at(8)
    assert allocations.as_of_values == [_at(7), _at(8)]
    assert physicals.as_of_values == [_at(7), _at(8)]


def test_capture_replays_exact_first_winner_and_rejects_anchor_collision() -> None:
    allocation = _allocation()
    physical = _physical()
    repository = _Repository()
    use_case = _use_case(
        _AllocationProvider(allocation),
        _PhysicalProvider(physical),
        repository,
    )
    command = _command(allocation, physical)
    first = use_case.execute(command)

    use_case._allocation_provider.value = None
    use_case._physical_provider.value = None
    assert use_case.execute(command) is first
    use_case._allocation_provider.value = allocation
    use_case._physical_provider.value = physical

    other = AllocatedPhysicalAccountRowObservationV3(
        observation_id="other-root",
        observation_version="v1",
        allocation=allocation,
        physical_observation=physical,
        recorded_at=_at(7),
        ttl_valid_until=_at(14),
        valid_until=_at(14),
    )
    repository.record = PersistedAllocatedPhysicalAccountRowObservationV3(
        observation=other,
        recorded_by=AllocatedPhysicalAccountRowObservationV3Recorder(
            service_id="creation-root-recorder",
        ),
    )
    with pytest.raises(AllocatedPhysicalAccountRowObservationV3Conflict):
        use_case.execute(command)


def test_capture_fails_closed_for_missing_or_drifting_inputs() -> None:
    allocation = _allocation()
    physical = _physical()
    repository = _Repository()
    with pytest.raises(AllocatedPhysicalAccountRowObservationV3Unavailable):
        _use_case(
            _AllocationProvider(None),
            _PhysicalProvider(physical),
            repository,
        ).execute(_command(allocation, physical))

    class _DriftingAllocation(_AllocationProvider):
        def get_exact_current_unconsumed(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            return allocation if self.calls == 1 else _allocation(allocation_id="other")

    with pytest.raises((AllocatedPhysicalAccountRowObservationV3Conflict, RuntimeError)):
        _use_case(
            _DriftingAllocation(allocation),
            _PhysicalProvider(physical),
            repository,
        ).execute(_command(allocation, physical))


def test_exact_pit_and_closed_current_require_exact_hash_and_head() -> None:
    allocation = _allocation()
    physical = _physical()
    repository = _Repository()
    observation = _use_case(
        _AllocationProvider(allocation),
        _PhysicalProvider(physical),
        repository,
    ).execute(_command(allocation, physical))

    exact = GetExactAllocatedPhysicalAccountRowObservationV3(repository).execute(
        GetExactAllocatedPhysicalAccountRowObservationV3Command(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            as_of=_at(8),
        )
    )
    current = GetCurrentAllocatedPhysicalAccountRowObservationV3(repository).execute(
        GetCurrentAllocatedPhysicalAccountRowObservationV3Command(
            expected_observation=observation,
            as_of=_at(8),
        )
    )
    assert exact is observation
    assert current is observation
    assert (
        GetExactAllocatedPhysicalAccountRowObservationV3(repository).execute(
            GetExactAllocatedPhysicalAccountRowObservationV3Command(
                observation_id=observation.observation_id,
                observation_version=observation.observation_version,
                expected_content_hash="a" * 64,
                as_of=_at(8),
            )
        )
        is None
    )
