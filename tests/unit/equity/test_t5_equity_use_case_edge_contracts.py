"""High-value orchestration and validation contracts for equity use cases."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.equity.application import use_cases
from apps.equity.application.use_cases import (
    ComprehensiveValuationRequest,
    ComprehensiveValuationUseCase,
    GetIntradayChartRequest,
    GetIntradayChartUseCase,
    GetTechnicalChartRequest,
    GetTechnicalChartUseCase,
    ScreenStocksRequest,
    ScreenStocksUseCase,
)
from apps.equity.domain import services_comprehensive_valuation
from apps.equity.domain.entities import (
    FinancialData,
    IntradayPricePoint,
    ScoringWeightConfig,
    StockInfo,
    TechnicalBar,
    ValuationMetrics,
)
from apps.equity.domain.rules import StockScreeningRule


def _stock() -> StockInfo:
    return StockInfo(
        stock_code="600000.SH",
        name="浦发银行",
        sector="银行",
        market="SH",
        list_date=date(1999, 11, 10),
    )


def _financial() -> FinancialData:
    return FinancialData(
        stock_code="600000.SH",
        report_date=date(2025, 12, 31),
        revenue=Decimal("100"),
        net_profit=Decimal("20"),
        revenue_growth=10.0,
        net_profit_growth=12.0,
        total_assets=Decimal("1000"),
        total_liabilities=Decimal("400"),
        equity=Decimal("600"),
        roe=15.0,
        roa=5.0,
        debt_ratio=40.0,
    )


def _valuation(*, pe: float = 10.0, pb: float = 1.2) -> ValuationMetrics:
    return ValuationMetrics(
        stock_code="600000.SH",
        trade_date=date(2026, 7, 24),
        pe=pe,
        pb=pb,
        ps=1.0,
        total_mv=Decimal("1000000000"),
        circ_mv=Decimal("800000000"),
        dividend_yield=3.0,
    )


@pytest.mark.parametrize(
    ("helper", "payload", "message"),
    [
        (use_cases._custom_float, {"value": True}, "numeric"),
        (use_cases._custom_float, {"value": "bad"}, "numeric"),
        (use_cases._custom_float, {"value": "nan"}, "finite"),
        (use_cases._custom_decimal, {"value": False}, "numeric"),
        (use_cases._custom_decimal, {"value": "bad"}, "numeric"),
        (use_cases._custom_decimal, {"value": "-1"}, "non-negative"),
        (use_cases._custom_count, {"value": True}, "integer"),
        (use_cases._custom_count, {"value": "bad"}, "integer"),
        (use_cases._custom_count, {"value": "101"}, "between"),
    ],
)
def test_custom_screening_numeric_helpers_reject_invalid_values(
    helper: object,
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        helper(payload, "value", 1)  # type: ignore[operator]


def test_custom_screening_helpers_apply_defaults_and_normalize_sectors() -> None:
    assert use_cases._custom_float({}, "value", 1.5) == 1.5
    assert use_cases._custom_float({"value": "2.5"}, "value", 0.0) == 2.5
    assert use_cases._custom_decimal({}, "value", Decimal("2")) == Decimal("2")
    assert use_cases._custom_decimal(
        {"value": "3.5"}, "value", Decimal("0")
    ) == Decimal("3.5")
    assert use_cases._custom_count({}, "value", 3) == 3
    assert use_cases._custom_count({"value": "4"}, "value", 1) == 4
    assert use_cases._custom_sectors({}) is None
    assert use_cases._custom_sectors(
        {"sector_preference": [" 银行 ", "", "科技"]}
    ) == ["银行", "科技"]
    with pytest.raises(ValueError, match="array of strings"):
        use_cases._custom_sectors({"sector_preference": ["银行", 1]})


def test_screen_stocks_serializes_ranked_matches_and_custom_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule = StockScreeningRule(regime="Recovery", name="default")
    monkeypatch.setattr(use_cases, "get_stock_screening_rule", lambda _regime: rule)
    config_repo = SimpleNamespace(get_active_config=lambda: ScoringWeightConfig(name="test"))
    monkeypatch.setattr(
        use_cases,
        "get_equity_scoring_weight_config_repository",
        lambda: config_repo,
    )
    screener = MagicMock()
    screener.screen.return_value = ["600000.SH", "missing"]
    monkeypatch.setattr(use_cases, "StockScreener", lambda **_kwargs: screener)
    stock_repo = SimpleNamespace(
        get_all_stocks_with_fundamentals=lambda: [
            (_stock(), _financial(), _valuation())
        ]
    )

    response = ScreenStocksUseCase(stock_repo, object()).execute(
        ScreenStocksRequest(
            regime="Recovery",
            custom_rule={
                "name": "custom",
                "min_roe": "8",
                "min_market_cap": "1",
                "sector_preference": ["银行"],
                "max_count": "5",
            },
            max_count=2,
        )
    )

    assert response.success is True
    assert response.stock_codes == ["600000.SH", "missing"]
    assert response.items[0]["rank"] == 1
    assert response.items[0]["name"] == "浦发银行"
    assert response.screening_criteria["rule_name"] == "custom"


def test_screen_stocks_rejects_invalid_request_and_rule_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(use_cases, "get_stock_screening_rule", lambda _regime: None)
    use_case = ScreenStocksUseCase(MagicMock(), object())
    assert use_case.execute(ScreenStocksRequest(regime="Recovery", max_count=0)).success is False
    assert use_case.execute(ScreenStocksRequest(regime="Recovery")).success is False
    with pytest.raises(ValueError, match="name must be a string"):
        use_case._parse_custom_rule({"name": 7}, "Recovery")


def test_technical_and_intraday_charts_serialize_success_and_failures() -> None:
    bar = TechnicalBar(
        stock_code="600000.SH",
        trade_date=date(2026, 7, 24),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=100,
        amount=Decimal("1000"),
        ma5=Decimal("10"),
        ma20=None,
        ma60=None,
        macd=1.0,
        macd_signal=0.5,
        macd_hist=0.5,
        rsi=60.0,
    )
    signal = SimpleNamespace(
        signal_type="golden_cross",
        trade_date=date(2026, 7, 24),
        price=Decimal("10.5"),
        short_value=Decimal("10"),
        long_value=Decimal("9.8"),
        label="金叉",
    )
    repository = MagicMock()
    repository.get_stock_info.return_value = _stock()
    repository.get_technical_bars.return_value = [bar]
    technical = GetTechnicalChartUseCase(repository)
    technical.chart_service = SimpleNamespace(
        aggregate_bars=lambda bars, timeframe: bars,
        detect_crossovers=lambda bars: [signal],
    )
    response = technical.execute(
        GetTechnicalChartRequest(
            stock_code="600000.SH", timeframe="week", lookback_days=30
        )
    )
    assert response.success is True
    assert response.candles[0]["ma20"] is None
    assert response.latest_signal == response.signals[0]
    assert technical._resolve_technical_lookback_days("month", 30) == 2000
    assert technical._resolve_technical_lookback_days("day", 30) == 30

    repository.get_stock_info.return_value = None
    assert technical.execute(GetTechnicalChartRequest("missing")).success is False

    point = IntradayPricePoint(
        stock_code="600000.SH",
        timestamp=datetime(2026, 7, 24, 9, 30, tzinfo=UTC),
        price=Decimal("10"),
        avg_price=None,
        volume=None,
    )
    repository.get_stock_info.return_value = _stock()
    repository.get_intraday_points.return_value = [point]
    repository.get_last_intraday_source.return_value = None
    intraday = GetIntradayChartUseCase(repository)
    intraday_response = intraday.execute(GetIntradayChartRequest("600000.SH"))
    assert intraday_response.success is True
    assert intraday_response.latest_point == intraday_response.points[0]
    assert intraday_response.source == "akshare"
    repository.get_intraday_points.return_value = []
    assert intraday.execute(GetIntradayChartRequest("600000.SH")).success is False


def test_comprehensive_valuation_serializes_analyzer_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    score = SimpleNamespace(
        method="pe",
        score=88.0,
        signal="undervalued",
        details={"percentile": 0.2},
    )
    result = SimpleNamespace(
        stock_code="600000.SH",
        overall_score=88.0,
        overall_signal="undervalued",
        recommendation="buy",
        confidence=0.9,
        scores=[score],
    )
    analyzer = SimpleNamespace(analyze=MagicMock(return_value=result))
    monkeypatch.setattr(
        services_comprehensive_valuation,
        "ComprehensiveValuationAnalyzer",
        lambda: analyzer,
    )
    repository = MagicMock()
    repository.get_stock_info.return_value = _stock()
    repository.get_latest_financial_data.return_value = _financial()
    repository.get_valuation_history.return_value = [
        _valuation(pe=-1.0, pb=-1.0),
        _valuation(),
    ]

    response = ComprehensiveValuationUseCase(repository).execute(
        ComprehensiveValuationRequest(stock_code="600000.SH")
    )

    assert response.success is True
    assert response.stock_name == "浦发银行"
    assert response.scores == [
        {
            "method": "pe",
            "score": 88.0,
            "signal": "undervalued",
            "details": {"percentile": 0.2},
        }
    ]
    assert analyzer.analyze.call_args.kwargs["historical_pe"] == [10.0]
