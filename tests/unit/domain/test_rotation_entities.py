"""
Unit tests for Rotation Domain Entities.

Pure Domain layer tests using only Python standard library.
"""

import pytest
from datetime import date
from decimal import Decimal
from apps.rotation.domain.entities import (
    AssetCategory,
    RotationStrategyType,
    AssetClass,
    MomentumScore,
    RotationConfig,
    RotationSignal,
    RotationPortfolio,
    get_common_etf_assets,
    create_default_regime_allocation,
    create_default_momentum_config,
    create_default_regime_config,
)


class TestAssetCategory:
    """Tests for AssetCategory enum"""

    def test_category_values(self):
        """Test asset category enum values"""
        assert AssetCategory.EQUITY.value == "equity"
        assert AssetCategory.BOND.value == "bond"
        assert AssetCategory.COMMODITY.value == "commodity"
        assert AssetCategory.CURRENCY.value == "currency"
        assert AssetCategory.ALTERNATIVE.value == "alternative"


class TestRotationStrategyType:
    """Tests for RotationStrategyType enum"""

    def test_strategy_type_values(self):
        """Test rotation strategy type enum values"""
        assert RotationStrategyType.REGIME_BASED.value == "regime_based"
        assert RotationStrategyType.MOMENTUM.value == "momentum"
        assert RotationStrategyType.RISK_PARITY.value == "risk_parity"
        assert RotationStrategyType.MEAN_REVERSION.value == "mean_reversion"
        assert RotationStrategyType.CUSTOM.value == "custom"


class TestAssetClass:
    """Tests for AssetClass entity"""

    def test_create_valid_asset(self):
        """Test creating a valid asset class"""
        asset = AssetClass(
            code="510300",
            name="沪深300ETF",
            category=AssetCategory.EQUITY,
            description="跟踪沪深300指数",
        )
        assert asset.code == "510300"
        assert asset.category == AssetCategory.EQUITY

    def test_default_values(self):
        """Test default values for optional fields"""
        asset = AssetClass(
            code="510300",
            name="沪深300ETF",
            category=AssetCategory.EQUITY,
            description="测试",
        )
        assert asset.underlying_index is None
        assert asset.currency == "CNY"
        assert asset.is_active is True

    def test_code_cannot_be_empty(self):
        """Test empty code raises error"""
        with pytest.raises(ValueError, match="Asset code cannot be empty"):
            AssetClass(
                code="",
                name="测试",
                category=AssetCategory.EQUITY,
                description="测试",
            )

    def test_name_cannot_be_empty(self):
        """Test empty name raises error"""
        with pytest.raises(ValueError, match="Asset name cannot be empty"):
            AssetClass(
                code="510300",
                name="",
                category=AssetCategory.EQUITY,
                description="测试",
            )


class TestMomentumScore:
    """Tests for MomentumScore entity"""

    def test_create_valid_score(self):
        """Test creating a valid momentum score"""
        score = MomentumScore(
            asset_code="510300",
            calc_date=date(2024, 1, 1),
            momentum_1m=0.05,
            momentum_3m=0.1,
            momentum_6m=0.15,
            momentum_12m=0.2,
            composite_score=0.125,
        )
        assert score.asset_code == "510300"
        assert score.composite_score == 0.125

    def test_default_values(self):
        """Test default values for optional fields"""
        score = MomentumScore(
            asset_code="510300",
            calc_date=date(2024, 1, 1),
        )
        assert score.momentum_1m == 0.0
        assert score.momentum_3m == 0.0
        assert score.momentum_6m == 0.0
        assert score.momentum_12m == 0.0
        assert score.composite_score == 0.0
        assert score.rank == 0
        assert score.sharpe_1m == 0.0
        assert score.sharpe_3m == 0.0
        assert score.ma_signal == "neutral"
        assert score.trend_strength == 0.0

    def test_asset_code_cannot_be_empty(self):
        """Test empty asset code raises error"""
        with pytest.raises(ValueError, match="Asset code cannot be empty"):
            MomentumScore(
                asset_code="",
                calc_date=date(2024, 1, 1),
            )


class TestRotationConfig:
    """Tests for RotationConfig entity"""

    def test_create_valid_config(self):
        """Test creating a valid rotation config"""
        config = RotationConfig(
            name="测试轮动策略",
            strategy_type=RotationStrategyType.MOMENTUM,
            asset_universe=["510300", "510500", "159915"],
        )
        assert config.name == "测试轮动策略"
        assert config.strategy_type == RotationStrategyType.MOMENTUM

    def test_default_values(self):
        """Test default values for optional fields"""
        config = RotationConfig(
            name="测试",
            asset_universe=["510300"],
        )
        assert config.description == ""
        assert config.strategy_type == RotationStrategyType.MOMENTUM
        assert config.params == {}
        assert config.rebalance_frequency == "monthly"
        assert config.min_weight == 0.0
        assert config.max_weight == 1.0
        assert config.max_turnover == 1.0
        assert config.lookback_period == 252
        assert config.regime_allocations == {}
        assert config.momentum_periods == [20, 60, 120, 252]
        assert config.top_n == 3
        assert config.is_active is True

    def test_name_cannot_be_empty(self):
        """Test empty name raises error"""
        with pytest.raises(ValueError, match="Configuration name cannot be empty"):
            RotationConfig(
                name="",
                asset_universe=["510300"],
            )

    def test_max_weight_bounds(self):
        """Test max_weight must be between 0 and 1"""
        with pytest.raises(ValueError, match="max_weight must be between 0 and 1"):
            RotationConfig(
                name="测试",
                asset_universe=["510300"],
                max_weight=0.0,
            )

        with pytest.raises(ValueError, match="max_weight must be between 0 and 1"):
            RotationConfig(
                name="测试",
                asset_universe=["510300"],
                max_weight=1.5,
            )

    def test_min_weight_non_negative(self):
        """Test min_weight must be non-negative"""
        with pytest.raises(ValueError, match="min_weight must be non-negative"):
            RotationConfig(
                name="测试",
                asset_universe=["510300"],
                min_weight=-0.1,
            )

    def test_min_weight_less_than_max_weight(self):
        """Test min_weight must be less than max_weight"""
        with pytest.raises(ValueError, match="min_weight must be less than max_weight"):
            RotationConfig(
                name="测试",
                asset_universe=["510300"],
                min_weight=0.5,
                max_weight=0.3,
            )

    def test_top_n_minimum(self):
        """Test top_n must be at least 1"""
        with pytest.raises(ValueError, match="top_n must be at least 1"):
            RotationConfig(
                name="测试",
                asset_universe=["510300"],
                top_n=0,
            )

    def test_asset_universe_cannot_be_empty(self):
        """Test asset_universe cannot be empty"""
        with pytest.raises(ValueError, match="asset_universe cannot be empty"):
            RotationConfig(
                name="测试",
                asset_universe=[],
            )


class TestRotationSignal:
    """Tests for RotationSignal entity"""

    def test_create_valid_signal(self):
        """Test creating a valid rotation signal"""
        signal = RotationSignal(
            config_name="测试策略",
            signal_date=date(2024, 1, 1),
            target_allocation={"510300": 0.6, "511260": 0.4},
        )
        assert signal.config_name == "测试策略"
        assert signal.target_allocation["510300"] == 0.6

    def test_default_values(self):
        """Test default values for optional fields"""
        signal = RotationSignal(
            config_name="测试",
            signal_date=date(2024, 1, 1),
            target_allocation={"510300": 1.0},
        )
        assert signal.current_regime == ""
        assert signal.momentum_ranking == []
        assert signal.expected_volatility == 0.0
        assert signal.expected_return == 0.0
        assert signal.action_required == "hold"
        assert signal.reason == ""

    def test_config_name_cannot_be_empty(self):
        """Test empty config name raises error"""
        with pytest.raises(ValueError, match="Config name cannot be empty"):
            RotationSignal(
                config_name="",
                signal_date=date(2024, 1, 1),
                target_allocation={"510300": 1.0},
            )

    def test_target_allocation_must_sum_to_one(self):
        """Test target allocation weights must sum to 1.0"""
        with pytest.raises(ValueError, match="Target allocation weights must sum to 1.0"):
            RotationSignal(
                config_name="测试",
                signal_date=date(2024, 1, 1),
                target_allocation={"510300": 0.5, "511260": 0.3},
            )

    def test_target_allocation_tolerance(self):
        """Test small tolerance in weight sum"""
        # Should pass with tolerance of 0.01
        signal = RotationSignal(
            config_name="测试",
            signal_date=date(2024, 1, 1),
            target_allocation={"510300": 0.505, "511260": 0.495},
        )
        assert signal.target_allocation["510300"] == 0.505


class TestRotationPortfolio:
    """Tests for RotationPortfolio entity"""

    def test_create_valid_portfolio(self):
        """Test creating a valid rotation portfolio"""
        portfolio = RotationPortfolio(
            config_name="测试策略",
            trade_date=date(2024, 1, 1),
            current_allocation={"510300": 0.6, "511260": 0.4},
        )
        assert portfolio.config_name == "测试策略"

    def test_default_values(self):
        """Test default values for optional fields"""
        portfolio = RotationPortfolio(
            config_name="测试",
            trade_date=date(2024, 1, 1),
            current_allocation={"510300": 1.0},
        )
        assert portfolio.daily_return == 0.0
        assert portfolio.cumulative_return == 0.0
        assert portfolio.portfolio_volatility == 0.0
        assert portfolio.max_drawdown == 0.0
        assert portfolio.turnover_since_last == 0.0

    def test_config_name_cannot_be_empty(self):
        """Test empty config name raises error"""
        with pytest.raises(ValueError, match="Config name cannot be empty"):
            RotationPortfolio(
                config_name="",
                trade_date=date(2024, 1, 1),
                current_allocation={"510300": 1.0},
            )

    def test_current_allocation_must_sum_to_one(self):
        """Test current allocation weights must sum to 1.0"""
        with pytest.raises(ValueError, match="Current allocation weights must sum to 1.0"):
            RotationPortfolio(
                config_name="测试",
                trade_date=date(2024, 1, 1),
                current_allocation={"510300": 0.5, "511260": 0.3},
            )


class TestFactoryFunctions:
    """Tests for factory functions"""

    def test_get_common_etf_assets(self):
        """Test getting common ETF assets"""
        assets = get_common_etf_assets()
        assert len(assets) > 0

        # Check for expected assets
        asset_codes = [a.code for a in assets]
        assert "510300" in asset_codes  # 沪深300ETF
        assert "510500" in asset_codes  # 中证500ETF
        assert "159915" in asset_codes  # 创业板ETF
        assert "511260" in asset_codes  # 十年国债ETF
        assert "159980" in asset_codes  # 黄金ETF

        # Check categories
        equity_assets = [a for a in assets if a.category == AssetCategory.EQUITY]
        bond_assets = [a for a in assets if a.category == AssetCategory.BOND]
        commodity_assets = [a for a in assets if a.category == AssetCategory.COMMODITY]

        assert len(equity_assets) > 0
        assert len(bond_assets) > 0
        assert len(commodity_assets) > 0

    def test_create_default_regime_allocation(self):
        """Test creating default regime allocation"""
        allocation = create_default_regime_allocation()
        assert isinstance(allocation, dict)

        # Check for expected regimes
        assert "Recovery" in allocation
        assert "Overheat" in allocation
        assert "Stagflation" in allocation
        assert "Deflation" in allocation

        # Check allocation weights sum to 1
        for regime, weights in allocation.items():
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.01, f"{regime} allocation sums to {total}"

    def test_create_default_momentum_config(self):
        """Test creating default momentum config"""
        config = create_default_momentum_config()
        assert config.name == "动量轮动策略"
        assert config.strategy_type == RotationStrategyType.MOMENTUM
        assert config.top_n == 3
        assert "momentum_periods" in config.params

    def test_create_default_regime_config(self):
        """Test creating default regime config"""
        config = create_default_regime_config()
        assert config.name == "宏观象限轮动策略"
        assert config.strategy_type == RotationStrategyType.REGIME_BASED
        assert len(config.regime_allocations) > 0
        assert config.max_weight == 0.5
