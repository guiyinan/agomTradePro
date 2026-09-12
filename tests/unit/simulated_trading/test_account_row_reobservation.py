"""Current row observation keeps source clocks and rejects identity drift."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRow,
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnership,
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)

NOW = datetime(2026, 9, 11, 1, tzinfo=UTC)


def _row():
    return CurrentAccountOwnership(
        7, 3, AccountType.REAL, True, NOW - timedelta(days=10), NOW - timedelta(days=2), NOW
    )


def _command():
    row = _row()
    return ReobserveExistingAccountRowCommand(
        observation_id="existing-row-chain",
        observation_version="new-observation",
        row_pk=row.row_pk,
        expected_user_id=3,
        expected_account_type=AccountType.REAL,
        expected_created_at=row.row_created_at,
        minimum_updated_at=row.row_updated_at,
    )


class Reader:
    database_alias = "isolated"

    def __init__(self, *rows):
        self.rows = list(rows)

    def read_locked(self, *, row_pk):
        assert row_pk == 7
        return self.rows.pop(0)


class Writer:
    database_alias = "isolated"

    def __init__(self, **overrides):
        self.calls = []
        self.overrides = overrides

    def record_update(self, mutation):
        self.calls.append(mutation)
        values = {
            "observation_id": mutation.observation_id,
            "observation_version": mutation.mutation_version,
            "row_pk": mutation.row_pk,
            "row_user_id": mutation.row_user_id,
            "raw_account_type": mutation.raw_account_type,
            "is_active": mutation.is_active,
            "row_created_at": mutation.row_created_at,
            "row_updated_at": mutation.row_updated_at,
            "observed_at": mutation.observed_at,
            "valid_until": mutation.observed_at + timedelta(minutes=5),
            "is_present": True,
            "is_tombstone": False,
            "supersedes_content_hash": "a" * 64,
        }
        values.update(self.overrides)
        return SimulatedAccountRawObservation(**values)


def test_observes_existing_row_without_rewriting_creation_or_update_time():
    row = _row()
    writer = Writer()
    service = ReobserveExistingAccountRow(
        reader=Reader(row, replace(row, observed_at=NOW + timedelta(seconds=1))), writer=writer
    )
    result = service.execute(_command())
    assert result.row_created_at == NOW - timedelta(days=10)
    assert result.row_updated_at == NOW - timedelta(days=2)
    assert result.observed_at == NOW
    assert result.supersedes_content_hash == "a" * 64
    assert len(writer.calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": 9},
        {"user_id": None},
        {"row_pk": 8},
        {"account_type": AccountType.SIMULATED},
        {"is_active": False},
        {"row_created_at": NOW - timedelta(days=9)},
        {"row_updated_at": NOW - timedelta(days=3)},
    ],
)
def test_mismatched_or_unavailable_source_cannot_be_recorded(changes):
    writer = Writer()
    service = ReobserveExistingAccountRow(reader=Reader(replace(_row(), **changes)), writer=writer)
    with pytest.raises(CurrentAccountOwnershipUnavailable):
        service.execute(_command())
    assert writer.calls == []


def test_missing_row_never_uses_old_evidence_as_a_fallback():
    writer = Writer()
    with pytest.raises(CurrentAccountOwnershipUnavailable):
        ReobserveExistingAccountRow(reader=Reader(None), writer=writer).execute(_command())
    assert writer.calls == []


@pytest.mark.parametrize(
    "changes", [{"user_id": 9}, {"is_active": False}, {"observed_at": NOW + timedelta(minutes=6)}]
)
def test_final_read_rejects_same_transaction_drift_or_expiry(changes):
    writer = Writer()
    with pytest.raises(CurrentAccountOwnershipUnavailable):
        ReobserveExistingAccountRow(
            reader=Reader(_row(), replace(_row(), **changes)), writer=writer
        ).execute(_command())
    assert len(writer.calls) == 1  # The outer transaction must roll this append back.


@pytest.mark.parametrize(
    "changes",
    [
        {"row_user_id": 8},
        {"observation_version": "other"},
        {"observed_at": NOW - timedelta(seconds=1)},
        {"supersedes_content_hash": None},
    ],
)
def test_writer_cannot_substitute_the_observed_snapshot(changes):
    with pytest.raises(CurrentAccountOwnershipUnavailable):
        ReobserveExistingAccountRow(
            reader=Reader(_row(), _row()), writer=Writer(**changes)
        ).execute(_command())


def test_mixed_database_aliases_fail_before_any_read():
    writer = Writer()
    writer.database_alias = "other"
    with pytest.raises(ValueError):
        ReobserveExistingAccountRow(reader=Reader(), writer=writer)


@pytest.mark.parametrize(
    "changes",
    [
        {"row_pk": True},
        {"expected_user_id": 0},
        {"observation_version": "bad key"},
        {"expected_account_type": "real"},
        {"expected_created_at": NOW.replace(tzinfo=None)},
    ],
)
def test_invalid_commands_are_rejected(changes):
    with pytest.raises((TypeError, ValueError)):
        replace(_command(), **changes)
