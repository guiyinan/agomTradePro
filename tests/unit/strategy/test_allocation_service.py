from types import SimpleNamespace

from apps.strategy.application.allocation_service import AllocationService


def _position(asset_code: str, asset_class: str, market_value: float):
    return SimpleNamespace(
        asset_code=asset_code,
        asset_class=SimpleNamespace(value=asset_class),
        market_value=market_value,
    )


def test_allocation_service_accepts_position_protocol_without_account_entity():
    advice = AllocationService.calculate_allocation_advice(
        current_regime="Recovery",
        risk_profile="moderate",
        policy_level="P1",
        total_assets=1000.0,
        current_positions=[_position("510300.SH", "equity", 600.0)],
        asset_name_resolver=None,
    )

    assert advice.current_allocation["equity"] == 0.6
    assert advice.current_allocation["cash"] == 0.4
