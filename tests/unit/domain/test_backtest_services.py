"""
Unit tests for Backtest Domain Services.

纯 Domain 层测试，只使用 Python 标准库。
"""

from datetime import date, timedelta
from typing import Dict, List, Optional

import pytest

from apps.backtest.domain.entities import (
    DEFAULT_PUBLICATION_LAGS,
    AssetClass,
    BacktestConfig,
    BacktestResult,
    PITDataConfig,
    PortfolioState,
    RebalanceFrequency,
    RebalanceResult,
    Trade,
)
from apps.backtest.domain.services import (
    BacktestEngine,
    PITDataProcessor,
)


class TestBacktestConfig:
    """测试回测配置"""

    def test_valid_config(self):
        """测试有效配置"""
        config = BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=10.0,
        )
        assert config.start_date == date(2020, 1, 1)
        assert config.initial_capital == 100000.0
        assert config.rebalance_frequency == "monthly"

    def test_invalid_initial_capital(self):
        """测试无效的初始资金"""
        with pytest.raises(ValueError, match="initial_capital must be positive"):
            BacktestConfig(
                start_date=date(2020, 1, 1),
                end_date=date(2024, 12, 31),
                initial_capital=-1000.0,
                rebalance_frequency="monthly",
                use_pit_data=False,
            )

    def test_invalid_date_range(self):
        """测试无效的日期范围"""
        with pytest.raises(ValueError, match="start_date must be before end_date"):
            BacktestConfig(
                start_date=date(2024, 12, 31),
                end_date=date(2020, 1, 1),
                initial_capital=100000.0,
                rebalance_frequency="monthly",
                use_pit_data=False,
            )

    def test_invalid_rebalance_frequency(self):
        """测试无效的再平衡频率"""
        with pytest.raises(ValueError, match="rebalance_frequency must be one of"):
            BacktestConfig(
                start_date=date(2020, 1, 1),
                end_date=date(2024, 12, 31),
                initial_capital=100000.0,
                rebalance_frequency="weekly",  # 无效频率
                use_pit_data=False,
            )

    def test_default_transaction_cost(self):
        """测试默认交易成本"""
        config = BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2024, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
        )
        assert config.transaction_cost_bps == 10.0


class TestPITDataProcessor:
    """测试 Point-in-Time 数据处理器"""

    def test_get_available_as_of_date(self):
        """测试获取数据可用日期"""
        lags = {
            "PMI": timedelta(days=35),
            "CPI": timedelta(days=10),
        }
        processor = PITDataProcessor(lags)

        # PMI 观测日期为 2024-01-01，发布日期应为 2024-02-05
        result = processor.get_available_as_of_date(
            observed_at=date(2024, 1, 1),
            indicator_code="PMI"
        )
        assert result == date(2024, 2, 5)

    def test_is_data_available(self):
        """测试检查数据是否可用"""
        lags = {
            "PMI": timedelta(days=35),
        }
        processor = PITDataProcessor(lags)

        # 2024-01-01 观测的 PMI，在 2024-02-01 时还不可用
        assert not processor.is_data_available(
            observed_at=date(2024, 1, 1),
            indicator_code="PMI",
            as_of_date=date(2024, 2, 1)
        )

        # 2024-01-01 观测的 PMI，在 2024-02-10 时可用
        assert processor.is_data_available(
            observed_at=date(2024, 1, 1),
            indicator_code="PMI",
            as_of_date=date(2024, 2, 10)
        )

    def test_no_lag_indicator(self):
        """测试无延迟的指标"""
        processor = PITDataProcessor({})

        # 无延迟指标，观测日即可用日
        assert processor.is_data_available(
            observed_at=date(2024, 1, 1),
            indicator_code="SHIBOR",
            as_of_date=date(2024, 1, 1)
        )


class TestBacktestEngine:
    """测试回测引擎"""

    @pytest.fixture
    def config(self):
        """创建测试配置"""
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
        """模拟 Regime 获取函数"""
        def _get_regime(as_of_date: date) -> dict | None:
            # 简单模拟：1月是 Recovery，2月是 Overheat，3月是 Stagflation
            month = as_of_date.month
            if month == 1:
                return {
                    "dominant_regime": "Recovery",
                    "confidence": 0.6,
                    "growth_momentum_z": 1.0,
                    "inflation_momentum_z": -0.5,
                    "distribution": {
                        "Recovery": 0.5,
                        "Overheat": 0.2,
                        "Stagflation": 0.1,
                        "Deflation": 0.2,
                    },
                }
            elif month == 2:
                return {
                    "dominant_regime": "Overheat",
                    "confidence": 0.7,
                    "growth_momentum_z": 1.5,
                    "inflation_momentum_z": 1.0,
                    "distribution": {
                        "Recovery": 0.2,
                        "Overheat": 0.6,
                        "Stagflation": 0.1,
                        "Deflation": 0.1,
                    },
                }
            else:
                return {
                    "dominant_regime": "Stagflation",
                    "confidence": 0.55,
                    "growth_momentum_z": -0.5,
                    "inflation_momentum_z": 1.0,
                    "distribution": {
                        "Recovery": 0.1,
                        "Overheat": 0.2,
                        "Stagflation": 0.5,
                        "Deflation": 0.2,
                    },
                }
        return _get_regime

    @pytest.fixture
    def mock_get_price(self):
        """模拟价格获取函数"""
        prices = {
            "a_share_growth": 3000.0,
            "a_share_value": 2500.0,
            "china_bond": 100.0,
            "gold": 500.0,
            "commodity": 200.0,
            "cash": 1.0,
        }

        def _get_price(asset_class: str, as_of_date: date) -> float | None:
            return prices.get(asset_class)

        return _get_price

    def test_engine_initialization(self, config, mock_get_regime, mock_get_price):
        """测试引擎初始化"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )
        assert engine.config == config
        assert engine._cash == config.initial_capital
        assert engine._positions == {}

    def test_generate_rebalance_dates_monthly(self, config, mock_get_regime, mock_get_price):
        """测试生成月度再平衡日期"""
        config = BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
        )
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        dates = engine._generate_rebalance_dates()
        assert len(dates) == 3
        assert dates[0] == date(2020, 1, 1)
        assert dates[1] == date(2020, 2, 1)
        assert dates[2] == date(2020, 3, 1)

    def test_generate_rebalance_dates_quarterly(self, mock_get_regime, mock_get_price):
        """测试生成季度再平衡日期"""
        config = BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="quarterly",
            use_pit_data=False,
        )
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        dates = engine._generate_rebalance_dates()
        assert len(dates) == 4
        assert dates[0] == date(2020, 1, 1)
        assert dates[1] == date(2020, 4, 1)
        assert dates[2] == date(2020, 7, 1)
        assert dates[3] == date(2020, 10, 1)

    def test_calculate_target_weights_recovery(self, config, mock_get_regime, mock_get_price):
        """测试计算 Recovery Regime 下的目标权重"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        weights = engine._calculate_target_weights("Recovery", 0.6)

        # Recovery 下，a_share_growth 和 a_share_value 应该是 PREFERRED
        assert "a_share_growth" in weights
        assert "a_share_value" in weights
        # 等权分配
        assert weights["a_share_growth"] == weights["a_share_value"]

    def test_calculate_transaction_cost(self, config, mock_get_regime, mock_get_price):
        """测试计算交易成本"""
        config = BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 3, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
            transaction_cost_bps=20.0,  # 20 基点
        )
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        # 10000 元名义价值，20 基点 = 0.2% = 20 元
        cost = engine._calculate_transaction_cost(10000.0)
        assert cost == 20.0

    def test_backtest_run_basic(self, config, mock_get_regime, mock_get_price):
        """测试基本回测运行"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        result = engine.run()

        assert isinstance(result, BacktestResult)
        assert result.config == config
        assert result.final_value > 0
        assert len(result.equity_curve) > 0
        assert len(result.regime_history) > 0

    def test_backtest_run_without_regime_data(self, config, mock_get_price):
        """测试没有 Regime 数据时的回测"""
        def no_regime(as_of_date: date) -> dict | None:
            return None

        engine = BacktestEngine(
            config=config,
            get_regime_func=no_regime,
            get_asset_price_func=mock_get_price,
        )

        result = engine.run()

        # 应该仍然运行，但不会进行再平衡
        assert result.final_value == config.initial_capital

    def test_calculate_annual_return(self, config, mock_get_regime, mock_get_price):
        """测试年化收益计算"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        # 3 个月，10% 收益
        # 年化收益 ≈ (1.1)^(4) - 1 = 46.41%
        # 实际使用 90 天计算：90/365.25 ≈ 0.246 年
        # (1.10)^(1/0.246) - 1 ≈ 47.2%
        annual_return = engine._calculate_annual_return(0.10)
        assert abs(annual_return - 0.47) < 0.02

    def test_calculate_max_drawdown(self, config, mock_get_regime, mock_get_price):
        """测试最大回撤计算"""
        engine = BacktestEngine(
            config=config,
            get_regime_func=mock_get_regime,
            get_asset_price_func=mock_get_price,
        )

        # 模拟权益曲线：先涨后跌
        engine._equity_curve = [
            (date(2020, 1, 1), 100000),
            (date(2020, 2, 1), 110000),  # 峰值
            (date(2020, 3, 1), 95000),   # 回撤
        ]

        max_dd = engine._calculate_max_drawdown()
        # (110000 - 95000) / 110000 = 13.6%
        assert abs(max_dd - 0.136) < 0.01


class TestTrade:
    """测试交易记录"""

    def test_trade_creation(self):
        """测试创建交易记录"""
        trade = Trade(
            trade_date=date(2024, 1, 1),
            asset_class="a_share_growth",
            action="buy",
            shares=100.0,
            price=10.5,
            notional=1050.0,
            cost=10.5,  # 10 基点
        )
        assert trade.trade_date == date(2024, 1, 1)
        assert trade.action == "buy"
        assert trade.notional == 1050.0


class TestPortfolioState:
    """测试组合状态"""

    def test_portfolio_state_creation(self):
        """测试创建组合状态"""
        state = PortfolioState(
            as_of_date=date(2024, 1, 1),
            cash=50000.0,
            positions={"a_share_growth": 100.0, "china_bond": 500.0},
            total_value=100000.0,
        )
        assert state.cash == 50000.0
        assert state.positions["a_share_growth"] == 100.0

    def test_get_position_value(self):
        """测试获取持仓价值"""
        state = PortfolioState(
            as_of_date=date(2024, 1, 1),
            cash=50000.0,
            positions={"a_share_growth": 100.0},
            total_value=100000.0,
        )
        value = state.get_position_value("a_share_growth", 10.5)
        assert value == 1050.0

    def test_to_dict(self):
        """测试转换为字典"""
        state = PortfolioState(
            as_of_date=date(2024, 1, 1),
            cash=50000.0,
            positions={"a_share_growth": 100.0},
            total_value=100000.0,
        )
        result = state.to_dict()
        assert result["cash"] == 50000.0
        assert result["as_of_date"] == "2024-01-01"


class TestBacktestResult:
    """测试回测结果"""

    @pytest.fixture
    def config(self):
        return BacktestConfig(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 12, 31),
            initial_capital=100000.0,
            rebalance_frequency="monthly",
            use_pit_data=False,
        )

    def test_to_summary_dict(self, config):
        """测试转换为摘要字典"""
        result = BacktestResult(
            config=config,
            final_value=120000.0,
            total_return=0.20,
            annualized_return=0.20,
            sharpe_ratio=1.5,
            max_drawdown=0.10,
            trades=[],
            equity_curve=[],
            regime_history=[],
        )
        summary = result.to_summary_dict()
        assert summary["total_return"] == 0.20
        assert summary["annualized_return"] == 0.20
        assert summary["sharpe_ratio"] == 1.5
        assert summary["max_drawdown"] == 0.10
        assert summary["num_trades"] == 0
