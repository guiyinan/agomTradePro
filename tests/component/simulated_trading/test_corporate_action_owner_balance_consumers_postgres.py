"""Exercise ordinary-owner tax cash coverage through the real public consumers."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

import tests.component.simulated_trading.test_execution_settlement_uow as trade_fixtures
from apps.simulated_trading.application.corporate_action_tax_cash_coverage import (
    TaxCashCoverageSnapshot,
    TaxCashCoverageStatus,
)
from apps.simulated_trading.corporate_action_owner_event_composition import (
    prepare_owner_official_corporate_action,
)
from apps.simulated_trading.corporate_action_owner_tax_prepare_composition import (
    prepare_owner_corporate_action_tax_assessment,
)
from apps.simulated_trading.corporate_action_tax_cash_coverage_composition import (
    DjangoCorporateActionTaxCashCoverageReader,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import OrderReservationResult
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from core.exceptions import BusinessLogicError
from shared.config.secrets import get_secrets
from tests.component.simulated_trading.test_corporate_action_owner_workflow_http_postgres import (
    _API_ROOT,
    _WORKFLOW_URLCONF,
    _event_id,
    _headers,
    _issue_v3_cash_tax_consent,
    _prepare_and_confirm,
    _read,
    _refresh,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
)
from tests.support.ash07_owner_account_authority import (
    ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)


class _ActualClock:
    """Keep reservation clocks on Django's restored live server clock."""

    def now(self) -> datetime:
        """Return the actual current aware UTC clock."""
        return timezone.now().astimezone(UTC)


@pytest.fixture(autouse=True)
def _isolated_task_channels() -> Iterator[None]:
    """Use process-local cache and in-memory Celery channels for this journey."""
    get_secrets.cache_clear()
    try:
        with isolated_task_channels():
            yield
    finally:
        get_secrets.cache_clear()


def _read_tax_coverage(world: OwnerWorkflowNativeWorld) -> TaxCashCoverageSnapshot:
    """Read the actual account's coverage under its physical account transaction."""
    reader = DjangoCorporateActionTaxCashCoverageReader(
        runtime_environment=world.owner.environment,
        using="default",
    )
    with transaction.atomic(using="default"):
        account = (
            SimulatedAccountModel._base_manager.using("default")
            .select_for_update()
            .get(pk=world.account_id, user_id=world.owner.owner.pk, account_type="simulated")
        )
        result = reader.read_locked(
            physical_account_id=account.pk,
            owner_user_id=world.owner.owner.pk,
            using="default",
        )
    return result


def _current_sell_withholding(world: OwnerWorkflowNativeWorld, *, event_id: str) -> Decimal:
    """Calculate the exact synthetic estimate from the same current source/model path."""
    prepared = prepare_owner_official_corporate_action(
        account_id=world.account_id,
        owner_user_id=world.owner.owner.pk,
        asset_code=world.asset_code,
        event_id=event_id,
        action="tax_assess",
        settlement_date=world.settlement_date,
        as_of=timezone.now(),
        runtime_environment=world.owner.environment,
        using="default",
        canonical_account_id=world.canonical_account_id,
    )
    if prepared.tax_action is None:
        raise AssertionError("the current synthetic cash source did not produce tax facts")
    preview = prepare_owner_corporate_action_tax_assessment(
        action=prepared.tax_action,
        operation="tax_assess",
        canonical_account_id=world.canonical_account_id,
        settlement_date=world.settlement_date,
        environment=world.owner.environment,
    )
    amount = preview.assessment.calculation.withholding_amount
    if type(amount) is not Decimal or not amount.is_finite() or amount <= 0:
        raise AssertionError("the real current modeled SELL exposure has no positive tax")
    return amount


def _reserve_synthetic_buy_with_actual_tax_coverage(
    *,
    monkeypatch: pytest.MonkeyPatch,
    world: OwnerWorkflowNativeWorld,
    coverage_reader: DjangoCorporateActionTaxCashCoverageReader,
) -> OrderReservationResult:
    """Use the real reservation repository and actual account coverage reader."""
    as_of = timezone.now().astimezone(UTC)
    monkeypatch.setattr(trade_fixtures, "AS_OF", as_of)
    config = FeeConfigModel.objects.create(
        config_name=f"ash05-owner-balance-fees-{uuid4().hex}",
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
    trade_fixtures._seed_fee_policy(config)
    original_calendar = trade_fixtures._calendar

    def current_synthetic_calendar(
        *,
        as_of: datetime,
        open_dates: set[date],
        exchange: str = "SH",
        start: date = date(2026, 10, 16),
        end: date = date(2026, 10, 21),
    ):
        del open_dates, start, end
        local_today = as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()
        calendar_start = local_today - timedelta(days=7)
        calendar_end = local_today + timedelta(days=7)
        sessions = {
            calendar_start + timedelta(days=offset)
            for offset in range((calendar_end - calendar_start).days + 1)
            if (calendar_start + timedelta(days=offset)).weekday() < 5
        }
        # Explicit synthetic reservation session, including real-world weekends.
        sessions.add(local_today)
        return original_calendar(
            as_of=as_of,
            open_dates=sessions,
            exchange=exchange,
            start=calendar_start,
            end=calendar_end,
        )

    monkeypatch.setattr(trade_fixtures, "_calendar", current_synthetic_calendar)
    intent = trade_fixtures._intent(
        user_id=world.owner.owner.pk,
        account_id=world.account_id,
        key=f"ash05-unassessed-sell-buy-{uuid4().hex}",
        side=SimulatedTradeSide.BUY,
    )
    bundle = trade_fixtures._bundle(as_of=as_of)
    execution = DjangoSimulatedTradeExecutionRepository(using="default")
    plan = trade_fixtures._v2_plan(
        repository=execution,
        intent=intent,
        as_of=as_of,
        source_exchange="SH",
        bundle=bundle,
    )
    fees = plan.fee_policy_v2.calculate_for(
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        side=intent.side,
        amount=plan.amount,
        as_of=as_of,
    )
    reservations = DjangoSimulatedOrderReservationRepository(
        using="default",
        tax_cash_coverage_reader=coverage_reader,
    )
    return reservations.reserve_order(
        plan=plan,
        execution_bundle=bundle,
        fee_budget=fees.total_fee,
        clock=_ActualClock(),
    )


def test_unassessed_sell_is_reserved_or_blocks_buy_and_legacy_marks_stay_unqualified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Prove real tax coverage and owner cash projections across the cash workflow."""
    if connection.vendor != "postgresql":
        pytest.skip("ordinary owner balance consumers require the assigned migrated PostgreSQL DB")
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        base = _API_ROOT.format(account_id=world.account_id)

        refreshed = _refresh(world)
        consent = _issue_v3_cash_tax_consent(world)
        assert refreshed["outcome"] == "success"
        assert consent["grant_schema"].endswith(".v3")
        event_id = _event_id(world, payload=refreshed)
        assert world.capture.listing_reads >= 1 and world.capture.pdf_reads >= 1

        before_cash = SimulatedAccountModel.objects.values_list("current_cash", flat=True).get(
            pk=world.account_id
        )
        _prepare_and_confirm(
            world,
            event_id=event_id,
            action="cash_entitlement",
            exact_retry=False,
        )
        _refresh(world)
        _issue_v3_cash_tax_consent(world)
        _prepare_and_confirm(
            world,
            event_id=event_id,
            action="cash_payment",
            exact_retry=False,
        )
        after_payment = SimulatedAccountModel.objects.values_list("current_cash", flat=True).get(
            pk=world.account_id
        )
        assert after_payment == before_cash + Decimal("20.00")
        _refresh(world)
        assert (
            SimulatedTradeModel.objects.filter(
                account_id=world.account_id,
                asset_code=world.asset_code,
                action="sell",
                status="executed",
            ).count()
            == 1
        )
        assert not CorporateActionTaxAssessmentHeaderModel.objects.filter(
            account_id=world.account_id
        ).exists()
        assert not CorporateActionTaxLiabilityOperationModel.objects.filter(
            account_id=world.account_id
        ).exists()

        # Calculate the exact modeled amount with the same retained source and
        # policy path used by the real assessment. No test-side tax DTO is made.
        modeled_withholding = _current_sell_withholding(world, event_id=event_id)
        # A real V4 SELL exists while its tax assessment and liability operations
        # are absent. It may only be covered by an exact reserve or UNKNOWN; an
        # empty accepted ledger with a zero reserve is not complete coverage.
        current_coverage = _read_tax_coverage(world)
        if current_coverage.coverage_status is TaxCashCoverageStatus.UNKNOWN:
            assert current_coverage.tax_cash_unavailable is None
        else:
            assert current_coverage.coverage_status is TaxCashCoverageStatus.COMPLETE
            assert current_coverage.accepted_unpaid_tax == Decimal("0")
            assert current_coverage.modeled_unapplied_tax_reserve == modeled_withholding
            assert current_coverage.tax_cash_unavailable == modeled_withholding
        reservations_before = SimulatedOrderReservationModel.objects.filter(
            account_id=world.account_id
        ).count()
        cash_before_failed_reservation = SimulatedAccountModel.objects.values_list(
            "current_cash", flat=True
        ).get(pk=world.account_id)
        reservation_reader = DjangoCorporateActionTaxCashCoverageReader(
            runtime_environment=world.owner.environment,
            using="default",
        )
        if current_coverage.coverage_status is TaxCashCoverageStatus.UNKNOWN:
            with pytest.raises(BusinessLogicError) as blocked:
                _reserve_synthetic_buy_with_actual_tax_coverage(
                    monkeypatch=monkeypatch,
                    world=world,
                    coverage_reader=reservation_reader,
                )
            assert blocked.value.code == "ORDER_TAX_CASH_COVERAGE_UNAVAILABLE"
        else:
            reserved = _reserve_synthetic_buy_with_actual_tax_coverage(
                monkeypatch=monkeypatch,
                world=world,
                coverage_reader=reservation_reader,
            )
            assert reserved.book.tax_cash_unavailable == modeled_withholding
            assert reserved.book.book_cash is not None
            assert reserved.book.order_cash_reserved is not None
            assert reserved.book.available_cash == (
                reserved.book.book_cash - reserved.book.order_cash_reserved - modeled_withholding
            )
            reservation_reader_cancel = DjangoSimulatedOrderReservationRepository(
                using="default",
                tax_cash_coverage_reader=reservation_reader,
            )
            reservation_reader_cancel.cancel_order(
                account_id=world.account_id,
                user_id=world.owner.owner.pk,
                idempotency_key=reserved.reservation.identity.idempotency_key,
                clock=_ActualClock(),
            )
        assert SimulatedOrderReservationModel.objects.filter(
            account_id=world.account_id
        ).count() == reservations_before + (
            1 if current_coverage.coverage_status is TaxCashCoverageStatus.COMPLETE else 0
        )
        assert (
            SimulatedAccountModel.objects.values_list("current_cash", flat=True).get(
                pk=world.account_id
            )
            == cash_before_failed_reservation
        )

        _issue_v3_cash_tax_consent(world)
        assessment = _prepare_and_confirm(
            world,
            event_id=event_id,
            action="tax_assess",
            settlement_date=world.settlement_date,
            exact_retry=False,
        )
        assert assessment["outcome"] == "success"
        _refresh(world)
        assessment_header = CorporateActionTaxAssessmentHeaderModel.objects.get(
            account_id=world.account_id,
            source_event_id=event_id,
            settlement_date=world.settlement_date,
        )
        withholding = Decimal(assessment_header.withholding_amount_text)
        assert withholding > 0

        # An assessment without an applied operation is still unknown or must
        # retain that exact estimate as unavailable cash. Recognition appends
        # the accepted unpaid liability without a cash debit; collection then
        # debits exactly that original amount.
        unapplied_coverage = _read_tax_coverage(world)
        if unapplied_coverage.coverage_status is TaxCashCoverageStatus.UNKNOWN:
            assert unapplied_coverage.tax_cash_unavailable is None
        else:
            assert unapplied_coverage.coverage_status is TaxCashCoverageStatus.COMPLETE
            assert unapplied_coverage.accepted_unpaid_tax == Decimal("0")
            assert unapplied_coverage.modeled_unapplied_tax_reserve == withholding
            assert unapplied_coverage.tax_cash_unavailable == withholding
        _issue_v3_cash_tax_consent(world)
        recognition = _prepare_and_confirm(
            world,
            event_id=event_id,
            action="tax_recognize",
            settlement_date=world.settlement_date,
            exact_retry=False,
        )
        assert recognition["outcome"] == "success"
        _refresh(world)
        recognized_coverage = _read_tax_coverage(world)
        assert recognized_coverage.coverage_status is TaxCashCoverageStatus.COMPLETE
        assert recognized_coverage.accepted_unpaid_tax == withholding
        assert recognized_coverage.modeled_unapplied_tax_reserve == Decimal("0")
        recognized_account = SimulatedAccountModel.objects.get(pk=world.account_id)
        assert recognized_account.current_cash == after_payment
        before_collection_cash = recognized_account.current_cash
        recognized_payload = _read(world.owner.client, base, _headers(world))
        assert Decimal(str(recognized_payload["tax_payable"])) == withholding
        assert Decimal(str(recognized_payload["spendable_cash"])) == (
            before_collection_cash - withholding
        )

        _issue_v3_cash_tax_consent(world)
        collection = _prepare_and_confirm(
            world,
            event_id=event_id,
            action="tax_collect",
            settlement_date=world.settlement_date,
            exact_retry=False,
        )
        assert collection["outcome"] == "success"
        _refresh(world)
        assert (
            CorporateActionTaxLiabilityOperationModel.objects.filter(
                account_id=world.account_id
            ).count()
            == 2
        )
        final_coverage = _read_tax_coverage(world)
        assert final_coverage.coverage_status is TaxCashCoverageStatus.COMPLETE
        assert final_coverage.accepted_unpaid_tax == Decimal("0")
        assert final_coverage.modeled_unapplied_tax_reserve == Decimal("0")
        final_account = SimulatedAccountModel.objects.get(pk=world.account_id)
        assert final_account.current_cash == before_collection_cash - withholding
        final_payload = _read(world.owner.client, base, _headers(world))
        assert Decimal(str(final_payload["book_cash"])) == final_account.current_cash
        assert Decimal(str(final_payload["tax_payable"])) == Decimal("0")
        assert Decimal(str(final_payload["spendable_cash"])) == final_account.current_cash

        position = PositionModel.objects.get(
            account_id=world.account_id, asset_code=world.asset_code
        )
        assert position.quantity > 0
        assert position.current_price is not None and position.current_price > 0
        assert position.market_value is not None and position.market_value > 0
        # No independent NAV raw-mark policy or daily price publication is
        # configured by this workflow world. The legacy fields above cannot
        # fill that evidence gap for a nonempty position.
        assert final_payload["net_asset_value"] is None
