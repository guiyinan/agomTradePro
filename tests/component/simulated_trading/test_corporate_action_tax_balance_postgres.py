"""Actual retained tax readback; price marks here are explicitly controlled inputs."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

import tests.component.simulated_trading.test_execution_settlement_uow as trade_fixtures
from apps.audit.corporate_action_tax_assessment_composition import (
    build_tax_assessment_audit_coordinator,
)
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.corporate_action_tax_balance import CorporateActionTaxBalance
from apps.simulated_trading.infrastructure.corporate_action_tax_balance_repository import (
    read_locked_corporate_action_tax_payable,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError
from tests.component.simulated_trading.test_corporate_action_tax_assessment_postgres import (
    _run as _assess,
)
from tests.component.simulated_trading.test_corporate_action_tax_liability_postgres import (
    _financial_counts,
    _fixture,
    _run,
)
from tests.component.simulated_trading.test_corporate_action_tax_liability_postgres import (
    require_real_financial_schema as require_real_financial_schema,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = [
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="Actual migrated tax balance readback"
    ),
    pytest.mark.django_db(
        transaction=True,
        available_apps=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "apps.account",
            "apps.simulated_trading",
            "apps.audit",
        ],
    ),
]


def _debt(account: SimulatedAccountModel) -> Decimal:
    with transaction.atomic():
        locked = SimulatedAccountModel.objects.select_for_update().get(pk=account.pk)
        return read_locked_corporate_action_tax_payable(account=locked, using="default")


def test_native_readonly_debt_and_partial_collection_preserve_controlled_net_assets():
    account, assessment = _fixture(cash=Decimal("0.50"))
    recognized = _run(assessment, action=None)
    before_counts = _financial_counts()
    with CaptureQueriesContext(connection) as queries:
        debt = _debt(account)
    assert debt == assessment.calculation.withholding_amount
    assert not any(
        query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "SAVEPOINT"))
        for query in queries.captured_queries
    )
    before = CorporateActionTaxBalance(
        currency=recognized.currency,
        currency_quantum=assessment.policy.currency_quantum,
        book_cash=Decimal("0.50"),
        marked_assets=Decimal("900"),
        dividend_receivable=Decimal("0"),
        tax_payable=debt,
        order_cash_reserved=Decimal("0"),
        source_complete=True,
        declared_blockers=(),
    )
    _run(assessment, operation="collect-after-recognition")
    account.refresh_from_db()
    remaining = _debt(account)
    assert remaining == debt - Decimal("0.50")
    after = replace(before, book_cash=account.current_cash, tax_payable=remaining)
    assert after.net_asset_value == before.net_asset_value
    assert after.spendable_cash == before.spendable_cash == Decimal("0")
    assert before_counts == (1, 1, 1) and _financial_counts() == (2, 2, 2)


def test_native_new_unapplied_assessment_blocks_order_cash_without_any_repair():
    account, assessment = _fixture()
    with pytest.raises(BusinessLogicError) as error:
        _debt(account)
    assert error.value.code == "TAX_ASSESSMENT_NOT_APPLIED"
    with transaction.atomic():
        book = DjangoSimulatedOrderReservationRepository(using="default")._current_book(
            account=account,
            position=None,
            active_rows=[],
            target=None,
            security_id=assessment.security_id,
            asset_code=assessment.asset_code,
        )
    assert book.tax_cash_unavailable is None and book.available_cash is None
    account.refresh_from_db()
    assert account.current_cash == Decimal("100") and _financial_counts() == (0, 0, 0)


def test_native_independent_dispositions_sum_and_cash_book_preserves_gross_cash():
    """Accepted debt does not qualify missing current exposure or spendable cash."""
    account, first = _fixture()
    _run(first, action=None)
    last = first.history.settlement_days[-1]
    day = replace(
        last,
        settlement_date=date(2025, 3, 4),
        opening_eod_quantity=Decimal("60"),
        gross_purchase_quantity=Decimal("0"),
        gross_sale_quantity=Decimal("5"),
        closing_eod_quantity=Decimal("55"),
        evidence_id="synthetic-balance-next-sale",
        evidence_sha256="f" * 64,
    )
    second = replace(
        first,
        history=replace(
            first.history,
            complete_through=day.settlement_date,
            covered_session_dates=first.history.covered_session_dates + (day.settlement_date,),
            settlement_days=first.history.settlement_days + (day,),
        ),
        target_settlement_date=day.settlement_date,
    )
    _assess(second)
    _run(second, operation="second-sale-recognition", action=None)
    debt = first.calculation.withholding_amount + second.calculation.withholding_amount
    assert _debt(account) == debt
    account.refresh_from_db()
    with transaction.atomic():
        book = DjangoSimulatedOrderReservationRepository(using="default")._current_book(
            account=account,
            position=None,
            active_rows=[],
            target=None,
            security_id=first.security_id,
            asset_code=first.asset_code,
        )
    assert book.book_cash == Decimal("100")
    assert book.tax_cash_unavailable is None and book.available_cash is None
    assert _debt(account) == debt


def test_native_missing_original_tax_outbox_blocks_read_without_repair():
    account, assessment = _fixture()
    _run(assessment, action=None)
    audit = build_tax_assessment_audit_coordinator(using="default")
    original = type(audit).get_exact_outbox_winner_targeted

    def hide(self, event):
        return (
            None
            if event.event_type == "simulated.corporate_action.tax_liability_applied"
            else original(self, event)
        )

    with patch.object(type(audit), "get_exact_outbox_winner_targeted", hide):
        with pytest.raises(BusinessLogicError, match="repair is forbidden"):
            _debt(account)
    assert _financial_counts() == (1, 1, 1)
    account.refresh_from_db()
    assert account.current_cash == Decimal("100")


@pytest.mark.parametrize("route", ["reservation", "legacy"])
def test_native_new_cash_debits_cannot_spend_verified_tax(route):
    """Actual storage paths preserve debt across securities; market/fee ports are controlled."""
    account, assessment = _fixture()
    _run(assessment, action=None)
    trade_fixtures._seed_fee_policy(
        FeeConfigModel.objects.create(
            config_name="tax-balance-legacy-fees",
            asset_type="equity",
            commission_rate_buy=0.0003,
            commission_rate_sell=0.0003,
            min_commission=1.0,
            stamp_duty_rate=0.001,
            transfer_fee_rate=0.00002,
            min_transfer_fee=0.0,
            slippage_rate=0.001,
            is_default=False,
            is_active=False,
        )
    )
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    intent = trade_fixtures._intent(
        user_id=account.user_id, account_id=account.pk, key="tax-protected-buy"
    )
    bundle = trade_fixtures._bundle(as_of=trade_fixtures.AS_OF)
    plan = trade_fixtures._v2_plan(
        repository=repository,
        intent=intent,
        as_of=trade_fixtures.AS_OF,
        source_exchange="SH",
        bundle=bundle,
    )
    fees = plan.fee_policy_v2.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=plan.amount,
        as_of=trade_fixtures.AS_OF,
    )
    required = plan.amount + fees.total_fee
    SimulatedAccountModel.objects.filter(pk=account.pk).update(
        current_cash=required, updated_at=timezone.now()
    )
    account.refresh_from_db()
    before = (
        SimulatedTradeModel.objects.filter(account_id=account.pk).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account.pk).count(),
        _financial_counts(),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        if route == "reservation":
            DjangoSimulatedOrderReservationRepository(using="default").reserve_order(
                plan=plan,
                execution_bundle=bundle,
                fee_budget=fees.total_fee,
                clock=trade_fixtures._Clock(trade_fixtures.AS_OF),
            )
        else:
            repository.execute_trade(
                plan=plan,
                execution_bundle=bundle,
                clock=trade_fixtures._Clock(trade_fixtures.AS_OF),
            )
    if route == "reservation":
        assert error.value.code == "ORDER_TAX_CASH_COVERAGE_UNAVAILABLE"
    else:
        assert "尚未完整核对" in str(error.value)
    account.refresh_from_db()
    assert account.current_cash == required
    assert _debt(account) == assessment.calculation.withholding_amount
    assert before == (
        SimulatedTradeModel.objects.filter(account_id=account.pk).count(),
        SimulatedOrderReservationModel.objects.filter(account_id=account.pk).count(),
        _financial_counts(),
    )
