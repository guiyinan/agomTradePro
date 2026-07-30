"""Exchange-rate freshness domain rules."""

from datetime import date

import pytest

from apps.account.domain.services import assess_exchange_rate_freshness


def test_exchange_rate_freshness_accepts_recent_business_day_observation() -> None:
    assessment = assess_exchange_rate_freshness(
        effective_date=date(2026, 7, 24),
        as_of_date=date(2026, 7, 27),
        max_business_days=1,
    )

    assert assessment.freshness_status == "fresh"
    assert assessment.staleness_days == 1
    assert assessment.is_stale is False
    assert assessment.must_not_use_for_decision is False
    assert assessment.blocked_reason == ""


def test_exchange_rate_freshness_blocks_stale_observation() -> None:
    assessment = assess_exchange_rate_freshness(
        effective_date=date(2026, 7, 23),
        as_of_date=date(2026, 7, 27),
        max_business_days=1,
    )

    assert assessment.freshness_status == "stale"
    assert assessment.staleness_days == 2
    assert assessment.is_stale is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.blocked_reason == "exchange_rate_stale"


def test_exchange_rate_freshness_blocks_future_dated_observation() -> None:
    assessment = assess_exchange_rate_freshness(
        effective_date=date(2026, 7, 28),
        as_of_date=date(2026, 7, 27),
    )

    assert assessment.freshness_status == "future"
    assert assessment.staleness_days == 0
    assert assessment.is_stale is True
    assert assessment.must_not_use_for_decision is True
    assert assessment.blocked_reason == "exchange_rate_future_dated"


@pytest.mark.parametrize("max_business_days", [-1, True])
def test_exchange_rate_freshness_rejects_invalid_threshold(
    max_business_days: int,
) -> None:
    with pytest.raises(ValueError, match="max_business_days"):
        assess_exchange_rate_freshness(
            effective_date=date(2026, 7, 27),
            as_of_date=date(2026, 7, 27),
            max_business_days=max_business_days,
        )
