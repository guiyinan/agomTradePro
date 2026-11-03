"""Focused contract tests for explicit source and policy acceptance bounds."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from apps.risk_center.application.portfolio_risk_policy_deadline import (
    earliest_portfolio_risk_acceptance_deadline,
)

_AS_OF = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)


def test_earliest_deadline_uses_minimum_actual_source_and_policy_bound() -> None:
    """An actual source expiry and existing policy deadlines compete by earliest."""

    policy_deadline = _AS_OF + timedelta(hours=3)
    source_expiry = _AS_OF + timedelta(hours=1)

    assert (
        earliest_portfolio_risk_acceptance_deadline(
            as_of=_AS_OF,
            policy_deadlines=(policy_deadline,),
            source_valid_until=source_expiry,
        )
        == source_expiry
    )


@pytest.mark.parametrize(
    "policy_deadlines, source_valid_until",
    [
        ((), None),
        ((_AS_OF,), None),
        ((_AS_OF - timedelta(seconds=1),), None),
        ((datetime(2026, 11, 3, 15, 0),), None),
        ((datetime(2026, 11, 3, 15, 0, tzinfo=UTC),), datetime(2026, 11, 3, 13, 0, tzinfo=UTC)),
    ],
)
def test_missing_or_expired_bounds_fail_closed(
    policy_deadlines: tuple[datetime, ...],
    source_valid_until: datetime | None,
) -> None:
    """An empty, naive or expired bound never manufactures an acceptance window."""

    assert (
        earliest_portfolio_risk_acceptance_deadline(
            as_of=_AS_OF,
            policy_deadlines=policy_deadlines,
            source_valid_until=source_valid_until,
        )
        is None
    )


def test_invalid_cutoff_or_policy_container_fails_closed() -> None:
    """Malformed clocks and untyped containers cannot produce a reusable deadline."""

    assert (
        earliest_portfolio_risk_acceptance_deadline(
            as_of=datetime(2026, 11, 3, 14, 0),
            policy_deadlines=(_AS_OF + timedelta(minutes=1),),
        )
        is None
    )
    assert (
        earliest_portfolio_risk_acceptance_deadline(
            as_of=_AS_OF,
            policy_deadlines=cast(tuple[datetime, ...], [_AS_OF + timedelta(minutes=1)]),
        )
        is None
    )
