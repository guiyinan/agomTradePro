"""Cash evidence contracts for real broker-projected accounts."""

from __future__ import annotations

import logging
from datetime import date

import pytest

from apps.simulated_trading.application import interface_services, query_services
from apps.simulated_trading.application.auto_trading_buy_risk import build_buy_risk_issue
from apps.simulated_trading.domain.auto_trading_outcomes import AutoTradingIssueKind
from apps.simulated_trading.domain.entities import (
    AccountType,
    SimulatedAccount,
)
from apps.simulated_trading.interface._view_helpers import _account_payload
from apps.simulated_trading.interface.serializers import AccountResponseSerializer


def _account(account_type: AccountType) -> SimulatedAccount:
    """Build one account with populated numeric storage and default evidence state."""

    return SimulatedAccount(
        account_id=1,
        account_name="cash knowledge fixture",
        account_type=account_type,
        initial_capital=100_000.0,
        current_cash=12_345.0,
        current_market_value=67_890.0,
        total_value=80_235.0,
        start_date=date(2026, 10, 19),
    )


class _PositionRepository:
    """A repository stub that records whether risk reached position lookup."""

    def __init__(self) -> None:
        self.called = False

    def get_by_account(self, account_id: int) -> list[object]:
        self.called = True
        return []


class _RiskGuard:
    """A guard stub that must not see an account with unknown cash."""

    def __init__(self) -> None:
        self.called = False

    def execute(self, **kwargs: object) -> object:
        self.called = True
        raise AssertionError("unknown account cash must stop before centralized risk")


def test_account_type_defaults_preserve_simulated_ledger_and_reject_real_cash_claim() -> None:
    """A real account never inherits the simulated account's known-cash default."""

    simulated = _account(AccountType.SIMULATED)
    real = _account(AccountType.REAL)

    assert simulated.cash_known is True
    assert simulated.cash_reconciliation_status.value == "simulated_ledger"
    assert real.cash_known is False
    assert real.cash_reconciliation_status.value == "unverified"
    assert real.available_cash_for_buy() == 0.0


def test_unknown_cash_blocks_auto_buy_before_position_or_risk_reads() -> None:
    """Automatic buy risk rejects placeholder cash with a stable business issue."""

    positions = _PositionRepository()
    guard = _RiskGuard()
    issue = build_buy_risk_issue(
        account=_account(AccountType.REAL),
        asset_code="600000.SH",
        quantity=100.0,
        price=10.0,
        position_repo=positions,  # type: ignore[arg-type]
        pre_trade_risk_guard=guard,  # type: ignore[arg-type]
        logger=logging.getLogger(__name__),
    )

    assert issue is not None
    assert issue.kind is AutoTradingIssueKind.BLOCKED
    assert issue.code == "ACCOUNT_CASH_UNKNOWN"
    assert positions.called is False
    assert guard.called is False


def test_account_cards_and_user_totals_return_null_for_unverified_cash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cards and aggregates do not serialize stored zero or stale cash as current."""

    account = _account(AccountType.REAL)

    class _AccountRepository:
        def get_by_user(self, user_id: int) -> list[SimulatedAccount]:
            return [account]

    class _PositionRepository:
        def get_by_account(self, account_id: int) -> list[object]:
            return []

    monkeypatch.setattr(
        query_services,
        "get_simulated_account_repository",
        lambda: _AccountRepository(),
    )
    monkeypatch.setattr(
        query_services,
        "get_simulated_position_repository",
        lambda: _PositionRepository(),
    )

    card = query_services.list_dashboard_account_payloads(user_id=7)[0]
    totals = query_services.get_user_account_totals(user_id=7)

    assert card["cash"] is None
    assert card["cash_known"] is False
    assert card["cash_reconciliation_status"] == "unverified"
    assert card["total_value"] is None
    assert "ACCOUNT_CASH_UNKNOWN" in card["blocking_reason_codes"]
    assert totals is not None
    assert totals["cash_balance"] is None
    assert totals["total_assets"] is None
    assert totals["cash_known"] is False


def test_account_http_response_serializes_unknown_cash_and_derived_values_as_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account API masks placeholder balances and uses stubbed Application evidence."""

    valuation_account_ids: list[int] = []
    cost_account_ids: list[int] = []

    def has_current_position_valuation(account_id: int) -> bool:
        valuation_account_ids.append(account_id)
        return True

    def has_complete_closed_trade_costs(account_id: int) -> bool:
        cost_account_ids.append(account_id)
        return True

    monkeypatch.setattr(
        interface_services,
        "has_current_position_valuation",
        has_current_position_valuation,
    )
    monkeypatch.setattr(
        interface_services,
        "has_complete_closed_trade_costs",
        has_complete_closed_trade_costs,
    )

    payload = _account_payload(_account(AccountType.REAL))
    serializer = AccountResponseSerializer(data=payload)

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["current_cash"] is None
    assert serializer.validated_data["total_value"] is None
    assert serializer.validated_data["total_return"] is None
    assert serializer.validated_data["winning_trades"] is None
    assert serializer.validated_data["cash_known"] is False
    assert serializer.validated_data["cash_reconciliation_status"] == "unverified"
    assert valuation_account_ids == [1]
    assert cost_account_ids == [1]
