"""Tests for the owner-side Account physical-row provider."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading.application.simulated_account_row_source import (
    PersistedSimulatedAccountRowSource,
    SimulatedAccountRowSourceActor,
    SimulatedAccountRowSourceCorruption,
    SimulatedAccountRowSourceRepository,
)
from apps.simulated_trading.domain.simulated_account_row_source import (
    SimulatedAccountRowSource,
)
from apps.simulated_trading.infrastructure.account_physical_row_provider import (
    DjangoExactPhysicalSimulatedAccountRowProvider,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def _record(**changes: object) -> PersistedSimulatedAccountRowSource:
    values: dict[str, object] = {
        "source_id": "row-7",
        "source_version": "v1",
        "account_namespace": "account",
        "account_id": "0007",
        "underlying_unified_account_namespace": "simulated-account-row",
        "underlying_unified_account_id": 7,
        "row_user_id": 19,
        "raw_account_type": "real",
        "is_active": True,
        "row_created_at": NOW - timedelta(days=2),
        "row_updated_at": NOW - timedelta(hours=2),
        "is_present": True,
        "is_tombstone": False,
        "observed_at": NOW - timedelta(hours=1),
        "recorded_at": NOW - timedelta(minutes=30),
        "source_valid_until": NOW + timedelta(days=2),
        "ttl_valid_until": NOW + timedelta(days=1),
        "valid_until": NOW + timedelta(days=1),
    }
    values.update(changes)
    return PersistedSimulatedAccountRowSource(
        SimulatedAccountRowSource(**values),  # type: ignore[arg-type]
        SimulatedAccountRowSourceActor("staff:1", 1, "source_recorder"),
    )


class _Repository(SimulatedAccountRowSourceRepository):
    def __init__(
        self,
        winner: PersistedSimulatedAccountRowSource | None,
        head: PersistedSimulatedAccountRowSource | None,
    ) -> None:
        self.winner = winner
        self.head = head

    def atomic(self):  # type: ignore[no-untyped-def]
        return nullcontext()

    def now(self) -> datetime:
        return NOW

    def get_winner(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.winner

    def get_current_head(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.head

    def append(self, record, **kwargs):  # type: ignore[no-untyped-def]
        return record

    def get_exact_by_hash(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.winner


def _read(provider: DjangoExactPhysicalSimulatedAccountRowProvider):
    return provider.get_exact_current(
        source_id="row-7",
        source_version="v1",
        account_namespace="account",
        account_id="0007",
        underlying_unified_account_namespace="simulated-account-row",
        underlying_unified_account_id=7,
        as_of=NOW,
    )


def test_provider_maps_exact_current_source_without_rewriting_fields() -> None:
    record = _record()
    value = _read(DjangoExactPhysicalSimulatedAccountRowProvider(_Repository(record, record)))
    assert value is not None
    assert (
        value.source_id,
        value.source_version,
        value.content_hash,
        value.account_id,
        value.row_user_id,
        value.account_type,
        value.observed_at,
        value.valid_until,
    ) == (
        record.source.source_id,
        record.source.source_version,
        record.source.content_hash,
        record.source.account_id,
        record.source.row_user_id,
        record.source.raw_account_type,
        record.source.observed_at,
        record.source.valid_until,
    )


def test_provider_returns_none_for_missing_superseded_or_final_bad_head() -> None:
    record = _record()
    assert _read(DjangoExactPhysicalSimulatedAccountRowProvider(_Repository(None, None))) is None
    successor = _record(
        source_version="v2",
        recorded_at=NOW - timedelta(minutes=5),
        observed_at=NOW - timedelta(minutes=10),
        row_updated_at=NOW - timedelta(minutes=20),
        supersedes_content_hash=record.source.content_hash,
    )
    assert (
        _read(DjangoExactPhysicalSimulatedAccountRowProvider(_Repository(record, successor)))
        is None
    )
    tombstone = _record(is_present=False, is_tombstone=True)
    assert (
        _read(DjangoExactPhysicalSimulatedAccountRowProvider(_Repository(tombstone, tombstone)))
        is None
    )


def test_provider_rejects_selector_substitution() -> None:
    substituted = _record(account_id="0008")
    provider = DjangoExactPhysicalSimulatedAccountRowProvider(_Repository(substituted, substituted))

    with pytest.raises(
        SimulatedAccountRowSourceCorruption,
        match="selector substitution",
    ):
        _read(provider)
