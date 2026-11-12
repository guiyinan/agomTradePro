"""Pure contract tests for read-only two-portfolio comparison."""

from datetime import date

import pytest

from apps.simulated_trading.domain.entities import (
    CoverageInfo,
    PerformancePeriod,
    PerformanceRatios,
    PerformanceReport,
    PerformanceReturns,
    PerformanceRisk,
    TradeStats,
    ValuationTimelinePoint,
)
from apps.simulated_trading.domain.portfolio_comparison import (
    PortfolioComparisonAccount,
    PortfolioComparisonHolding,
    compare_portfolio_data,
)


def _report(twr: float | None, drawdown: float | None) -> PerformanceReport:
    return PerformanceReport(
        period=PerformancePeriod(start_date=date(2024, 1, 1), end_date=date(2024, 1, 3), days=2),
        returns=PerformanceReturns(
            twr=twr,
            mwr=twr,
            annualized_twr=twr,
            annualized_mwr=twr,
        ),
        risk=PerformanceRisk(
            volatility=12.0,
            downside_volatility=8.0,
            max_drawdown=drawdown,
        ),
        ratios=PerformanceRatios(sharpe=1.2, sortino=1.4, calmar=1.1, treynor=0.8),
        benchmark=None,
        trade_stats=TradeStats(win_rate=60.0, profit_factor=1.5, total_closed_trades=2),
        coverage=CoverageInfo(
            data_start=date(2024, 1, 1),
            data_end=date(2024, 1, 3),
            warnings=[],
        ),
        warnings=[],
    )


def _point(day: int, twr: float | None) -> ValuationTimelinePoint:
    return ValuationTimelinePoint(
        date=date(2024, 1, day),
        cash=50.0,
        market_value=50.0,
        total_value=100.0,
        net_value=1.0,
        twr_cumulative=twr,
        drawdown=0.0,
    )


def test_comparison_builds_metrics_normalized_curve_and_holding_differences() -> None:
    result = compare_portfolio_data(
        left_account=PortfolioComparisonAccount(account_id=1, account_name="稳健组合"),
        right_account=PortfolioComparisonAccount(account_id=2, account_name="进取组合"),
        left_report=_report(10.0, 8.0),
        right_report=_report(6.0, 12.0),
        left_timeline=[_point(1, 0.0), _point(2, 10.0)],
        right_timeline=[_point(1, 0.0), _point(3, 5.0)],
        left_holdings=[
            PortfolioComparisonHolding("A", "甲", "科技", 60.0),
            PortfolioComparisonHolding("B", "乙", "银行", 40.0),
        ],
        right_holdings=[
            PortfolioComparisonHolding("A", "甲", "科技", 30.0),
            PortfolioComparisonHolding("C", "丙", "银行", 70.0),
        ],
    )

    assert result.outcome == "success"
    assert result.relative_twr_percentage_points == pytest.approx(4.0)
    metrics = {row.key: row for row in result.metrics}
    assert metrics["twr"].left == 10.0
    assert metrics["twr"].right == 6.0
    assert metrics["max_drawdown"].difference == pytest.approx(-4.0)
    assert [(point.date.isoformat(), point.left, point.right) for point in result.curve] == [
        ("2024-01-01", 100.0, 100.0),
        ("2024-01-02", 110.0, None),
        ("2024-01-03", None, 105.0),
    ]
    assert result.holdings.overlap_percentage == pytest.approx(30.0)
    assert result.holdings.shared_count == 1
    assert result.holdings.left_only_count == 1
    assert result.holdings.right_only_count == 1
    holding_rows = {row.asset_code: row for row in result.holdings.rows}
    assert holding_rows["A"].left_weight_percentage == pytest.approx(60.0)
    assert holding_rows["A"].right_weight_percentage == pytest.approx(30.0)
    assert holding_rows["B"].right_weight_percentage is None
    sector_rows = {row.industry: row for row in result.holdings.industry_rows}
    assert sector_rows["科技"].difference_percentage_points == pytest.approx(30.0)
    assert sector_rows["银行"].difference_percentage_points == pytest.approx(-30.0)


def test_comparison_preserves_unknown_valuation_and_missing_history() -> None:
    result = compare_portfolio_data(
        left_account=PortfolioComparisonAccount(account_id=1, account_name="组合甲"),
        right_account=PortfolioComparisonAccount(account_id=2, account_name="组合乙"),
        left_report=_report(None, None),
        right_report=_report(3.0, 5.0),
        left_timeline=[_point(1, None)],
        right_timeline=[],
        left_holdings=[PortfolioComparisonHolding("A", "甲", None, None)],
        right_holdings=[PortfolioComparisonHolding("A", "甲", "科技", 100.0)],
    )

    assert result.outcome == "partial"
    assert result.relative_twr_percentage_points is None
    assert result.holdings.overlap_percentage is None
    assert result.holdings.valuation_known is False
    assert result.holdings.rows[0].left_weight_percentage is None
    industry_rows = {row.industry: row for row in result.holdings.industry_rows}
    assert industry_rows["行业未知"].left_weight_percentage is None
    assert industry_rows["科技"].right_weight_percentage == pytest.approx(100.0)
    assert result.curve[0].left is None
    assert result.curve[0].right is None
    assert "组合乙没有所选区间的净值历史" in result.warnings


def test_comparison_rejects_same_account() -> None:
    account = PortfolioComparisonAccount(account_id=1, account_name="同一组合")
    with pytest.raises(ValueError, match="两个不同的投资组合"):
        compare_portfolio_data(
            left_account=account,
            right_account=account,
            left_report=_report(1.0, 1.0),
            right_report=_report(1.0, 1.0),
            left_timeline=[],
            right_timeline=[],
            left_holdings=[],
            right_holdings=[],
        )
