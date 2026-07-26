"""Macro ORM model contract regressions."""

from datetime import date

import pytest

from apps.macro.infrastructure.models import MacroIndicator


@pytest.mark.parametrize(
    ("period_type", "expected_label"),
    [
        ("D", "日"),
        ("M", "月"),
        ("3M", "3月期"),
        ("10Y", "10年期"),
        ("CUSTOM", "CUSTOM"),
    ],
)
def test_period_type_display_preserves_standard_extended_and_unknown_values(
    period_type: str,
    expected_label: str,
) -> None:
    indicator = MacroIndicator(period_type=period_type)

    assert indicator.get_period_type_display() == expected_label


@pytest.mark.parametrize("period_type", ["3M", "10Y", "24M", "2Y"])
def test_numeric_month_and_year_durations_are_term_data(period_type: str) -> None:
    indicator = MacroIndicator(period_type=period_type)

    assert indicator.is_term_data is True


@pytest.mark.parametrize("period_type", ["D", "M", "Y", "CUSTOM", "FAMILY", ""])
def test_non_duration_period_types_are_not_term_data(period_type: str) -> None:
    indicator = MacroIndicator(period_type=period_type)

    assert indicator.is_term_data is False


def test_reporting_date_aliases_preserve_date_value() -> None:
    reporting_period = date(2026, 7, 26)
    indicator = MacroIndicator(reporting_period=reporting_period)

    assert indicator.reporting_date == reporting_period
    assert indicator.observed_at == reporting_period
