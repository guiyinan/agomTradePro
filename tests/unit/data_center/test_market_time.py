"""China-market date boundary contracts."""

from datetime import UTC, date, datetime

import pytest

from apps.data_center.domain.market_time import (
    cn_market_date_from_observation,
    cn_market_date_start_utc,
)


def test_cn_market_date_start_maps_local_midnight_to_previous_utc_day() -> None:
    """A mainland market date starts eight hours before UTC midnight."""

    assert cn_market_date_start_utc(date(2026, 8, 9)) == datetime(2026, 8, 8, 16, tzinfo=UTC)


def test_cn_market_date_projection_preserves_post_midnight_market_day() -> None:
    """An evening UTC observation belongs to the following China-market date."""

    assert cn_market_date_from_observation(datetime(2026, 8, 8, 16, 30, tzinfo=UTC)) == date(
        2026, 8, 9
    )


def test_cn_market_date_projection_rejects_naive_timestamp() -> None:
    """A missing timezone cannot be guessed at a decision-data boundary."""

    with pytest.raises(ValueError, match="timezone-aware"):
        cn_market_date_from_observation(datetime(2026, 8, 8, 16, 30))
