"""Daily inspection safety and normalization tests."""

from dataclasses import replace
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


class TrackingStrategyGateway:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate_position_rule(
        self,
        rule_id: int,
        context: dict[str, object],
    ) -> dict[str, object]:
        self.calls += 1
        return {"rule_id": rule_id, "entry_price": context["entry_price"]}


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


def test_position_rule_is_blocked_for_unknown_cost_basis(monkeypatch) -> None:
    """An old numeric average cost cannot be passed as a known rule entry price."""
    _disable_asset_class_checks(monkeypatch)
    gateway = TrackingStrategyGateway()
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service."
        "get_strategy_execution_gateway",
        lambda: gateway,
    )
    position = _position()
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([position]))

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=InspectionSelection(
            strategy_id=None,
            rule_id=17,
            rule_metadata={},
        ),
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert gateway.calls == 0
    assert checks[0]["rule_eval"] is None
    assert checks[0]["rule_eval_blocked_reason_code"] == "POSITION_COST_BASIS_UNKNOWN"
    assert checks[0]["cost_basis_status"] == "unknown"


def test_position_rule_uses_cost_basis_only_when_explicitly_known(monkeypatch) -> None:
    """An explicitly complete basis preserves the existing rule evaluation path."""
    _disable_asset_class_checks(monkeypatch)
    gateway = TrackingStrategyGateway()
    monkeypatch.setattr(
        "apps.simulated_trading.application.daily_inspection_service."
        "get_strategy_execution_gateway",
        lambda: gateway,
    )
    position = replace(_position(), cost_basis_known=True)
    monkeypatch.setattr(DailyInspectionService, "position_repo", PositionRepo([position]))

    checks = DailyInspectionService._build_checks(
        account=_account(),
        selection=InspectionSelection(
            strategy_id=None,
            rule_id=17,
            rule_metadata={},
        ),
        macro_regime="Recovery",
        policy_gear="P0",
        pulse_context=DailyInspectionService._empty_pulse_context(),
    )

    assert gateway.calls == 1
    assert checks[0]["rule_eval"] == {"rule_id": 17, "entry_price": 5.0}
    assert checks[0]["rule_eval_blocked_reason_code"] is None
    assert checks[0]["cost_basis_status"] == "known"
