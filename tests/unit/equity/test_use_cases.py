from types import SimpleNamespace

from apps.equity.application.use_cases import (
    AnalyzeRegimeCorrelationUseCase,
    ComprehensiveValuationRequest,
    ComprehensiveValuationUseCase,
    ScreenStocksRequest,
    ScreenStocksUseCase,
)


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
