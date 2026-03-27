from apps.simulated_trading.domain.services import PositionCostBasisService


class TestPositionCostBasisService:
    def test_calculate_lot_cost_includes_commission_and_slippage(self):
        avg_cost, total_cost = PositionCostBasisService.calculate_lot_cost(
            quantity=1000,
            price=10.0,
            commission=5.0,
            slippage=10.0,
        )

        assert total_cost == 10015.0
        assert avg_cost == 10.015

    def test_merge_position_cost_uses_total_cost_basis(self):
        avg_cost, total_cost = PositionCostBasisService.merge_position_cost(
            existing_quantity=1000,
            existing_total_cost=10015.0,
            added_quantity=1000,
            added_total_cost=12017.0,
        )

        assert total_cost == 22032.0
        assert avg_cost == 11.016
