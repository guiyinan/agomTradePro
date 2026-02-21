"""
Unit tests for Factor Domain Entities.

Pure Domain layer tests using only Python standard library.
"""

import pytest
from datetime import date
from decimal import Decimal
from apps.factor.domain.entities import (
    FactorCategory,
    FactorDirection,
    FactorDefinition,
    FactorExposure,
    FactorScore,
    FactorPortfolioConfig,
    FactorPortfolioHolding,
    FactorPerformance,
    create_default_factor_config,
    get_common_factors,
)


class TestFactorCategory:
    """Tests for FactorCategory enum"""

    def test_category_values(self):
        """Test factor category enum values"""
        assert FactorCategory.VALUE.value == "value"
        assert FactorCategory.QUALITY.value == "quality"
        assert FactorCategory.GROWTH.value == "growth"
        assert FactorCategory.MOMENTUM.value == "momentum"
        assert FactorCategory.VOLATILITY.value == "volatility"
        assert FactorCategory.LIQUIDITY.value == "liquidity"
        assert FactorCategory.TECHNICAL.value == "technical"


class TestFactorDirection:
    """Tests for FactorDirection enum"""

    def test_direction_values(self):
        """Test factor direction enum values"""
        assert FactorDirection.POSITIVE.value == "positive"
        assert FactorDirection.NEGATIVE.value == "negative"
        assert FactorDirection.NEUTRAL.value == "neutral"


class TestFactorDefinition:
    """Tests for FactorDefinition entity"""

    def test_create_valid_definition(self):
        """Test creating a valid factor definition"""
        definition = FactorDefinition(
            code="pe_ttm",
            name="PE(TTM)",
            category=FactorCategory.VALUE,
            description="滚动市盈率",
            data_source="tushare",
            data_field="pe_ttm",
            direction=FactorDirection.NEGATIVE,
        )
        assert definition.code == "pe_ttm"
        assert definition.direction == FactorDirection.NEGATIVE

    def test_default_values(self):
        """Test default values for optional fields"""
        definition = FactorDefinition(
            code="test",
            name="测试因子",
            category=FactorCategory.VALUE,
            description="测试",
            data_source="test",
            data_field="test",
        )
        assert definition.direction == FactorDirection.POSITIVE
        assert definition.update_frequency == "daily"
        assert definition.is_active is True
        assert definition.min_data_points == 20
        assert definition.allow_missing is False

    def test_code_cannot_be_empty(self):
        """Test empty code raises error"""
        with pytest.raises(ValueError, match="Factor code cannot be empty"):
            FactorDefinition(
                code="",
                name="测试",
                category=FactorCategory.VALUE,
                description="测试",
                data_source="test",
                data_field="test",
            )

    def test_name_cannot_be_empty(self):
        """Test empty name raises error"""
        with pytest.raises(ValueError, match="Factor name cannot be empty"):
            FactorDefinition(
                code="test",
                name="",
                category=FactorCategory.VALUE,
                description="测试",
                data_source="test",
                data_field="test",
            )

    def test_data_source_cannot_be_empty(self):
        """Test empty data source raises error"""
        with pytest.raises(ValueError, match="Data source cannot be empty"):
            FactorDefinition(
                code="test",
                name="测试",
                category=FactorCategory.VALUE,
                description="测试",
                data_source="",
                data_field="test",
            )

    def test_min_data_points_validation(self):
        """Test min_data_points must be at least 1"""
        with pytest.raises(ValueError, match="min_data_points must be at least 1"):
            FactorDefinition(
                code="test",
                name="测试",
                category=FactorCategory.VALUE,
                description="测试",
                data_source="test",
                data_field="test",
                min_data_points=0,
            )

    def test_higher_better_backward_compatibility(self):
        """Test higher_better sets direction for backward compatibility"""
        # Test with higher_better=True
        definition1 = FactorDefinition(
            code="test1",
            name="测试1",
            category=FactorCategory.VALUE,
            description="测试",
            data_source="test",
            data_field="test",
            direction=FactorDirection.NEUTRAL,
            higher_better=True,
        )
        assert definition1.direction == FactorDirection.POSITIVE

        # Test with higher_better=False
        definition2 = FactorDefinition(
            code="test2",
            name="测试2",
            category=FactorCategory.VALUE,
            description="测试",
            data_source="test",
            data_field="test",
            direction=FactorDirection.NEUTRAL,
            higher_better=False,
        )
        assert definition2.direction == FactorDirection.NEGATIVE


class TestFactorExposure:
    """Tests for FactorExposure entity"""

    def test_create_valid_exposure(self):
        """Test creating a valid factor exposure"""
        exposure = FactorExposure(
            stock_code="000001.SZ",
            trade_date=date(2024, 1, 1),
            factor_code="pe_ttm",
            factor_value=15.5,
            percentile_rank=0.5,
            z_score=0.0,
            normalized_score=50.0,
        )
        assert exposure.stock_code == "000001.SZ"
        assert exposure.factor_value == 15.5

    def test_default_normalized_score(self):
        """Test default normalized_score is 0.0"""
        exposure = FactorExposure(
            stock_code="000001.SZ",
            trade_date=date(2024, 1, 1),
            factor_code="pe_ttm",
            factor_value=15.5,
            percentile_rank=0.5,
            z_score=0.0,
        )
        assert exposure.normalized_score == 0.0

    def test_stock_code_cannot_be_empty(self):
        """Test empty stock code raises error"""
        with pytest.raises(ValueError, match="Stock code cannot be empty"):
            FactorExposure(
                stock_code="",
                trade_date=date(2024, 1, 1),
                factor_code="test",
                factor_value=10.0,
                percentile_rank=0.5,
                z_score=0.0,
            )

    def test_factor_code_cannot_be_empty(self):
        """Test empty factor code raises error"""
        with pytest.raises(ValueError, match="Factor code cannot be empty"):
            FactorExposure(
                stock_code="000001.SZ",
                trade_date=date(2024, 1, 1),
                factor_code="",
                factor_value=10.0,
                percentile_rank=0.5,
                z_score=0.0,
            )

    def test_percentile_rank_bounds(self):
        """Test percentile_rank must be between 0 and 1"""
        # Test valid boundaries
        exposure1 = FactorExposure(
            stock_code="000001.SZ",
            trade_date=date(2024, 1, 1),
            factor_code="test",
            factor_value=10.0,
            percentile_rank=0.0,
            z_score=0.0,
        )
        assert exposure1.percentile_rank == 0.0

        exposure2 = FactorExposure(
            stock_code="000001.SZ",
            trade_date=date(2024, 1, 1),
            factor_code="test",
            factor_value=10.0,
            percentile_rank=1.0,
            z_score=0.0,
        )
        assert exposure2.percentile_rank == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="percentile_rank must be between 0 and 1"):
            FactorExposure(
                stock_code="000001.SZ",
                trade_date=date(2024, 1, 1),
                factor_code="test",
                factor_value=10.0,
                percentile_rank=1.1,
                z_score=0.0,
            )

    def test_normalized_score_bounds(self):
        """Test normalized_score must be between 0 and 100"""
        # Test valid boundaries
        exposure1 = FactorExposure(
            stock_code="000001.SZ",
            trade_date=date(2024, 1, 1),
            factor_code="test",
            factor_value=10.0,
            percentile_rank=0.5,
            z_score=0.0,
            normalized_score=0.0,
        )
        assert exposure1.normalized_score == 0.0

        exposure2 = FactorExposure(
            stock_code="000001.SZ",
            trade_date=date(2024, 1, 1),
            factor_code="test",
            factor_value=10.0,
            percentile_rank=0.5,
            z_score=0.0,
            normalized_score=100.0,
        )
        assert exposure2.normalized_score == 100.0

        # Test out of range
        with pytest.raises(ValueError, match="normalized_score must be between 0 and 100"):
            FactorExposure(
                stock_code="000001.SZ",
                trade_date=date(2024, 1, 1),
                factor_code="test",
                factor_value=10.0,
                percentile_rank=0.5,
                z_score=0.0,
                normalized_score=100.1,
            )


class TestFactorScore:
    """Tests for FactorScore entity"""

    def test_create_valid_score(self):
        """Test creating a valid factor score"""
        score = FactorScore(
            stock_code="000001.SZ",
            stock_name="平安银行",
            trade_date=date(2024, 1, 1),
            factor_scores={"pe_ttm": 60.0, "roe": 70.0},
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            composite_score=65.0,
            percentile_rank=0.8,
        )
        assert score.stock_code == "000001.SZ"
        assert score.composite_score == 65.0

    def test_default_values(self):
        """Test default values for optional fields"""
        score = FactorScore(
            stock_code="000001.SZ",
            stock_name="平安银行",
            trade_date=date(2024, 1, 1),
            factor_scores={"test": 50.0},
            factor_weights={"test": 1.0},
            composite_score=50.0,
            percentile_rank=0.5,
        )
        assert score.sector == ""
        assert score.market_cap is None
        assert score.value_score == 0.0
        assert score.quality_score == 0.0
        assert score.growth_score == 0.0
        assert score.momentum_score == 0.0
        assert score.volatility_score == 0.0
        assert score.liquidity_score == 0.0

    def test_stock_code_cannot_be_empty(self):
        """Test empty stock code raises error"""
        with pytest.raises(ValueError, match="Stock code cannot be empty"):
            FactorScore(
                stock_code="",
                stock_name="测试",
                trade_date=date(2024, 1, 1),
                factor_scores={},
                factor_weights={},
                composite_score=50.0,
                percentile_rank=0.5,
            )

    def test_stock_name_cannot_be_empty(self):
        """Test empty stock name raises error"""
        with pytest.raises(ValueError, match="Stock name cannot be empty"):
            FactorScore(
                stock_code="000001.SZ",
                stock_name="",
                trade_date=date(2024, 1, 1),
                factor_scores={},
                factor_weights={},
                composite_score=50.0,
                percentile_rank=0.5,
            )

    def test_factor_weights_must_sum_to_one(self):
        """Test factor weights must sum to 1.0"""
        with pytest.raises(ValueError, match="Factor weights must sum to 1.0"):
            FactorScore(
                stock_code="000001.SZ",
                stock_name="测试",
                trade_date=date(2024, 1, 1),
                factor_scores={},
                factor_weights={"pe_ttm": 0.5, "roe": 0.3},
                composite_score=50.0,
                percentile_rank=0.5,
            )

    def test_factor_weights_tolerance(self):
        """Test small tolerance in weight sum"""
        # Should pass with tolerance of 0.01
        score = FactorScore(
            stock_code="000001.SZ",
            stock_name="测试",
            trade_date=date(2024, 1, 1),
            factor_scores={},
            factor_weights={"pe_ttm": 0.505, "roe": 0.495},
            composite_score=50.0,
            percentile_rank=0.5,
        )
        assert score.factor_weights["pe_ttm"] == 0.505


class TestFactorPortfolioConfig:
    """Tests for FactorPortfolioConfig entity"""

    def test_create_valid_config(self):
        """Test creating a valid portfolio config"""
        config = FactorPortfolioConfig(
            name="测试组合",
            description="测试描述",
            factor_weights={"pe_ttm": 0.5, "roe": 0.5},
            universe="zz500",
            top_n=30,
        )
        assert config.name == "测试组合"
        assert config.description == "测试描述"

    def test_default_values(self):
        """Test default values for optional fields"""
        config = FactorPortfolioConfig(
            name="测试",
        )
        assert config.description == ""
        assert config.factor_weights == {}
        assert config.universe == "all_a"
        assert config.min_market_cap is None
        assert config.max_market_cap is None
        assert config.top_n == 30
        assert config.rebalance_frequency == "monthly"
        assert config.weight_method == "equal_weight"
        assert config.max_sector_weight == 0.4
        assert config.max_single_stock_weight == 0.05
        assert config.is_active is True

    def test_name_cannot_be_empty(self):
        """Test empty name raises error"""
        with pytest.raises(ValueError, match="Configuration name cannot be empty"):
            FactorPortfolioConfig(name="")

    def test_top_n_minimum(self):
        """Test top_n must be at least 1"""
        with pytest.raises(ValueError, match="top_n must be at least 1"):
            FactorPortfolioConfig(name="测试", top_n=0)

    def test_max_sector_weight_bounds(self):
        """Test max_sector_weight must be between 0 and 1"""
        with pytest.raises(ValueError, match="max_sector_weight must be between 0 and 1"):
            FactorPortfolioConfig(name="测试", max_sector_weight=0.0)

        with pytest.raises(ValueError, match="max_sector_weight must be between 0 and 1"):
            FactorPortfolioConfig(name="测试", max_sector_weight=1.5)

    def test_max_single_stock_weight_bounds(self):
        """Test max_single_stock_weight must be between 0 and 1"""
        with pytest.raises(ValueError, match="max_single_stock_weight must be between 0 and 1"):
            FactorPortfolioConfig(name="测试", max_single_stock_weight=0.0)

        with pytest.raises(ValueError, match="max_single_stock_weight must be between 0 and 1"):
            FactorPortfolioConfig(name="测试", max_single_stock_weight=1.5)

    def test_factor_weights_must_sum_to_one(self):
        """Test factor weights must sum to 1.0"""
        with pytest.raises(ValueError, match="Factor weights must sum to 1.0"):
            FactorPortfolioConfig(
                name="测试",
                factor_weights={"pe_ttm": 0.5, "roe": 0.3},
            )

    def test_get_effective_universe(self):
        """Test get_effective_universe method"""
        config = FactorPortfolioConfig(
            name="测试",
            universe="hs300",
        )
        assert config.get_effective_universe() == "hs300"


class TestFactorPortfolioHolding:
    """Tests for FactorPortfolioHolding entity"""

    def test_create_valid_holding(self):
        """Test creating a valid portfolio holding"""
        holding = FactorPortfolioHolding(
            config_name="测试组合",
            trade_date=date(2024, 1, 1),
            stock_code="000001.SZ",
            stock_name="平安银行",
            weight=0.03,
            factor_score=65.0,
            rank=5,
        )
        assert holding.stock_code == "000001.SZ"
        assert holding.weight == 0.03

    def test_default_values(self):
        """Test default values for optional fields"""
        holding = FactorPortfolioHolding(
            config_name="测试",
            trade_date=date(2024, 1, 1),
            stock_code="000001.SZ",
            stock_name="测试",
            weight=0.03,
            factor_score=65.0,
            rank=5,
        )
        assert holding.sector == ""
        assert holding.factor_scores == {}

    def test_stock_code_cannot_be_empty(self):
        """Test empty stock code raises error"""
        with pytest.raises(ValueError, match="Stock code cannot be empty"):
            FactorPortfolioHolding(
                config_name="测试",
                trade_date=date(2024, 1, 1),
                stock_code="",
                stock_name="测试",
                weight=0.03,
                factor_score=65.0,
                rank=5,
            )

    def test_weight_bounds(self):
        """Test weight must be between 0 and 1"""
        # Test boundaries
        holding1 = FactorPortfolioHolding(
            config_name="测试",
            trade_date=date(2024, 1, 1),
            stock_code="000001.SZ",
            stock_name="测试",
            weight=0.0,
            factor_score=65.0,
            rank=5,
        )
        assert holding1.weight == 0.0

        holding2 = FactorPortfolioHolding(
            config_name="测试",
            trade_date=date(2024, 1, 1),
            stock_code="000001.SZ",
            stock_name="测试",
            weight=1.0,
            factor_score=65.0,
            rank=5,
        )
        assert holding2.weight == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="Weight must be between 0 and 1"):
            FactorPortfolioHolding(
                config_name="测试",
                trade_date=date(2024, 1, 1),
                stock_code="000001.SZ",
                stock_name="测试",
                weight=1.1,
                factor_score=65.0,
                rank=5,
            )

    def test_rank_minimum(self):
        """Test rank must be at least 1"""
        with pytest.raises(ValueError, match="Rank must be at least 1"):
            FactorPortfolioHolding(
                config_name="测试",
                trade_date=date(2024, 1, 1),
                stock_code="000001.SZ",
                stock_name="测试",
                weight=0.03,
                factor_score=65.0,
                rank=0,
            )


class TestFactorPerformance:
    """Tests for FactorPerformance entity"""

    def test_create_valid_performance(self):
        """Test creating a valid performance record"""
        performance = FactorPerformance(
            factor_code="pe_ttm",
            period_start=date(2023, 1, 1),
            period_end=date(2024, 1, 1),
            total_return=0.15,
            annual_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.08,
            win_rate=0.6,
            avg_rank=0.5,
        )
        assert performance.factor_code == "pe_ttm"
        assert performance.total_return == 0.15

    def test_default_turnover(self):
        """Test default turnover_rate is 0.0"""
        performance = FactorPerformance(
            factor_code="test",
            period_start=date(2023, 1, 1),
            period_end=date(2024, 1, 1),
            total_return=0.1,
            annual_return=0.1,
            sharpe_ratio=1.0,
            max_drawdown=-0.05,
            win_rate=0.5,
            avg_rank=0.5,
        )
        assert performance.turnover_rate == 0.0

    def test_period_start_before_end(self):
        """Test period_start must be before period_end"""
        with pytest.raises(ValueError, match="period_start must be before period_end"):
            FactorPerformance(
                factor_code="test",
                period_start=date(2024, 1, 1),
                period_end=date(2023, 1, 1),
                total_return=0.1,
                annual_return=0.1,
                sharpe_ratio=1.0,
                max_drawdown=-0.05,
                win_rate=0.5,
                avg_rank=0.5,
            )


class TestFactoryFunctions:
    """Tests for factory functions"""

    def test_create_default_factor_config(self):
        """Test creating default factor configuration"""
        config = create_default_factor_config()
        assert config.name == "默认价值成长组合"
        assert config.universe == "zz500"
        assert config.top_n == 30
        assert "pe_ttm" in config.factor_weights
        assert "roe" in config.factor_weights

    def test_get_common_factors(self):
        """Test getting common factors list"""
        factors = get_common_factors()
        assert len(factors) > 0

        # Check for expected factors
        factor_codes = [f.code for f in factors]
        assert "pe_ttm" in factor_codes
        assert "pb" in factor_codes
        assert "roe" in factor_codes
        assert "momentum_3m" in factor_codes

        # Check categories
        pe_factor = next(f for f in factors if f.code == "pe_ttm")
        assert pe_factor.category == FactorCategory.VALUE
        assert pe_factor.direction == FactorDirection.NEGATIVE

        roe_factor = next(f for f in factors if f.code == "roe")
        assert roe_factor.category == FactorCategory.QUALITY
        assert roe_factor.direction == FactorDirection.POSITIVE
