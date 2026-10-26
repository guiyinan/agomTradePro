"""Tests for simulated buy execution traceability."""

from dataclasses import replace

from apps.simulated_trading.application.use_cases import ExecuteBuyOrderUseCase
from apps.simulated_trading.domain.entities import (
    AccountType,
    FeeConfig,
    Position,
    SimulatedAccount,
    SimulatedTrade,
)


class InMemoryAccountRepo:
    def __init__(self, account: SimulatedAccount) -> None:
        self.account = account

    def get_by_id(self, account_id: int) -> SimulatedAccount | None:
        return self.account if self.account.account_id == account_id else None

    def save(self, account: SimulatedAccount) -> None:
        self.account = account


class InMemoryPositionRepo:
    def __init__(self) -> None:
        self.positions: dict[tuple[int, str], Position] = {}

    def get_position(self, account_id: int, asset_code: str) -> Position | None:
        return self.positions.get((account_id, asset_code))

    def save(self, position: Position) -> None:
        self.positions[(position.account_id, position.asset_code)] = position

    def delete(self, account_id: int, asset_code: str) -> bool:
        return self.positions.pop((account_id, asset_code), None) is not None


class InMemoryTradeRepo:
    def __init__(
        self,
        account_repo: InMemoryAccountRepo,
        position_repo: InMemoryPositionRepo,
    ) -> None:
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.saved: list[SimulatedTrade] = []

    def save(self, trade: SimulatedTrade) -> int:
        self.saved.append(trade)
        return len(self.saved)

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
        """Commit the Trade and account/position snapshots after exact rechecks."""

        del fee_config
        current_position = self.position_repo.get_position(
            expected_account.account_id,
            trade.asset_code,
        )
        if (
            self.account_repo.get_by_id(expected_account.account_id) != expected_account
            or current_position != expected_position
            or trade.account_id != expected_account.account_id
            or trade.trade_id != 0
            or resulting_account.account_id != expected_account.account_id
        ):
            raise AssertionError("fake trade repository received a stale or mismatched snapshot")

        persisted_trade = replace(trade, trade_id=len(self.saved) + 1)
        self.account_repo.save(resulting_account)
        if resulting_position is None:
            self.position_repo.delete(expected_account.account_id, trade.asset_code)
        else:
            self.position_repo.save(resulting_position)
        self.saved.append(persisted_trade)
        return persisted_trade


class StubSignalRepo:
    def get_signal_invalidation_payload(self, signal_id: int):
        assert signal_id == 99
        return (
            '{"logic":"AND","conditions":[{"indicator_code":"PMI","operator":"<","threshold":50}]}',
            "PMI 跌破 50",
        )


class StaticFeeConfigRepo:
    def get_default_config(self, asset_type: str = "all") -> FeeConfig:
        return FeeConfig(
            config_id=1,
            config_name="test",
            asset_type=asset_type,
            min_commission=5.0,
            is_default=True,
        )


def test_execute_buy_order_copies_signal_traceability_into_position():
    account_repo = InMemoryAccountRepo(
        SimulatedAccount(
            account_id=1,
            account_name="Demo",
            account_type=AccountType.SIMULATED,
            initial_capital=100000.0,
            current_cash=100000.0,
            current_market_value=0.0,
            total_value=100000.0,
        )
    )
    position_repo = InMemoryPositionRepo()
    trade_repo = InMemoryTradeRepo(account_repo, position_repo)

    use_case = ExecuteBuyOrderUseCase(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        fee_config_repo=StaticFeeConfigRepo(),
        signal_repo=StubSignalRepo(),
    )

    trade = use_case.execute(
        account_id=1,
        asset_code="000001.SZ",
        asset_name="PingAn",
        asset_type="equity",
        quantity=100,
        price=10.0,
        reason="alpha buy",
        signal_id=99,
    )

    position = position_repo.get_position(1, "000001.SZ")

    assert trade.trade_id == 1
    assert trade.signal_id == 99
    assert position is not None
    assert position.signal_id == 99
    assert position.invalidation_rule_json == (
        '{"logic":"AND","conditions":[{"indicator_code":"PMI","operator":"<","threshold":50}]}'
    )
    assert position.invalidation_description == "PMI 跌破 50"
