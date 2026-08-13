from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.simulated_trading.application.simulated_account_raw_observation import (
    PersistedSimulatedAccountRawObservation,
    SimulatedAccountRawObservationCorruption,
    SimulatedAccountRawObservationUnavailable,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2Corruption,
)
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.infrastructure.simulated_account_raw_observation_v2_provider import (
    DjangoExactRawSimulatedAccountObservationV2Provider,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _observation(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-account-row-7",
        "observation_version": "event-v1",
        "row_pk": 7,
        "row_user_id": None,
        "raw_account_type": "SIMULATED",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=20),
        "row_updated_at": NOW - timedelta(minutes=2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(minutes=10),
    }
    values.update(changes)
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


def _record(
    observation: SimulatedAccountRawObservation | None = None,
) -> PersistedSimulatedAccountRawObservation:
    return PersistedSimulatedAccountRawObservation(
        observation=observation or _observation(),
        recorded_at=NOW - timedelta(seconds=30),
    )


class _Repository:
    def __init__(
        self,
        *,
        winner: PersistedSimulatedAccountRawObservation | None = None,
        head: PersistedSimulatedAccountRawObservation | None = None,
        error: ValueError | None = None,
    ) -> None:
        self.winner = winner
        self.head = head
        self.error = error
        self.winner_calls: list[tuple[str, str, datetime]] = []
        self.head_calls: list[tuple[str, int, datetime]] = []

    def atomic(self) -> nullcontext[None]:
        raise AssertionError("read-only provider must not open a write UOW")

    def now(self) -> datetime:
        raise AssertionError("read-only provider must not fabricate a clock")

    def get_winner(
        self,
        *,
        observation_id: str,
        observation_version: str,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None:
        self.winner_calls.append((observation_id, observation_version, as_of))
        if self.error is not None:
            raise self.error
        return self.winner

    def get_current_head(
        self,
        *,
        observation_id: str,
        row_pk: int,
        as_of: datetime,
    ) -> PersistedSimulatedAccountRawObservation | None:
        self.head_calls.append((observation_id, row_pk, as_of))
        return self.head

    def append(self, *args: object, **kwargs: object) -> PersistedSimulatedAccountRawObservation:
        raise AssertionError("read-only provider must not append")

    def get_exact_by_hash(
        self, *args: object, **kwargs: object
    ) -> PersistedSimulatedAccountRawObservation | None:
        raise AssertionError("provider must use winner plus logical head")


def _read(
    repository: _Repository,
    *,
    observation: SimulatedAccountRawObservation | None = None,
    as_of: datetime = NOW,
):
    expected = observation or _observation()
    return DjangoExactRawSimulatedAccountObservationV2Provider(repository).get_exact_current(
        observation_id=expected.observation_id,
        observation_version=expected.observation_version,
        expected_content_hash=expected.content_hash,
        row_pk=expected.row_pk,
        as_of=as_of,
    )


def test_zero_rows_returns_none_without_opening_a_writer_graph() -> None:
    repository = _Repository()
    assert _read(repository) is None
    assert repository.head_calls == []


def test_exact_first_winner_and_final_head_maps_every_field_unchanged() -> None:
    observation = _observation(row_user_id=42, raw_account_type="PAPER")
    record = _record(observation)
    repository = _Repository(winner=record, head=record)

    value = _read(repository, observation=observation)

    assert value is not None
    assert value.to_observation() == observation
    assert repository.winner_calls == [
        (observation.observation_id, observation.observation_version, NOW)
    ]
    assert repository.head_calls == [(observation.observation_id, 7, NOW)]


def test_superseded_missing_head_and_expired_final_return_none_without_fallback() -> None:
    first = _record()
    successor_observation = _observation(
        observation_version="event-v2",
        row_updated_at=NOW,
        observed_at=NOW,
        valid_until=NOW + timedelta(minutes=20),
        supersedes_content_hash=first.observation.content_hash,
    )
    successor = PersistedSimulatedAccountRawObservation(successor_observation, NOW)
    assert _read(_Repository(winner=first, head=successor)) is None
    assert _read(_Repository(winner=first, head=None)) is None

    expired_observation = _observation(valid_until=NOW)
    expired = PersistedSimulatedAccountRawObservation(
        expired_observation,
        NOW - timedelta(seconds=30),
    )
    assert _read(_Repository(winner=expired, head=expired), observation=expired_observation) is None


def test_tombstone_is_returned_as_an_exact_raw_fact() -> None:
    tombstone = _observation(is_active=False, is_present=False, is_tombstone=True)
    record = _record(tombstone)
    value = _read(_Repository(winner=record, head=record), observation=tombstone)
    assert value is not None
    assert value.is_tombstone is True
    assert value.is_present is False


def test_future_or_unavailable_cutoff_translates_to_none() -> None:
    repository = _Repository(
        error=SimulatedAccountRawObservationUnavailable("future PIT is forbidden")
    )
    assert _read(repository, as_of=NOW + timedelta(days=1)) is None


def test_selector_or_record_type_substitution_fails_closed() -> None:
    substituted = _observation(observation_id="simulated-account-row-8")
    record = _record(substituted)
    expected = _observation()
    provider = DjangoExactRawSimulatedAccountObservationV2Provider(
        _Repository(winner=record, head=record)
    )
    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="selector"):
        provider.get_exact_current(
            observation_id=expected.observation_id,
            observation_version=expected.observation_version,
            expected_content_hash=substituted.content_hash,
            row_pk=expected.row_pk,
            as_of=NOW,
        )

    invalid = _Repository(
        winner=cast(PersistedSimulatedAccountRawObservation, {}),
        head=cast(PersistedSimulatedAccountRawObservation, {}),
    )
    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="record type"):
        _read(invalid)


def test_closed_world_corruption_is_translated_to_v2_corruption() -> None:
    repository = _Repository(error=SimulatedAccountRawObservationCorruption("ledger seal invalid"))
    with pytest.raises(SimulatedAccountRowSourceV2Corruption, match="closed-world"):
        _read(repository)


def test_provider_and_composition_are_read_only_and_do_not_import_writer_use_cases() -> None:
    provider_source = Path(
        "apps/simulated_trading/infrastructure/simulated_account_raw_observation_v2_provider.py"
    ).read_text(encoding="utf-8")
    composition_source = Path("apps/simulated_trading/source_v2_composition.py").read_text(
        encoding="utf-8"
    )
    assert ".append(" not in provider_source
    assert ".atomic(" not in provider_source
    assert "RecordSimulatedAccountRawObservation" not in provider_source
    assert "CaptureSimulatedAccountRowSourceV2" not in composition_source
    assert "RecordSimulatedAccountRawObservation" not in composition_source
