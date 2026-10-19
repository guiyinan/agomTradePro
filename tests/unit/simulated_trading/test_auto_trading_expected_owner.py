"""Keep automatic bridge ownership bound to the HTTP authorization principal."""

from __future__ import annotations

from collections.abc import Callable
from inspect import signature
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock
from uuid import UUID

import pytest

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.application.automatic_invocation import AutoTradingRequestActor
from apps.simulated_trading.application.automatic_trade_execution import (
    AutomaticTradeExecutionBridge,
    AutomaticTradeExecutionPreflightBlocked,
)
from apps.simulated_trading.application.interface_services import AutoTradingAccountScopeResult
from apps.simulated_trading.application.manual_trade_execution import (
    ExecuteCurrentReferenceManualTradeUseCase,
)
from apps.simulated_trading.domain.auto_trading_outcomes import AccountAutoTradingOutcome
from apps.simulated_trading.domain.entities import SimulatedTrade
from apps.simulated_trading.execution_current_reference_composition import (
    build_automatic_trade_execution_bridge,
)
from tests.unit.simulated_trading.test_automatic_invocation_application import (
    _MemoryInvocationRepository,
)
from tests.unit.simulated_trading.test_automatic_trade_execution import (
    ACCOUNT_ID,
    ASSET_CODE,
    RUN_ID,
    TRADE_DATE,
    USER_ID,
    _Harness,
    _harness,
)


class _ObservedOwnerReader:
    """Return a persisted owner once, optionally changing after that read."""

    def __init__(self, owner_id: int, *, owner_after_read: int | None = None) -> None:
        """Configure the owner value observed by the bridge and later by storage."""
        self.owner_id = owner_id
        self.owner_after_read = owner_after_read
        self.read_account_ids: list[int] = []

    def get_owner_id(self, *, account_id: int) -> int | None:
        """Record the scoped lookup, then model a transfer after the returned read."""
        self.read_account_ids.append(account_id)
        observed = self.owner_id
        if self.owner_after_read is not None:
            self.owner_id = self.owner_after_read
            self.owner_after_read = None
        return observed


def _require_keyword(function: Callable[..., object], keyword: str) -> None:
    """Fail as a behavior assertion when the expected-owner seam is not wired."""
    if keyword not in signature(function).parameters:
        pytest.fail(f"{function.__qualname__} does not accept {keyword}")


def _owner_bound_bridge(
    *, expected_owner_id: int, owner_reader: _ObservedOwnerReader
) -> tuple[AutomaticTradeExecutionBridge, _Harness]:
    """Reuse exact current-reference/calendar fixtures with an owner-aware bridge."""
    _require_keyword(AutomaticTradeExecutionBridge, "expected_owner_id")
    harness = _harness()
    bridge = AutomaticTradeExecutionBridge(
        run_id=RUN_ID,
        execution_date=TRADE_DATE,
        account_ids=(ACCOUNT_ID,),
        expected_owner_id=expected_owner_id,
        owner_reader=owner_reader,
        position_repository=harness.position_reader,
        identity_reader=harness.identity_reader,
        calendar_reader=harness.calendar_reader,
        manual_use_case=cast(ExecuteCurrentReferenceManualTradeUseCase, harness.manual_executor),
        clock=harness.clock,
        price_lookup=harness.price_lookup,
    )
    return bridge, harness


def _execute_fixture_buy(bridge: AutomaticTradeExecutionBridge) -> SimulatedTrade:
    """Invoke the actual bridge callback with the fixture's captured historical price."""
    price = bridge.price_provider.require_price(ASSET_CODE, TRADE_DATE)
    return bridge.buy_use_case.execute(
        account_id=ACCOUNT_ID,
        asset_code=ASSET_CODE,
        asset_name="Unit Security",
        asset_type="equity",
        quantity=100,
        price=price,
        reason="owner binding fixture",
        execution_date=TRADE_DATE,
    )


@pytest.mark.parametrize(
    ("is_superuser", "expected_owner_id"),
    ((False, USER_ID), (True, None)),
)
def test_http_request_binds_actor_owner_before_engine_construction(
    monkeypatch: pytest.MonkeyPatch,
    is_superuser: bool,
    expected_owner_id: int | None,
) -> None:
    """Bind ordinary callers to their actor and leave trusted superuser runs unbound."""
    repository = _MemoryInvocationRepository()
    monkeypatch.setattr(
        interface_services,
        "get_auto_invocation_repository",
        Mock(return_value=repository),
    )
    scope_reads: list[tuple[int, tuple[int, ...] | None]] = []

    def resolve_scope(
        actor: AutoTradingRequestActor, selected: list[int] | None
    ) -> AutoTradingAccountScopeResult:
        """Return one test-owned authorized account scope for both authorization passes."""
        scope_reads.append((actor.id, tuple(selected) if selected is not None else None))
        return AutoTradingAccountScopeResult(account_ids=(ACCOUNT_ID,))

    monkeypatch.setattr(interface_services, "resolve_auto_trading_account_scope", resolve_scope)
    engine = Mock()
    engine.run_daily_trading.return_value = {
        ACCOUNT_ID: AccountAutoTradingOutcome(
            account_id=ACCOUNT_ID,
            buy_count=0,
            sell_count=0,
        )
    }
    builder = Mock(return_value=engine)
    monkeypatch.setattr(interface_services, "build_auto_trading_engine", builder)

    actor = AutoTradingRequestActor(id=USER_ID, is_superuser=is_superuser)
    interface_services.run_auto_trading_request(
        actor=actor,
        invocation_key=f"owner-http-{int(is_superuser)}-001",
        trade_date=TRADE_DATE,
        account_ids=[ACCOUNT_ID],
    )

    builder.assert_called_once()
    assert builder.call_args is not None
    assert builder.call_args.kwargs.get("expected_owner_id") == expected_owner_id
    assert scope_reads == [(USER_ID, (ACCOUNT_ID,)), (USER_ID, (ACCOUNT_ID,))]


def test_auto_engine_builder_forwards_expected_owner_to_bridge_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the original HTTP owner in the bridge factory call, not a later lookup."""
    _require_keyword(interface_services.build_auto_trading_engine, "expected_owner_id")
    for name in (
        "get_simulated_account_repository",
        "get_simulated_position_repository",
        "get_simulated_trade_repository",
        "get_signal_repository",
        "get_asset_pool_query_repository",
        "GetAccountPerformanceUseCase",
        "AssetPoolQueryService",
        "build_decision_rhythm_exit_advisor",
    ):
        monkeypatch.setattr(interface_services, name, Mock(return_value=object()))
    invocation_id = UUID("06eaad8e-37b0-4c44-a310-e154b1453b7e")
    bridge = SimpleNamespace(
        buy_use_case=object(),
        sell_use_case=object(),
        price_provider=object(),
    )
    bridge_factory = Mock(return_value=bridge)
    monkeypatch.setattr(interface_services, "get_automatic_trade_execution_bridge", bridge_factory)
    monkeypatch.setattr(interface_services, "build_decision_execution_link_recorder", Mock())
    monkeypatch.setattr(interface_services, "AutoTradingEngine", Mock())

    interface_services.build_auto_trading_engine(
        invocation_id=invocation_id,
        expected_owner_id=USER_ID,
    )

    bridge_factory.assert_called_once_with(invocation_id, expected_owner_id=USER_ID)


def test_root_composition_binds_expected_owner_into_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Carry the same expected owner through root composition without reading a new one."""
    import apps.simulated_trading.execution_current_reference_composition as composition

    _require_keyword(build_automatic_trade_execution_bridge, "expected_owner_id")
    invocation_id = UUID("fa8ae815-4d20-4e4c-8a1f-991c00fb1d08")
    scope = SimpleNamespace(trade_date=TRADE_DATE, account_ids=(ACCOUNT_ID,))
    invocation_repository = SimpleNamespace(get_preparing_scope=Mock(return_value=scope))
    components = SimpleNamespace(
        identity_reader=object(),
        calendar_reader=object(),
        clock=object(),
        manual_use_case=object(),
    )
    bridge = object()
    bridge_factory = Mock(return_value=bridge)
    monkeypatch.setattr(
        composition,
        "DjangoAutoTradingInvocationRepository",
        Mock(return_value=invocation_repository),
    )
    monkeypatch.setattr(
        composition,
        "_build_current_reference_manual_execution_components",
        Mock(return_value=components),
    )
    for name in (
        "DjangoSimulatedAccountRepository",
        "DjangoPositionRepository",
        "UnifiedPriceService",
    ):
        monkeypatch.setattr(composition, name, Mock(return_value=object()))
    monkeypatch.setattr(composition, "AutomaticTradeExecutionBridge", bridge_factory)

    actual = build_automatic_trade_execution_bridge(
        invocation_id,
        expected_owner_id=USER_ID,
    )

    assert actual is bridge
    bridge_factory.assert_called_once()
    assert bridge_factory.call_args is not None
    assert bridge_factory.call_args.kwargs["expected_owner_id"] == USER_ID
    assert invocation_repository.get_preparing_scope.call_args.kwargs == {
        "invocation_id": invocation_id
    }


def test_owner_transfer_before_bridge_read_is_blocked_before_manual_execution() -> None:
    """A newly read owner cannot replace the caller whose HTTP authorization expired."""
    owner_reader = _ObservedOwnerReader(USER_ID + 1)
    bridge, harness = _owner_bound_bridge(
        expected_owner_id=USER_ID,
        owner_reader=owner_reader,
    )

    with pytest.raises(AutomaticTradeExecutionPreflightBlocked):
        _execute_fixture_buy(bridge)

    assert owner_reader.read_account_ids == [ACCOUNT_ID]
    assert harness.manual_executor.requests == []


def test_owner_transfer_after_read_keeps_original_owner_on_manual_request() -> None:
    """The UoW receives the actor owner id; this stub does not prove its lock-time check."""
    owner_reader = _ObservedOwnerReader(USER_ID, owner_after_read=USER_ID + 1)
    bridge, harness = _owner_bound_bridge(
        expected_owner_id=USER_ID,
        owner_reader=owner_reader,
    )

    _execute_fixture_buy(bridge)

    assert owner_reader.owner_id == USER_ID + 1
    assert len(harness.manual_executor.requests) == 1
    assert harness.manual_executor.requests[0].user_id == USER_ID
    assert owner_reader.read_account_ids == [ACCOUNT_ID]
