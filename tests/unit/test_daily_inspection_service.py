"""Daily inspection safety and normalization tests."""

from datetime import date

from apps.simulated_trading.application.daily_inspection_service import (
    DailyInspectionService,
    InspectionSelection,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    Position,
    SimulatedAccount,
)


class PositionRepo:
    def __init__(self, positions: list[Position]) -> None:
        self.positions = positions

    def get_by_account(self, account_id: int) -> list[Position]:
        return self.positions


class StrategyGateway:
    def evaluate_position_rule(
        self,
        rule_id: int,
        context: dict[str, object],
    ) -> None:
        return None


def _account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="inspection",
        account_type=AccountType.SIMULATED,
        initial_capital=100_000.0,
        current_cash=50_000.0,
        current_market_value=50_000.0,
        total_value=100_000.0,
    )


def _position() -> Position:
    return Position(
        account_id=1,
        asset_code="abc.sz",
        asset_name="test asset",
        asset_type="equity",
        quantity=10_000.0,
        available_quantity=10_000.0,
        avg_cost=5.0,
        total_cost=50_000.0,
        current_price=0.0,
        market_value=50_000.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 1, 1),
        last_update_date=date(2026, 1, 1),
    )


def _disable_asset_class_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        DailyInspectionService,
        "_build_asset_class_checks",
        staticmethod(lambda **kwargs: []),
    )
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service."
        "get_strategy_execution_gateway",
        lambda: StrategyGateway(),
    )


def test_asset_targets_normalize_codes_without_creating_duplicate_buy(
    monkeypatch,
) -> None:
    _disable_asset_class_checks(monkeypatch)
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([_position()]))
    selection = InspectionSelection(
        strategy_id=None,
        rule_id=None,
        rule_metadata={
            "rebalance": {
                "target_weights": {" ABC.SZ ": 0.30},
                "drift_threshold": 0.05,
            }
        },
    )

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=selection,
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert len(checks) == 1
    assert checks[0]["target_weight"] == 0.30
    assert checks[0]["rebalance_action"] == "sell"
    assert checks[0]["rebalance_qty_suggest"] == 0
    assert checks[0]["quantity_available"] is False


def test_invalid_target_weights_do_not_generate_trade_advice(monkeypatch) -> None:
    _disable_asset_class_checks(monkeypatch)
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([_position()]))
    selection = InspectionSelection(
        strategy_id=None,
        rule_id=None,
        rule_metadata={
            "rebalance": {
                "target_weights": {
                    "ABC.SZ": float("nan"),
                    "OTHER.SZ": -0.2,
                },
                "drift_threshold": -1,
            }
        },
    )

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=selection,
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert len(checks) == 1
    assert checks[0]["target_weight"] is None
    assert checks[0]["rebalance_action"] == "hold"
