"""Knowledge states and order rules reject numeric placeholders as evidence."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from apps.simulated_trading.domain.entities import (
    AccountCashReconciliationStatus,
    AccountType,
    FeeConfig,
    Position,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)
from apps.simulated_trading.domain.rules import TradingConstraintRule


def _account(account_type: AccountType = AccountType.SIMULATED) -> SimulatedAccount:
    """Build a complete account with realistic positive ledger balances."""
    return SimulatedAccount(
        account_id=17,
        account_name="Domain knowledge guardrail fixture",
        account_type=account_type,
        initial_capital=100_000.0,
        current_cash=100_000.0,
        current_market_value=0.0,
        total_value=100_000.0,
        start_date=date(2026, 10, 19),
    )


def _position(**changes: object) -> Position:
    """Build a complete position before applying one explicit evidence state."""
    position = Position(
        account_id=17,
        asset_code="600000.SH",
        asset_name="Guardrail holding",
        asset_type="equity",
        quantity=300.0,
        available_quantity=300.0,
        avg_cost=10.0,
        total_cost=3_000.0,
        current_price=11.0,
        market_value=3_300.0,
        unrealized_pnl=300.0,
        unrealized_pnl_pct=10.0,
        first_buy_date=date(2026, 10, 1),
        last_update_date=date(2026, 10, 19),
    )
    for name, value in changes.items():
        setattr(position, name, value)
    return position


def _fee_config(*, asset_type: str = "equity") -> FeeConfig:
    """Use explicit minimum commission and zero incidental rates for order checks."""
    return FeeConfig(
        config_id=2,
        config_name="Domain guardrail fee fixture",
        asset_type=asset_type,
        min_commission=0.0,
        commission_rate_buy=0.0,
        commission_rate_sell=0.0,
        stamp_duty_rate=0.001,
        transfer_fee_rate=0.00002,
        slippage_rate=0.0,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"cash_reconciliation_status": "unknown"},
        {"cash_known": 1},
        {"cash_known": False},
        {
            "cash_known": False,
            "cash_reconciliation_status": AccountCashReconciliationStatus.UNVERIFIED,
        },
        {
            "account_type": AccountType.REAL,
            "cash_known": True,
            "cash_reconciliation_status": AccountCashReconciliationStatus.SIMULATED_LEDGER,
        },
    ],
    ids=[
        "unknown-status",
        "nonboolean-known",
        "status-mismatch",
        "simulated-unverified",
        "real-claims-sim-ledger",
    ],
)
def test_cash_evidence_rejects_contradictory_or_untyped_account_states(
    changes: dict[str, object],
) -> None:
    """The account entity will not label an unsupported or inconsistent balance known."""
    with pytest.raises(ValueError):
        replace(_account(), **changes)


def test_real_account_default_keeps_stored_cash_out_of_buying_power() -> None:
    """A legacy numeric cash field on a real account is not evidence of available funds."""
    account = _account(AccountType.REAL)
    assert account.cash_known is False
    assert account.cash_reconciliation_status is AccountCashReconciliationStatus.UNVERIFIED
    assert account.available_cash_for_buy() == 0.0


@pytest.mark.parametrize(
    ("known", "expected"),
    [(True, "known"), (False, "partial"), (None, "unknown")],
)
def test_position_cost_basis_status_preserves_known_partial_and_unknown(
    known: bool | None,
    expected: str,
) -> None:
    """A stored subtotal is not upgraded when the fee evidence is partial or absent."""
    assert _position(cost_basis_known=known).cost_basis_status == expected


def test_position_invalidation_properties_follow_the_stored_evidence() -> None:
    """The rule and close signal remain independently visible on the entity."""
    position = _position(invalidation_rule_json=None, is_invalidated=False)
    assert position.has_invalidation_rule is False
    assert position.should_close is False
    position.invalidation_rule_json = '{"price_below": 9.0}'
    position.is_invalidated = True
    assert position.has_invalidation_rule is True
    assert position.should_close is True


def _trade(*, fee_known: bool | None, basis_known: bool | None) -> SimulatedTrade:
    """Build a fully identified SELL execution with an aware execution instant."""
    return SimulatedTrade(
        trade_id=23,
        account_id=17,
        asset_code="600000.SH",
        asset_name="Guardrail holding",
        asset_type="equity",
        action=TradeAction.SELL,
        quantity=100.0,
        price=11.0,
        amount=1_100.0,
        order_date=date(2026, 10, 19),
        execution_date=date(2026, 10, 19),
        execution_time=datetime(2026, 10, 19, 2, 0, tzinfo=UTC),
        fee_amounts_known=fee_known,
        cost_basis_known=basis_known,
    )


@pytest.mark.parametrize(
    ("known", "expected"),
    [(True, "known"), (False, "partial"), (None, "unknown")],
)
def test_trade_fee_status_distinguishes_complete_partial_and_missing_amounts(
    known: bool | None,
    expected: str,
) -> None:
    """Zero-filled storage remains distinct from fees established by the source."""
    assert _trade(fee_known=known, basis_known=None).fee_amounts_status == expected


@pytest.mark.parametrize(
    ("known", "expected"),
    [(True, "known"), (False, "partial"), (None, "unknown")],
)
def test_trade_cost_basis_status_distinguishes_complete_partial_and_missing_basis(
    known: bool | None,
    expected: str,
) -> None:
    """Historical PnL inputs carry their own basis completeness state."""
    assert _trade(fee_known=None, basis_known=known).cost_basis_status == expected


def test_fund_sell_fee_does_not_charge_equity_only_taxes_or_transfer_fee() -> None:
    """A fund execution does not inherit stock stamp duty or Shanghai transfer fees."""
    result = _fee_config(asset_type="fund").calculate_sell_fee(10_000.0, is_shanghai=True)
    assert result["stamp_duty"] == 0.0
    assert result["transfer_fee"] == 0.0


def test_buy_order_rejects_disabled_auto_trading_before_pricing() -> None:
    """A disabled account is rejected before fees or cash can make an order appear valid."""
    account = replace(_account(), auto_trading_enabled=False)
    assert TradingConstraintRule.validate_buy_order(
        account, "600000.SH", 100, 10, 0, _fee_config()
    ) == (False, "自动交易未启用")


def test_buy_order_rejects_nonpositive_price() -> None:
    """A zero quote cannot produce an accepted zero-value purchase."""
    assert TradingConstraintRule.validate_buy_order(
        _account(), "600000.SH", 100, 0, 0, _fee_config()
    ) == (False, "买入价格必须大于0")


def test_buy_order_rejects_nonpositive_quantity_after_lot_validation() -> None:
    """Zero shares satisfy the lot modulus but are still not an executable buy."""
    assert TradingConstraintRule.validate_buy_order(
        _account(), "600000.SH", 0, 10, 0, _fee_config()
    ) == (False, "买入数量必须大于0")


def test_buy_order_rejects_position_that_would_exceed_account_limit() -> None:
    """A valid-lot order cannot push one holding above its configured value cap."""
    account = replace(_account(), total_value=10_000.0, max_position_pct=20.0)
    allowed, reason = TradingConstraintRule.validate_buy_order(
        account,
        "600000.SH",
        100,
        2,
        1_900,
        _fee_config(),
    )
    assert allowed is False
    assert "超过最大持仓比例" in reason


def test_sell_order_rejects_nonpositive_execution_price() -> None:
    """An invalid explicit fill price is rejected before position evidence is read."""
    assert TradingConstraintRule.validate_sell_order(_position(), 100, 0) == (
        False,
        "卖出价格必须大于0",
    )


def test_sell_order_rejects_non_lot_quantity() -> None:
    """The A-share sell lot rule applies after quantity and valuation are known."""
    assert TradingConstraintRule.validate_sell_order(_position(), 50, 11) == (
        False,
        "数量必须为100的倍数",
    )


def test_sell_order_rejects_zero_quantity_after_lot_validation() -> None:
    """Zero shares pass modulo arithmetic but cannot be a sell instruction."""
    assert TradingConstraintRule.validate_sell_order(_position(), 0, 11) == (
        False,
        "卖出数量必须大于0",
    )
