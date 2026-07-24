"""Strategy target-output and cross-module gateway contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.strategy.application.execution_gateway import (
    InspectionSelection,
    StrategyExecutionGateway,
    get_strategy_execution_gateway,
)
from apps.strategy.application.target_portfolio_use_cases import (
    BuildTargetPortfolioUseCase,
)


def test_target_portfolio_is_deterministic_and_requires_snapshot() -> None:
    """Strategy weights become a validated, stable target tied to one snapshot."""
    strategy = SimpleNamespace(
        calculate_targets=lambda snapshot_id, parameters: {
            "600000.SH": Decimal("0.3"),
            "000001.SZ": Decimal("0.5"),
        }
    )
    use_case = BuildTargetPortfolioUseCase(strategy)
    target = use_case.execute(
        decision_snapshot_id="snapshot-1",
        strategy_version="v1",
        parameters={"lookback": 20},
        target_cash_weight=Decimal("0.2"),
        explanation="recovery",
    )
    repeated = use_case.execute(
        decision_snapshot_id="snapshot-1",
        strategy_version="v1",
        parameters={"lookback": 20},
        target_cash_weight=Decimal("0.2"),
    )
    assert target.target_id == repeated.target_id
    assert [position.asset_code for position in target.positions] == [
        "000001.SZ",
        "600000.SH",
    ]
    with pytest.raises(ValueError, match="snapshot"):
        use_case.execute(
            decision_snapshot_id="",
            strategy_version="v1",
            parameters={},
            target_cash_weight=Decimal("1"),
        )


def test_strategy_execution_gateway_maps_success_failure_and_exceptions() -> None:
    """Gateway returns stable DTOs for executor success, business failure, and crash."""
    raw_signal = SimpleNamespace(
        asset_code="000001.SZ",
        asset_name="Ping An",
        action=SimpleNamespace(value="buy"),
        quantity=100,
        confidence=0.9,
        reason="momentum",
        metadata={"source": "rule"},
    )
    executed_at = datetime.now(UTC)
    executor = SimpleNamespace(
        execute_strategy=lambda **kwargs: SimpleNamespace(
            is_success=True,
            signals=[raw_signal],
            execution_time=executed_at,
            error_message="",
        )
    )
    gateway = StrategyExecutionGateway(executor=executor)
    result = gateway.execute_for_account(1, 2)
    assert result.success is True
    assert result.signals[0].action == "buy"
    assert result.execution_time == executed_at

    executor.execute_strategy = lambda **kwargs: SimpleNamespace(
        is_success=False,
        signals=[],
        execution_time=None,
        error_message="risk denied",
    )
    assert gateway.execute_for_account(1, 2).error_message == "risk denied"

    def _raise(**kwargs: object):
        raise RuntimeError("engine unavailable")

    executor.execute_strategy = _raise
    assert gateway.execute_for_account(1, 2).error_message == "engine unavailable"


def test_strategy_gateway_query_fallbacks_and_singleton(monkeypatch) -> None:
    """Query methods preserve repository values and fail closed on dependency errors."""
    repository = SimpleNamespace(
        get_strategy_info=lambda strategy_id: {"id": strategy_id, "is_active": True},
        get_active_strategy_binding=lambda account_id: {"account_id": account_id},
        get_inspection_selection=lambda **kwargs: InspectionSelection(
            strategy_id=kwargs.get("strategy_id"),
            position_rule_id=9,
            rule_metadata={"mode": "daily"},
        ),
        evaluate_position_rule=lambda rule_id, context: {"rule_id": rule_id, **context},
    )
    gateway = StrategyExecutionGateway(query_repository=repository)
    assert gateway.get_strategy_info(3)["id"] == 3
    assert gateway.get_active_strategy_binding(4)["account_id"] == 4
    assert gateway.is_strategy_active(3) is True
    assert gateway.get_inspection_selection(4, 3).position_rule_id == 9
    assert gateway.evaluate_position_rule(None, {}) is None
    assert gateway.evaluate_position_rule(9, {"price": 10})["price"] == 10

    repository.get_strategy_info = lambda strategy_id: (_ for _ in ()).throw(
        RuntimeError("offline")
    )
    repository.get_active_strategy_binding = lambda account_id: (_ for _ in ()).throw(
        RuntimeError("offline")
    )
    repository.get_inspection_selection = lambda **kwargs: (_ for _ in ()).throw(
        RuntimeError("offline")
    )
    repository.evaluate_position_rule = lambda *args: (_ for _ in ()).throw(RuntimeError("offline"))
    assert gateway.get_strategy_info(3) is None
    assert gateway.get_active_strategy_binding(4) is None
    assert gateway.get_inspection_selection(4).strategy_id is None
    assert gateway.evaluate_position_rule(9, {}) is None

    import apps.strategy.application.execution_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "_gateway_instance", None)
    assert get_strategy_execution_gateway() is get_strategy_execution_gateway()
