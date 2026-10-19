"""Unit checks for the explicitly synthetic calendar sample selector."""

from datetime import date

import pytest

from tests.playwright.tests.uat.m5_calendar_fixture import (
    _select_synthetic_sample_session,
)


@pytest.mark.parametrize(
    ("coverage_end", "expected_session"),
    (
        (date(2026, 10, 19), date(2026, 10, 16)),  # Monday avoids a Sunday sample.
        (date(2026, 10, 24), date(2026, 10, 23)),  # Saturday run chooses Friday.
        (date(2026, 10, 25), date(2026, 10, 23)),  # Sunday run also chooses Friday.
    ),
)
def test_synthetic_sample_is_weekday_shaped_for_weekday_and_weekend_runs(
    coverage_end: date, expected_session: date
) -> None:
    """Synthetic samples avoid weekend-shaped dates without claiming market truth."""

    selected = _select_synthetic_sample_session(
        date(2026, 9, 1),
        coverage_end,
    )

    assert selected == expected_session
    assert selected.weekday() < 5


def test_synthetic_sample_fails_when_window_contains_only_weekend_date() -> None:
    """An unusable synthetic window must fail instead of inventing a session."""

    with pytest.raises(ValueError, match="no weekday-shaped sample"):
        _select_synthetic_sample_session(date(2026, 10, 24), date(2026, 10, 25))
