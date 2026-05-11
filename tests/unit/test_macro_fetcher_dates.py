from apps.macro.infrastructure.adapters.fetchers.base_fetchers import parse_chinese_date
from apps.macro.infrastructure.adapters.fetchers.financial_fetchers import (
    parse_chinese_date as parse_financial_chinese_date,
)


def test_parse_chinese_month_returns_period_end_date():
    assert parse_chinese_date("2026年3月") == "2026-03-31"


def test_parse_chinese_month_handles_leap_year():
    assert parse_chinese_date("2024年2月") == "2024-02-29"


def test_parse_chinese_date_preserves_non_month_values():
    assert parse_chinese_date("2026-04-24") == "2026-04-24"


def test_financial_parse_chinese_month_returns_period_end_date():
    assert parse_financial_chinese_date("2026年3月") == "2026-03-31"
