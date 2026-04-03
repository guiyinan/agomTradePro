"""
账户业绩 Domain 层单元测试

覆盖：
- TWR / MWR / XIRR 公式
- 最大回撤与空样本处理
- 组合基准加权收益
- Sharpe / Sortino / Calmar / Beta / Alpha / IR / TE / Treynor
- Win rate / Profit factor
- BenchmarkComponent、PerformanceReport 等实体构造
"""
import math
from datetime import date, timedelta

import pytest

from apps.simulated_trading.domain.entities import (
    BenchmarkComponent,
    BenchmarkStats,
    CashFlowType,
    CoverageInfo,
    PerformancePeriod,
    PerformanceRatios,
    PerformanceReport,
    PerformanceReturns,
    PerformanceRisk,
    TradeStats,
    UnifiedAccountCashFlow,
    ValuationRow,
    ValuationSnapshot,
    ValuationTimelinePoint,
    AccountValuationSummary,
)
from apps.simulated_trading.domain.services import PerformanceCalculatorService


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def _make_values(amounts: list[float], start: date | None = None) -> list[tuple[date, float]]:
    start = start or date(2024, 1, 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(amounts)]


# ---------------------------------------------------------------------------
# PerformanceCalculatorService.calculate_twr
# ---------------------------------------------------------------------------


class TestCalculateTWR:
    def test_simple_growth(self):
        """100 → 110: TWR = 10%"""
        values = _make_values([100.0, 110.0])
        result = PerformanceCalculatorService.calculate_twr(values)
        assert result == pytest.approx(10.0, abs=1e-6)

    def test_two_periods(self):
        """100 → 110 → 115.5: TWR = 1.1 * 1.05 - 1 = 15.5%"""
        values = _make_values([100.0, 110.0, 115.5])
        result = PerformanceCalculatorService.calculate_twr(values)
        assert result == pytest.approx(15.5, abs=1e-4)

    def test_with_cashflow(self):
        """
        V0=100, 第二天注入20，V1=125:
        sub_period = (125 - 100 - 20) / 100 = 5%
        """
        values = _make_values([100.0, 125.0])
        cfs = [(_make_values([100.0, 125.0])[1][0], 20.0)]
        result = PerformanceCalculatorService.calculate_twr(values, cfs)
        assert result == pytest.approx(5.0, abs=1e-6)

    def test_insufficient_data_returns_none(self):
        values = _make_values([100.0])
        assert PerformanceCalculatorService.calculate_twr(values) is None

    def test_empty_returns_none(self):
        assert PerformanceCalculatorService.calculate_twr([]) is None

    def test_negative_return(self):
        """100 → 90: TWR = -10%"""
        values = _make_values([100.0, 90.0])
        result = PerformanceCalculatorService.calculate_twr(values)
        assert result == pytest.approx(-10.0, abs=1e-6)


# ---------------------------------------------------------------------------
# PerformanceCalculatorService.calculate_annualized_twr
# ---------------------------------------------------------------------------


class TestAnnualizedTWR:
    def test_one_year(self):
        """10% over 365 days → 10% annualized"""
        result = PerformanceCalculatorService.calculate_annualized_twr(10.0, 365)
        assert result == pytest.approx(10.0, abs=0.01)

    def test_half_year(self):
        """10% over 182 days → ~(1.1)^2 - 1 ≈ 21%"""
        result = PerformanceCalculatorService.calculate_annualized_twr(10.0, 182)
        assert result is not None
        assert result > 10.0  # 年化高于区间收益

    def test_zero_days_returns_none(self):
        assert PerformanceCalculatorService.calculate_annualized_twr(10.0, 0) is None


# ---------------------------------------------------------------------------
# PerformanceCalculatorService.calculate_xirr
# ---------------------------------------------------------------------------


class TestXIRR:
    def test_simple_one_year_10_pct(self):
        """投入100，一年后取出110: XIRR ≈ 10%"""
        cf = [(date(2024, 1, 1), 100.0)]
        result = PerformanceCalculatorService.calculate_xirr(cf, 110.0, date(2025, 1, 1))
        assert result is not None
        assert result == pytest.approx(10.0, abs=0.1)

    def test_two_deposits(self):
        """两次投入，验证可以收敛"""
        cfs = [
            (date(2024, 1, 1), 100.0),
            (date(2024, 7, 1), 50.0),
        ]
        result = PerformanceCalculatorService.calculate_xirr(cfs, 165.0, date(2025, 1, 1))
        assert result is not None
        assert isinstance(result, float)

    def test_no_cashflows_returns_none(self):
        result = PerformanceCalculatorService.calculate_xirr([], 110.0, date(2025, 1, 1))
        assert result is None


# ---------------------------------------------------------------------------
# Max Drawdown
# ---------------------------------------------------------------------------


class TestMaxDrawdown:
    def test_clear_drawdown(self):
        """100 → 120 → 96: max drawdown = (120-96)/120 = 20%"""
        values = _make_values([100.0, 120.0, 96.0])
        result = PerformanceCalculatorService.calculate_max_drawdown(values)
        assert result == pytest.approx(20.0, abs=1e-4)

    def test_no_drawdown(self):
        """单调上涨时回撤为 0"""
        values = _make_values([100.0, 110.0, 120.0, 130.0])
        result = PerformanceCalculatorService.calculate_max_drawdown(values)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_empty_returns_none(self):
        assert PerformanceCalculatorService.calculate_max_drawdown([]) is None

    def test_single_point_returns_none(self):
        assert PerformanceCalculatorService.calculate_max_drawdown(_make_values([100.0])) is None

    def test_multiple_drawdowns_picks_max(self):
        """选最大的回撤"""
        values = _make_values([100.0, 90.0, 100.0, 80.0])
        result = PerformanceCalculatorService.calculate_max_drawdown(values)
        assert result == pytest.approx(20.0, abs=1e-4)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


class TestVolatility:
    def test_constant_returns_zero_vol(self):
        """固定收益率时波动率为 0"""
        returns = [0.01] * 50
        result = PerformanceCalculatorService.calculate_volatility(returns)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_insufficient_returns_none(self):
        assert PerformanceCalculatorService.calculate_volatility([]) is None
        assert PerformanceCalculatorService.calculate_volatility([0.01]) is None

    def test_positive_volatility(self):
        returns = [0.01, -0.01, 0.02, -0.02, 0.005]
        result = PerformanceCalculatorService.calculate_volatility(returns)
        assert result is not None
        assert result > 0

    def test_downside_volatility_ignores_positive(self):
        """下行波动率只统计负收益"""
        returns = [0.05, 0.05, 0.05, -0.01]  # 大量正收益，1 次负收益
        dv = PerformanceCalculatorService.calculate_downside_volatility(returns)
        # 只有 1 个负收益点，少于 2 个，返回 None
        assert dv is None

    def test_downside_volatility_computed(self):
        returns = [0.05, -0.01, -0.02, -0.03]
        dv = PerformanceCalculatorService.calculate_downside_volatility(returns)
        assert dv is not None
        assert dv > 0


# ---------------------------------------------------------------------------
# Sharpe / Sortino / Calmar
# ---------------------------------------------------------------------------


class TestRatios:
    RF = PerformanceCalculatorService.RISK_FREE_RATE * 100.0

    def test_sharpe_positive(self):
        ann_ret = self.RF + 10.0
        vol = 15.0
        s = PerformanceCalculatorService.calculate_sharpe(ann_ret, vol)
        assert s == pytest.approx(10.0 / 15.0, abs=1e-6)

    def test_sharpe_zero_vol_returns_none(self):
        assert PerformanceCalculatorService.calculate_sharpe(10.0, 0.0) is None

    def test_sortino_positive(self):
        ann_ret = self.RF + 10.0
        dv = 8.0
        s = PerformanceCalculatorService.calculate_sortino(ann_ret, dv)
        assert s == pytest.approx(10.0 / 8.0, abs=1e-6)

    def test_calmar(self):
        result = PerformanceCalculatorService.calculate_calmar(20.0, 10.0)
        assert result == pytest.approx(2.0, abs=1e-6)

    def test_calmar_zero_drawdown_returns_none(self):
        assert PerformanceCalculatorService.calculate_calmar(20.0, 0.0) is None

    def test_treynor(self):
        ann_ret = self.RF + 10.0
        beta = 1.2
        expected = 10.0 / 1.2
        result = PerformanceCalculatorService.calculate_treynor(ann_ret, beta)
        assert result == pytest.approx(expected, abs=1e-6)

    def test_treynor_zero_beta_returns_none(self):
        assert PerformanceCalculatorService.calculate_treynor(10.0, 0.0) is None


# ---------------------------------------------------------------------------
# Beta / Alpha
# ---------------------------------------------------------------------------


class TestBetaAlpha:
    def test_beta_one_when_identical(self):
        returns = [0.01, -0.01, 0.02, -0.02]
        beta, alpha = PerformanceCalculatorService.calculate_beta_alpha(
            returns, returns, 10.0, 10.0
        )
        assert beta == pytest.approx(1.0, abs=1e-6)
        assert alpha == pytest.approx(0.0, abs=1e-6)

    def test_insufficient_data(self):
        beta, alpha = PerformanceCalculatorService.calculate_beta_alpha([], [], 10.0, 10.0)
        assert beta is None
        assert alpha is None

    def test_zero_benchmark_variance_returns_none(self):
        constant_bm = [0.0, 0.0, 0.0]
        portfolio = [0.01, 0.02, 0.03]
        beta, alpha = PerformanceCalculatorService.calculate_beta_alpha(
            portfolio, constant_bm, 10.0, 0.0
        )
        assert beta is None


# ---------------------------------------------------------------------------
# Tracking Error / Information Ratio
# ---------------------------------------------------------------------------


class TestTrackingErrorIR:
    def test_zero_te_when_identical(self):
        r = [0.01, -0.01, 0.02]
        te = PerformanceCalculatorService.calculate_tracking_error(r, r)
        assert te == pytest.approx(0.0, abs=1e-6)

    def test_ir_computed(self):
        ir = PerformanceCalculatorService.calculate_information_ratio(5.0, 2.5)
        assert ir == pytest.approx(2.0, abs=1e-6)

    def test_ir_zero_te_returns_none(self):
        assert PerformanceCalculatorService.calculate_information_ratio(5.0, 0.0) is None


# ---------------------------------------------------------------------------
# Win Rate / Profit Factor
# ---------------------------------------------------------------------------


class TestWinRateProfitFactor:
    def test_all_wins(self):
        pnls = [100.0, 200.0, 50.0]
        win_rate, pf = PerformanceCalculatorService.calculate_win_rate_profit_factor(pnls)
        assert win_rate == pytest.approx(100.0)
        assert pf is None  # 无亏损，profit_factor 无意义

    def test_all_losses(self):
        pnls = [-100.0, -50.0]
        win_rate, pf = PerformanceCalculatorService.calculate_win_rate_profit_factor(pnls)
        assert win_rate == pytest.approx(0.0)
        assert pf == pytest.approx(0.0, abs=1e-6)

    def test_mixed(self):
        pnls = [100.0, -50.0]
        win_rate, pf = PerformanceCalculatorService.calculate_win_rate_profit_factor(pnls)
        assert win_rate == pytest.approx(50.0)
        assert pf == pytest.approx(2.0, abs=1e-6)  # 100 / 50

    def test_empty_returns_none(self):
        wr, pf = PerformanceCalculatorService.calculate_win_rate_profit_factor([])
        assert wr is None
        assert pf is None


# ---------------------------------------------------------------------------
# Weighted Benchmark Return
# ---------------------------------------------------------------------------


class TestWeightedBenchmarkReturn:
    def test_single_component(self):
        result = PerformanceCalculatorService.calculate_weighted_benchmark_return([(1.0, 10.0)])
        assert result == pytest.approx(10.0)

    def test_two_components_equal_weight(self):
        result = PerformanceCalculatorService.calculate_weighted_benchmark_return([(0.5, 10.0), (0.5, 20.0)])
        assert result == pytest.approx(15.0)

    def test_empty_returns_none(self):
        assert PerformanceCalculatorService.calculate_weighted_benchmark_return([]) is None

    def test_zero_total_weight_returns_none(self):
        assert PerformanceCalculatorService.calculate_weighted_benchmark_return([(0.0, 10.0)]) is None


# ---------------------------------------------------------------------------
# Domain Entities 构造验证
# ---------------------------------------------------------------------------


class TestDomainEntities:
    def test_benchmark_component(self):
        bc = BenchmarkComponent(
            account_id=1,
            benchmark_code="000300.SH",
            weight=0.6,
            display_name="沪深300",
            sort_order=0,
        )
        assert bc.account_id == 1
        assert bc.weight == 0.6
        assert bc.is_active is True  # 默认值

    def test_unified_account_cash_flow(self):
        cf = UnifiedAccountCashFlow(
            flow_id=1,
            account_id=2,
            flow_type=CashFlowType.INITIAL_CAPITAL,
            amount=100000.0,
            flow_date=date(2024, 1, 1),
            source_app="simulated_trading",
        )
        assert cf.flow_type == CashFlowType.INITIAL_CAPITAL
        assert cf.amount == 100000.0

    def test_valuation_row(self):
        row = ValuationRow(
            asset_code="000001.SZ",
            asset_name="平安银行",
            asset_type="equity",
            quantity=1000.0,
            avg_cost=10.5,
            close_price=11.0,
            market_value=11000.0,
            weight=0.25,
            unrealized_pnl=500.0,
            unrealized_pnl_pct=4.76,
        )
        assert row.market_value == 11000.0

    def test_performance_report_frozen(self):
        """PerformanceReport 必须是 frozen（不可变）"""
        period = PerformancePeriod(start_date=date(2024, 1, 1), end_date=date(2024, 12, 31), days=365)
        report = PerformanceReport(
            period=period,
            returns=PerformanceReturns(twr=10.0, mwr=9.5, annualized_twr=10.0, annualized_mwr=9.5),
            risk=PerformanceRisk(volatility=15.0, downside_volatility=10.0, max_drawdown=5.0),
            ratios=PerformanceRatios(sharpe=1.2, sortino=1.8, calmar=2.0, treynor=None),
            benchmark=None,
            trade_stats=TradeStats(win_rate=60.0, profit_factor=1.5, total_closed_trades=10),
            coverage=CoverageInfo(data_start=date(2024, 1, 1), data_end=date(2024, 12, 31), warnings=[]),
            warnings=[],
        )
        with pytest.raises((AttributeError, TypeError)):
            report.warnings = ["mutated"]  # type: ignore[misc]

    def test_valuation_timeline_point(self):
        pt = ValuationTimelinePoint(
            date=date(2024, 6, 1),
            cash=10000.0,
            market_value=90000.0,
            total_value=100000.0,
            net_value=1.0,
            twr_cumulative=0.0,
            drawdown=0.0,
        )
        assert pt.total_value == 100000.0

    def test_account_valuation_summary(self):
        summary = AccountValuationSummary(
            total_value=100000.0,
            cash=20000.0,
            market_value=80000.0,
            unrealized_pnl=5000.0,
            unrealized_pnl_pct=6.67,
        )
        assert summary.cash + summary.market_value == pytest.approx(summary.total_value)


# ---------------------------------------------------------------------------
# 日收益率序列构造
# ---------------------------------------------------------------------------


class TestBuildDailyReturns:
    def test_simple(self):
        values = _make_values([100.0, 105.0, 100.0])
        returns = PerformanceCalculatorService.build_daily_returns(values)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(0.05, abs=1e-6)
        assert returns[1] == pytest.approx(-5.0 / 105.0, abs=1e-6)

    def test_with_cashflow_excluded(self):
        """现金流应从分子扣除"""
        d = date(2024, 1, 2)
        values = [(date(2024, 1, 1), 100.0), (d, 120.0)]
        cfs = [(d, 15.0)]
        returns = PerformanceCalculatorService.build_daily_returns(values, cfs)
        # (120 - 100 - 15) / 100 = 5%
        assert returns[0] == pytest.approx(0.05, abs=1e-6)
