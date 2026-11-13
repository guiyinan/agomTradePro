"""Actual SQLite ledger checks for conservative spent-share correction fencing."""

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils import timezone

from apps.simulated_trading.application.corporate_action_posting import (
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_corporate_action_posting_repository import (
    _repository,
    _request,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)


@pytest.fixture
def action_ledger(db: None) -> tuple[AbstractBaseUser, SimulatedAccountModel]:
    """Use rollback-isolated SQLite rows; native serialization has a separate suite."""
    del db
    user = get_user_model().objects.create_user(username="share-guard-owner", password="unused")
    account = SimulatedAccountModel.objects.create(
        user=user,
        account_name="share-guard",
        account_type="simulated",
        initial_capital=Decimal("10000.00"),
        current_cash=Decimal("10000.00"),
        current_market_value=Decimal("0.00"),
        total_value=Decimal("10000.00"),
        is_active=True,
    )
    return user, account


def _delivered(
    account: SimulatedAccountModel,
) -> tuple[tuple[CorporateActionStageRequest, ...], tuple[CorporateActionPostingReceipt, ...]]:
    """Retain a complete synthetic 40-share entitlement, delivery and release."""
    PositionModel.objects.create(
        account=account,
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        asset_type="equity",
        quantity=Decimal("50.000000"),
        available_quantity=Decimal("50.000000"),
        available_quantity_known=True,
        avg_cost=Decimal("10.0000"),
        total_cost=Decimal("500.00"),
        cost_basis_known=True,
        current_price=Decimal("12.0000"),
        market_value=Decimal("600.00"),
        valuation_known=True,
        first_buy_date=date(2026, 8, 1),
    )
    entitlement = _request(
        account,
        action_kind=CorporateActionKind.SHARE_DISTRIBUTION,
        stage=CorporateActionStage.SHARE_ENTITLEMENT,
        cash_amount=None,
        share_amount=Decimal("40.000000"),
        tax_treatment="not_applicable",
        odd_lot_policy="whole_shares",
    )
    delivery = replace(
        entitlement,
        stage=CorporateActionStage.SHARE_DELIVERY,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
        sellable_date=entitlement.effective_date,
    )
    release = replace(delivery, stage=CorporateActionStage.SHARE_SELLABLE_RELEASE)
    requests = (entitlement, delivery, release)
    use_case = PostCorporateActionStageUseCase(_repository())
    receipts = tuple(use_case.execute((request,))[0] for request in requests)
    return requests, receipts


def _correction(
    requests: tuple[CorporateActionStageRequest, ...],
    receipts: tuple[CorporateActionPostingReceipt, ...],
) -> tuple[CorporateActionStageRequest, ...]:
    """Unwind all original stages and replace them with an explicit 30-share grant."""
    successors = tuple(
        replace(
            request,
            source_record_id="SZSE:synthetic-share-correction",
            source_revision_id="sha256:source-v2",
            supersedes_revision_id=request.source_revision_id,
            entry_kind=CorporateActionEntryKind.SUCCESSOR,
            share_amount=Decimal("30.000000"),
        )
        for request in requests
    )
    reversals = tuple(
        replace(
            successor,
            entry_kind=CorporateActionEntryKind.REVERSAL,
            reversal_of_entry_id=receipt.entry_id,
            share_amount=None,
            tax_treatment=None,
            ownership_snapshot_id=None,
            ownership_snapshot_sha256=None,
            ownership_snapshot_as_of_date=None,
            ownership_snapshot_observed_at=None,
            eligible_quantity=None,
            entitlement_calculation_sha256=None,
            odd_lot_policy=None,
        )
        for successor, receipt in zip(successors, receipts, strict=True)
    )
    return tuple(reversed(reversals)) + successors


def _trade(
    account: SimulatedAccountModel, *, action: str = "sell", status: str = "executed"
) -> SimulatedTradeModel:
    """Record a synthetic executed trade without pretending its ledger is a live feed."""
    today = timezone.localdate()
    return SimulatedTradeModel.objects.create(
        account=account,
        asset_code="002727.SZ",
        asset_name="Synthetic security",
        asset_type="equity",
        action=action,
        status=status,
        quantity=Decimal("1.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("10.00"),
        total_cost=Decimal("10.00"),
        order_date=today,
        execution_date=today,
    )


@pytest.mark.parametrize("clock_case", ["both_after", "created_after", "executed_after", "equal"])
def test_share_correction_blocks_any_later_executed_sale_before_writes(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel], clock_case: str
) -> None:
    """Positive remaining shares cannot prove that delivered shares were never sold."""
    _, account = action_ledger
    requests, receipts = _delivered(account)
    delivery = CorporateActionPostingModel.objects.get(pk=receipts[1].entry_id)
    trade = _trade(account)
    before = delivery.created_at - timedelta(seconds=1)
    after = delivery.created_at + timedelta(seconds=1)
    created = before if clock_case == "executed_after" else after
    executed = before if clock_case == "created_after" else after
    if clock_case == "equal":
        created = executed = delivery.created_at
    SimulatedTradeModel.objects.filter(pk=trade.pk).update(
        created_at=created, execution_time=executed, execution_date=requests[0].record_date
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        PostCorporateActionStageUseCase(_repository()).execute(_correction(requests, receipts))
    assert blocked.value.code == "CORPORATE_ACTION_DELIVERED_SHARES_SPENT"
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 3
    position = PositionModel.objects.get(account=account)
    assert position.quantity == position.available_quantity == Decimal("90.000000")
    assert position.total_cost == Decimal("500.00")


@pytest.mark.parametrize(
    "unrelated", ["buy", "cancelled", "failed", "pending", "other_asset", "earlier"]
)
def test_share_correction_allows_unrelated_trades_and_preserves_exact_replay(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel], unrelated: str
) -> None:
    """The fence uses exact account/security/executed-sale scope and keeps replay read-only."""
    _, account = action_ledger
    requests, receipts = _delivered(account)
    delivery = CorporateActionPostingModel.objects.get(pk=receipts[1].entry_id)
    trade = _trade(
        account,
        action="buy" if unrelated == "buy" else "sell",
        status=unrelated if unrelated in {"cancelled", "failed", "pending"} else "executed",
    )
    if unrelated == "other_asset":
        SimulatedTradeModel.objects.filter(pk=trade.pk).update(asset_code="000426.SZ")
    if unrelated == "earlier":
        before = delivery.created_at - timedelta(seconds=1)
        SimulatedTradeModel.objects.filter(pk=trade.pk).update(
            created_at=before, execution_time=before
        )
    correction = _correction(requests, receipts)
    use_case = PostCorporateActionStageUseCase(_repository())
    corrected = use_case.execute(correction)
    assert all(not receipt.replayed for receipt in corrected)
    _trade(account)
    replay = use_case.execute(correction)
    assert all(receipt.replayed for receipt in replay)
    assert [receipt.entry_id for receipt in replay] == [receipt.entry_id for receipt in corrected]
    assert CorporateActionPostingModel.objects.filter(account=account).count() == 9
    position = PositionModel.objects.get(account=account)
    assert position.quantity == position.available_quantity == Decimal("80.000000")


@pytest.mark.parametrize(
    "stage", [CorporateActionStage.SHARE_DELIVERY, CorporateActionStage.SHARE_SELLABLE_RELEASE]
)
def test_share_stage_must_settle_the_full_event_quantity(
    action_ledger: tuple[AbstractBaseUser, SimulatedAccountModel], stage: CorporateActionStage
) -> None:
    """A unique delivery or release cannot strand part of its event's exact entitlement."""
    _, account = action_ledger
    requests, _ = _delivered(account)
    event_id = "SZSE:002727:synthetic-full-share-settlement"
    entitlement, delivery, release = tuple(
        replace(request, source_event_id=event_id) for request in requests
    )
    use_case = PostCorporateActionStageUseCase(_repository())
    use_case.execute((entitlement,))
    if stage is CorporateActionStage.SHARE_SELLABLE_RELEASE:
        use_case.execute((delivery,))
    position = PositionModel.objects.get(account=account)
    before = (position.quantity, position.available_quantity, position.total_cost)
    retained = CorporateActionPostingModel.objects.count()
    partial = replace(
        delivery if stage is CorporateActionStage.SHARE_DELIVERY else release,
        share_amount=Decimal("30.000000"),
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute((partial,))
    assert blocked.value.code == (
        "CORPORATE_ACTION_SHARE_RECEIVABLE_NOT_FULLY_SETTLED"
        if stage is CorporateActionStage.SHARE_DELIVERY
        else "CORPORATE_ACTION_SELLABLE_NOT_FULLY_RELEASED"
    )
    assert CorporateActionPostingModel.objects.count() == retained
    position.refresh_from_db()
    assert (position.quantity, position.available_quantity, position.total_cost) == before
