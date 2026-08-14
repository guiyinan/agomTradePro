from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.account.application.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2Corruption,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
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
from apps.simulated_trading.infrastructure.account_physical_row_v2_provider import (
    DjangoExactPhysicalSimulatedAccountRowV2Provider,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _raw(**changes: object) -> SimulatedAccountRawObservation:
    values: dict[str, object] = {
        "observation_id": "simulated-account-row-7",
        "observation_version": "event-v1",
        "row_pk": 7,
        "row_user_id": 42,
        "raw_account_type": "PAPER",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=20),
        "row_updated_at": NOW - timedelta(hours=2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": NOW - timedelta(hours=1),
        "valid_until": NOW + timedelta(days=2),
    }
    values.update(changes)
    return SimulatedAccountRawObservation(**values)  # type: ignore[arg-type]


def _record(**changes: object) -> PersistedSimulatedAccountRowSourceV2:
    raw = cast(SimulatedAccountRawObservation | None, changes.pop("raw", None)) or _raw()
    values: dict[str, object] = {
        "source_id": raw.observation_id,
        "source_version": raw.observation_version,
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": raw.row_pk,
        "row_user_id": raw.row_user_id,
        "raw_account_type": raw.raw_account_type,
        "is_active": raw.is_active,
        "row_created_at": raw.row_created_at,
        "row_updated_at": raw.row_updated_at,
        "is_present": raw.is_present,
        "is_tombstone": raw.is_tombstone,
        "observed_at": raw.observed_at,
        "recorded_at": NOW - timedelta(minutes=30),
        "source_valid_until": raw.valid_until,
        "ttl_valid_until": NOW + timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
        "raw_observation_id": raw.observation_id,
        "raw_observation_version": raw.observation_version,
        "raw_observation_identity_hash": raw.identity_hash,
        "raw_observation_content_hash": raw.content_hash,
        "raw_observation_observed_at": raw.observed_at,
        "raw_observation_valid_until": raw.valid_until,
        "raw_observation_supersedes_content_hash": raw.supersedes_content_hash,
    }
    values.update(changes)
    return PersistedSimulatedAccountRowSourceV2(
        SimulatedAccountRowSourceV2(**values)  # type: ignore[arg-type]
    )


class _Repository:
    def __init__(
        self,
        *,
        winner: PersistedSimulatedAccountRowSourceV2 | None = None,
        head: PersistedSimulatedAccountRowSourceV2 | None = None,
        error: ValueError | None = None,
    ) -> None:
        self.winner = winner
        self.head = head
        self.error = error
        self.winner_calls: list[tuple[str, str, datetime]] = []
        self.head_calls: list[tuple[object, ...]] = []

    def get_winner(
        self, *, source_id: str, source_version: str, as_of: datetime
    ) -> PersistedSimulatedAccountRowSourceV2 | None:
        self.winner_calls.append((source_id, source_version, as_of))
        if self.error is not None:
            raise self.error
        return self.winner

    def get_current_head(self, **kwargs: object) -> PersistedSimulatedAccountRowSourceV2 | None:
        self.head_calls.append(tuple(kwargs.values()))
        return self.head

    def atomic(self) -> object:
        raise AssertionError("read-only provider must not open a write UOW")

    def now(self) -> datetime:
        raise AssertionError("read-only provider must not fabricate a clock")

    def append(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("read-only provider must not append")

    def get_exact_by_hash(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("provider must use winner plus full logical head")


def _read(
    repository: _Repository,
    *,
    record: PersistedSimulatedAccountRowSourceV2 | None = None,
    current: bool = False,
    as_of: datetime = NOW,
):
    expected = record or _record()
    method = (
        DjangoExactPhysicalSimulatedAccountRowV2Provider(repository).get_exact_current
        if current
        else DjangoExactPhysicalSimulatedAccountRowV2Provider(repository).get_exact_final
    )
    source = expected.source
    return method(
        source_id=source.source_id,
        source_version=source.source_version,
        expected_content_hash=source.content_hash,
        account_namespace=source.account_namespace,
        account_id=source.account_id,
        underlying_unified_account_namespace=source.underlying_unified_account_namespace,
        underlying_unified_account_id=source.underlying_unified_account_id,
        as_of=as_of,
    )


def test_zero_rows_returns_none_without_reading_a_logical_head() -> None:
    repository = _Repository()
    assert _read(repository) is None
    assert repository.head_calls == []


def test_exact_winner_and_full_logical_head_maps_all_source_and_raw_seals() -> None:
    record = _record()
    repository = _Repository(winner=record, head=record)
    value = _read(repository, record=record)
    assert value is not None
    source = record.source
    assert (
        value.source_id,
        value.source_version,
        value.identity_hash,
        value.content_hash,
        value.source_supersedes_content_hash,
        value.recorded_at,
        value.source_valid_until,
        value.ttl_valid_until,
        value.valid_until,
    ) == (
        source.source_id,
        source.source_version,
        source.identity_hash,
        source.content_hash,
        source.supersedes_content_hash,
        source.recorded_at,
        source.source_valid_until,
        source.ttl_valid_until,
        source.valid_until,
    )
    assert (
        value.raw_observation_id,
        value.raw_observation_version,
        value.raw_observation_identity_hash,
        value.raw_observation_content_hash,
        value.raw_observation_supersedes_content_hash,
        value.raw_observation_observed_at,
        value.raw_observation_valid_until,
    ) == (
        source.raw_observation_id,
        source.raw_observation_version,
        source.raw_observation_identity_hash,
        source.raw_observation_content_hash,
        source.raw_observation_supersedes_content_hash,
        source.raw_observation_observed_at,
        source.raw_observation_valid_until,
    )
    assert repository.head_calls == [
        (
            source.source_id,
            source.account_namespace,
            source.account_id,
            source.underlying_unified_account_namespace,
            source.underlying_unified_account_id,
            NOW,
        )
    ]


def test_final_allows_terminal_tombstone_but_current_does_not() -> None:
    raw = _raw(is_active=False, is_present=False, is_tombstone=True)
    record = _record(raw=raw, is_active=False, is_present=False, is_tombstone=True)
    repository = _Repository(winner=record, head=record)
    assert _read(repository, record=record) is not None
    assert _read(repository, record=record, current=True) is None


def test_superseded_missing_and_expired_final_return_none_without_fallback() -> None:
    record = _record()
    other = _record(account_id="0008")
    assert _read(_Repository(winner=record, head=other), record=record) is None
    assert _read(_Repository(winner=record, head=None), record=record) is None
    assert (
        _read(
            _Repository(winner=record, head=record), record=record, as_of=record.source.valid_until
        )
        is None
    )


def test_selector_substitution_fails_closed_in_account_taxonomy() -> None:
    record = _record(account_id="0008")
    expected = _record()
    provider = DjangoExactPhysicalSimulatedAccountRowV2Provider(
        _Repository(winner=record, head=record)
    )
    with pytest.raises(PhysicalAccountRowObservationV2Corruption, match="selector"):
        provider.get_exact_final(
            source_id=expected.source.source_id,
            source_version=expected.source.source_version,
            expected_content_hash=record.source.content_hash,
            account_namespace=expected.source.account_namespace,
            account_id=expected.source.account_id,
            underlying_unified_account_namespace=(
                expected.source.underlying_unified_account_namespace
            ),
            underlying_unified_account_id=expected.source.underlying_unified_account_id,
            as_of=NOW,
        )


def test_record_type_substitution_fails_closed() -> None:
    invalid = cast(PersistedSimulatedAccountRowSourceV2, {})
    with pytest.raises(PhysicalAccountRowObservationV2Corruption, match="record type"):
        _read(_Repository(winner=invalid, head=invalid))


@pytest.mark.parametrize(
    "error",
    [
        SimulatedAccountRowSourceV2Conflict("ambiguous head"),
        SimulatedAccountRowSourceV2Corruption("bad ledger seal"),
    ],
)
def test_source_closed_world_failures_translate_to_account_corruption(error: ValueError) -> None:
    with pytest.raises(PhysicalAccountRowObservationV2Corruption, match="closed-world"):
        _read(_Repository(error=error))


def test_unavailable_cutoff_and_composition_remain_read_only() -> None:
    assert _read(_Repository(error=SimulatedAccountRowSourceV2Unavailable("future"))) is None
    provider_source = Path(
        "apps/simulated_trading/infrastructure/account_physical_row_v2_provider.py"
    ).read_text(encoding="utf-8")
    composition_source = Path(
        "apps/simulated_trading/account_physical_row_v2_composition.py"
    ).read_text(encoding="utf-8")
    assert ".atomic(" not in provider_source
    assert ".append(" not in provider_source
    assert "CapturePhysicalAccountRowObservationV2" not in composition_source
    assert "CaptureSimulatedAccountRowSourceV2" not in composition_source
