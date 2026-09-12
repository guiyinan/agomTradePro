from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from datetime import datetime

import pytest

from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1Conflict,
    CanonicalAccountOwnershipReobservationV1Corruption,
    GetCurrentCanonicalAccountOwnershipReobservationV1,
    GetCurrentCanonicalAccountOwnershipReobservationV1Command,
    GetExactCanonicalAccountOwnershipReobservationV1,
    GetExactCanonicalAccountOwnershipReobservationV1Command,
    PersistedCanonicalAccountOwnershipReobservationV1,
    RecordCanonicalAccountOwnershipReobservationV1,
    RecordCanonicalAccountOwnershipReobservationV1Command,
)
from apps.account.application.physical_account_row_observation_v2 import (
    GetCurrentPhysicalAccountRowObservationV2Command,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)
from tests.unit.account.test_canonical_account_ownership_reobservation_v1 import (
    _at,
    _current_physical,
    _reobservation,
)


class _MemoryRepository:
    def __init__(
        self,
        *,
        now: datetime,
        record: PersistedCanonicalAccountOwnershipReobservationV1 | None = None,
    ) -> None:
        self.now_value = now
        self.record = record
        self.append_calls = 0

    def atomic(self) -> AbstractContextManager[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.now_value

    def get_winner(
        self, *, observation_id: str, observation_version: str, as_of: datetime
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        del observation_id, observation_version
        if self.record is None or self.record.reobservation.recorded_at > as_of:
            return None
        return self.record

    def append(
        self,
        record: PersistedCanonicalAccountOwnershipReobservationV1,
        *,
        recorded_at: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1:
        assert recorded_at == record.reobservation.recorded_at
        self.append_calls += 1
        self.record = record
        return record

    def get_exact_by_hash(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedCanonicalAccountOwnershipReobservationV1 | None:
        del observation_id, observation_version, expected_content_hash
        if self.record is None or self.record.reobservation.recorded_at > as_of:
            return None
        return self.record


class _CurrentPhysicalReader:
    def __init__(self, result: PhysicalAccountRowObservationV2 | None) -> None:
        self.result = result
        self.commands: list[GetCurrentPhysicalAccountRowObservationV2Command] = []

    def execute(
        self, command: GetCurrentPhysicalAccountRowObservationV2Command
    ) -> PhysicalAccountRowObservationV2 | None:
        self.commands.append(command)
        return self.result


def _stored(
    value: CanonicalAccountOwnershipReobservationV1 | None = None,
) -> PersistedCanonicalAccountOwnershipReobservationV1:
    return PersistedCanonicalAccountOwnershipReobservationV1(value or _reobservation())


def test_record_appends_once_and_replays_the_exact_first_winner() -> None:
    expected = _reobservation()
    repository = _MemoryRepository(now=_at(10, minute=5))
    usecase = RecordCanonicalAccountOwnershipReobservationV1(repository)
    command = RecordCanonicalAccountOwnershipReobservationV1Command(expected)

    assert usecase.execute(command) == expected
    assert usecase.execute(command) == expected
    assert repository.append_calls == 1


def test_record_rejects_a_different_first_winner_and_future_proof() -> None:
    expected = _reobservation()
    other = _reobservation(recorded_at=_at(10, minute=1))
    repository = _MemoryRepository(now=_at(10, minute=5), record=_stored(other))

    with pytest.raises(CanonicalAccountOwnershipReobservationV1Conflict, match="winner"):
        RecordCanonicalAccountOwnershipReobservationV1(repository).execute(
            RecordCanonicalAccountOwnershipReobservationV1Command(expected)
        )

    future_repository = _MemoryRepository(now=_at(9))
    with pytest.raises(CanonicalAccountOwnershipReobservationV1Corruption, match="future"):
        RecordCanonicalAccountOwnershipReobservationV1(future_repository).execute(
            RecordCanonicalAccountOwnershipReobservationV1Command(expected)
        )


def test_record_rejects_an_identical_winner_ahead_of_repository_time() -> None:
    expected = _reobservation()
    repository = _MemoryRepository(now=_at(9), record=_stored(expected))

    def future_winner(
        *, observation_id: str, observation_version: str, as_of: datetime
    ) -> PersistedCanonicalAccountOwnershipReobservationV1:
        del observation_id, observation_version, as_of
        return _stored(expected)

    repository.get_winner = future_winner  # type: ignore[method-assign]
    with pytest.raises(CanonicalAccountOwnershipReobservationV1Corruption, match="future"):
        RecordCanonicalAccountOwnershipReobservationV1(repository).execute(
            RecordCanonicalAccountOwnershipReobservationV1Command(expected)
        )


def test_exact_history_remains_readable_after_expiry_but_not_before_recording() -> None:
    expected = _reobservation()
    repository = _MemoryRepository(now=_at(13), record=_stored(expected))
    usecase = GetExactCanonicalAccountOwnershipReobservationV1(repository)

    assert (
        usecase.execute(
            GetExactCanonicalAccountOwnershipReobservationV1Command(
                observation_id=expected.observation_id,
                observation_version=expected.observation_version,
                expected_content_hash=expected.content_hash,
                as_of=_at(13),
            )
        )
        == expected
    )
    assert (
        usecase.execute(
            GetExactCanonicalAccountOwnershipReobservationV1Command(
                observation_id=expected.observation_id,
                observation_version=expected.observation_version,
                expected_content_hash=expected.content_hash,
                as_of=_at(9),
            )
        )
        is None
    )


def test_exact_history_rejects_repository_selector_substitution() -> None:
    expected = _reobservation()
    other = _reobservation(recorded_at=_at(10, minute=1))
    repository = _MemoryRepository(now=_at(11), record=_stored(other))

    with pytest.raises(CanonicalAccountOwnershipReobservationV1Corruption, match="selector"):
        GetExactCanonicalAccountOwnershipReobservationV1(repository).execute(
            GetExactCanonicalAccountOwnershipReobservationV1Command(
                observation_id=expected.observation_id,
                observation_version=expected.observation_version,
                expected_content_hash=expected.content_hash,
                as_of=_at(11),
            )
        )


def test_current_requires_the_exact_physical_logical_head() -> None:
    expected = _reobservation()
    repository = _MemoryRepository(now=_at(11), record=_stored(expected))
    reader = _CurrentPhysicalReader(expected.current_physical)
    command = GetCurrentCanonicalAccountOwnershipReobservationV1Command(
        observation_id=expected.observation_id,
        observation_version=expected.observation_version,
        expected_content_hash=expected.content_hash,
        as_of=_at(11),
    )

    assert (
        GetCurrentCanonicalAccountOwnershipReobservationV1(
            repository=repository, current_physical_reader=reader
        ).execute(command)
        == expected
    )
    assert reader.commands == [
        GetCurrentPhysicalAccountRowObservationV2Command(
            expected_observation=expected.current_physical,
            as_of=_at(11),
        )
    ]


def test_current_returns_none_for_expiry_or_a_noncurrent_physical_parent() -> None:
    expected = _reobservation()
    repository = _MemoryRepository(now=_at(12), record=_stored(expected))
    reader = _CurrentPhysicalReader(expected.current_physical)
    expired = GetCurrentCanonicalAccountOwnershipReobservationV1Command(
        observation_id=expected.observation_id,
        observation_version=expected.observation_version,
        expected_content_hash=expected.content_hash,
        as_of=_at(12),
    )
    usecase = GetCurrentCanonicalAccountOwnershipReobservationV1(
        repository=repository, current_physical_reader=reader
    )

    assert usecase.execute(expired) is None
    assert reader.commands == []

    reader.result = None
    current = GetCurrentCanonicalAccountOwnershipReobservationV1Command(
        observation_id=expected.observation_id,
        observation_version=expected.observation_version,
        expected_content_hash=expected.content_hash,
        as_of=_at(11),
    )
    assert usecase.execute(current) is None


def test_current_rejects_a_substituted_physical_result() -> None:
    expected = _reobservation()
    repository = _MemoryRepository(now=_at(11), record=_stored(expected))
    other = _current_physical(observation_id="another-current-physical")
    reader = _CurrentPhysicalReader(other)

    with pytest.raises(CanonicalAccountOwnershipReobservationV1Corruption, match="logical head"):
        GetCurrentCanonicalAccountOwnershipReobservationV1(
            repository=repository, current_physical_reader=reader
        ).execute(
            GetCurrentCanonicalAccountOwnershipReobservationV1Command(
                observation_id=expected.observation_id,
                observation_version=expected.observation_version,
                expected_content_hash=expected.content_hash,
                as_of=_at(11),
            )
        )
