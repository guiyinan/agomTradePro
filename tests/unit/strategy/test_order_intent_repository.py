import uuid

import pytest
from django.contrib.auth.models import User

from apps.account.infrastructure.models import AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel
from apps.strategy.domain.entities import (
    DecisionAction,
    DecisionResult,
    OrderIntent,
    OrderSide,
    OrderStatus,
    RiskSnapshot,
    SizingResult,
)
from apps.strategy.infrastructure.models import OrderIntentModel, StrategyModel
from apps.strategy.infrastructure.repositories import DjangoOrderIntentRepository


def _create_base_objects():
    unique = str(uuid.uuid4())[:8]
    user = User.objects.create_user(
        username=f"test_order_intent_repo_{unique}",
        email=f"test_order_intent_repo_{unique}@example.com",
        password="testpass123",
    )
    profile = AccountProfileModel.objects.get(user=user)
    strategy = StrategyModel.objects.create(
        name=f"OrderIntentRepoStrategy-{unique}",
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
        account_name=f"OrderIntentRepoPortfolio-{unique}",
        account_type="simulated",
        initial_capital=100000.00,
        current_cash=100000.00,
        current_market_value=0.00,
        total_value=100000.00,
    )
    return strategy, portfolio


def _build_intent(strategy_id: int, portfolio_id: int, *, key: str, status: OrderStatus = OrderStatus.DRAFT):
    return OrderIntent(
        intent_id=str(uuid.uuid4()),
        strategy_id=strategy_id,
        portfolio_id=portfolio_id,
        symbol="000001.SH",
        side=OrderSide.BUY,
        qty=100,
        decision=DecisionResult(
            action=DecisionAction.ALLOW,
            reason_codes=["SIGNAL_STRONG"],
            reason_text="ok",
            confidence=0.9,
        ),
        sizing=SizingResult(
            target_notional=10000.0,
            qty=100,
            expected_risk_pct=1.0,
            sizing_method="fixed_fraction",
            sizing_explain="test",
        ),
        risk_snapshot=RiskSnapshot(
            total_equity=100000.0,
            cash_balance=90000.0,
            total_position_value=10000.0,
            daily_pnl_pct=0.0,
            max_single_position_pct=10.0,
            top3_position_pct=10.0,
            current_regime="HG",
            regime_confidence=0.8,
            volatility_index=1.0,
            max_position_limit_pct=20.0,
            daily_loss_limit_pct=5.0,
            daily_trade_limit=10,
        ),
        limit_price=100.0,
        reason="unit-test",
        idempotency_key=key,
        status=status,
    )


@pytest.mark.django_db
def test_save_and_get_by_idempotency_key():
    strategy, portfolio = _create_base_objects()
    repo = DjangoOrderIntentRepository()
    key = f"key-{uuid.uuid4()}"
    intent = _build_intent(strategy.id, portfolio.id, key=key)

    saved = repo.save(intent)
    fetched = repo.get_by_idempotency_key(key)

    assert saved.intent_id == intent.intent_id
    assert fetched is not None
    assert fetched.intent_id == intent.intent_id
    assert fetched.status == OrderStatus.DRAFT
    assert fetched.idempotency_key == key


@pytest.mark.django_db
def test_update_status_and_get_by_id():
    strategy, portfolio = _create_base_objects()
    repo = DjangoOrderIntentRepository()
    key = f"key-{uuid.uuid4()}"
    intent = _build_intent(strategy.id, portfolio.id, key=key)
    repo.save(intent)

    updated = repo.update_status(intent.intent_id, OrderStatus.SENT)
    fetched = repo.get_by_id(intent.intent_id)

    assert updated is True
    assert fetched is not None
    assert fetched.status == OrderStatus.SENT


@pytest.mark.django_db
def test_get_pending_intents_filters_by_portfolio_and_status():
    strategy, portfolio = _create_base_objects()
    repo = DjangoOrderIntentRepository()

    draft = _build_intent(strategy.id, portfolio.id, key=f"k-{uuid.uuid4()}", status=OrderStatus.DRAFT)
    pending = _build_intent(
        strategy.id, portfolio.id, key=f"k-{uuid.uuid4()}", status=OrderStatus.PENDING_APPROVAL
    )
    approved = _build_intent(strategy.id, portfolio.id, key=f"k-{uuid.uuid4()}", status=OrderStatus.APPROVED)
    sent = _build_intent(strategy.id, portfolio.id, key=f"k-{uuid.uuid4()}", status=OrderStatus.SENT)

    repo.save(draft)
    repo.save(pending)
    repo.save(approved)
    repo.save(sent)

    other_strategy, other_portfolio = _create_base_objects()
    other = _build_intent(
        other_strategy.id, other_portfolio.id, key=f"k-{uuid.uuid4()}", status=OrderStatus.DRAFT
    )
    repo.save(other)

    pending_list = repo.get_pending_intents(portfolio.id)
    pending_ids = {item.intent_id for item in pending_list}

    assert draft.intent_id in pending_ids
    assert pending.intent_id in pending_ids
    assert approved.intent_id in pending_ids
    assert sent.intent_id not in pending_ids
    assert other.intent_id not in pending_ids


@pytest.mark.django_db
def test_save_same_intent_id_updates_instead_of_duplicate():
    strategy, portfolio = _create_base_objects()
    repo = DjangoOrderIntentRepository()
    key = f"key-{uuid.uuid4()}"
    intent = _build_intent(strategy.id, portfolio.id, key=key, status=OrderStatus.DRAFT)
    repo.save(intent)

    intent.status = OrderStatus.APPROVED
    intent.qty = 120
    repo.save(intent)

    assert OrderIntentModel.objects.filter(intent_id=intent.intent_id).count() == 1
    fetched = repo.get_by_id(intent.intent_id)
    assert fetched is not None
    assert fetched.status == OrderStatus.APPROVED
    assert fetched.qty == 120
