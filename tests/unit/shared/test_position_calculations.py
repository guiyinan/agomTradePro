"""
Unit tests for shared.domain.position_calculations.
"""

import pytest

from shared.domain.position_calculations import recalculate_derived_fields


class TestRecalculateDerivedFields:

    def test_basic_profit(self):
        mv, pnl, pnl_pct = recalculate_derived_fields(1000, 10.0, 12.0)
        assert mv == pytest.approx(12000.0)
        assert pnl == pytest.approx(2000.0)
        assert pnl_pct == pytest.approx(20.0)

    def test_basic_loss(self):
        mv, pnl, pnl_pct = recalculate_derived_fields(500, 20.0, 15.0)
        assert mv == pytest.approx(7500.0)
        assert pnl == pytest.approx(-2500.0)
        assert pnl_pct == pytest.approx(-25.0)

    def test_zero_pnl(self):
        mv, pnl, pnl_pct = recalculate_derived_fields(100, 5.0, 5.0)
        assert mv == pytest.approx(500.0)
        assert pnl == pytest.approx(0.0)
        assert pnl_pct == pytest.approx(0.0)

    def test_zero_cost_basis_returns_zero_pct(self):
        """Avoid division by zero when avg_cost is 0."""
        mv, pnl, pnl_pct = recalculate_derived_fields(100, 0.0, 10.0)
        assert mv == pytest.approx(1000.0)
        assert pnl == pytest.approx(1000.0)
        assert pnl_pct == 0.0

    def test_zero_shares(self):
        """Closed position: shares = 0."""
        mv, pnl, pnl_pct = recalculate_derived_fields(0, 10.0, 12.0)
        assert mv == pytest.approx(0.0)
        assert pnl == pytest.approx(0.0)
        assert pnl_pct == 0.0

    def test_fractional_shares(self):
        """Fund positions may have fractional units."""
        mv, pnl, pnl_pct = recalculate_derived_fields(10.5, 100.0, 110.0)
        assert mv == pytest.approx(1155.0)
        assert pnl == pytest.approx(105.0)
        assert pnl_pct == pytest.approx(10.0)
