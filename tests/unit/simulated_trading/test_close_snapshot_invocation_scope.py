"""Bind explicit close-purpose execution to one confirmed, bounded invocation."""

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest

from apps.simulated_trading.application import interface_services
from apps.simulated_trading.application.automatic_invocation import AutoTradingInvocationRequest
from core.exceptions import InvalidInputError


def _request(**changes: object) -> AutoTradingInvocationRequest:
    baseline = AutoTradingInvocationRequest(
        namespace="http:user:101",
        invocation_key="close-snapshot-check",
        trade_date=date(2026, 11, 2),
        requested_account_ids=(7,),
        market_purpose="close_snapshot_simulation",
        execution_scope="account_stop_loss_only",
        confirmed=True,
    )
    return replace(baseline, **changes)


def test_close_purpose_and_stop_loss_scope_are_distinct_immutable_identities() -> None:
    close = _request()
    intraday = _request(market_purpose="local_simulation_only")
    daily = AutoTradingInvocationRequest(
        "http:user:101", "close-snapshot-check", date(2026, 11, 2), (7,)
    )
    assert len({close.content_hash, intraday.content_hash, daily.content_hash}) == 3
    assert close.to_payload()["market_purpose"] == "close_snapshot_simulation"
    assert close.to_payload()["execution_scope"] == "account_stop_loss_only"
    assert close.to_payload()["confirmed"] is True
    assert set(daily.to_payload()) == {"schema", "trade_date", "account_ids"}


@pytest.mark.parametrize(
    "changes",
    [
        {"execution_scope": "daily_simulation"},
        {"requested_account_ids": None},
        {"confirmed": None},
        {"confirmed": False},
        {"confirmed": 1},
        {"market_purpose": "fresh_close"},
        {"execution_scope": "strategy_and_buy"},
    ],
)
def test_close_check_rejects_implicit_scope_or_missing_literal_confirmation(
    changes: dict[str, object],
) -> None:
    with pytest.raises(InvalidInputError):
        _request(**changes)


@pytest.mark.parametrize(
    "purpose,scope",
    [
        ("close_snapshot_simulation", "daily_simulation"),
        ("close_snapshot_simulation", "unknown"),
        ("local_simulation_only", "unknown"),
        ("unknown", "account_stop_loss_only"),
    ],
)
def test_direct_engine_composition_rejects_unbounded_close_execution_before_io(
    monkeypatch: pytest.MonkeyPatch,
    purpose: str,
    scope: str,
) -> None:
    """Direct Application callers cannot wire close sources into strategy or BUY runs."""

    def unexpected_read() -> None:
        raise AssertionError("invalid scope must fail before repository construction")

    monkeypatch.setattr(interface_services, "get_simulated_account_repository", unexpected_read)
    with pytest.raises(InvalidInputError):
        interface_services.build_auto_trading_engine(
            invocation_id=uuid4(),
            market_purpose=purpose,
            execution_scope=scope,
        )
