"""China-market date boundary contracts."""

from datetime import UTC, date, datetime

import pytest

from apps.data_center.domain.market_time import (
    CN_MARKET_TIMEZONE,
    cn_market_date_from_observation,
    cn_market_date_start_utc,
    cn_market_session_close_utc,
    latest_closed_cn_market_session,
)


def test_cn_market_date_start_maps_local_midnight_to_previous_utc_day() -> None:
    """A mainland market date starts eight hours before UTC midnight."""

    assert cn_market_date_start_utc(date(2026, 8, 9)) == datetime(2026, 8, 8, 16, tzinfo=UTC)


def test_cn_market_session_close_maps_to_official_close_in_utc() -> None:
    """Date-only daily facts use the completed session close as observation time."""

    assert cn_market_session_close_utc(date(2026, 9, 23)) == datetime(2026, 9, 23, 7, tzinfo=UTC)


def test_cn_market_date_projection_preserves_post_midnight_market_day() -> None:
    """An evening UTC observation belongs to the following China-market date."""

    assert cn_market_date_from_observation(datetime(2026, 8, 8, 16, 30, tzinfo=UTC)) == date(
        2026, 8, 9
    )


def test_cn_market_date_projection_rejects_naive_timestamp() -> None:
    """A missing timezone cannot be guessed at a decision-data boundary."""

    with pytest.raises(ValueError, match="timezone-aware"):
        cn_market_date_from_observation(datetime(2026, 8, 8, 16, 30))


def test_latest_closed_session_uses_previous_weekday_during_live_market() -> None:
    """A refresh started during trading targets the prior completed session."""

    live_market_time = datetime(2026, 9, 24, 10, 0, tzinfo=CN_MARKET_TIMEZONE)

    assert latest_closed_cn_market_session(
        live_market_time,
        open_sessions=(date(2026, 9, 23), date(2026, 9, 24)),
    ) == date(2026, 9, 23)


def test_latest_closed_session_skips_source_observed_holiday() -> None:
    """A weekday exchange holiday cannot become a manufactured market session."""

    holiday_time = datetime(2026, 9, 25, 16, 30, tzinfo=CN_MARKET_TIMEZONE)

    assert latest_closed_cn_market_session(
        holiday_time,
        open_sessions=(date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 28)),
    ) == date(2026, 9, 24)
