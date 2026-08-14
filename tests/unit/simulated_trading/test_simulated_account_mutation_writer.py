from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading.application.simulated_account_raw_observation import (
    PersistedSimulatedAccountRawObservation,
    SimulatedAccountPhysicalRowMutation,
    SimulatedAccountRawObservationConflict,
)
from apps.simulated_trading.infrastructure.simulated_account_mutation_writer import (
    DjangoSimulatedAccountMutationWriter,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


class _Connection:
    in_atomic_block = True


class _Repository:
    database_alias = "owner"

    def __init__(self) -> None:
        self.records: list[PersistedSimulatedAccountRawObservation] = []

    def atomic(self) -> nullcontext[None]:
        return nullcontext()

    def now(self) -> datetime:
        return NOW

    def get_winner(self, *, observation_id: str, observation_version: str, as_of: datetime):
        del as_of
        return next(
            (
                record
                for record in self.records
                if record.observation.observation_id == observation_id
                and record.observation.observation_version == observation_version
            ),
            None,
        )

    def get_current_head(self, *, observation_id: str, row_pk: int, as_of: datetime):
        del as_of
        values = [
            record
            for record in self.records
            if record.observation.observation_id == observation_id
            and record.observation.row_pk == row_pk
        ]
        return values[-1] if values else None

    def get_physical_row_head(self, *, row_pk: int, as_of: datetime):
        del as_of
        values = [record for record in self.records if record.observation.row_pk == row_pk]
        return values[-1] if values else None

    def append(self, record, *, expected_predecessor_hash: str | None, recorded_at: datetime):
        assert record.observation.supersedes_content_hash == expected_predecessor_hash
        assert recorded_at == NOW
        self.records.append(record)
        return record

    def get_exact_by_hash(self, **kwargs: object):
        raise AssertionError("writer does not use historical reads")


def _mutation(version: str, minute: int = 0) -> SimulatedAccountPhysicalRowMutation:
    return SimulatedAccountPhysicalRowMutation(
        observation_id="opaque-row-stream-7",
        mutation_version=version,
        row_pk=7,
        row_user_id=19,
        raw_account_type="simulated",
        is_active=True,
        row_created_at=NOW - timedelta(days=2),
        row_updated_at=NOW - timedelta(minutes=10 - minute),
        observed_at=NOW - timedelta(minutes=5 - minute),
    )


def _writer(monkeypatch: pytest.MonkeyPatch, repository: _Repository):
    monkeypatch.setattr(
        "apps.simulated_trading.infrastructure.simulated_account_mutation_writer.connections",
        {"owner": _Connection()},
    )
    return DjangoSimulatedAccountMutationWriter(
        repository=repository,  # type: ignore[arg-type]
        using="owner",
        validity_period=timedelta(days=1),
    )


def test_create_update_delete_build_exact_cas_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _Repository()
    writer = _writer(monkeypatch, repository)
    created = writer.record_create(_mutation("event-1"))
    updated = writer.record_update(_mutation("event-2", 1))
    deleted = writer.record_delete(_mutation("event-3", 2))
    assert created.supersedes_content_hash is None
    assert updated.supersedes_content_hash == created.content_hash
    assert deleted.supersedes_content_hash == updated.content_hash
    assert (deleted.is_present, deleted.is_tombstone, deleted.is_active) == (False, True, False)


def test_same_event_replays_exact_first_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = _Repository()
    writer = _writer(monkeypatch, repository)
    first = writer.record_create(_mutation("event-1"))
    assert writer.record_create(_mutation("event-1")) == first
    assert len(repository.records) == 1


def test_requires_outer_transaction_alias_and_stable_opaque_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _Repository()
    writer = _writer(monkeypatch, repository)
    writer.record_create(_mutation("event-1"))
    changed = replace(_mutation("event-2", 1), observation_id="another-stream")
    with pytest.raises(SimulatedAccountRawObservationConflict, match="observation_id"):
        writer.record_update(changed)
    _Connection.in_atomic_block = False
    with pytest.raises(SimulatedAccountRawObservationConflict, match="transaction"):
        writer.record_update(_mutation("event-2", 1))
    _Connection.in_atomic_block = True
