"""End-to-end style tests for the alpha exit loop."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock

from apps.decision_rhythm.application.exit_advisors import DecisionRhythmExitAdvisor
from apps.decision_rhythm.domain.entities import (
    RecommendationStatus,
    UnifiedRecommendation,
    UserDecisionAction,
)
from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
from apps.simulated_trading.application.use_cases import (
    ExecuteBuyOrderUseCase,
    ExecuteSellOrderUseCase,
)
from apps.simulated_trading.domain.entities import (
    AccountType,
    Position,
    SimulatedAccount,
    TradeAction,
)


class InMemoryAccountRepo:
    def __init__(self, account: SimulatedAccount):
        self.account = account

    def get_by_id(self, account_id: int):
        return self.account if self.account.account_id == account_id else None

    def get_active_accounts(self):
        return [self.account] if self.account.is_active else []

    def save(self, account: SimulatedAccount):
        self.account = account


class InMemoryPositionRepo:
    def __init__(self):
        self.positions: dict[tuple[int, str], Position] = {}

    def get_position(self, account_id: int, asset_code: str):
        return self.positions.get((account_id, asset_code))

    def get_by_account(self, account_id: int):
        return [
            position
            for (stored_account_id, _), position in self.positions.items()
            if stored_account_id == account_id
        ]

    def save(self, position: Position):
        self.positions[(position.account_id, position.asset_code)] = position

    def delete(self, account_id: int, asset_code: str):
        self.positions.pop((account_id, asset_code), None)


class InMemoryTradeRepo:
    def __init__(self):
        self.saved = []

    def save(self, trade) -> int:
        self.saved.append(trade)
        return len(self.saved)


class StaticPriceProvider:
    def __init__(self, price: float):
        self.price = price

    def get_price(self, asset_code: str, trade_date: date) -> float | None:
        return self.price


class StubSignalRepo:
    def get_signal_invalidation_payload(self, signal_id: int):
        assert signal_id == 99
        return (
            '{"logic":"AND","conditions":[{"indicator_code":"PMI","operator":"<","threshold":50}]}',
            "PMI 跌破 50",
        )


class StaticSignalService:
    def get_signal_by_id(self, signal_id: int) -> dict | None:
        return {"id": signal_id, "is_valid": True}


class FakeRecommendationRepo:
    def __init__(self, recommendations: list[UnifiedRecommendation]):
        self.recommendations = recommendations

    def get_by_account(self, account_id: str):
        return [rec for rec in self.recommendations if rec.account_id == account_id]


class NullTransitionPlanRepo:
    def get_latest_for_account(self, account_id: str):
        return None


def _build_account() -> SimulatedAccount:
    return SimulatedAccount(
        account_id=1,
        account_name="Demo",
        account_type=AccountType.SIMULATED,
        initial_capital=100000.0,
        current_cash=100000.0,
        current_market_value=0.0,
        total_value=100000.0,
        auto_trading_enabled=True,
    )


def _build_engine(
    *,
    account_repo: InMemoryAccountRepo,
    position_repo: InMemoryPositionRepo,
    trade_repo: InMemoryTradeRepo,
    price: float,
    exit_advisor=None,
):
    buy_use_case = ExecuteBuyOrderUseCase(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        signal_repo=StubSignalRepo(),
    )
    sell_use_case = ExecuteSellOrderUseCase(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
    )
    engine = AutoTradingEngine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        buy_use_case=buy_use_case,
        sell_use_case=sell_use_case,
        performance_use_case=Mock(),
        price_provider=StaticPriceProvider(price),
        signal_service=StaticSignalService(),
        exit_advisor=exit_advisor,
    )
    engine._get_buy_candidates = Mock(return_value=[])
    engine._update_account_performance = Mock()
    return engine, buy_use_case


def _make_sell_recommendation(account_id: str, security_code: str) -> UnifiedRecommendation:
    now = datetime.now(UTC)
    return UnifiedRecommendation(
        recommendation_id="urec_exit_001",
        account_id=account_id,
        security_code=security_code,
        side="SELL",
        confidence=0.82,
        composite_score=0.22,
        fair_value=Decimal("9.80"),
        entry_price_low=Decimal("9.50"),
        entry_price_high=Decimal("10.00"),
        target_price_low=Decimal("11.50"),
        target_price_high=Decimal("12.20"),
        stop_loss_price=Decimal("9.10"),
        position_pct=5.0,
        suggested_quantity=0,
        max_capital=Decimal("50000"),
        source_signal_ids=["99"],
        source_candidate_ids=[],
        feature_snapshot_id="fsn_exit_001",
        status=RecommendationStatus.NEW,
        user_action=UserDecisionAction.ADOPTED,
        user_action_note="",
        user_action_at=now,
        created_at=now,
        updated_at=now,
        human_rationale="Alpha 衰减，统一推荐转 SELL",
    )


def test_buy_then_position_invalidation_then_next_auto_trading_sells():
    account_repo = InMemoryAccountRepo(_build_account())
    position_repo = InMemoryPositionRepo()
    trade_repo = InMemoryTradeRepo()
    engine, buy_use_case = _build_engine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        price=9.8,
    )

    buy_trade = buy_use_case.execute(
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
    assert position is not None
    assert position.invalidation_rule_json is not None

    position.is_invalidated = True
    position.invalidation_reason = "PMI 跌破 50"
    position_repo.save(position)

    buy_count, sell_count = engine._execute_legacy_trading(account_repo.account, date(2026, 4, 30))

    assert buy_trade.signal_id == 99
    assert buy_count == 0
    assert sell_count == 1
    assert position_repo.get_position(1, "000001.SZ") is None
    assert len(trade_repo.saved) == 2
    assert trade_repo.saved[-1].action == TradeAction.SELL
    assert trade_repo.saved[-1].signal_id == 99
    assert trade_repo.saved[-1].reason == "PMI 跌破 50"


def test_buy_then_sell_recommendation_exits_on_next_auto_trading_cycle():
    account_repo = InMemoryAccountRepo(_build_account())
    position_repo = InMemoryPositionRepo()
    trade_repo = InMemoryTradeRepo()
    recommendation_repo = FakeRecommendationRepo(
        [_make_sell_recommendation(account_id="1", security_code="000001.SZ")]
    )
    exit_advisor = DecisionRhythmExitAdvisor(
        recommendation_repo=recommendation_repo,
        transition_plan_repo=NullTransitionPlanRepo(),
    )
    engine, buy_use_case = _build_engine(
        account_repo=account_repo,
        position_repo=position_repo,
        trade_repo=trade_repo,
        price=10.2,
        exit_advisor=exit_advisor,
    )

    buy_use_case.execute(
        account_id=1,
        asset_code="000001.SZ",
        asset_name="PingAn",
        asset_type="equity",
        quantity=100,
        price=10.0,
        reason="alpha buy",
        signal_id=99,
    )

    buy_count, sell_count = engine._execute_legacy_trading(account_repo.account, date(2026, 4, 30))

    assert buy_count == 0
    assert sell_count == 1
    assert position_repo.get_position(1, "000001.SZ") is None
    assert len(trade_repo.saved) == 2
    assert trade_repo.saved[-1].action == TradeAction.SELL
    assert trade_repo.saved[-1].reason == "Alpha 衰减，统一推荐转 SELL"
