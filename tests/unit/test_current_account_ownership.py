"""Boundary checks for live ownership observations without ownership grants."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.simulated_trading.application.current_account_ownership import CurrentAccountOwnership
from apps.simulated_trading.domain.entities import AccountType


def _observation():
    now = datetime(2026, 9, 11, tzinfo=UTC)
    return CurrentAccountOwnership(1, 2, AccountType.SIMULATED, True, now, now, now)


@pytest.mark.parametrize(
    "field,value",
    [
        ("row_pk", True),
        ("row_pk", 0),
        ("user_id", True),
        ("user_id", -1),
        ("account_type", "simulated"),
        ("is_active", 1),
        ("observed_at", datetime(2026, 9, 11)),
    ],
)
def test_malformed_observations_reject(field, value):
    with pytest.raises((TypeError, ValueError)):
        replace(_observation(), **{field: value})


def test_nullable_owner_and_inactive_row_are_preserved():
    actual = replace(_observation(), user_id=None, is_active=False)
    assert actual.user_id is None and actual.is_active is False


def test_observation_never_relabels_future_source_or_backwards_update():
    current = _observation()
    with pytest.raises(ValueError, match="clock sequence"):
        replace(current, row_updated_at=current.observed_at + timedelta(microseconds=1))
    with pytest.raises(ValueError, match="clock sequence"):
        replace(current, row_created_at=current.row_updated_at + timedelta(microseconds=1))
