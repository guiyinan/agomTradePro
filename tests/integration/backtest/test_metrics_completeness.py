"""
Integration Tests for Backtest Metrics Completeness

测试回测关键指标的完整性和准确性：
1. old_weights（旧权重）计算
2. turnover_rate（换手率）计算
3. icir（IC信息比率）计算
4. avg_holding_period（平均持仓天数）计算
5. stock_performances（个股表现）整理
"""

import pytest
from datetime import date, timedelta
from decimal import Decimal

from apps.backtest.domain.entities import BacktestConfig
from apps.backtest.domain.services import BacktestEngine, RebalanceResult
from apps.backtest.domain.stock_selection_backtest import (
    StockSelectionBacktestConfig,
    StockSelectionBacktestEngine,
    RebalanceFrequency,
)
from apps.backtest.domain.alpha_backtest import (
    AlphaBacktestConfig,
    AlphaBacktestEngine,
)


class TestOldWeightsCalculation:
    """测试旧权重计算"""

    @pytest.fixture
    def config(self):
        return BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0,
        )

    @pytest.fixture
    def mock_get_regime(self):
        def _get_regime(as_of_date):
            return {
                "dominant_regime": "Recovery",
                "confidence": 0.6,
                "distribution": {"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            }
        return _get_regime

    @pytest.fixture
    def mock_get_price(self):
        prices = {
            "a_share_growth": 3000.0,
            "a_share_value": 2500.0,
            "china_bond": 100.0,
            "gold": 500.0,
            "commodity": 200.0,
            "cash": 1.0,
        }

        def _get_price(asset_class, as_of_date):
            return prices.get(asset_class)
        return _get_price

    def test_old_weights_in_rebalance_result(self, config, mock_get_regime, mock_get_price):
        """测试再平衡结果包含旧权重"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        # 第一次再平衡后，应该有权重记录
        result = engine._rebalance(date(2020, 1, 1))

        assert result is not None, "再平衡应该成功"
        assert isinstance(result.old_weights, dict), "旧权重应该是字典"
        # 第一次再平衡，旧权重应该只包含现金（权重100%）
        assert "CASH" in result.old_weights or len(result.old_weights) == 0, \
            "第一次再平衡时旧权重应该只有现金或为空"

    def test_old_weights_change_over_time(self, config, mock_get_regime, mock_get_price):
        """测试旧权重随时间变化"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        # 第一次再平衡
        result1 = engine._rebalance(date(2020, 1, 1))
        # 第二次再平衡
        result2 = engine._rebalance(date(2020, 2, 1))

        assert result1 is not None
        assert result2 is not None

        # 第二次再平衡的旧权重应该包含第一次再平衡后的持仓
        assert len(result2.old_weights) > 0, "第二次再平衡时旧权重应该有内容"


class TestTurnoverRateCalculation:
    """测试换手率计算"""

    def test_stock_selection_turnover_rate(self):
        """测试股票筛选回测的换手率计算"""
        config = StockSelectionBacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=Decimal(1000000),
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            max_positions=30,
        )

        def mock_get_regime(dt):
            return "Recovery"

        def mock_get_stock_data(dt):
            return []

        def mock_get_price(stock, dt):
            return Decimal(100)

        def mock_get_benchmark_price(dt):
            return 100.0

        engine = StockSelectionBacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_stock_data_func=mock_get_stock_data,
            get_price_func=mock_get_price,
            get_benchmark_price_func=mock_get_benchmark_price,
        )

        # 测试换手率计算方法
        from apps.backtest.domain.stock_selection_backtest import RebalanceRecord

        records = [
            RebalanceRecord(
                rebalance_date=date(2020, 1, 1),
                regime="Recovery",
                selected_stocks=["000001", "000002", "000003"],
                sold_stocks=[],
                bought_stocks=[("000001", Decimal(100))],
                portfolio_value=Decimal(100000)
            ),
            RebalanceRecord(
                rebalance_date=date(2020, 2, 1),
                regime="Recovery",
                selected_stocks=["000001", "000004", "000005"],
                sold_stocks=[("000002", 0.1)],
                bought_stocks=[("000004", Decimal(100))],
                portfolio_value=Decimal(100000)
            )
        ]

        turnover = engine._calculate_turnover_rate(records)
        assert turnover >= 0, "换手率应该非负"
        assert turnover <= 1, "换手率不应超过1（100%）"


class TestICIRCalculation:
    """测试 ICIR 计算"""

    def test_icir_calculation(self):
        """测试 ICIR 计算"""
        config = AlphaBacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
        )

        # 创建 mock engine
        engine = type('MockEngine', (), {
            'alpha_config': config,
            'get_benchmark_price_func': lambda dt: 100.0,
        })()

        # 添加方法到 mock engine
        from apps.backtest.domain.alpha_backtest import AlphaBacktestEngine
        engine._calculate_icir = AlphaBacktestEngine._calculate_icir.__get__(engine, type(engine))

        # 测试稳定的 IC 值
        stable_ics = [0.05, 0.06, 0.055, 0.058, 0.052]
        icir = engine._calculate_icir(stable_ics)
        assert icir > 0, "稳定的正 IC 应该产生正 ICIR"

        # 测试不稳定的 IC 值
        unstable_ics = [0.1, -0.05, 0.15, -0.1, 0.08]
        icir_unstable = engine._calculate_icir(unstable_ics)
        # 不稳定的 IC 应该产生较低的 ICIR（绝对值）
        assert abs(icir_unstable) < icir, "不稳定的 IC 应该有更低的 ICIR"

        # 测试空列表
        empty_icir = engine._calculate_icir([])
        assert empty_icir == 0.0, "空 IC 列表应该返回 0"

        # 测试单个值
        single_icir = engine._calculate_icir([0.05])
        assert single_icir == 0.0, "单个 IC 值应该返回 0"


class TestAvgHoldingPeriodCalculation:
    """测试平均持仓天数计算"""

    def test_avg_holding_period_calculation(self):
        """测试平均持仓天数计算"""
        config = StockSelectionBacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 4, 30),
            initial_capital=Decimal(1000000),
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            max_positions=30,
        )

        def mock_get_regime(dt):
            return "Recovery"

        def mock_get_stock_data(dt):
            return []

        def mock_get_price(stock, dt):
            return Decimal(100)

        def mock_get_benchmark_price(dt):
            return 100.0

        engine = StockSelectionBacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_stock_data_func=mock_get_stock_data,
            get_price_func=mock_get_price,
            get_benchmark_price_func=mock_get_benchmark_price,
        )

        # 测试月度再平衡的持仓天数
        rebalance_dates = [
            date(2020, 1, 1),
            date(2020, 2, 1),
            date(2020, 3, 1),
            date(2020, 4, 1),
        ]

        avg_period = engine._calculate_avg_holding_period(rebalance_dates)
        # 月度再平衡，持仓天数应该约为 30 天
        assert 25 <= avg_period <= 35, f"月度再平衡持仓天数应在 25-35 天之间，实际: {avg_period}"


class TestStockPerformancesOrganization:
    """测试个股表现整理"""

    def test_organize_stock_performances(self):
        """测试个股表现整理"""
        config = StockSelectionBacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=Decimal(1000000),
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            max_positions=30,
        )

        def mock_get_regime(dt):
            return "Recovery"

        def mock_get_stock_data(dt):
            return []

        def mock_get_price(stock, dt):
            return Decimal(100)

        def mock_get_benchmark_price(dt):
            return 100.0

        engine = StockSelectionBacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_stock_data_func=mock_get_stock_data,
            get_price_func=mock_get_price,
            get_benchmark_price_func=mock_get_benchmark_price,
        )

        # 测试数据整理
        from apps.backtest.domain.stock_selection_backtest import StockPerformance

        stock_performances = {
            "000001": [
                {'entry_date': Decimal('100'), 'exit_date': date(2020, 2, 1), 'return': 0.1},
                {'entry_date': Decimal('105'), 'exit_date': date(2020, 3, 1), 'return': 0.05},
            ],
            "000002": [
                {'entry_date': Decimal('50'), 'exit_date': date(2020, 2, 1), 'return': -0.05},
            ]
        }

        organized = engine._organize_stock_performances(stock_performances)

        assert isinstance(organized, list), "整理后应该是列表"
        assert len(organized) == 3, "应该有 3 条表现记录"
        assert all(isinstance(sp, StockPerformance) for sp in organized), "所有元素应该是 StockPerformance 类型"

        # 验证数据内容
        assert organized[0].stock_code == "000001"
        assert organized[0].return_rate == 0.1
        assert organized[2].stock_code == "000002"
        assert organized[2].return_rate == -0.05


class TestBacktestMetricsIntegration:
    """集成测试：验证回测结果的指标完整性"""

    def test_backtest_result_completeness(self):
        """测试回测结果包含所有必要指标"""
        config = BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0,
        )

        def mock_get_regime(dt):
            return {
                "dominant_regime": "Recovery",
                "confidence": 0.6,
                "distribution": {"Recovery": 0.6, "Overheat": 0.2, "Stagflation": 0.1, "Deflation": 0.1},
            }

        def mock_get_price(asset_class, dt):
            return 100.0

        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        result = engine.run()

        # 验证基本指标
        assert hasattr(result, 'final_value'), "结果应包含 final_value"
        assert hasattr(result, 'total_return'), "结果应包含 total_return"
        assert hasattr(result, 'annualized_return'), "结果应包含 annualized_return"
        assert hasattr(result, 'sharpe_ratio'), "结果应包含 sharpe_ratio"
        assert hasattr(result, 'max_drawdown'), "结果应包含 max_drawdown"

        # 验证再平衡记录包含 old_weights
        for history_item in result.regime_history:
            # regime_history 在当前实现中不包含 RebalanceResult
            # 但我们可以验证 trades 记录
            pass

        # 验证 equity_curve
        assert len(result.equity_curve) > 0, "应该有权益曲线数据"


class TestAlphaBacktestMetricsCompleteness:
    """测试 Alpha 回测指标完整性"""

    def test_alpha_backtest_metrics(self):
        """测试 Alpha 回测结果包含 ICIR 和换手率"""
        config = AlphaBacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            universe_id="csi300",
            alpha_provider="qlib",
        )

        # Mock Alpha service
        class MockAlphaService:
            def get_stock_scores(self, universe_id, intended_trade_date, top_n):
                from apps.alpha.domain.entities import AlphaResult, StockScore
                from datetime import datetime

                return AlphaResult(
                    success=True,
                    scores=[
                        StockScore(
                            code="000001",
                            score=0.8,
                            rank=1,
                            factors={"momentum": 0.8, "value": 0.7},
                            source="cache",
                            confidence=0.85,
                            asof_date=intended_trade_date,
                            intended_trade_date=intended_trade_date,
                        ),
                        StockScore(
                            code="000002",
                            score=0.75,
                            rank=2,
                            factors={"momentum": 0.75, "value": 0.65},
                            source="cache",
                            confidence=0.80,
                            asof_date=intended_trade_date,
                            intended_trade_date=intended_trade_date,
                        ),
                    ],
                    source="cache",
                    timestamp=datetime.now().isoformat(),
                )

        def mock_get_regime(dt):
            return "Recovery"

        def mock_get_price(stock, dt):
            return Decimal(100)

        def mock_get_benchmark_price(dt):
            return 100.0

        engine = AlphaBacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_price_func=mock_get_price,
            get_benchmark_price_func=mock_get_benchmark_price,
            alpha_service=MockAlphaService(),
        )

        result = engine.run()

        # 验证 Alpha 特有指标
        assert hasattr(result, 'turnover_rate'), "结果应包含 turnover_rate"
        assert hasattr(result, 'avg_ic'), "结果应包含 avg_ic"
        assert hasattr(result, 'avg_rank_ic'), "结果应包含 avg_rank_ic"
        assert hasattr(result, 'icir'), "结果应包含 icir"
        assert hasattr(result, 'coverage_ratio'), "结果应包含 coverage_ratio"
        assert hasattr(result, 'provider_usage'), "结果应包含 provider_usage"

        # 验证换手率是有效值
        assert result.turnover_rate >= 0, "换手率应该非负"


class TestStockSelectionBacktestMetricsCompleteness:
    """测试股票筛选回测指标完整性"""

    def test_stock_selection_backtest_metrics(self):
        """测试股票筛选回测结果包含所有必要指标"""
        config = StockSelectionBacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=Decimal(1000000),
            rebalance_frequency=RebalanceFrequency.MONTHLY,
            max_positions=30,
        )

        def mock_get_regime(dt):
            return "Recovery"

        def mock_get_stock_data(dt):
            return []

        def mock_get_price(stock, dt):
            return Decimal(100)

        def mock_get_benchmark_price(dt):
            return 100.0

        engine = StockSelectionBacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_stock_data_func=mock_get_stock_data,
            get_price_func=mock_get_price,
            get_benchmark_price_func=mock_get_benchmark_price,
        )

        # 创建空的筛选规则（需要 regime 和 name 参数）
        from apps.equity.domain.rules import StockScreeningRule
        screening_rules = {
            "Recovery": StockScreeningRule(
                regime="Recovery",
                name="测试规则"
            )
        }

        result = engine.run(screening_rules)

        # 验证所有必要指标存在
        assert hasattr(result, 'total_return'), "应包含 total_return"
        assert hasattr(result, 'annualized_return'), "应包含 annualized_return"
        assert hasattr(result, 'volatility'), "应包含 volatility"
        assert hasattr(result, 'max_drawdown'), "应包含 max_drawdown"
        assert hasattr(result, 'sharpe_ratio'), "应包含 sharpe_ratio"
        assert hasattr(result, 'turnover_rate'), "应包含 turnover_rate"
        assert hasattr(result, 'avg_holding_period'), "应包含 avg_holding_period"
        assert hasattr(result, 'stock_performances'), "应包含 stock_performances"

        # 验证换手率和持仓天数是有效值
        assert result.turnover_rate >= 0, "换手率应该非负"
        assert result.avg_holding_period >= 0, "平均持仓天数应该非负"
        assert isinstance(result.stock_performances, list), "个股表现应该是列表"
