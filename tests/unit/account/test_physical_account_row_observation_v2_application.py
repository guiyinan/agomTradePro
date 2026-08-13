from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2,
    CapturePhysicalAccountRowObservationV2Command,
    ExactPhysicalSimulatedAccountRowV2,
    GetCurrentPhysicalAccountRowObservationV2,
    GetCurrentPhysicalAccountRowObservationV2Command,
    GetExactPhysicalAccountRowObservationV2,
    GetExactPhysicalAccountRowObservationV2Command,
    PersistedPhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Conflict,
    PhysicalAccountRowObservationV2Recorder,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)


def _at(day: int) -> datetime:
    return datetime(2026, 8, day, 12, tzinfo=UTC)


def _source(*, terminal: bool = False) -> SimulatedAccountRowSourceV2:
    raw = SimulatedAccountRawObservation(
        observation_id="simulated-account-row-7",
        observation_version="event-v1",
        row_pk=7,
        row_user_id=None,
        raw_account_type="SIMULATED",
        is_active=not terminal,
        row_created_at=_at(1),
        row_updated_at=_at(2),
        is_present=not terminal,
        is_tombstone=terminal,
        observed_at=_at(3),
        valid_until=_at(20),
    )
    return SimulatedAccountRowSourceV2(
        source_id=raw.observation_id,
        source_version=raw.observation_version,
        account_namespace="account",
        account_id="0007",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=raw.row_pk,
        row_user_id=raw.row_user_id,
        raw_account_type=raw.raw_account_type,
        is_active=raw.is_active,
        row_created_at=raw.row_created_at,
        row_updated_at=raw.row_updated_at,
        is_present=raw.is_present,
        is_tombstone=raw.is_tombstone,
        observed_at=raw.observed_at,
        recorded_at=_at(4),
        source_valid_until=raw.valid_until,
        ttl_valid_until=_at(15),
        valid_until=_at(15),
        raw_observation_id=raw.observation_id,
        raw_observation_version=raw.observation_version,
        raw_observation_identity_hash=raw.identity_hash,
        raw_observation_content_hash=raw.content_hash,
        raw_observation_observed_at=raw.observed_at,
        raw_observation_valid_until=raw.valid_until,
    )


def _dto(*, terminal: bool = False) -> ExactPhysicalSimulatedAccountRowV2:
    source = _source(terminal=terminal)
    return ExactPhysicalSimulatedAccountRowV2(
        source_id=source.source_id,
        source_version=source.source_version,
        identity_hash=source.identity_hash,
        content_hash=source.content_hash,
        source_supersedes_content_hash=source.supersedes_content_hash,
        account_namespace=source.account_namespace,
        account_id=source.account_id,
        underlying_unified_account_namespace=(source.underlying_unified_account_namespace),
        underlying_unified_account_id=source.underlying_unified_account_id,
        row_user_id=source.row_user_id,
        raw_account_type=source.raw_account_type,
        is_active=source.is_active,
        row_created_at=source.row_created_at,
        row_updated_at=source.row_updated_at,
        is_present=source.is_present,
        is_tombstone=source.is_tombstone,
        observed_at=source.observed_at,
        recorded_at=source.recorded_at,
        source_valid_until=source.source_valid_until,
        ttl_valid_until=source.ttl_valid_until,
        valid_until=source.valid_until,
        raw_observation_id=source.raw_observation_id,
        raw_observation_version=source.raw_observation_version,
        raw_observation_identity_hash=source.raw_observation_identity_hash,
        raw_observation_content_hash=source.raw_observation_content_hash,
        raw_observation_supersedes_content_hash=(source.raw_observation_supersedes_content_hash),
        raw_observation_observed_at=source.raw_observation_observed_at,
        raw_observation_valid_until=source.raw_observation_valid_until,
    )


class _Provider:
    def __init__(self, values: list[ExactPhysicalSimulatedAccountRowV2 | None]) -> None:
        self.values = values
        self.final_calls: list[dict[str, object]] = []
        self.current_calls: list[dict[str, object]] = []

    def _pop(self) -> ExactPhysicalSimulatedAccountRowV2 | None:
        return self.values.pop(0) if len(self.values) > 1 else self.values[0]

    def get_exact_final(self, **kwargs: object) -> ExactPhysicalSimulatedAccountRowV2 | None:
        self.final_calls.append(kwargs)
        return self._pop()

    def get_exact_current(self, **kwargs: object) -> ExactPhysicalSimulatedAccountRowV2 | None:
        self.current_calls.append(kwargs)
        return self._pop()


class _Repository:
    def __init__(self) -> None:
        self.clock = _at(5)
        self.winner: PersistedPhysicalAccountRowObservationV2 | None = None
        self.head: PersistedPhysicalAccountRowObservationV2 | None = None
        self.appended: list[tuple[PersistedPhysicalAccountRowObservationV2, str | None]] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return self.clock

    def get_winner(self, **kwargs: object) -> PersistedPhysicalAccountRowObservationV2 | None:
        return self.winner

    def get_current_head(self, **kwargs: object) -> PersistedPhysicalAccountRowObservationV2 | None:
        return self.head

    def append(
        self,
        record: PersistedPhysicalAccountRowObservationV2,
        *,
        expected_predecessor_hash: str | None,
        recorded_at: datetime,
    ) -> PersistedPhysicalAccountRowObservationV2:
        self.appended.append((record, expected_predecessor_hash))
        self.winner = self.head = record
        return record

    def get_exact_by_hash(
        self, **kwargs: object
    ) -> PersistedPhysicalAccountRowObservationV2 | None:
        return self.winner


def _command(
    value: ExactPhysicalSimulatedAccountRowV2,
) -> CapturePhysicalAccountRowObservationV2Command:
    return CapturePhysicalAccountRowObservationV2Command(
        observation_id="physical-account-row-7",
        observation_version="capture-v1",
        source_id=value.source_id,
        source_version=value.source_version,
        expected_source_content_hash=value.content_hash,
        account_namespace=value.account_namespace,
        account_id=value.account_id,
        underlying_unified_account_namespace=value.underlying_unified_account_namespace,
        underlying_unified_account_id=value.underlying_unified_account_id,
    )


def _use_case(
    provider: _Provider,
    repository: _Repository,
) -> CapturePhysicalAccountRowObservationV2:
    return CapturePhysicalAccountRowObservationV2(
        row_provider=provider,
        repository=repository,
        recorder=PhysicalAccountRowObservationV2Recorder(
            recorder_id="account-v2-projector",
            service_name="account",
        ),
        validity_period=timedelta(days=5),
    )


def test_capture_double_reads_exact_final_at_one_cutoff_and_seals_all_layers() -> None:
    value = _dto()
    provider = _Provider([value])
    repository = _Repository()

    observation = _use_case(provider, repository).execute(_command(value))

    assert len(provider.final_calls) == 2
    assert not provider.current_calls
    assert {call["as_of"] for call in provider.final_calls} == {_at(5)}
    assert observation.source_content_hash == value.content_hash
    assert observation.raw_observation_content_hash == value.raw_observation_content_hash
    assert observation.source_recorded_at == value.recorded_at
    assert observation.recorded_at == _at(5)
    assert repository.appended[0][1] is None


def test_capture_allows_terminal_final_evidence_without_using_current_provider() -> None:
    value = _dto(terminal=True)
    provider = _Provider([value])
    repository = _Repository()

    observation = _use_case(provider, repository).execute(_command(value))

    assert observation.is_tombstone is True
    assert observation.is_present is False
    assert len(provider.final_calls) == 2
    assert not provider.current_calls


def test_capture_fails_when_same_cutoff_double_read_changes() -> None:
    first = _dto()
    second = replace(first, is_active=False)
    provider = _Provider([first, second])

    with pytest.raises(PhysicalAccountRowObservationV2Conflict, match="changed"):
        _use_case(provider, _Repository()).execute(_command(first))


def test_exact_and_current_reads_are_closed_by_full_expected_observation() -> None:
    value = _dto()
    provider = _Provider([value])
    repository = _Repository()
    observation = _use_case(provider, repository).execute(_command(value))

    exact = GetExactPhysicalAccountRowObservationV2(repository).execute(
        GetExactPhysicalAccountRowObservationV2Command(
            observation_id=observation.observation_id,
            observation_version=observation.observation_version,
            expected_content_hash=observation.content_hash,
            as_of=_at(6),
        )
    )
    current = GetCurrentPhysicalAccountRowObservationV2(
        repository=repository,
        row_provider=provider,
    ).execute(
        GetCurrentPhysicalAccountRowObservationV2Command(
            expected_observation=observation,
            as_of=_at(6),
        )
    )

    assert exact is observation
    assert current is observation
    assert provider.current_calls[-1]["expected_content_hash"] == value.content_hash


def test_current_never_falls_back_when_owner_current_read_is_missing() -> None:
    value = _dto()
    repository = _Repository()
    observation = _use_case(_Provider([value]), repository).execute(_command(value))

    result = GetCurrentPhysicalAccountRowObservationV2(
        repository=repository,
        row_provider=_Provider([None]),
    ).execute(
        GetCurrentPhysicalAccountRowObservationV2Command(
            expected_observation=observation,
            as_of=_at(6),
        )
    )

    assert result is None


def test_capture_command_contains_only_ids_hash_and_logical_selectors() -> None:
    assert set(CapturePhysicalAccountRowObservationV2Command.__dataclass_fields__) == {
        "observation_id",
        "observation_version",
        "source_id",
        "source_version",
        "expected_source_content_hash",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
    }
    recorder = PhysicalAccountRowObservationV2Recorder(
        recorder_id="account-v2-projector",
        service_name="account",
    )
    assert (recorder.role, recorder.kind, recorder.is_automated) == (
        "evidence_projector",
        "service",
        True,
    )
    with pytest.raises(ValueError, match="kind is fixed"):
        PhysicalAccountRowObservationV2Recorder(
            recorder_id="human-1",
            service_name="account",
            kind="human",
        )
