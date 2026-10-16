"""Pure tests for exact execution quote TTL checks."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.infrastructure.execution_quote_freshness import (
    validate_execution_quote_member_freshness,
)


def test_execution_quote_observation_is_fresh_strictly_before_deadline() -> None:
    """The exact instant immediately before the deadline remains fresh."""

    observed_at = datetime(2026, 10, 16, 9, tzinfo=UTC)
    validate_execution_quote_member_freshness(
        (observed_at,),
        as_of=observed_at + timedelta(seconds=59, microseconds=999_999),
        execution_freshness_seconds=60,
    )


@pytest.mark.parametrize(
    ("observations", "as_of", "ttl"),
    (
        (
            (datetime(2026, 10, 16, 9, tzinfo=UTC),),
            datetime(2026, 10, 16, 9, 1, tzinfo=UTC),
            60,
        ),
        (
            (
                datetime(2026, 10, 16, 9, tzinfo=UTC),
                datetime(2026, 10, 16, 9, 0, 1, tzinfo=UTC),
            ),
            datetime(2026, 10, 16, 9, 1, 1, tzinfo=UTC),
            60,
        ),
        (
            (datetime(2026, 10, 16, 9, 0, 1, tzinfo=UTC),),
            datetime(2026, 10, 16, 9, tzinfo=UTC),
            60,
        ),
        (
            (datetime(2026, 10, 16, 9, tzinfo=UTC),),
            datetime(2026, 10, 16, 9, tzinfo=UTC),
            True,
        ),
    ),
)
def test_execution_quote_freshness_rejects_expired_future_and_invalid_ttl(
    observations: tuple[datetime, ...],
    as_of: datetime,
    ttl: int,
) -> None:
    """Expired, any-member-expired, future, and non-integer TTL evidence blocks."""

    with pytest.raises(ValueError):
        validate_execution_quote_member_freshness(
            observations,
            as_of=as_of,
            execution_freshness_seconds=ttl,
        )


def test_execution_quote_freshness_rejects_missing_naive_and_overflow_inputs() -> None:
    """Missing or malformed time evidence and unrepresentable deadlines fail closed."""

    with pytest.raises(ValueError, match="observation time is missing"):
        validate_execution_quote_member_freshness(
            (None,),
            as_of=datetime(2026, 10, 16, 9, tzinfo=UTC),
            execution_freshness_seconds=60,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_execution_quote_member_freshness(
            (datetime(2026, 10, 16, 9),),
            as_of=datetime(2026, 10, 16, 9, tzinfo=UTC),
            execution_freshness_seconds=60,
        )
    maximum = datetime.max.replace(tzinfo=UTC)
    with pytest.raises(ValueError, match="overflows"):
        validate_execution_quote_member_freshness(
            (maximum,),
            as_of=maximum,
            execution_freshness_seconds=1,
        )
