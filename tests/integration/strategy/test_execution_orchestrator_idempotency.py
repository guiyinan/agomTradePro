import uuid

import pytest
from django.contrib.auth.models import User

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.strategy.application.execution_orchestrator import (
    ExecutionConfig,
    ExecutionMode,
    ExecutionOrchestrator,
)
from apps.strategy.domain.entities import OrderStatus
from apps.strategy.infrastructure.models import OrderIntentModel, StrategyModel
from apps.strategy.infrastructure.repositories import DjangoOrderIntentRepository


class DummyPaperAdapter:
    def __init__(self):
        self.submit_count = 0

    def submit_order(self, intent) -> str:
        self.submit_count += 1
        return f"PAPER-{intent.intent_id}"

    def query_order_status(self, broker_order_id: str):
        return {"status": "filled", "filled_qty": 0, "filled_price": None, "remaining_qty": 0, "error_message": None}

    def cancel_order(self, broker_order_id: str) -> bool:
        return True

    def get_name(self) -> str:
        return "paper"

    def is_live(self) -> bool:
        return False


def _create_base_objects():
    unique = str(uuid.uuid4())[:8]
    user = User.objects.create_user(
        username=f"test_orchestrator_{unique}",
        email=f"test_orchestrator_{unique}@example.com",
        password="testpass123",
    )
    profile = AccountProfileModel.objects.get(user=user)
    strategy = StrategyModel.objects.create(
        name=f"ExecutionOrchestratorStrategy-{unique}",
        strategy_type="rule_based",
        version=1,
        is_active=True,
        description="test",
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        created_by=profile,
    )
    portfolio = SimulatedAccountModel.objects.create(
        user=user,
        account_name=f"ExecutionOrchestratorPortfolio-{unique}",
        account_type="simulated",
        initial_capital=100000.00,
        current_cash=100000.00,
        current_market_value=0.00,
        total_value=100000.00,
    )
    return strategy, portfolio


@pytest.mark.django_db
def test_idempotency_key_replay_submits_only_once():
    strategy, portfolio = _create_base_objects()
    repo = DjangoOrderIntentRepository()
    paper = DummyPaperAdapter()
    orchestrator = ExecutionOrchestrator(
        intent_repository=repo,
        paper_adapter=paper,
        broker_adapter=None,
        config=ExecutionConfig(mode=ExecutionMode.PAPER),
    )

    idem_key = f"idem-{uuid.uuid4()}"
    first = orchestrator.execute(
        strategy_id=strategy.id,
        portfolio_id=portfolio.id,
        symbol="000001.SH",
        side="buy",
        signal_strength=0.8,
        signal_confidence=0.9,
        current_price=100.0,
        account_equity=100000.0,
        current_position_value=0.0,
        daily_trade_count=0,
        daily_pnl_pct=0.0,
        regime="HG",
        regime_confidence=0.9,
        avg_volume=1000000,
        idempotency_key=idem_key,
    )
    second = orchestrator.execute(
        strategy_id=strategy.id,
        portfolio_id=portfolio.id,
        symbol="000001.SH",
        side="buy",
        signal_strength=0.8,
        signal_confidence=0.9,
        current_price=100.0,
        account_equity=100000.0,
        current_position_value=0.0,
        daily_trade_count=0,
        daily_pnl_pct=0.0,
        regime="HG",
        regime_confidence=0.9,
        avg_volume=1000000,
        idempotency_key=idem_key,
    )

    assert first.success is True
    assert second.success is True
    assert second.error_message == "idempotent_replay"
    assert paper.submit_count == 1
    assert OrderIntentModel.objects.filter(idempotency_key=idem_key).count() == 1


@pytest.mark.django_db
def test_watch_requires_confirmation_persists_pending_approval():
    strategy, portfolio = _create_base_objects()
    repo = DjangoOrderIntentRepository()
    paper = DummyPaperAdapter()
    orchestrator = ExecutionOrchestrator(
        intent_repository=repo,
        paper_adapter=paper,
        broker_adapter=None,
        config=ExecutionConfig(mode=ExecutionMode.PAPER, require_confirmation_for_watch=True),
    )

    result = orchestrator.execute(
        strategy_id=strategy.id,
        portfolio_id=portfolio.id,
        symbol="000001.SH",
        side="buy",
        signal_strength=0.8,
        signal_confidence=0.4,  # 触发 WATCH
        current_price=100.0,
        account_equity=100000.0,
        current_position_value=0.0,
        daily_trade_count=0,
        daily_pnl_pct=0.0,
        regime="HG",
        regime_confidence=0.9,
        avg_volume=1000000,
        idempotency_key=f"idem-watch-{uuid.uuid4()}",
    )

    persisted = OrderIntentModel.objects.get(intent_id=result.intent_id)

    assert result.success is True
    assert result.status == "pending_approval"
    assert persisted.status == OrderStatus.PENDING_APPROVAL.value
    assert paper.submit_count == 0
