from datetime import date
from decimal import Decimal

from apps.equity.domain.entities import TechnicalBar
from apps.equity.domain.services_technical import TechnicalChartService


def _build_bar(
    trade_date: date,
    open_price: str,
    high_price: str,
    low_price: str,
    close_price: str,
    ma5: str | None,
    ma20: str | None,
    macd: float | None = None,
    macd_signal: float | None = None,
    macd_hist: float | None = None,
) -> TechnicalBar:
    return TechnicalBar(
        stock_code="000001.SZ",
        trade_date=trade_date,
        open=Decimal(open_price),
        high=Decimal(high_price),
        low=Decimal(low_price),
        close=Decimal(close_price),
        volume=1000,
        amount=Decimal("1000000"),
        ma5=Decimal(ma5) if ma5 is not None else None,
        ma20=Decimal(ma20) if ma20 is not None else None,
        ma60=None,
        macd=macd,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        rsi=None,
    )


def test_technical_chart_service_aggregates_weekly_bars():
    service = TechnicalChartService()
    bars = [
        _build_bar(date(2026, 3, 2), "10.0", "10.5", "9.8", "10.2", "10.0", "10.4"),
        _build_bar(date(2026, 3, 3), "10.2", "10.8", "10.1", "10.6", "10.1", "10.3"),
        _build_bar(date(2026, 3, 4), "10.6", "11.0", "10.4", "10.9", "10.3", "10.2"),
    ]

    aggregated = service.aggregate_bars(bars, "week")

    assert len(aggregated) == 1
    weekly_bar = aggregated[0]
    assert weekly_bar.open == Decimal("10.0")
    assert weekly_bar.close == Decimal("10.9")
    assert weekly_bar.high == Decimal("11.0")
    assert weekly_bar.low == Decimal("9.8")
    assert weekly_bar.ma5 is None
    assert weekly_bar.ma20 is None


def test_technical_chart_service_recalculates_weekly_indicators_from_aggregated_closes():
    service = TechnicalChartService()
    bars = [
        _build_bar(date(2026, 1, 5), "10.0", "10.5", "9.8", "10.0", "99.0", "99.0"),
        _build_bar(date(2026, 1, 12), "10.8", "11.0", "10.5", "11.0", "99.0", "99.0"),
        _build_bar(date(2026, 1, 19), "11.2", "11.8", "11.0", "12.0", "99.0", "99.0"),
        _build_bar(date(2026, 1, 26), "12.1", "12.7", "12.0", "13.0", "99.0", "99.0"),
        _build_bar(date(2026, 2, 2), "13.1", "13.8", "13.0", "14.0", "99.0", "99.0"),
    ]

    aggregated = service.aggregate_bars(bars, "week")

    assert len(aggregated) == 5
    assert aggregated[-1].ma5 == Decimal("12")
    assert aggregated[-1].ma20 is None
    assert aggregated[-1].macd is not None
    assert aggregated[-1].macd_signal is not None
    assert aggregated[-1].macd_hist is not None


def test_technical_chart_service_detects_golden_and_death_cross():
    service = TechnicalChartService()
    bars = [
        _build_bar(date(2026, 3, 2), "10.0", "10.5", "9.8", "10.1", "9.8", "10.0"),
        _build_bar(date(2026, 3, 3), "10.1", "10.8", "10.0", "10.7", "10.2", "10.0"),
        _build_bar(date(2026, 3, 4), "10.7", "10.9", "10.2", "10.3", "9.9", "10.1"),
    ]

    signals = service.detect_crossovers(bars)

    assert [signal.signal_type for signal in signals] == ["golden_cross", "death_cross"]
    assert signals[0].label == "MA5 上穿 MA20"
    assert signals[1].label == "MA5 下穿 MA20"
