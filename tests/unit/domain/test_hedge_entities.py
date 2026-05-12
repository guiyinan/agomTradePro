"""
Unit tests for Hedge Domain Entities.

Pure Domain layer tests using only Python standard library.
"""

from datetime import date

import pytest

from apps.hedge.domain.entities import (
    CorrelationMetric,
    HedgeAlert,
    HedgeAlertType,
    HedgeMethod,
    HedgePair,
    HedgePerformance,
    HedgePortfolio,
    create_default_hedge_config,
    get_common_hedge_pairs,
)


class TestHedgeMethod:
    """Tests for HedgeMethod enum"""

    def test_method_values(self):
        """Test hedge method enum values"""
        assert HedgeMethod.BETA.value == "beta"
        assert HedgeMethod.MIN_VARIANCE.value == "min_variance"
        assert HedgeMethod.EQUAL_RISK.value == "equal_risk"
        assert HedgeMethod.DOLLAR_NEUTRAL.value == "dollar_neutral"
        assert HedgeMethod.FIXED_RATIO.value == "fixed_ratio"


class TestHedgeAlertType:
    """Tests for HedgeAlertType enum"""

    def test_alert_type_values(self):
        """Test hedge alert type enum values"""
        assert HedgeAlertType.CORRELATION_BREAKDOWN.value == "correlation_breakdown"
        assert HedgeAlertType.HEDGE_RATIO_DRIFT.value == "hedge_ratio_drift"
        assert HedgeAlertType.BETA_CHANGE.value == "beta_change"
        assert HedgeAlertType.LIQUIDITY_RISK.value == "liquidity_risk"


class TestHedgePair:
    """Tests for HedgePair entity"""

    def test_create_valid_pair(self):
        """Test creating a valid hedge pair"""
        pair = HedgePair(
            name="股债对冲",
            long_asset="510300",
            hedge_asset="511260",
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.7,
            target_hedge_weight=0.3,
        )
        assert pair.name == "股债对冲"
        assert pair.long_asset == "510300"
        assert pair.hedge_asset == "511260"

    def test_default_values(self):
        """Test default values for optional fields"""
        pair = HedgePair(
            name="测试",
            long_asset="510300",
            hedge_asset="511260",
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.7,
        )
        assert pair.target_hedge_weight == 0.0
        assert pair.rebalance_trigger == 0.05
        assert pair.correlation_window == 60
        assert pair.min_correlation == -0.3
        assert pair.max_correlation == -0.9
        assert pair.correlation_alert_threshold == 0.2
        assert pair.max_hedge_cost == 0.05
        assert pair.beta_target is None
        assert pair.is_active is True

    def test_name_cannot_be_empty(self):
        """Test empty name raises error"""
        with pytest.raises(ValueError, match="Pair name cannot be empty"):
            HedgePair(
                name="",
                long_asset="510300",
                hedge_asset="511260",
                hedge_method=HedgeMethod.BETA,
                target_long_weight=0.7,
            )

    def test_long_asset_cannot_be_empty(self):
        """Test empty long asset raises error"""
        with pytest.raises(ValueError, match="Long asset cannot be empty"):
            HedgePair(
                name="测试",
                long_asset="",
                hedge_asset="511260",
                hedge_method=HedgeMethod.BETA,
                target_long_weight=0.7,
            )

    def test_hedge_asset_cannot_be_empty(self):
        """Test empty hedge asset raises error"""
        with pytest.raises(ValueError, match="Hedge asset cannot be empty"):
            HedgePair(
                name="测试",
                long_asset="510300",
                hedge_asset="",
                hedge_method=HedgeMethod.BETA,
                target_long_weight=0.7,
            )

    def test_long_and_hedge_assets_cannot_be_same(self):
        """Test long and hedge assets cannot be the same"""
        with pytest.raises(ValueError, match="Long and hedge assets cannot be the same"):
            HedgePair(
                name="测试",
                long_asset="510300",
                hedge_asset="510300",
                hedge_method=HedgeMethod.BETA,
                target_long_weight=0.7,
            )

    def test_target_long_weight_bounds(self):
        """Test target_long_weight must be between 0 and 1"""
        # Test valid boundaries
        pair1 = HedgePair(
            name="测试",
            long_asset="510300",
            hedge_asset="511260",
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.0,
        )
        assert pair1.target_long_weight == 0.0

        pair2 = HedgePair(
            name="测试",
            long_asset="510300",
            hedge_asset="511260",
            hedge_method=HedgeMethod.BETA,
            target_long_weight=1.0,
        )
        assert pair2.target_long_weight == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="target_long_weight must be between 0 and 1"):
            HedgePair(
                name="测试",
                long_asset="510300",
                hedge_asset="511260",
                hedge_method=HedgeMethod.BETA,
                target_long_weight=1.1,
            )

    def test_target_hedge_weight_bounds(self):
        """Test target_hedge_weight must be between 0 and 1"""
        # Test valid boundaries
        pair1 = HedgePair(
            name="测试",
            long_asset="510300",
            hedge_asset="511260",
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.7,
            target_hedge_weight=0.0,
        )
        assert pair1.target_hedge_weight == 0.0

        pair2 = HedgePair(
            name="测试",
            long_asset="510300",
            hedge_asset="511260",
            hedge_method=HedgeMethod.BETA,
            target_long_weight=0.7,
            target_hedge_weight=1.0,
        )
        assert pair2.target_hedge_weight == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="target_hedge_weight must be between 0 and 1"):
            HedgePair(
                name="测试",
                long_asset="510300",
                hedge_asset="511260",
                hedge_method=HedgeMethod.BETA,
                target_long_weight=0.7,
                target_hedge_weight=-0.1,
            )


class TestCorrelationMetric:
    """Tests for CorrelationMetric entity"""

    def test_create_valid_metric(self):
        """Test creating a valid correlation metric"""
        metric = CorrelationMetric(
            asset1="510300",
            asset2="511260",
            calc_date=date(2024, 1, 1),
            window_days=60,
            correlation=-0.7,
        )
        assert metric.asset1 == "510300"
        assert metric.correlation == -0.7

    def test_default_values(self):
        """Test default values for optional fields"""
        metric = CorrelationMetric(
            asset1="510300",
            asset2="511260",
            calc_date=date(2024, 1, 1),
            window_days=60,
            correlation=-0.5,
        )
        assert metric.covariance == 0.0
        assert metric.beta == 0.0
        assert metric.p_value == 0.0
        assert metric.standard_error == 0.0
        assert metric.correlation_trend == "neutral"
        assert metric.correlation_ma == 0.0
        assert metric.alert is None
        assert metric.alert_type is None

    def test_asset1_cannot_be_empty(self):
        """Test empty asset1 raises error"""
        with pytest.raises(ValueError, match="asset1 cannot be empty"):
            CorrelationMetric(
                asset1="",
                asset2="511260",
                calc_date=date(2024, 1, 1),
                window_days=60,
                correlation=-0.5,
            )

    def test_asset2_cannot_be_empty(self):
        """Test empty asset2 raises error"""
        with pytest.raises(ValueError, match="asset2 cannot be empty"):
            CorrelationMetric(
                asset1="510300",
                asset2="",
                calc_date=date(2024, 1, 1),
                window_days=60,
                correlation=-0.5,
            )

    def test_correlation_bounds(self):
        """Test correlation must be between -1 and 1"""
        # Test valid boundaries
        metric1 = CorrelationMetric(
            asset1="510300",
            asset2="511260",
            calc_date=date(2024, 1, 1),
            window_days=60,
            correlation=-1.0,
        )
        assert metric1.correlation == -1.0

        metric2 = CorrelationMetric(
            asset1="510300",
            asset2="511260",
            calc_date=date(2024, 1, 1),
            window_days=60,
            correlation=1.0,
        )
        assert metric2.correlation == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="correlation must be between -1 and 1"):
            CorrelationMetric(
                asset1="510300",
                asset2="511260",
                calc_date=date(2024, 1, 1),
                window_days=60,
                correlation=1.1,
            )


class TestHedgePortfolio:
    """Tests for HedgePortfolio entity"""

    def test_create_valid_portfolio(self):
        """Test creating a valid hedge portfolio"""
        portfolio = HedgePortfolio(
            pair_name="股债对冲",
            trade_date=date(2024, 1, 1),
            long_weight=0.7,
            hedge_weight=0.3,
            hedge_ratio=0.43,
        )
        assert portfolio.pair_name == "股债对冲"
        assert portfolio.long_weight == 0.7

    def test_default_values(self):
        """Test default values for optional fields"""
        portfolio = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=0.7,
            hedge_weight=0.3,
            hedge_ratio=0.43,
        )
        assert portfolio.hedge_ratio == 0.43
        assert portfolio.target_hedge_ratio == 0.0
        assert portfolio.current_correlation == 0.0
        assert portfolio.correlation_20d == 0.0
        assert portfolio.correlation_60d == 0.0
        assert portfolio.portfolio_beta == 0.0
        assert portfolio.portfolio_volatility == 0.0
        assert portfolio.hedge_effectiveness == 0.0
        assert portfolio.daily_return == 0.0
        assert portfolio.unhedged_return == 0.0
        assert portfolio.hedge_return == 0.0
        assert portfolio.value_at_risk == 0.0
        assert portfolio.max_drawdown == 0.0
        assert portfolio.rebalance_needed is False
        assert portfolio.rebalance_reason == ""

    def test_pair_name_cannot_be_empty(self):
        """Test empty pair name raises error"""
        with pytest.raises(ValueError, match="Pair name cannot be empty"):
            HedgePortfolio(
                pair_name="",
                trade_date=date(2024, 1, 1),
                long_weight=0.7,
                hedge_weight=0.3,
                hedge_ratio=0.43,
            )

    def test_long_weight_bounds(self):
        """Test long_weight must be between 0 and 1"""
        # Test valid boundaries
        portfolio1 = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=0.0,
            hedge_weight=0.3,
            hedge_ratio=0.43,
        )
        assert portfolio1.long_weight == 0.0

        portfolio2 = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=1.0,
            hedge_weight=0.0,
            hedge_ratio=0.0,
        )
        assert portfolio2.long_weight == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="long_weight must be between 0 and 1"):
            HedgePortfolio(
                pair_name="测试",
                trade_date=date(2024, 1, 1),
                long_weight=1.1,
                hedge_weight=0.0,
                hedge_ratio=0.0,
            )

    def test_hedge_weight_bounds(self):
        """Test hedge_weight must be between 0 and 1"""
        # Test valid boundaries
        portfolio1 = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=0.7,
            hedge_weight=0.0,
            hedge_ratio=0.0,
        )
        assert portfolio1.hedge_weight == 0.0

        portfolio2 = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=0.0,
            hedge_weight=1.0,
            hedge_ratio=1.0,
        )
        assert portfolio2.hedge_weight == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="hedge_weight must be between 0 and 1"):
            HedgePortfolio(
                pair_name="测试",
                trade_date=date(2024, 1, 1),
                long_weight=0.0,
                hedge_weight=-0.1,
                hedge_ratio=0.0,
            )

    def test_current_correlation_bounds(self):
        """Test current_correlation must be between -1 and 1"""
        # Test valid boundaries
        portfolio1 = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=0.7,
            hedge_weight=0.3,
            hedge_ratio=0.43,
            current_correlation=-1.0,
        )
        assert portfolio1.current_correlation == -1.0

        portfolio2 = HedgePortfolio(
            pair_name="测试",
            trade_date=date(2024, 1, 1),
            long_weight=0.7,
            hedge_weight=0.3,
            hedge_ratio=0.43,
            current_correlation=1.0,
        )
        assert portfolio2.current_correlation == 1.0

        # Test out of range
        with pytest.raises(ValueError, match="current_correlation must be between -1 and 1"):
            HedgePortfolio(
                pair_name="测试",
                trade_date=date(2024, 1, 1),
                long_weight=0.7,
                hedge_weight=0.3,
                hedge_ratio=0.43,
                current_correlation=1.1,
            )


class TestHedgeAlert:
    """Tests for HedgeAlert entity"""

    def test_create_valid_alert(self):
        """Test creating a valid hedge alert"""
        alert = HedgeAlert(
            pair_name="股债对冲",
            alert_date=date(2024, 1, 1),
            alert_type=HedgeAlertType.CORRELATION_BREAKDOWN,
            message="对冲相关性失效",
            current_value=0.5,
            threshold_value=0.3,
            action_required="调整对冲比例",
        )
        assert alert.pair_name == "股债对冲"
        assert alert.alert_type == HedgeAlertType.CORRELATION_BREAKDOWN

    def test_default_values(self):
        """Test default values for optional fields"""
        alert = HedgeAlert(
            pair_name="测试",
            alert_date=date(2024, 1, 1),
            alert_type=HedgeAlertType.BETA_CHANGE,
            message="测试消息",
        )
        assert alert.severity == "medium"
        assert alert.current_value == 0.0
        assert alert.threshold_value == 0.0
        assert alert.action_required == ""
        assert alert.action_priority == 5
        assert alert.is_resolved is False
        assert alert.resolved_at is None

    def test_pair_name_cannot_be_empty(self):
        """Test empty pair name raises error"""
        with pytest.raises(ValueError, match="Pair name cannot be empty"):
            HedgeAlert(
                pair_name="",
                alert_date=date(2024, 1, 1),
                alert_type=HedgeAlertType.BETA_CHANGE,
                message="测试",
            )

    def test_message_cannot_be_empty(self):
        """Test empty message raises error"""
        with pytest.raises(ValueError, match="Alert message cannot be empty"):
            HedgeAlert(
                pair_name="测试",
                alert_date=date(2024, 1, 1),
                alert_type=HedgeAlertType.BETA_CHANGE,
                message="",
            )

    def test_action_priority_bounds(self):
        """Test action_priority must be between 1 and 10"""
        # Test valid boundaries
        alert1 = HedgeAlert(
            pair_name="测试",
            alert_date=date(2024, 1, 1),
            alert_type=HedgeAlertType.BETA_CHANGE,
            message="测试",
            action_priority=1,
        )
        assert alert1.action_priority == 1

        alert2 = HedgeAlert(
            pair_name="测试",
            alert_date=date(2024, 1, 1),
            alert_type=HedgeAlertType.BETA_CHANGE,
            message="测试",
            action_priority=10,
        )
        assert alert2.action_priority == 10

        # Test out of range
        with pytest.raises(ValueError, match="action_priority must be between 1 and 10"):
            HedgeAlert(
                pair_name="测试",
                alert_date=date(2024, 1, 1),
                alert_type=HedgeAlertType.BETA_CHANGE,
                message="测试",
                action_priority=0,
            )

        with pytest.raises(ValueError, match="action_priority must be between 1 and 10"):
            HedgeAlert(
                pair_name="测试",
                alert_date=date(2024, 1, 1),
                alert_type=HedgeAlertType.BETA_CHANGE,
                message="测试",
                action_priority=11,
            )


class TestHedgePerformance:
    """Tests for HedgePerformance entity"""

    def test_create_valid_performance(self):
        """Test creating a valid hedge performance record"""
        performance = HedgePerformance(
            pair_name="股债对冲",
            period_start=date(2023, 1, 1),
            period_end=date(2024, 1, 1),
            total_return=0.08,
            annual_return=0.08,
            sharpe_ratio=1.2,
            volatility_reduction=0.3,
            drawdown_reduction=0.25,
            hedge_effectiveness=0.7,
            hedge_cost=0.02,
            cost_benefit_ratio=3.5,
            avg_correlation=-0.6,
            correlation_stability=0.8,
        )
        assert performance.pair_name == "股债对冲"
        assert performance.total_return == 0.08

    def test_default_values(self):
        """Test values are set correctly"""
        performance = HedgePerformance(
            pair_name="测试",
            period_start=date(2023, 1, 1),
            period_end=date(2024, 1, 1),
            total_return=0.05,
            annual_return=0.05,
            sharpe_ratio=0.8,
            volatility_reduction=0.2,
            drawdown_reduction=0.15,
            hedge_effectiveness=0.6,
            hedge_cost=0.01,
            cost_benefit_ratio=2.0,
            avg_correlation=-0.5,
            correlation_stability=0.7,
        )
        assert performance.volatility_reduction == 0.2
        assert performance.drawdown_reduction == 0.15
        assert performance.hedge_effectiveness == 0.6

    def test_period_start_before_end(self):
        """Test period_start must be before period_end"""
        with pytest.raises(ValueError, match="period_start must be before period_end"):
            HedgePerformance(
                pair_name="测试",
                period_start=date(2024, 1, 1),
                period_end=date(2023, 1, 1),
                total_return=0.05,
                annual_return=0.05,
                sharpe_ratio=0.8,
                volatility_reduction=0.2,
                drawdown_reduction=0.15,
                hedge_effectiveness=0.6,
                hedge_cost=0.01,
                cost_benefit_ratio=2.0,
                avg_correlation=-0.5,
                correlation_stability=0.7,
            )


class TestFactoryFunctions:
    """Tests for factory functions"""

    def test_get_common_hedge_pairs(self):
        """Test getting common hedge pairs"""
        pairs = get_common_hedge_pairs()
        assert len(pairs) > 0

        # Check for expected pairs
        pair_names = [p.name for p in pairs]
        assert "股债对冲" in pair_names
        assert "成长价值对冲" in pair_names
        assert "大小盘对冲" in pair_names

        # Check all pairs have valid assets
        for pair in pairs:
            assert pair.long_asset != pair.hedge_asset
            assert 0 <= pair.target_long_weight <= 1
            assert 0 <= pair.target_hedge_weight <= 1

    def test_create_default_hedge_config(self):
        """Test creating default hedge configuration"""
        config = create_default_hedge_config()
        assert config.name == "默认股债对冲"
        assert config.long_asset == "510300"
        assert config.hedge_asset == "511260"
        assert config.hedge_method == HedgeMethod.BETA
        assert config.target_long_weight == 0.7
        assert config.target_hedge_weight == 0.3
        assert config.min_correlation == -0.8
        assert config.max_correlation == -0.2
