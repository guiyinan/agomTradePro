"""Invariant coverage for simulated buy and sell execution."""

from datetime import date
from inspect import Parameter, signature

import pytest

from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    FeeConfig,
    Position,
    SimulatedAccount,
    SimulatedTrade,
)
from apps.simulated_trading.infrastructure.models import FeeConfigModel


class AccountRepo:
    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account
        self.saved: list[SimulatedAccount] = []

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.account if self.account.account_id == account_id else None

    def save(
        self,
        account: SimulatedAccount,
        user_id: int | None = None,
    ) -> int:
        self.account = account
        self.saved.append(account)
        return account.account_id


class PositionRepo:
    def __init__(self, position: Position | None = None) -> None:
        self.position = position
        self.saved: list[Position] = []
        self.deleted = False

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        if (
            self.position is not None
            and self.position.account_id == account_id
            and self.position.asset_code == asset_code
        ):
            return self.position
        return None

    def save(self, position: Position) -> int:
        self.position = position
        self.saved.append(position)
        return 1

    def delete(self, account_id: int, asset_code: str) -> bool:
        self.deleted = True
        self.position = None
        return True


class TradeRepo:
    def __init__(self) -> None:
        self.saved: list[SimulatedTrade] = []

    def save(self, trade: SimulatedTrade) -> int:
        self.saved.append(trade)
        return len(self.saved)


class FeeConfigRepo:
    def __init__(self, config: FeeConfig | None) -> None:
        self.config = config
        self.requested_asset_types: list[str] = []

    def get_default_config(self, asset_type: str = "all") -> FeeConfig | None:
        self.requested_asset_types.append(asset_type)
        return self.config


def _account(*, cash: float = 100_000.0, market_value: float = 0.0) -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="test",
        account_type=AccountType.SIMULATED,
        initial_capital=100_000.0,
        current_cash=cash,
        current_market_value=market_value,
        total_value=cash + market_value,
        max_position_pct=100.0,
    )


def _fee_config(*, minimum: float = 7.5) -> FeeConfig:
    return FeeConfig(
        config_id=7,
        config_name="database-config",
        asset_type="equity",
        commission_rate_buy=0.0,
        commission_rate_sell=0.0,
        min_commission=minimum,
        stamp_duty_rate=0.0,
        transfer_fee_rate=0.0,
        min_transfer_fee=0.0,
        slippage_rate=0.0,
        is_default=True,
    )


def _position(*, invalidated: bool = False) -> Position:
    return Position(
        account_id=1,
        asset_code="000001.SZ",
        asset_name="test asset",
        asset_type="equity",
        quantity=1_000.0,
        available_quantity=500.0,
        avg_cost=10.0,
        total_cost=10_000.0,
        current_price=10.0,
        market_value=10_000.0,
        unrealized_pnl=0.0,
        unrealized_pnl_pct=0.0,
        first_buy_date=date(2026, 7, 1),
        last_update_date=date(2026, 7, 1),
        is_invalidated=invalidated,
    )


def test_minimum_commission_has_no_runtime_or_orm_default() -> None:
    domain_parameter = signature(FeeConfig).parameters["min_commission"]
    model_field = FeeConfigModel._meta.get_field("min_commission")

    assert domain_parameter.default is Parameter.empty
    assert model_field.has_default() is False


def test_buy_uses_configured_minimum_commission_in_cash_validation() -> None:
    account_repo = AccountRepo(_account(cash=1_006.0))
    position_repo = PositionRepo()
    trade_repo = TradeRepo()
    use_case = ExecuteBuyOrderUseCase(
        account_repo,
        position_repo,
        trade_repo,
        FeeConfigRepo(_fee_config(minimum=7.5)),
    )

    with pytest.raises(ValueError, match=r"现金不足.*1007\.50"):
        use_case.execute(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="test asset",
            asset_type="equity",
            quantity=100,
            price=10.0,
        )

    assert trade_repo.saved == []
    assert position_repo.saved == []
    assert account_repo.saved == []


def test_buy_rejects_missing_fee_configuration() -> None:
    use_case = ExecuteBuyOrderUseCase(
        AccountRepo(_account()),
        PositionRepo(),
        TradeRepo(),
        FeeConfigRepo(None),
    )

    with pytest.raises(ValueError, match="未配置启用的默认交易费率"):
        use_case.execute(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="test asset",
            asset_type="equity",
            quantity=100,
            price=10.0,
        )


@pytest.mark.parametrize("price", [0.0, -1.0])
def test_order_execution_rejects_nonpositive_prices(price: float) -> None:
    fee_repo = FeeConfigRepo(_fee_config())
    buy_use_case = ExecuteBuyOrderUseCase(
        AccountRepo(_account()),
        PositionRepo(),
        TradeRepo(),
        fee_repo,
    )
    sell_use_case = ExecuteSellOrderUseCase(
        AccountRepo(_account(market_value=10_000.0)),
        PositionRepo(_position()),
        TradeRepo(),
        fee_repo,
    )

    with pytest.raises(ValueError, match="买入价格必须大于0"):
        buy_use_case.execute(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="test asset",
            asset_type="equity",
            quantity=100,
            price=price,
        )
    with pytest.raises(ValueError, match="卖出价格必须大于0"):
        sell_use_case.execute(
            account_id=1,
            asset_code="000001.SZ",
            quantity=100,
            price=price,
        )


def test_partial_sell_preserves_unavailable_quantity_and_execution_date() -> None:
    account_repo = AccountRepo(_account(market_value=10_000.0))
    position_repo = PositionRepo(_position())
    trade_repo = TradeRepo()
    use_case = ExecuteSellOrderUseCase(
        account_repo,
        position_repo,
        trade_repo,
        FeeConfigRepo(_fee_config()),
    )
    trade_date = date(2026, 7, 23)

    trade = use_case.execute(
        account_id=1,
        asset_code="000001.SZ",
        quantity=500,
        price=11.0,
        execution_date=trade_date,
    )

    assert trade.commission == 7.5
    assert trade.execution_date == trade_date
    assert position_repo.position is not None
    assert position_repo.position.quantity == 500.0
    assert position_repo.position.available_quantity == 0.0
    assert position_repo.position.last_update_date == trade_date
    assert account_repo.account.last_trade_date == trade_date


def test_buy_rejects_addition_to_invalidated_position() -> None:
    use_case = ExecuteBuyOrderUseCase(
        AccountRepo(_account(market_value=10_000.0)),
        PositionRepo(_position(invalidated=True)),
        TradeRepo(),
        FeeConfigRepo(_fee_config()),
    )

    with pytest.raises(ValueError, match="禁止加仓"):
        use_case.execute(
            account_id=1,
            asset_code="000001.SZ",
            asset_name="test asset",
            asset_type="equity",
            quantity=100,
            price=10.0,
        )
