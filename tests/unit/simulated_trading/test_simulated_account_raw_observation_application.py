"""Tests for raw SimulatedAccount observation owner workflows."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading.application.simulated_account_raw_observation import (
    GetCurrentSimulatedAccountRawObservation,
    GetCurrentSimulatedAccountRawObservationCommand,
    GetExactSimulatedAccountRawObservation,
    GetExactSimulatedAccountRawObservationCommand,
    PersistedSimulatedAccountRawObservation,
    RecordSimulatedAccountRawObservation,
    SimulatedAccountRawObservationConflict,
    SimulatedAccountRawObservationCorruption,
    SimulatedAccountRawObservationRepository,
    SimulatedAccountRawObservationUnavailable,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _observation(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "row-7",
        "observation_version": "mutation-1",
        "row_pk": 7,
        "row_user_id": 19,
        "raw_account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=2),
        "row_updated_at": NOW - timedelta(hours=2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": NOW - timedelta(hours=1),
        "valid_until": NOW + timedelta(days=2),
    }
    values.update(changes)
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


class _Repository(SimulatedAccountRawObservationRepository):
    def __init__(self, *, now: datetime = NOW) -> None:
        self.cutoff = now
        self.winner: PersistedSimulatedAccountRawObservation | None = None
        self.head: PersistedSimulatedAccountRawObservation | None = None
        self.appended: list[PersistedSimulatedAccountRawObservation] = []
        self.expected_predecessor_hash: str | None = None
        self.substitute_append: object | None = None

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return self.cutoff

    def get_winner(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.winner

    def get_current_head(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.head

    def append(self, record, **kwargs):  # type: ignore[no-untyped-def]
        self.appended.append(record)
        self.expected_predecessor_hash = kwargs["expected_predecessor_hash"]
        return self.substitute_append if self.substitute_append is not None else record

    def get_exact_by_hash(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.winner


def _record(
    observation: SimulatedAccountRawObservation,
    *,
    recorded_at: datetime = NOW,
) -> PersistedSimulatedAccountRawObservation:
    return PersistedSimulatedAccountRawObservation(observation, recorded_at)


def test_record_root_uses_repository_clock_and_first_winner() -> None:
    repository = _Repository()
    observation = _observation()

    value = RecordSimulatedAccountRawObservation(repository).execute(observation)

    assert value == observation
    assert repository.appended == [_record(observation)]
    assert repository.expected_predecessor_hash is None


def test_record_successor_binds_logical_head_and_predecessor_cas() -> None:
    previous = _observation(valid_until=NOW + timedelta(days=3))
    repository = _Repository()
    repository.head = _record(previous, recorded_at=NOW - timedelta(minutes=30))
    successor = _observation(
        observation_version="mutation-2",
        row_updated_at=NOW - timedelta(minutes=20),
        observed_at=NOW - timedelta(minutes=10),
        supersedes_content_hash=previous.content_hash,
    )

    assert RecordSimulatedAccountRawObservation(repository).execute(successor) == successor
    assert repository.expected_predecessor_hash == previous.content_hash


def test_record_replays_exact_winner_but_rejects_hijack_or_superseded_replay() -> None:
    observation = _observation()
    repository = _Repository()
    repository.winner = repository.head = _record(observation)
    use_case = RecordSimulatedAccountRawObservation(repository)

    assert use_case.execute(observation) == observation
    assert repository.appended == []

    repository.winner = _record(_observation(row_user_id=20))
    with pytest.raises(SimulatedAccountRawObservationConflict, match="another first winner"):
        use_case.execute(observation)

    repository.winner = _record(observation)
    repository.head = _record(
        _observation(
            observation_version="mutation-2",
            row_updated_at=NOW - timedelta(minutes=20),
            observed_at=NOW - timedelta(minutes=10),
            supersedes_content_hash=observation.content_hash,
        )
    )
    with pytest.raises(SimulatedAccountRawObservationConflict, match="no longer"):
        use_case.execute(observation)


def test_record_rejects_bad_repository_clock_and_append_substitution() -> None:
    observation = _observation()
    before_owner = _Repository(now=observation.observed_at - timedelta(seconds=1))
    with pytest.raises(SimulatedAccountRawObservationCorruption, match="clock precedes"):
        RecordSimulatedAccountRawObservation(before_owner).execute(observation)

    expired = _Repository(now=observation.valid_until)
    with pytest.raises(SimulatedAccountRawObservationUnavailable, match="expired"):
        RecordSimulatedAccountRawObservation(expired).execute(observation)

    substituted = _Repository()
    substituted.substitute_append = {"observation": "forged"}
    with pytest.raises(SimulatedAccountRawObservationCorruption, match="record type"):
        RecordSimulatedAccountRawObservation(substituted).execute(observation)


def test_exact_read_respects_recorded_clock_hash_and_tombstone_fact() -> None:
    tombstone = _observation(is_active=False, is_present=False, is_tombstone=True)
    repository = _Repository()
    repository.winner = _record(tombstone)
    command = GetExactSimulatedAccountRawObservationCommand(
        tombstone.observation_id,
        tombstone.observation_version,
        tombstone.content_hash,
        NOW,
    )

    assert GetExactSimulatedAccountRawObservation(repository).execute(command) == tombstone
    before_recording = GetExactSimulatedAccountRawObservationCommand(
        tombstone.observation_id,
        tombstone.observation_version,
        tombstone.content_hash,
        NOW - timedelta(seconds=1),
    )
    assert GetExactSimulatedAccountRawObservation(repository).execute(before_recording) is None


def test_current_read_requires_exact_final_head_and_never_falls_back() -> None:
    previous = _observation(valid_until=NOW + timedelta(days=3))
    repository = _Repository()
    repository.winner = repository.head = _record(previous)
    command = GetCurrentSimulatedAccountRawObservationCommand(previous, NOW)
    reader = GetCurrentSimulatedAccountRawObservation(repository)

    assert reader.execute(command) == previous

    successor = _observation(
        observation_version="mutation-2",
        row_updated_at=NOW - timedelta(minutes=20),
        observed_at=NOW - timedelta(minutes=10),
        valid_until=NOW + timedelta(days=1),
        supersedes_content_hash=previous.content_hash,
    )
    repository.head = _record(successor)
    assert reader.execute(command) is None


def test_current_read_rejects_expected_object_substitution() -> None:
    observation = _observation()
    repository = _Repository()
    repository.winner = repository.head = _record(_observation(row_user_id=20))

    with pytest.raises(SimulatedAccountRawObservationCorruption, match="selector substitution"):
        GetCurrentSimulatedAccountRawObservation(repository).execute(
            GetCurrentSimulatedAccountRawObservationCommand(observation, NOW)
        )


def test_commands_and_public_boundaries_require_exact_types() -> None:
    observation = _observation()
    repository = _Repository()

    with pytest.raises(TypeError, match="observation must be an exact"):
        RecordSimulatedAccountRawObservation(repository).execute(  # type: ignore[arg-type]
            {"observation_id": observation.observation_id}
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        GetCurrentSimulatedAccountRawObservationCommand(
            observation,
            datetime(2026, 8, 13, 12),
        )
