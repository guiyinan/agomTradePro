"""Bounded retry coverage for account-first compatibility settlement."""

from dataclasses import replace
from datetime import date

import pytest

from apps.simulated_trading.application.use_cases import ExecuteSellOrderUseCase
from apps.simulated_trading.domain.entities import (
    AccountType,
    FeeConfig,
    Position,
    SimulatedAccount,
    SimulatedTrade,
)
from core.exceptions import BusinessLogicError


class _State:
    def __init__(self) -> None:
        self.account = SimulatedAccount(
            account_id=1,
            account_name="retry-test",
            account_type=AccountType.SIMULATED,
            initial_capital=100_000.0,
            current_cash=50_000.0,
            current_market_value=2_200.0,
            total_value=52_200.0,
        )
        self.position: Position | None = Position(
            account_id=1,
            asset_code="600000.SH",
            asset_name="asset",
            asset_type="equity",
            quantity=200.0,
            available_quantity=200.0,
            avg_cost=10.0,
            total_cost=2_000.0,
            current_price=11.0,
            market_value=2_200.0,
            unrealized_pnl=200.0,
            unrealized_pnl_pct=10.0,
            first_buy_date=date(2026, 10, 1),
            last_update_date=date(2026, 10, 1),
            cost_basis_known=True,
        )
        self.trade: SimulatedTrade | None = None
        self.attempts = 0
        self.always_stale = False


class _AccountRepository:
    def __init__(self, state: _State) -> None:
        self.state = state

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.state.account if account_id == self.state.account.account_id else None


class _PositionRepository:
    def __init__(self, state: _State) -> None:
        self.state = state

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        position = self.state.position
        if position is not None and (position.account_id, position.asset_code) == (
            account_id,
            asset_code,
        ):
            return position
        return None


class _FeeConfigRepository:
    def __init__(self) -> None:
        self.config = FeeConfig(
            config_id=1,
            config_name="zero-fee",
            asset_type="equity",
            min_commission=0.0,
            commission_rate_buy=0.0,
            commission_rate_sell=0.0,
            stamp_duty_rate=0.0,
            transfer_fee_rate=0.0,
            min_transfer_fee=0.0,
            slippage_rate=0.0,
            is_default=True,
        )

    def get_default_config(self, asset_type: str = "all") -> FeeConfig | None:
        return self.config if asset_type in {"all", "equity"} else None


class _AtomicTradeRepository:
    def __init__(self, state: _State) -> None:
        self.state = state

    def execute_legacy_trade_atomically(
        self,
        *,
        expected_account: SimulatedAccount,
        expected_position: Position | None,
        fee_config: FeeConfig,
        trade: SimulatedTrade,
        resulting_position: Position | None,
        resulting_account: SimulatedAccount,
    ) -> SimulatedTrade:
        del fee_config
        self.state.attempts += 1
        if self.state.always_stale or self.state.attempts == 1:
            # Model an intervening correction under the account lock boundary.
            self.state.account = replace(
                self.state.account,
                current_cash=self.state.account.current_cash - 10.0,
                total_value=self.state.account.total_value - 10.0,
            )
            if self.state.position is not None:
                self.state.position = replace(
                    self.state.position,
                    avg_cost=10.05,
                    total_cost=2_010.0,
                )
            raise BusinessLogicError(
                "snapshot changed",
                code="POSITION_CHANGED_RETRY_REQUIRED",
            )

        if self.state.account != expected_account or self.state.position != expected_position:
            raise BusinessLogicError(
                "snapshot changed",
                code="POSITION_CHANGED_RETRY_REQUIRED",
            )
        self.state.account = resulting_account
        self.state.position = resulting_position
        self.state.trade = replace(trade, trade_id=1)
        return self.state.trade


def _sell_use_case(state: _State) -> ExecuteSellOrderUseCase:
    return ExecuteSellOrderUseCase(
        _AccountRepository(state),
        _PositionRepository(state),
        _AtomicTradeRepository(state),
        _FeeConfigRepository(),
    )


def test_sell_retries_from_corrected_cash_and_basis_snapshot() -> None:
    state = _State()

    trade = _sell_use_case(state).execute(
        account_id=1,
        asset_code="600000.SH",
        quantity=100,
        price=11.0,
        execution_date=date(2026, 10, 25),
    )

    assert state.attempts == 2
    assert trade.trade_id == 1
    assert trade.realized_pnl == pytest.approx(95.0, abs=1e-9, rel=0)
    assert state.position is not None
    assert state.position.quantity == 100.0
    assert state.account.current_cash == 51_090.0
    assert state.trade == trade


def test_sell_retry_exhaustion_does_not_publish_a_trade() -> None:
    state = _State()
    state.always_stale = True

    with pytest.raises(BusinessLogicError) as raised:
        _sell_use_case(state).execute(
            account_id=1,
            asset_code="600000.SH",
            quantity=100,
            price=11.0,
        )

    assert raised.value.code == "POSITION_CHANGED_RETRY_EXHAUSTED"
    assert state.attempts == 3
    assert state.trade is None
    assert state.account.current_cash == 49_970.0
    assert state.account.total_trades == 0
    assert state.position is not None
    assert state.position.quantity == 200.0
    assert state.position.total_cost == 2_010.0
