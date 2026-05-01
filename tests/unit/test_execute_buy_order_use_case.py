"""Tests for simulated buy execution traceability."""

from apps.simulated_trading.application.use_cases import ExecuteBuyOrderUseCase
from apps.simulated_trading.domain.entities import AccountType, SimulatedAccount


class InMemoryAccountRepo:
    def __init__(self, account: SimulatedAccount):
        self.account = account

    def get_by_id(self, account_id: int):
        return self.account if self.account.account_id == account_id else None

    def save(self, account: SimulatedAccount):
        self.account = account


class InMemoryPositionRepo:
    def __init__(self):
        self.positions: dict[tuple[int, str], object] = {}

    def get_position(self, account_id: int, asset_code: str):
        return self.positions.get((account_id, asset_code))

    def save(self, position):
        self.positions[(position.account_id, position.asset_code)] = position


class InMemoryTradeRepo:
    def __init__(self):
        self.saved = []

    def save(self, trade) -> int:
        self.saved.append(trade)
        return len(self.saved)


class StubSignalRepo:
    def get_signal_invalidation_payload(self, signal_id: int):
        assert signal_id == 99
        return (
            '{"logic":"AND","conditions":[{"indicator_code":"PMI","operator":"<","threshold":50}]}',
            "PMI 跌破 50",
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
    trade_repo = InMemoryTradeRepo()

    use_case = ExecuteBuyOrderUseCase(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
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
