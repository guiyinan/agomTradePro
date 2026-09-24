"""Trading-calendar evidence must prove every requested calendar member."""

from datetime import date

import pandas as pd
import pytest

from apps.data_center.infrastructure.tushare_model_market_source import TushareModelMarketSource
from core.exceptions import DataFetchError


class CalendarClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def trade_cal(self, **kwargs: object) -> pd.DataFrame:
        self.calls.append(kwargs)
        return pd.DataFrame(self.rows)


def test_complete_calendar_binds_closed_days_source_and_coverage() -> None:
    client = CalendarClient(
        [
            {"cal_date": "20260923", "is_open": "1"},
            {"cal_date": "20260924", "is_open": "1"},
            {"cal_date": "20260925", "is_open": "0"},
        ]
    )
    source = TushareModelMarketSource(client, source="configured-tushare")

    evidence = source.trading_calendar_evidence(date(2026, 9, 23), date(2026, 9, 25))

    assert evidence.open_sessions == (date(2026, 9, 23), date(2026, 9, 24))
    assert evidence.coverage_start == date(2026, 9, 23)
    assert evidence.coverage_end == date(2026, 9, 25)
    assert evidence.source == "configured-tushare"
    assert "is_open" not in client.calls[0]


def test_numeric_zero_is_a_valid_closed_session_state() -> None:
    source = TushareModelMarketSource(
        CalendarClient(
            [
                {"cal_date": "20260924", "is_open": 1},
                {"cal_date": "20260925", "is_open": 0},
            ]
        )
    )

    evidence = source.trading_calendar_evidence(date(2026, 9, 24), date(2026, 9, 25))

    assert evidence.open_sessions == (date(2026, 9, 24),)


def test_truncated_calendar_is_rejected_instead_of_manufacturing_coverage() -> None:
    source = TushareModelMarketSource(CalendarClient([{"cal_date": "20260923", "is_open": "1"}]))

    with pytest.raises(DataFetchError) as caught:
        source.trading_calendar_evidence(date(2026, 9, 23), date(2026, 9, 25))

    assert caught.value.code == "MODEL_MARKET_CALENDAR_COVERAGE_INCOMPLETE"


def test_conflicting_calendar_state_is_rejected() -> None:
    source = TushareModelMarketSource(
        CalendarClient(
            [
                {"cal_date": "20260923", "is_open": "1"},
                {"cal_date": "20260923", "is_open": "0"},
            ]
        )
    )

    with pytest.raises(DataFetchError) as caught:
        source.trading_calendar_evidence(date(2026, 9, 23), date(2026, 9, 23))

    assert caught.value.code == "MODEL_MARKET_CALENDAR_CONFLICT"
