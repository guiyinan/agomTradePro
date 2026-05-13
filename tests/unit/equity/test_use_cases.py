from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from apps.equity.application.use_cases import (
    AnalyzeRegimeCorrelationUseCase,
    AnalyzeValuationRequest,
    AnalyzeValuationUseCase,
    ComprehensiveValuationRequest,
    ComprehensiveValuationUseCase,
    ScreenStocksRequest,
    ScreenStocksUseCase,
)
from apps.equity.domain.entities import FinancialData, StockInfo, ValuationMetrics


def test_screen_stocks_returns_failure_response_when_repository_raises(mocker) -> None:
    stock_repo = mocker.Mock()
    stock_repo.get_all_stocks_with_fundamentals.side_effect = ValueError("stocks unavailable")
    regime_repo = mocker.Mock()
    mocker.patch(
        "apps.equity.application.use_cases.get_stock_screening_rule",
        return_value=SimpleNamespace(
            regime="Recovery",
            name="default",
            min_roe=0.0,
            min_revenue_growth=0.0,
            min_profit_growth=0.0,
            max_debt_ratio=100.0,
            max_pe=100.0,
            max_pb=10.0,
            min_market_cap=0,
            sector_preference=None,
            max_count=30,
        ),
    )

    response = ScreenStocksUseCase(stock_repo, regime_repo).execute(
        ScreenStocksRequest(regime="Recovery")
    )

    assert response.success is False
    assert response.stock_codes == []
    assert response.error == "stocks unavailable"


def test_regime_history_returns_empty_dict_when_repository_fails(mocker) -> None:
    use_case = AnalyzeRegimeCorrelationUseCase(mocker.Mock(), mocker.Mock())
    regime_repo = mocker.Mock()
    regime_repo.get_snapshots_in_range.side_effect = ValueError("regime down")
    mocker.patch(
        "apps.equity.application.use_cases.get_equity_regime_repository",
        return_value=regime_repo,
    )

    result = use_case._get_regime_history(
        start_date=SimpleNamespace(),
        end_date=SimpleNamespace(),
    )

    assert result == {}


def test_market_returns_returns_empty_dict_when_market_adapter_fails(mocker) -> None:
    use_case = AnalyzeRegimeCorrelationUseCase(mocker.Mock(), mocker.Mock())
    market_repo = mocker.Mock()
    market_repo.get_index_daily_returns.side_effect = ValueError("market down")
    mocker.patch(
        "apps.equity.application.use_cases.get_equity_market_data_repository",
        return_value=market_repo,
    )
    mocker.patch(
        "core.integration.runtime_benchmarks.get_runtime_benchmark_code",
        return_value="000300.SH",
    )

    result = use_case._get_market_returns(
        start_date=SimpleNamespace(),
        end_date=SimpleNamespace(),
    )

    assert result == {}


def test_comprehensive_valuation_returns_failure_response_when_financial_missing(mocker) -> None:
    stock_repo = mocker.Mock()
    stock_repo.get_stock_info.return_value = SimpleNamespace(name="贵州茅台")
    stock_repo.get_latest_financial_data.return_value = None

    response = ComprehensiveValuationUseCase(stock_repo).execute(
        ComprehensiveValuationRequest(stock_code="600519.SH")
    )

    assert response.success is False
    assert response.stock_code == "600519.SH"
    assert "财务数据" in response.error


class _FakeStockRepository:
    def __init__(
        self,
        *,
        valuation_history_cached,
        valuation_history_hydrated,
        financial_cached,
        financial_hydrated,
        daily_prices_cached,
        daily_prices_hydrated,
    ) -> None:
        self.valuation_history_cached = valuation_history_cached
        self.valuation_history_hydrated = valuation_history_hydrated
        self.financial_cached = financial_cached
        self.financial_hydrated = financial_hydrated
        self.daily_prices_cached = daily_prices_cached
        self.daily_prices_hydrated = daily_prices_hydrated
        self.calls: list[tuple[str, bool]] = []

    def get_stock_info(self, stock_code: str) -> StockInfo:
        return StockInfo(
            stock_code=stock_code,
            name="测试股票",
            sector="电子",
            market="SZ",
            list_date=date(2020, 1, 2),
        )

    def get_valuation_history(self, *args, hydrate: bool = False, **kwargs):
        self.calls.append(("valuation", hydrate))
        return self.valuation_history_hydrated if hydrate else self.valuation_history_cached

    def get_latest_financial_data(self, *args, hydrate: bool = False, **kwargs):
        self.calls.append(("financial", hydrate))
        return self.financial_hydrated if hydrate else self.financial_cached

    def get_daily_prices(self, *args, hydrate: bool = False, **kwargs):
        self.calls.append(("daily_prices", hydrate))
        return self.daily_prices_hydrated if hydrate else self.daily_prices_cached


def _build_valuation_metrics(stock_code: str, trade_date: date) -> ValuationMetrics:
    return ValuationMetrics(
        stock_code=stock_code,
        trade_date=trade_date,
        pe=18.5,
        pb=3.2,
        ps=2.4,
        total_mv=Decimal("1000000000"),
        circ_mv=Decimal("800000000"),
        dividend_yield=1.2,
        fetched_at=datetime(2026, 5, 13, 9, 30, tzinfo=timezone.utc),
    )


def _build_financial_data(stock_code: str, report_date: date) -> FinancialData:
    return FinancialData(
        stock_code=stock_code,
        report_date=report_date,
        revenue=Decimal("100000000"),
        net_profit=Decimal("10000000"),
        revenue_growth=12.5,
        net_profit_growth=8.2,
        total_assets=Decimal("500000000"),
        total_liabilities=Decimal("200000000"),
        equity=Decimal("300000000"),
        roe=14.8,
        roa=4.3,
        debt_ratio=40.0,
        period_end=report_date,
        period_type="annual",
        source="test",
        fetched_at=datetime(2026, 5, 13, 9, 35, tzinfo=timezone.utc),
    )


def test_analyze_valuation_prefers_cached_payloads_before_hydration() -> None:
    valuation = _build_valuation_metrics("002493.SZ", date(2026, 5, 12))
    financial = _build_financial_data("002493.SZ", date(2025, 12, 31))
    repo = _FakeStockRepository(
        valuation_history_cached=[valuation],
        valuation_history_hydrated=[valuation],
        financial_cached=financial,
        financial_hydrated=financial,
        daily_prices_cached=[(date(2026, 5, 12), Decimal("19.88"))],
        daily_prices_hydrated=[(date(2026, 5, 13), Decimal("20.01"))],
    )

    response = AnalyzeValuationUseCase(stock_repository=repo).execute(
        AnalyzeValuationRequest(stock_code="002493.SZ", lookback_days=252)
    )

    assert response.success is True
    assert response.stock_name == "测试股票"
    assert response.latest_valuation is not None
    assert response.latest_valuation["price"] == 19.88
    assert repo.calls == [
        ("valuation", False),
        ("financial", False),
        ("daily_prices", False),
    ]


def test_analyze_valuation_hydrates_only_when_cached_payload_missing() -> None:
    valuation = _build_valuation_metrics("002493.SZ", date(2026, 5, 12))
    financial = _build_financial_data("002493.SZ", date(2025, 12, 31))
    repo = _FakeStockRepository(
        valuation_history_cached=[],
        valuation_history_hydrated=[valuation],
        financial_cached=None,
        financial_hydrated=financial,
        daily_prices_cached=[],
        daily_prices_hydrated=[(date(2026, 5, 12), Decimal("19.88"))],
    )

    response = AnalyzeValuationUseCase(stock_repository=repo).execute(
        AnalyzeValuationRequest(stock_code="002493.SZ", lookback_days=252)
    )

    assert response.success is True
    assert response.latest_valuation is not None
    assert response.latest_valuation["price"] == 19.88
    assert repo.calls == [
        ("valuation", False),
        ("valuation", True),
        ("financial", False),
        ("financial", True),
        ("daily_prices", False),
        ("daily_prices", True),
    ]
