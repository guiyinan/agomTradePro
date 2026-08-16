from __future__ import annotations

from contextlib import nullcontext
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2,
    CaptureSimulatedAccountRowSourceV2Command,
    ExactRawSimulatedAccountObservationV2,
    GetCurrentSimulatedAccountRowSourceV2,
    GetCurrentSimulatedAccountRowSourceV2Command,
    GetExactSimulatedAccountRowSourceV2,
    GetExactSimulatedAccountRowSourceV2Command,
    PersistedSimulatedAccountRowSourceV2,
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _raw_domain(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-account-row-7",
        "observation_version": "event-v1",
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
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


def _raw(**changes: object) -> ExactRawSimulatedAccountObservationV2:
    observation = _raw_domain(**changes)
    return ExactRawSimulatedAccountObservationV2(
        observation_id=observation.observation_id,
        observation_version=observation.observation_version,
        identity_hash=observation.identity_hash,
        content_hash=observation.content_hash,
        row_pk=observation.row_pk,
        row_user_id=observation.row_user_id,
        raw_account_type=observation.raw_account_type,
        is_active=observation.is_active,
        row_created_at=observation.row_created_at,
        row_updated_at=observation.row_updated_at,
        is_present=observation.is_present,
        is_tombstone=observation.is_tombstone,
        observed_at=observation.observed_at,
        valid_until=observation.valid_until,
        supersedes_content_hash=observation.supersedes_content_hash,
    )


def _command(**changes: object) -> CaptureSimulatedAccountRowSourceV2Command:
    raw = _raw()
    values: dict[str, object] = {
        "source_id": raw.observation_id,
        "source_version": raw.observation_version,
        "expected_raw_observation_content_hash": raw.content_hash,
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": raw.row_pk,
    }
    values.update(changes)
    return CaptureSimulatedAccountRowSourceV2Command(**values)  # type: ignore[arg-type]


class _Provider:
    def __init__(
        self,
        values: list[ExactRawSimulatedAccountObservationV2 | None],
    ) -> None:
        self.values = values
        self.calls: list[tuple[str, str, str, int, datetime]] = []

    def get_exact_current(
        self,
        *,
        observation_id: str,
        observation_version: str,
        expected_content_hash: str,
        row_pk: int,
        as_of: datetime,
    ) -> ExactRawSimulatedAccountObservationV2 | None:
        self.calls.append(
            (
                observation_id,
                observation_version,
                expected_content_hash,
                row_pk,
                as_of,
            )
        )
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


class _Repository:
    def __init__(self, clocks: list[datetime] | None = None) -> None:
        self.clocks = clocks or [_at(4), _at(4)]
        self.records: list[PersistedSimulatedAccountRowSourceV2] = []
        self.head: PersistedSimulatedAccountRowSourceV2 | None = None
        self.expected_predecessors: list[str | None] = []
        self.append_result: object | None = None

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
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
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
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
        del as_of
        if self.head is None:
            return None
        source = self.head.source
        selectors = (
            source.source_id,
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
        )
        expected = (
            source_id,
            account_namespace,
            account_id,
            underlying_unified_account_namespace,
            underlying_unified_account_id,
        )
        return self.head if selectors == expected else None

    def append(
        self,
        record: PersistedSimulatedAccountRowSourceV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedSimulatedAccountRowSourceV2:
        assert record.source.recorded_at == recorded_at
        actual = self.head.source.content_hash if self.head is not None else None
        if actual != expected_predecessor_hash:
            raise SimulatedAccountRowSourceV2Conflict("predecessor CAS conflict")
        self.expected_predecessors.append(expected_predecessor_hash)
        if self.append_result is not None:
            return cast(PersistedSimulatedAccountRowSourceV2, self.append_result)
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
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
        return next(
            (
                record
                for record in self.records
                if record.source.source_id == source_id
                and record.source.source_version == source_version
                and record.source.content_hash == expected_content_hash
                and record.source.recorded_at <= as_of
            ),
            None,
        )


def _capture(
    repository: _Repository,
    *,
    raw_values: list[ExactRawSimulatedAccountObservationV2 | None] | None = None,
) -> tuple[CaptureSimulatedAccountRowSourceV2, _Provider]:
    observation = _raw()
    provider = _Provider(raw_values or [observation, observation])
    return (
        CaptureSimulatedAccountRowSourceV2(
            observation_provider=provider,
            repository=repository,
            validity_period=timedelta(days=6),
        ),
        provider,
    )


def _capture_once(
    repository: _Repository,
    *,
    command: CaptureSimulatedAccountRowSourceV2Command | None = None,
    raw: ExactRawSimulatedAccountObservationV2 | None = None,
) -> SimulatedAccountRowSourceV2:
    observation = raw or _raw()
    service, _ = _capture(repository, raw_values=[observation, observation])
    return service.execute(command or _command())


def test_command_is_id_hash_only_and_raw_dto_restores_exact_authority() -> None:
    assert {field.name for field in fields(CaptureSimulatedAccountRowSourceV2Command)} == {
        "source_id",
        "source_version",
        "expected_raw_observation_content_hash",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
    }
    raw = _raw()
    assert raw.to_observation().content_hash == raw.content_hash
    with pytest.raises(ValueError, match="content_hash"):
        replace(raw, content_hash="b" * 64)
    with pytest.raises(ValueError, match="fixed"):
        replace(raw, owner="account")


def test_capture_double_reads_exact_raw_hash_at_one_cutoff_and_preserves_facts() -> None:
    repository = _Repository()
    service, provider = _capture(repository)
    command = _command()

    source = service.execute(command)

    expected_call = (
        command.source_id,
        command.source_version,
        command.expected_raw_observation_content_hash,
        command.underlying_unified_account_id,
        _at(4),
    )
    assert provider.calls == [expected_call, expected_call]
    assert source.source_id == source.raw_observation_id == command.source_id
    assert source.source_version == source.raw_observation_version == command.source_version
    assert source.raw_observation_content_hash == command.expected_raw_observation_content_hash
    assert source.raw_observation_identity_hash == _raw().identity_hash
    assert source.raw_observation_supersedes_content_hash is None
    assert source.row_user_id is None
    assert source.recorded_at == _at(4)
    assert source.valid_until == _at(10)
    assert repository.expected_predecessors == [None]


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ([None], SimulatedAccountRowSourceV2Unavailable),
        ([_raw(observation_version="event-v2")], SimulatedAccountRowSourceV2Corruption),
        ([_raw(row_pk=8)], SimulatedAccountRowSourceV2Corruption),
        ([_raw(valid_until=_at(4))], SimulatedAccountRowSourceV2Unavailable),
    ],
)
def test_capture_rejects_missing_expired_or_selector_substituted_raw(
    values: list[ExactRawSimulatedAccountObservationV2 | None],
    error: type[ValueError],
) -> None:
    service, _ = _capture(_Repository(clocks=[_at(4)]), raw_values=values)
    command = _command()
    if values[0] is not None and error is SimulatedAccountRowSourceV2Unavailable:
        command = replace(
            command,
            expected_raw_observation_content_hash=values[0].content_hash,
        )
    with pytest.raises(error):
        service.execute(command)


def test_capture_rejects_double_read_change_and_repository_clock_failures() -> None:
    root = _raw()
    changed = _raw(row_user_id=42)
    service, _ = _capture(_Repository(), raw_values=[root, changed])
    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="substitution"):
        service.execute(_command())

    backwards = _Repository(clocks=[_at(4), _at(3)])
    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="backwards"):
        _capture_once(backwards)

    expired = _raw(valid_until=_at(5))
    late = _Repository(clocks=[_at(4), _at(5)])
    with pytest.raises(SimulatedAccountRowSourceV2Unavailable, match="expired"):
        _capture_once(
            late,
            command=_command(expected_raw_observation_content_hash=expired.content_hash),
            raw=expired,
        )


def test_first_winner_replay_requires_exact_current_source_head() -> None:
    repository = _Repository()
    first = _capture_once(repository)
    repository.clocks = [_at(5)]
    assert _capture_once(repository) == first
    assert len(repository.records) == 1

    repository.head = None
    repository.clocks = [_at(5)]
    with pytest.raises(SimulatedAccountRowSourceV2Conflict, match="current head"):
        _capture_once(repository)


def test_successor_binds_both_raw_hash_and_source_predecessor_cas() -> None:
    repository = _Repository()
    first = _capture_once(repository)
    next_raw = _raw(
        observation_version="event-v2",
        row_user_id=42,
        raw_account_type="PAPER",
        row_updated_at=_at(5),
        observed_at=_at(6),
        valid_until=_at(20),
        supersedes_content_hash=first.raw_observation_content_hash,
    )
    repository.clocks = [_at(7), _at(7)]
    command = _command(
        source_version="event-v2",
        expected_raw_observation_content_hash=next_raw.content_hash,
    )

    successor = _capture_once(repository, command=command, raw=next_raw)

    assert successor.supersedes_content_hash == first.content_hash
    assert successor.raw_observation_supersedes_content_hash == first.raw_observation_content_hash
    assert repository.expected_predecessors == [None, first.content_hash]

    fork = _raw(
        observation_version="event-v3",
        row_updated_at=_at(8),
        observed_at=_at(9),
        valid_until=_at(22),
        supersedes_content_hash="b" * 64,
    )
    repository.clocks = [_at(10), _at(10)]
    with pytest.raises(SimulatedAccountRowSourceV2Conflict, match="raw hash"):
        _capture_once(
            repository,
            command=_command(
                source_version="event-v3",
                expected_raw_observation_content_hash=fork.content_hash,
            ),
            raw=fork,
        )


def test_append_return_type_or_first_winner_substitution_fails_closed() -> None:
    repository = _Repository()
    repository.append_result = {}
    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="record type"):
        _capture_once(repository)

    repository = _Repository()
    alternate_raw = _raw(row_user_id=42)
    alternate = _capture_once(
        _Repository(),
        command=_command(expected_raw_observation_content_hash=alternate_raw.content_hash),
        raw=alternate_raw,
    )
    repository.append_result = PersistedSimulatedAccountRowSourceV2(alternate)
    with pytest.raises(SimulatedAccountRowSourceV2Conflict, match="winner differs"):
        _capture_once(repository)


def test_exact_reader_is_hash_and_recorded_pit_closed_but_keeps_tombstone_fact() -> None:
    tombstone = _raw(is_active=False, is_present=False, is_tombstone=True)
    repository = _Repository()
    source = _capture_once(
        repository,
        command=_command(expected_raw_observation_content_hash=tombstone.content_hash),
        raw=tombstone,
    )
    reader = GetExactSimulatedAccountRowSourceV2(repository)
    command = GetExactSimulatedAccountRowSourceV2Command(
        source.source_id,
        source.source_version,
        source.content_hash,
        source.recorded_at,
    )

    assert reader.execute(command) == source
    assert reader.execute(replace(command, as_of=_at(3))) is None
    assert reader.execute(replace(command, expected_content_hash="b" * 64)) is None


def test_current_reader_rechecks_raw_final_head_and_projection_lag_fails_closed() -> None:
    repository = _Repository()
    raw = _raw()
    source = _capture_once(repository, raw=raw)
    provider = _Provider([raw])
    reader = GetCurrentSimulatedAccountRowSourceV2(
        repository=repository,
        observation_provider=provider,
    )
    command = GetCurrentSimulatedAccountRowSourceV2Command(source, _at(5))

    assert reader.execute(command) == source
    assert provider.calls[-1][2] == source.raw_observation_content_hash

    lagged = GetCurrentSimulatedAccountRowSourceV2(
        repository=repository,
        observation_provider=_Provider([None]),
    )
    assert lagged.execute(command) is None


def test_current_reader_never_falls_back_from_source_or_raw_supersession() -> None:
    repository = _Repository()
    raw = _raw()
    first = _capture_once(repository, raw=raw)
    command = GetCurrentSimulatedAccountRowSourceV2Command(first, _at(8))

    repository.head = None
    reader = GetCurrentSimulatedAccountRowSourceV2(
        repository=repository,
        observation_provider=_Provider([raw]),
    )
    assert reader.execute(command) is None

    inactive_repository = _Repository()
    inactive_raw = _raw(is_active=False)
    inactive = _capture_once(
        inactive_repository,
        command=_command(expected_raw_observation_content_hash=inactive_raw.content_hash),
        raw=inactive_raw,
    )
    inactive_reader = GetCurrentSimulatedAccountRowSourceV2(
        repository=inactive_repository,
        observation_provider=_Provider([inactive_raw]),
    )
    assert (
        inactive_reader.execute(GetCurrentSimulatedAccountRowSourceV2Command(inactive, _at(5)))
        is None
    )


def test_current_reader_detects_source_to_raw_field_substitution() -> None:
    repository = _Repository()
    raw = _raw()
    source = _capture_once(repository, raw=raw)
    substituted_raw = _raw(row_user_id=42)
    substituted = replace(
        source,
        row_user_id=42,
        raw_observation_content_hash=substituted_raw.content_hash,
        content_hash="",
    )
    record = PersistedSimulatedAccountRowSourceV2(substituted)
    repository.records = [record]
    repository.head = record
    reader = GetCurrentSimulatedAccountRowSourceV2(
        repository=repository,
        observation_provider=_Provider([raw]),
    )

    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="selector substitution"):
        reader.execute(GetCurrentSimulatedAccountRowSourceV2Command(substituted, _at(5)))


def test_application_v2_is_isolated_from_v1_orm_and_cross_app_implementations() -> None:
    source = Path(
        "apps/simulated_trading/application/simulated_account_row_source_v2.py"
    ).read_text(encoding="utf-8")
    assert "simulated_account_row_source import" not in source
    assert "django" not in source
    assert ".infrastructure" not in source
    assert ".objects" not in source
    assert "from apps.account" not in source
    assert "datetime.now" not in source
    assert "timezone.now" not in source
