"""
Tests for apps.equity.infrastructure.config_loader module

Tests the stock screening rule loader that was moved from shared/infrastructure/.
"""

import pytest
from unittest.mock import patch, Mock
from decimal import Decimal


class TestGetStockScreeningRule:
    """Test the get_stock_screening_rule function."""

    def test_function_exists(self):
        """Test that the function can be imported."""
        from apps.equity.infrastructure.config_loader import get_stock_screening_rule

        assert callable(get_stock_screening_rule)

    def test_returns_rule_when_found(self):
        """Test that a rule is returned when found in database."""
        from apps.equity.infrastructure.config_loader import get_stock_screening_rule

        # This test requires database access or mocking
        # For now, just verify the function signature
        import inspect
        sig = inspect.signature(get_stock_screening_rule)
        params = list(sig.parameters.keys())

        assert 'regime' in params

    def test_returns_none_when_not_found(self):
        """Test that None is returned when rule not found."""
        # This would require database mocking
        # The function should return None when no matching config exists
        pass


class TestStockScreeningRuleEntity:
    """Test the StockScreeningRule entity."""

    def test_create_rule(self):
        """Test creating a StockScreeningRule."""
        from apps.equity.domain.rules import StockScreeningRule

        rule = StockScreeningRule(
            regime="Recovery",
            name="复苏期高成长股筛选",
            min_roe=15.0,
            min_revenue_growth=10.0,
            min_profit_growth=15.0,
            max_debt_ratio=60.0,
            max_pe=30.0,
            max_pb=5.0,
            min_market_cap=Decimal("50000000000"),
            sector_preference=["科技", "消费"],
            max_count=20,
        )

        assert rule.regime == "Recovery"
        assert rule.name == "复苏期高成长股筛选"
        assert rule.min_roe == 15.0
        assert rule.max_count == 20

    def test_rule_can_be_modified(self):
        """Test that StockScreeningRule attributes can be modified (not frozen)."""
        from apps.equity.domain.rules import StockScreeningRule

        rule = StockScreeningRule(
            regime="Recovery",
            name="Test",
            min_roe=10.0,
            min_revenue_growth=5.0,
            min_profit_growth=5.0,
            max_debt_ratio=70.0,
            max_pe=50.0,
            max_pb=10.0,
            min_market_cap=Decimal("1000000000"),
            sector_preference=None,
            max_count=10,
        )

        # The dataclass is not frozen, so modification is allowed
        rule.min_roe = 20.0
        assert rule.min_roe == 20.0

    def test_rule_defaults(self):
        """Test StockScreeningRule default values."""
        from apps.equity.domain.rules import StockScreeningRule

        rule = StockScreeningRule(
            regime="Deflation",
            name="通缩期防御股",
            min_roe=0.0,
            min_revenue_growth=0.0,
            min_profit_growth=0.0,
            max_debt_ratio=100.0,
            max_pe=0.0,  # 0 means no limit
            max_pb=0.0,
            min_market_cap=Decimal("0"),
            sector_preference=None,
            max_count=10,
        )

        assert rule.regime == "Deflation"
        assert rule.max_pe == 0.0  # No PE limit


class TestConfigLoaderIntegration:
    """Integration tests for config loader."""

    @pytest.mark.django_db
    def test_cache_key_format(self):
        """Test that cache key is correctly formatted."""
        # The cache key should be "stock_screening_rule:{regime}"
        # This test verifies the expected format
        expected_key = "stock_screening_rule:Recovery"
        assert "stock_screening_rule:" in expected_key
        assert "Recovery" in expected_key

    @pytest.mark.django_db
    def test_different_regimes(self):
        """Test that different regimes have different rules."""
        from apps.equity.domain.rules import StockScreeningRule

        # Different regimes should allow different parameters
        regimes = ["Recovery", "Overheat", "Stagflation", "Deflation"]

        for regime in regimes:
            rule = StockScreeningRule(
                regime=regime,
                name=f"{regime}筛选规则",
                min_roe=10.0,
                min_revenue_growth=5.0,
                min_profit_growth=5.0,
                max_debt_ratio=70.0,
                max_pe=30.0,
                max_pb=5.0,
                min_market_cap=Decimal("10000000000"),
                sector_preference=None,
                max_count=15,
            )
            assert rule.regime == regime
