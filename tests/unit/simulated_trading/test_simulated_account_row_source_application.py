from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.simulated_trading.application.simulated_account_row_source import (
    CaptureSimulatedAccountRowSource,
    CaptureSimulatedAccountRowSourceCommand,
    ExactRawSimulatedAccountObservation,
    GetCurrentSimulatedAccountRowSource,
    GetCurrentSimulatedAccountRowSourceCommand,
    GetExactSimulatedAccountRowSource,
    GetExactSimulatedAccountRowSourceCommand,
    PersistedSimulatedAccountRowSource,
    SimulatedAccountRowSourceActor,
    SimulatedAccountRowSourceConflict,
    SimulatedAccountRowSourceCorruption,
    SimulatedAccountRowSourceUnavailable,
)
from apps.simulated_trading.domain.simulated_account_row_source import (
    SimulatedAccountRowSource,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _actor(**changes: object) -> SimulatedAccountRowSourceActor:
    values: dict[str, object] = {
        "actor_id": "staff-17",
        "user_id": 17,
        "role": "source_recorder",
    }
    values.update(changes)
    return SimulatedAccountRowSourceActor(**values)  # type: ignore[arg-type]


def _command(**changes: object) -> CaptureSimulatedAccountRowSourceCommand:
    values: dict[str, object] = {
        "source_id": "simulated-row-7",
        "source_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
    }
    values.update(changes)
    return CaptureSimulatedAccountRowSourceCommand(**values)  # type: ignore[arg-type]


def _observation(**changes: object) -> ExactRawSimulatedAccountObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-row-7",
        "observation_version": "v1",
        "content_hash": HASH_A,
        "row_pk": 7,
        "row_user_id": None,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(3),
        "valid_until": _at(20),
    }
    values.update(changes)
    return ExactRawSimulatedAccountObservation(**values)  # type: ignore[arg-type]


class _Provider:
    def __init__(
        self,
        values: list[ExactRawSimulatedAccountObservation | None],
    ) -> None:
        self.values = values
        self.calls: list[tuple[str, str, int, datetime]] = []

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        row_pk: int,
        as_of: datetime,
    ) -> ExactRawSimulatedAccountObservation | None:
        self.calls.append((observation_id, observation_version, row_pk, as_of))
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class _Repository:
    def __init__(self, clocks: list[datetime] | None = None) -> None:
        self.clocks = clocks or [_at(4), _at(4)]
        self.records: list[PersistedSimulatedAccountRowSource] = []
        self.head: PersistedSimulatedAccountRowSource | None = None
        self.append_expected: str | None = None
        self.append_recorded_at: datetime | None = None

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        if len(self.clocks) > 1:
            return self.clocks.pop(0)
        return self.clocks[0]

    def get_winner(
        self,
        *,
        source_id: str,
        source_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        return next(
            (
                record
                for record in self.records
                if record.source.source_id == source_id
                and record.source.source_version == source_version
                and record.source.recorded_at <= as_of
            ),
            None,
        )

    def get_current_head(
        self,
        *,
        source_id: str,
        account_namespace: str,
        account_id: str,
        underlying_unified_account_namespace: str,
        underlying_unified_account_id: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        del as_of
        if self.head is None:
            return None
        source = self.head.source
        if (
            source.source_id == source_id
            and source.account_namespace == account_namespace
            and source.account_id == account_id
            and source.underlying_unified_account_namespace == underlying_unified_account_namespace
            and source.underlying_unified_account_id == underlying_unified_account_id
        ):
            return self.head
        return None

    def append(
        self,
        record: PersistedSimulatedAccountRowSource,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRowSource:
        self.append_expected = expected_predecessor_hash
        self.append_recorded_at = recorded_at
        self.records.append(record)
        self.head = record
        return record

    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        del as_of
        return next(
            (
                record
                for record in self.records
                if record.source.source_id == source_id
                and record.source.source_version == source_version
                and record.source.content_hash == expected_content_hash
            ),
            None,
        )


class _SubstitutingRepository(_Repository):
    def get_exact_by_hash(
        self,
        *,
        source_id: str,
        source_version: str,
        expected_content_hash: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRowSource | None:
        del source_id, source_version, expected_content_hash, as_of
        return cast(PersistedSimulatedAccountRowSource, {})


def _capture(
    repository: _Repository,
    *,
    observations: list[ExactRawSimulatedAccountObservation | None] | None = None,
    actor: SimulatedAccountRowSourceActor | None = None,
) -> tuple[CaptureSimulatedAccountRowSource, _Provider]:
    raw = _observation()
    provider = _Provider(observations or [raw, raw])
    return (
        CaptureSimulatedAccountRowSource(
            observation_provider=provider,
            repository=repository,
            actor=actor or _actor(),
            validity_period=timedelta(days=10),
        ),
        provider,
    )


def _persisted_source(**changes: object) -> PersistedSimulatedAccountRowSource:
    values: dict[str, object] = {
        "source_id": "simulated-row-7",
        "source_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": None,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": _at(1),
        "row_updated_at": _at(2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": _at(3),
        "recorded_at": _at(4),
        "source_valid_until": _at(20),
        "ttl_valid_until": _at(14),
        "valid_until": _at(14),
    }
    values.update(changes)
    return PersistedSimulatedAccountRowSource(
        source=SimulatedAccountRowSource(**values),  # type: ignore[arg-type]
        captured_by=_actor(),
    )


def test_capture_command_is_strictly_id_only() -> None:
    assert {field.name for field in fields(CaptureSimulatedAccountRowSourceCommand)} == {
        "source_id",
        "source_version",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
    }
    command = _command(account_id="0007", underlying_unified_account_id=7)
    assert type(command.account_id) is str
    assert type(command.underlying_unified_account_id) is int
    with pytest.raises(TypeError, match="account_id must be an exact string"):
        _command(account_id=7)
    with pytest.raises(TypeError, match="underlying.*exact integer"):
        _command(underlying_unified_account_id="7")


def test_raw_observation_requires_typed_owner_issued_identity_hash_and_clocks() -> None:
    raw = _observation(row_user_id=42, raw_account_type="SIMULATED")
    assert raw.content_hash == HASH_A
    assert raw.row_pk == 7
    assert raw.row_user_id == 42
    assert raw.raw_account_type == "SIMULATED"
    assert raw.observed_at > raw.row_updated_at
    with pytest.raises(ValueError, match="SHA-256"):
        _observation(content_hash="")
    with pytest.raises(ValueError, match="clock sequence"):
        _observation(observed_at=_at(1))
    with pytest.raises(ValueError, match="validity"):
        _observation(valid_until=_at(3))


def test_capture_uses_typed_observation_and_one_repository_cutoff_twice() -> None:
    repository = _Repository()
    service, provider = _capture(repository)

    source = service.execute(_command())

    assert provider.calls == [
        ("simulated-row-7", "v1", 7, _at(4)),
        ("simulated-row-7", "v1", 7, _at(4)),
    ]
    assert source.source_id == "simulated-row-7"
    assert source.source_version == "v1"
    assert source.account_id == "0007"
    assert source.underlying_unified_account_id == 7
    assert source.raw_account_type == "SIMULATED"
    assert source.observed_at == _at(3)
    assert source.observed_at != source.row_updated_at
    assert source.observed_at != source.recorded_at
    assert source.source_valid_until == _at(20)
    assert source.ttl_valid_until == _at(14)
    assert source.valid_until == _at(14)
    assert source.owner_assignment_state == "unknown"
    assert source.must_not_execute is True
    assert repository.append_recorded_at == _at(4)


@pytest.mark.parametrize(
    ("observations", "error"),
    [
        ([None], SimulatedAccountRowSourceUnavailable),
        ([_observation(observation_id="other")], SimulatedAccountRowSourceCorruption),
        ([_observation(observation_version="v2")], SimulatedAccountRowSourceCorruption),
        ([_observation(row_pk=8)], SimulatedAccountRowSourceCorruption),
        ([_observation(valid_until=_at(4))], SimulatedAccountRowSourceUnavailable),
    ],
)
def test_capture_rejects_missing_expired_or_substituted_observation(
    observations: list[ExactRawSimulatedAccountObservation | None],
    error: type[ValueError],
) -> None:
    service, _ = _capture(_Repository(), observations=observations)
    with pytest.raises(error):
        service.execute(_command())


def test_capture_rejects_double_read_change_before_append() -> None:
    repository = _Repository()
    service, _ = _capture(
        repository,
        observations=[_observation(), _observation(content_hash=HASH_B)],
    )
    with pytest.raises(SimulatedAccountRowSourceConflict, match="changed during capture"):
        service.execute(_command())
    assert repository.records == []


def test_first_winner_replays_only_for_same_actor_and_current_head() -> None:
    repository = _Repository()
    service, _ = _capture(repository)
    first = service.execute(_command())

    replay, _ = _capture(repository)
    assert replay.execute(_command()) == first

    other_actor, _ = _capture(repository, actor=_actor(actor_id="staff-18", user_id=18))
    with pytest.raises(SimulatedAccountRowSourceConflict, match="another actor"):
        other_actor.execute(_command())

    repository.head = None
    with pytest.raises(SimulatedAccountRowSourceConflict, match="current head"):
        replay.execute(_command())


def test_successor_uses_repository_head_as_exact_predecessor_cas() -> None:
    repository = _Repository()
    first_service, _ = _capture(repository)
    first = first_service.execute(_command())
    repository.clocks = [_at(8), _at(8)]
    next_raw = _observation(
        observation_version="v2",
        content_hash=HASH_B,
        row_user_id=42,
        row_updated_at=_at(5),
        observed_at=_at(6),
        valid_until=_at(25),
    )
    successor_service, _ = _capture(repository, observations=[next_raw, next_raw])

    successor = successor_service.execute(_command(source_version="v2"))

    assert successor.supersedes_content_hash == first.content_hash
    assert repository.append_expected == first.content_hash
    assert successor.recorded_at == _at(8)


def test_exact_pit_is_hash_bound_and_allows_inactive_evidence() -> None:
    repository = _Repository()
    record = _persisted_source(is_active=False)
    repository.records = [record]
    repository.head = record
    service = GetExactSimulatedAccountRowSource(repository)

    assert (
        service.execute(
            GetExactSimulatedAccountRowSourceCommand(
                source_id=record.source.source_id,
                source_version=record.source.source_version,
                expected_content_hash=record.source.content_hash,
                as_of=_at(5),
            )
        )
        == record.source
    )
    assert (
        service.execute(
            GetExactSimulatedAccountRowSourceCommand(
                source_id=record.source.source_id,
                source_version=record.source.source_version,
                expected_content_hash=HASH_B,
                as_of=_at(5),
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"is_active": False},
        {"is_present": False, "is_tombstone": True},
        {"ttl_valid_until": _at(8), "valid_until": _at(8)},
    ],
)
def test_closed_current_rejects_final_inactive_tombstone_or_expired_without_fallback(
    changes: dict[str, object],
) -> None:
    repository = _Repository()
    first = _persisted_source(
        source_valid_until=_at(30),
        ttl_valid_until=_at(30),
        valid_until=_at(30),
    )
    final_values: dict[str, object] = {
        "source_version": "v2",
        "row_updated_at": _at(5),
        "observed_at": _at(6),
        "recorded_at": _at(7),
        "source_valid_until": _at(25),
        "ttl_valid_until": _at(20),
        "valid_until": _at(20),
        "supersedes_content_hash": first.source.content_hash,
    }
    final_values.update(changes)
    final = _persisted_source(**final_values)
    repository.records = [first, final]
    repository.head = final

    first_command = GetCurrentSimulatedAccountRowSourceCommand.from_source(
        first.source,
        as_of=_at(9),
    )
    final_command = GetCurrentSimulatedAccountRowSourceCommand.from_source(
        final.source,
        as_of=_at(9),
    )
    service = GetCurrentSimulatedAccountRowSource(repository)

    assert service.execute(first_command) is None
    assert service.execute(final_command) is None


def test_closed_current_requires_every_selector_to_match() -> None:
    repository = _Repository()
    record = _persisted_source()
    repository.records = [record]
    repository.head = record
    command = GetCurrentSimulatedAccountRowSourceCommand.from_source(
        record.source,
        as_of=_at(5),
    )
    service = GetCurrentSimulatedAccountRowSource(repository)

    assert service.execute(command) == record.source
    assert service.execute(replace(command, raw_account_type="real")) is None


def test_repository_or_provider_type_substitution_fails_closed() -> None:
    service, _ = _capture(
        _Repository(),
        observations=[cast(ExactRawSimulatedAccountObservation, {})],
    )
    with pytest.raises(SimulatedAccountRowSourceCorruption, match="type substitution"):
        service.execute(_command())

    repository = _SubstitutingRepository()
    with pytest.raises(SimulatedAccountRowSourceCorruption, match="record type"):
        GetExactSimulatedAccountRowSource(repository).execute(
            GetExactSimulatedAccountRowSourceCommand(
                source_id="simulated-row-7",
                source_version="v1",
                expected_content_hash=HASH_A,
                as_of=_at(5),
            )
        )


def test_application_has_no_orm_cross_app_implementation_or_clock_fabrication() -> None:
    source = Path("apps/simulated_trading/application/simulated_account_row_source.py").read_text(
        encoding="utf-8"
    )

    assert "django" not in source
    assert ".infrastructure" not in source
    assert ".objects" not in source
    assert "timezone.now" not in source
    assert "datetime.now" not in source
    assert "observed_at=observation.row_updated_at" not in source
