"""Sell use-case behavior when cost-basis knowledge is incomplete."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date

import pytest

from apps.simulated_trading.application.use_cases import ExecuteSellOrderUseCase
from apps.simulated_trading.domain.entities import (
    AccountType,
    FeeConfig,
    OrderStatus,
    Position,
    SimulatedAccount,
    SimulatedTrade,
    TradeAction,
)

_LOGGER_NAME = "apps.simulated_trading.application.use_cases"
_EXECUTION_DATE = date(2026, 10, 19)


class _AccountRepository:
    """In-memory account port that records each use-case save call."""

    def __init__(self, account: SimulatedAccount, owner_user_id: int = 1) -> None:
        self.account: SimulatedAccount | None = account
        self.owner_user_id = owner_user_id
        self.saved: list[SimulatedAccount] = []

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        if self.account is None or self.account.account_id != account_id:
            return None
        return self.account

    def get_by_name(
        self,
        account_name: str,
        user_id: int | None = None,
    ) -> SimulatedAccount | None:
        if (
            self.account is None
            or self.account.account_name != account_name
            or (user_id is not None and user_id != self.owner_user_id)
        ):
            return None
        return self.account

    def get_active_accounts(self) -> list[SimulatedAccount]:
        if self.account is None or not self.account.is_active:
            return []
        return [self.account]

    def get_all_accounts(self) -> list[SimulatedAccount]:
        return [self.account] if self.account is not None else []

    def get_by_user(self, user_id: int) -> list[SimulatedAccount]:
        if self.account is None or user_id != self.owner_user_id:
            return []
        return [self.account]

    def save(self, account: SimulatedAccount, user_id: int | None = None) -> int:
        self.account = account
        if user_id is not None:
            self.owner_user_id = user_id
        self.saved.append(account)
        return account.account_id

    def delete(self, account_id: int) -> bool:
        if self.account is None or self.account.account_id != account_id:
            return False
        self.account = None
        return True


class _PositionRepository:
    """In-memory position port that records update and delete operations."""

    def __init__(self, position: Position) -> None:
        self.positions: dict[tuple[int, str], Position] = {
            (position.account_id, position.asset_code): position
        }
        self.saved: list[Position] = []
        self.deleted: list[tuple[int, str]] = []

    def save(self, position: Position) -> int:
        key = (position.account_id, position.asset_code)
        self.positions[key] = position
        self.saved.append(position)
        return len(self.saved)

    def get_by_account(self, account_id: int) -> list[Position]:
        return [
            position for position in self.positions.values() if position.account_id == account_id
        ]

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        return self.positions.get((account_id, asset_code))

    def delete(self, account_id: int, asset_code: str) -> bool:
        self.deleted.append((account_id, asset_code))
        return self.positions.pop((account_id, asset_code), None) is not None


class _TradeRepository:
    """In-memory trade port that commits deterministic trade and ledger snapshots."""

    def __init__(
        self,
        account_repo: _AccountRepository,
        position_repo: _PositionRepository,
    ) -> None:
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.saved: list[SimulatedTrade] = []

    def save(self, trade: SimulatedTrade) -> int:
        trade_id = len(self.saved) + 1
        self.saved.append(replace(trade, trade_id=trade_id))
        return trade_id

    def get_by_account(self, account_id: int) -> list[SimulatedTrade]:
        return [trade for trade in self.saved if trade.account_id == account_id]

    def get_by_date_range(
        self,
        account_id: int,
        start: date,
        end: date,
    ) -> list[SimulatedTrade]:
        return [
            trade
            for trade in self.saved
            if trade.account_id == account_id and start <= trade.execution_date <= end
        ]

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
        """Commit the in-memory ledger update through the current repository port."""

        del fee_config
        current_position = self.position_repo.get_position(
            expected_account.account_id,
            trade.asset_code,
        )
        if self.account_repo.account != expected_account or current_position != expected_position:
            raise AssertionError("fake trade repository received a stale account/position snapshot")

        trade_id = self.save(trade)
        persisted_trade = self.saved[-1]
        if persisted_trade.trade_id != trade_id:
            raise AssertionError("fake trade repository assigned an inconsistent trade identity")
        self.account_repo.save(resulting_account)
        if resulting_position is None:
            self.position_repo.delete(expected_account.account_id, trade.asset_code)
        else:
            self.position_repo.save(resulting_position)
        return persisted_trade


class _FeeConfigRepository:
    """Return an explicit zero-fee configuration for deterministic PnL cases."""

    def __init__(self) -> None:
        self.config = FeeConfig(
            config_id=1,
            config_name="nullable-sell-log-test",
            asset_type="equity",
            min_commission=0.0,
            commission_rate_sell=0.0,
            stamp_duty_rate=0.0,
            transfer_fee_rate=0.0,
            min_transfer_fee=0.0,
            slippage_rate=0.0,
            is_default=True,
        )

    def get_default_config(self, asset_type: str = "all") -> FeeConfig | None:
        return self.config if asset_type in {"equity", "all"} else None


def _build_sell_use_case(
    *,
    cost_basis_known: bool | None,
    current_price: float,
    starting_quantity: float = 200.0,
    avg_cost: float = 10.0,
) -> tuple[
    ExecuteSellOrderUseCase,
    _AccountRepository,
    _PositionRepository,
    _TradeRepository,
]:
    """Construct the actual use case with typed in-memory repository ports."""

    market_value = starting_quantity * current_price
    unrealized_pnl = (current_price - avg_cost) * starting_quantity
    if avg_cost == 0.0:
        # The zero-basis fixture fully closes before this nonnullable percentage is reused.
        unrealized_pnl_pct = 0.0
    else:
        unrealized_pnl_pct = ((current_price - avg_cost) / avg_cost) * 100.0
    position = Position(
        account_id=1,
        asset_code="600000.SH",
        asset_name="浦发银行",
        asset_type="equity",
        quantity=starting_quantity,
        available_quantity=starting_quantity,
        avg_cost=avg_cost,
        total_cost=starting_quantity * avg_cost,
        current_price=current_price,
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_pct=unrealized_pnl_pct,
        first_buy_date=date(2026, 10, 16),
        last_update_date=date(2026, 10, 16),
        available_quantity_known=True,
        valuation_known=True,
        cost_basis_known=cost_basis_known,
    )
    account = SimulatedAccount(
        account_id=1,
        account_name="nullable sell log test",
        account_type=AccountType.SIMULATED,
        initial_capital=100_000.0,
        current_cash=100_000.0,
        current_market_value=market_value,
        total_value=100_000.0 + market_value,
        max_position_pct=100.0,
    )
    account_repo = _AccountRepository(account)
    position_repo = _PositionRepository(position)
    trade_repo = _TradeRepository(account_repo, position_repo)
    sell_use_case = ExecuteSellOrderUseCase(
        account_repo,
        position_repo,
        trade_repo,
        _FeeConfigRepository(),
    )
    return sell_use_case, account_repo, position_repo, trade_repo


@pytest.mark.parametrize(
    ("cost_basis_known", "sell_all"),
    [
        (False, False),
        (None, False),
        (False, True),
        (None, True),
    ],
    ids=(
        "partial-basis-incomplete",
        "partial-basis-unknown",
        "full-basis-incomplete",
        "full-basis-unknown",
    ),
)
def test_unknown_cost_sell_returns_trade_and_updates_three_ports(
    caplog: pytest.LogCaptureFixture,
    cost_basis_known: bool | None,
    sell_all: bool,
) -> None:
    """Verify return values and individual port writes, without asserting transaction atomicity."""

    starting_quantity = 100.0 if sell_all else 200.0
    sell_quantity = int(starting_quantity) if sell_all else 100
    sell_use_case, account_repo, position_repo, trade_repo = _build_sell_use_case(
        cost_basis_known=cost_basis_known,
        current_price=11.0,
        starting_quantity=starting_quantity,
    )
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)

    trade = sell_use_case.execute(
        account_id=1,
        asset_code="600000.SH",
        quantity=sell_quantity,
        price=11.0,
        reason="unknown cost basis fixture",
        execution_date=_EXECUTION_DATE,
    )

    assert trade.trade_id == 1
    assert trade.action is TradeAction.SELL
    assert trade.status is OrderStatus.EXECUTED
    assert trade.quantity == float(sell_quantity)
    assert trade.amount == pytest.approx(float(sell_quantity) * 11.0)
    assert trade.realized_pnl is None
    assert trade.realized_pnl_pct is None
    assert trade.cost_basis_known is cost_basis_known
    assert trade.fee_amounts_known is True
    assert len(trade_repo.saved) == 1
    assert trade_repo.saved[0].realized_pnl is None
    assert trade_repo.saved[0].realized_pnl_pct is None
    assert trade_repo.saved[0].cost_basis_known is cost_basis_known

    remaining_quantity = starting_quantity - float(sell_quantity)
    if sell_all:
        assert position_repo.saved == []
        assert position_repo.deleted == [(1, "600000.SH")]
        assert position_repo.get_position(1, "600000.SH") is None
    else:
        remaining = position_repo.get_position(1, "600000.SH")
        assert remaining is not None
        assert remaining.quantity == remaining_quantity
        assert remaining.available_quantity == remaining_quantity
        assert remaining.cost_basis_known is cost_basis_known
        assert position_repo.saved == [remaining]
        assert position_repo.deleted == []

    assert len(account_repo.saved) == 1
    updated_account = account_repo.account
    assert updated_account is not None
    expected_cash = 100_000.0 + float(sell_quantity) * 11.0
    expected_market_value = remaining_quantity * 11.0
    assert updated_account.current_cash == pytest.approx(expected_cash)
    assert updated_account.current_market_value == pytest.approx(expected_market_value)
    assert updated_account.total_value == pytest.approx(expected_cash + expected_market_value)
    assert updated_account.total_trades == 1
    assert updated_account.winning_trades == 0
    assert "盈亏: 未知 (未知)" in caplog.text


def test_known_zero_average_cost_full_sell_keeps_pnl_known_and_pct_unknown(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Zero basis is allowed and leaves only the realized percentage undefined."""

    sell_use_case, account_repo, position_repo, trade_repo = _build_sell_use_case(
        cost_basis_known=True,
        current_price=10.0,
        starting_quantity=100.0,
        avg_cost=0.0,
    )
    initial_position = position_repo.get_position(1, "600000.SH")
    assert initial_position is not None
    assert initial_position.avg_cost == 0.0
    assert initial_position.total_cost == 0.0
    assert initial_position.cost_basis_known is True
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)

    trade = sell_use_case.execute(
        account_id=1,
        asset_code="600000.SH",
        quantity=100,
        price=10.0,
        reason="known zero cost basis fixture",
        execution_date=_EXECUTION_DATE,
    )

    assert trade.status is OrderStatus.EXECUTED
    assert trade.cost_basis_known is True
    assert trade.fee_amounts_known is True
    assert trade.realized_pnl == pytest.approx(1_000.0)
    assert trade.realized_pnl_pct is None
    assert len(trade_repo.saved) == 1
    assert trade_repo.saved[0].realized_pnl == pytest.approx(1_000.0)
    assert trade_repo.saved[0].realized_pnl_pct is None
    assert position_repo.saved == []
    assert position_repo.deleted == [(1, "600000.SH")]
    assert position_repo.get_position(1, "600000.SH") is None

    assert len(account_repo.saved) == 1
    updated_account = account_repo.account
    assert updated_account is not None
    assert updated_account.current_cash == pytest.approx(101_000.0)
    assert updated_account.current_market_value == pytest.approx(0.0)
    assert updated_account.total_value == pytest.approx(101_000.0)
    assert "盈亏: 1000.00 (未知)" in caplog.text


def test_known_break_even_sell_keeps_zero_amounts_visible(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Known break-even values remain visible instead of being treated as missing."""

    sell_use_case, _, _, _ = _build_sell_use_case(
        cost_basis_known=True,
        current_price=10.0,
    )
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)

    trade = sell_use_case.execute(
        account_id=1,
        asset_code="600000.SH",
        quantity=100,
        price=10.0,
        reason="known breakeven fixture",
        execution_date=_EXECUTION_DATE,
    )

    assert trade.realized_pnl == 0.0
    assert trade.realized_pnl_pct == 0.0
    assert "盈亏: 0.00 (0.00%)" in caplog.text
