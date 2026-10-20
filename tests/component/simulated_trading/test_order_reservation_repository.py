"""Database component tests for durable simulated-order reservations."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.risk_center.domain.execution_settlement_v3 import ExecutionSettlementBundleV3
from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    ExecutionFeeScheduleUnavailable,
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.fee_policy_v2 import FeePolicyVersionCommand
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
    ReserveSimulatedOrderUseCase,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionCalendarEvidence,
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationRequest,
    OrderReservationStatus,
)
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.fee_policy_v2_repository import (
    DjangoFeePolicyV2Repository,
)
from apps.simulated_trading.infrastructure.models import (
    FeeConfigModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    current_order_reservation_book,
    decode_order_reservation,
    fee_policy_from_snapshot,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _bundle,
    _calendar,
    _CalendarReader,
    _Clock,
    _execute_use_case,
    _IdentityReader,
    _intent,
    _RuleReader,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@dataclass(frozen=True)
class _Harness:
    account: SimulatedAccountModel
    user_id: int
    repository: DjangoSimulatedOrderReservationRepository
    preparer: ExecuteSettlementBoundSimulatedTradeUseCase
    reserve: ReserveSimulatedOrderUseCase
    rule_reader: _RuleReader


class _SecurityScopedRuleReader:
    """Read the complete source fixture for a test-specific canonical security."""

    def __init__(self, bundle: ExecutionSettlementBundleV3) -> None:
        self.bundle = bundle

    def execute(self, *, security_id: str, as_of: datetime) -> ExecutionSettlementBundleV3:
        expected_security_id = self.bundle.execution_submission_v2.execution_rule_v1.security_id
        assert security_id == expected_security_id
        assert self.bundle.source_available_at <= as_of < self.bundle.valid_until
        return self.bundle


@pytest.fixture
def reservation_harness(
    ledger: tuple[object, SimulatedAccountModel],
) -> Iterator[_Harness]:
    """Add only the reservation table to the established real ledger fixture."""

    _, account = ledger
    assert type(account.pk) is int
    assert type(account.user_id) is int
    with isolated_schema((SimulatedOrderReservationModel,)):
        evidence = _calendar(
            as_of=AS_OF,
            open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
        )
        preparer, rule_reader, _ = _execute_use_case(
            account_id=account.pk,
            user_id=account.user_id,
            as_of=AS_OF,
            evidence=evidence,
        )
        repository = DjangoSimulatedOrderReservationRepository(using="default")
        yield _Harness(
            account=account,
            user_id=account.user_id,
            repository=repository,
            preparer=preparer,
            reserve=ReserveSimulatedOrderUseCase(
                preparer=preparer,
                repository=repository,
                clock=_Clock(AS_OF),
            ),
            rule_reader=rule_reader,
        )


def _intent_for(
    harness: _Harness,
    *,
    side: SimulatedTradeSide = SimulatedTradeSide.BUY,
    key: str = "reservation-001",
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("10.00"),
    security_id: str = "SH.UOW.SECURITY",
    asset_code: str = "600000.SH",
) -> SimulatedTradeIntent:
    """Build the established fully populated intent with optional identity changes."""

    assert type(harness.account.pk) is int
    intent = _intent(
        user_id=harness.user_id,
        account_id=harness.account.pk,
        side=side,
        key=key,
        quantity=quantity,
        price=price,
    )
    return replace(intent, security_id=security_id, asset_code=asset_code)


def _create_position(
    account: SimulatedAccountModel,
    *,
    asset_code: str = "600000.SH",
    quantity: Decimal = Decimal("100"),
    available_quantity: Decimal = Decimal("100"),
    available_quantity_known: bool = True,
) -> PositionModel:
    """Create a real ledger position with an explicit T+1 sellable amount."""

    return PositionModel.objects.create(
        account=account,
        asset_code=asset_code,
        asset_name="Test security",
        asset_type="equity",
        quantity=quantity,
        available_quantity=available_quantity,
        available_quantity_known=available_quantity_known,
        avg_cost=Decimal("9.0000"),
        total_cost=Decimal("900.00"),
        current_price=Decimal("10.0000"),
        market_value=Decimal("1000.00"),
        first_buy_date=date(2025, 1, 2),
    )


def _bundle_for_security(security_id: str) -> ExecutionSettlementBundleV3:
    """Retain complete source-backed fixture evidence while rebinding its security."""

    source = _bundle(as_of=AS_OF)
    source_rule = replace(
        source.execution_submission_v2.execution_rule_v1,
        security_id=security_id,
        content_hash="",
    )
    submission = replace(
        source.execution_submission_v2,
        execution_rule_v1=source_rule,
        content_hash="",
    )
    settlement_policy = replace(
        source.settlement_policy_v1,
        security_id=security_id,
        bound_execution_rule_v2_hash=submission.content_hash,
        content_hash="",
    )
    return replace(
        source,
        execution_submission_v2=submission,
        settlement_policy_v1=settlement_policy,
        content_hash="",
    )


def _use_case_for_bundle(
    *,
    account_id: int,
    user_id: int,
    evidence: ExecutionCalendarEvidence,
    bundle: ExecutionSettlementBundleV3,
) -> ExecuteSettlementBoundSimulatedTradeUseCase:
    """Compose ordinary execution around a complete bundle for one test identity."""

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    return ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=_SecurityScopedRuleReader(bundle),
        identity_reader=_IdentityReader(),
        calendar_reader=_CalendarReader(evidence),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(AS_OF),
    )


def test_buy_reservation_persists_exact_fee_budget_without_creating_a_trade(
    reservation_harness: _Harness,
) -> None:
    """A BUY hold includes the caller's full fee budget and leaves the trade ledger alone."""

    intent = _intent_for(reservation_harness)
    result = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )

    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert row.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert row.notional == Decimal("1000.00")
    assert row.fee_budget == Decimal("5.00")
    assert row.cash_reserved == Decimal("1005.00")
    assert row.shares_reserved == Decimal("0.000000")
    assert row.fee_estimate <= row.fee_budget
    assert row.plan_snapshot_hash
    assert result.reservation.cash_reserved == row.cash_reserved
    assert result.book.available_cash == Decimal("98995.00")
    assert SimulatedTradeModel.objects.count() == 0
    reservation_harness.account.refresh_from_db()
    assert reservation_harness.account.current_cash == Decimal("100000.00")


def test_buy_fee_budget_below_fee_source_estimate_fails_without_a_row(
    reservation_harness: _Harness,
) -> None:
    """A budget smaller than the sealed FeeV2 estimate cannot create a hold."""

    intent = _intent_for(reservation_harness)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.reserve.execute(
            intent,
            fee_budget=Decimal("0.00"),
            as_of=AS_OF,
        )

    assert blocked.value.code == "BUY_FEE_BUDGET_INSUFFICIENT"
    assert SimulatedOrderReservationModel.objects.count() == 0
    assert SimulatedTradeModel.objects.count() == 0


def test_sell_with_fee_covered_by_proceeds_needs_no_cash_even_at_low_decimal_precision(
    reservation_harness: _Harness,
) -> None:
    """SELL proceeds can cover fees without an invented cash hold under a small context."""

    _create_position(reservation_harness.account)
    reservation_harness.account.current_cash = Decimal("0.00")
    reservation_harness.account.save(update_fields=["current_cash"])
    intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="sell-proceeds-cover-fees",
    )

    with localcontext() as context:
        context.prec = 2
        result = reservation_harness.reserve.execute(intent, fee_budget=None, as_of=AS_OF)

    row = SimulatedOrderReservationModel.objects.get(idempotency_key=intent.idempotency_key)
    assert row.notional == Decimal("1000.00")
    assert row.fee_estimate == Decimal("3.02")
    assert row.cash_reserved == Decimal("0.00")
    assert row.shares_reserved == Decimal("100.000000")
    assert result.book.available_cash == Decimal("0.00")


def test_sell_fee_deficit_is_blocked_when_zero_cash_cannot_cover_it(
    reservation_harness: _Harness,
) -> None:
    """A tiny SELL whose proceeds miss minimum fees requires real account cash."""

    _create_position(
        reservation_harness.account,
        quantity=Decimal("1"),
        available_quantity=Decimal("1"),
    )
    reservation_harness.account.current_cash = Decimal("0.00")
    reservation_harness.account.save(update_fields=["current_cash"])
    intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="sell-fee-deficit-no-cash",
        quantity=Decimal("1"),
        price=Decimal("0.01"),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.reserve.execute(intent, fee_budget=None, as_of=AS_OF)

    assert blocked.value.code == "INSUFFICIENT_AVAILABLE_CASH"
    assert SimulatedOrderReservationModel.objects.count() == 0
    reservation_harness.account.refresh_from_db()
    assert reservation_harness.account.current_cash == Decimal("0.00")


def test_sell_cannot_reserve_same_day_buy_shares_before_t_plus_one_release(
    reservation_harness: _Harness,
) -> None:
    """An actual pending BUY receipt leaves its shares unavailable to a new SELL hold."""

    buy = _intent_for(reservation_harness, key="same-day-buy")
    reservation_harness.preparer.execute(buy, as_of=AS_OF)
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=buy.asset_code,
    )
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("0.000000")

    sell = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="same-day-sell",
    )
    with pytest.raises(SimulatedTradeExecutionBlocked):
        reservation_harness.reserve.execute(sell, fee_budget=None, as_of=AS_OF)

    assert SimulatedOrderReservationModel.objects.count() == 0
    assert SimulatedTradeModel.objects.count() == 1


def test_sell_blocks_when_persisted_sellable_quantity_is_unknown(
    reservation_harness: _Harness,
) -> None:
    """Unknown availability is not treated as the total held share count."""

    _create_position(
        reservation_harness.account,
        available_quantity=Decimal("100"),
        available_quantity_known=False,
    )
    intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="unknown-sellable-position",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reservation_harness.reserve.execute(intent, fee_budget=None, as_of=AS_OF)

    assert SimulatedOrderReservationModel.objects.count() == 0


def test_missing_effective_fee_source_blocks_before_persistence(
    reservation_harness: _Harness,
) -> None:
    """A missing persisted FeeV2 source cannot fall back to account defaults."""

    fee_row = FeeConfigModel.objects.get(config_name="uow-equity-fees")
    assert type(fee_row.pk) is int
    with connection.cursor() as cursor:
        cursor.execute(
            'DELETE FROM "simulated_fee_config" WHERE "id" = %s',
            [fee_row.pk],
        )
    intent = _intent_for(reservation_harness, key="no-explicit-fee-policy")

    with pytest.raises(ExecutionFeeScheduleUnavailable):
        reservation_harness.reserve.execute(
            intent,
            fee_budget=Decimal("5.00"),
            as_of=AS_OF,
        )

    assert SimulatedOrderReservationModel.objects.count() == 0
    assert SimulatedTradeModel.objects.count() == 0


def test_plan_stale_at_locked_clock_blocks_before_persisting_a_hold(
    reservation_harness: _Harness,
) -> None:
    """Evidence prepared at the cutoff is rejected after its policy window expires."""

    stale_reserver = ReserveSimulatedOrderUseCase(
        preparer=reservation_harness.preparer,
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF + timedelta(days=31)),
    )
    intent = _intent_for(reservation_harness, key="stale-plan-clock")

    with pytest.raises(SimulatedTradeExecutionBlocked):
        stale_reserver.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)

    assert SimulatedOrderReservationModel.objects.count() == 0


@pytest.mark.parametrize(
    ("changed_field", "changed_value", "fee_budget"),
    [
        ("asset_type", "fund", Decimal("5.00")),
        ("market", "SZ", Decimal("5.00")),
        ("board", "GEM", Decimal("5.00")),
        ("asset_name", "Renamed security", Decimal("5.00")),
        ("reason", "different reason", Decimal("5.00")),
        ("quantity", Decimal("101"), Decimal("5.00")),
        ("price", Decimal("10.01"), Decimal("5.00")),
        (None, None, Decimal("6.00")),
    ],
)
def test_same_key_rejects_any_changed_intent_dimension_or_fee_budget(
    reservation_harness: _Harness,
    changed_field: str | None,
    changed_value: object,
    fee_budget: Decimal,
) -> None:
    """One key remains bound to the complete caller payload and explicit budget."""

    intent = _intent_for(reservation_harness, key="same-key-full-payload")
    reservation_harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    changed = intent if changed_field is None else replace(intent, **{changed_field: changed_value})

    with pytest.raises(SimulatedTradeIdempotencyConflict):
        reservation_harness.reserve.execute(
            changed,
            fee_budget=fee_budget,
            as_of=AS_OF,
        )

    assert SimulatedOrderReservationModel.objects.count() == 1
    assert SimulatedTradeModel.objects.count() == 0


def test_exact_replay_uses_stored_fee_policy_after_source_policy_changes(
    reservation_harness: _Harness,
) -> None:
    """An exact retry replays its sealed fee policy without rereading current fees."""

    intent = _intent_for(reservation_harness, key="replay-original-fee-policy")
    original = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    reads_after_create = reservation_harness.rule_reader.reads
    original_fee = FeeConfigModel.objects.get(config_name="uow-equity-fees")
    successor_start = AS_OF + timedelta(days=30)
    successor_cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=(
                FeeApplicability.APPLIES
                if side is SimulatedTradeSide.SELL
                else FeeApplicability.NOT_APPLICABLE
            ),
            slippage=FeeApplicability.APPLIES,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    successor_policy = DjangoFeePolicyV2Repository(using="default").create_fee_policy_version(
        FeePolicyVersionCommand(
            config_name="uow-equity-fees-v2",
            asset_type="equity",
            commission_rate_buy=0.01,
            commission_rate_sell=original_fee.commission_rate_sell,
            min_commission=original_fee.min_commission,
            stamp_duty_rate=original_fee.stamp_duty_rate,
            transfer_fee_rate=original_fee.transfer_fee_rate,
            min_transfer_fee=original_fee.min_transfer_fee,
            slippage_rate=original_fee.slippage_rate,
            policy_id="component-uow-fees",
            policy_version=2,
            account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
            effective_from=successor_start,
            valid_until=successor_start + timedelta(days=30),
            transaction_cases=successor_cases,
            description="successor policy for durable reservation replay test",
        )
    )
    assert original_fee.fee_policy_version == 1
    assert successor_policy.policy_version == 2
    assert successor_policy.fee_schedule_v1.commission_rate_buy == Decimal.from_float(0.01)

    replay = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=successor_start,
    )

    assert replay.replayed is True
    assert replay.reservation == original.reservation
    assert reservation_harness.rule_reader.reads == reads_after_create
    assert SimulatedTradeModel.objects.count() == 0


def test_cancel_releases_once_and_owner_can_cancel_after_account_deactivation(
    reservation_harness: _Harness,
) -> None:
    """Cancellation preserves the key and releases the full remainder idempotently."""

    intent = _intent_for(reservation_harness, key="cancel-after-deactivation")
    created = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    account_repository = DjangoSimulatedAccountRepository()
    account = account_repository.get_by_id(reservation_harness.account.pk)
    assert account is not None
    account_repository.save(replace(account, is_active=False, auto_trading_enabled=False))
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF + timedelta(minutes=1)),
    )

    first = cancel.execute(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=intent.idempotency_key,
    )
    second = cancel.execute(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=intent.idempotency_key,
    )

    assert first.status is OrderReservationStatus.CANCELLED
    assert first.cash_released == created.reservation.cash_reserved
    assert first == second
    stored = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert stored.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert stored.cash_released == created.reservation.cash_reserved


def test_non_owner_cannot_read_or_cancel_another_users_reservation(
    reservation_harness: _Harness,
) -> None:
    """Both read and cancellation paths remain scoped to the current account owner."""

    intent = _intent_for(reservation_harness, key="owner-scoped-cancel")
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    other_user = get_user_model().objects.create_user(
        username="reservation-non-owner",
        password="unused",
    )
    assert type(other_user.pk) is int
    assert (
        reservation_harness.repository.find_order(
            account_id=reservation_harness.account.pk,
            user_id=other_user.pk,
            idempotency_key=intent.idempotency_key,
        )
        is None
    )
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF),
    )

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        cancel.execute(
            account_id=reservation_harness.account.pk,
            user_id=other_user.pk,
            idempotency_key=intent.idempotency_key,
        )

    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert row.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert row.cash_released == Decimal("0.00")


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("plan_snapshot_hash", "0" * 64),
        ("cash_reserved", Decimal("1005.01")),
    ],
)
def test_generic_queryset_cannot_rewrite_snapshot_or_resource_fields(
    reservation_harness: _Harness,
    field_name: str,
    field_value: object,
) -> None:
    """Reservation identity and amount columns reject generic ORM rewrites."""

    intent = _intent_for(reservation_harness, key=f"corrupt-{field_name}")
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    original_value = getattr(row, field_name)

    with pytest.raises(ValidationError):
        SimulatedOrderReservationModel.objects.filter(pk=row.pk).update(**{field_name: field_value})

    row.refresh_from_db()
    assert getattr(row, field_name) == original_value


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("plan_snapshot_hash", "0" * 64),
        ("fee_estimate", Decimal("4.00")),
    ],
    ids=["snapshot-hash", "fee-estimate"],
)
def test_reader_fail_closes_an_out_of_band_damaged_reservation(
    reservation_harness: _Harness,
    field_name: str,
    field_value: object,
) -> None:
    """A DB-valid but plan-inconsistent snapshot or fee cannot become a valid hold."""

    intent = _intent_for(reservation_harness, key=f"out-of-band-corruption-{field_name}")
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert type(row.pk) is int
    if field_name == "fee_estimate":
        assert row.fee_estimate != Decimal("4.00")
        assert row.fee_budget == Decimal("5.00")
        assert row.fee_budget >= Decimal("4.00")
    with connection.cursor() as cursor:
        cursor.execute(
            f'UPDATE "simulated_order_reservation" SET "{field_name}" = %s WHERE "id" = %s',
            [field_value, row.pk],
        )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reservation_harness.repository.find_order(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            idempotency_key=intent.idempotency_key,
        )


@pytest.mark.parametrize(
    ("tampered_quantity", "tampered_limit_price"),
    [
        (Decimal("50.000000"), Decimal("10.0000")),
        (Decimal("100.000000"), Decimal("5.0000")),
    ],
    ids=["quantity-only", "limit-price-only"],
)
@pytest.mark.parametrize(
    "side",
    [SimulatedTradeSide.BUY, SimulatedTradeSide.SELL],
    ids=["buy", "sell"],
)
def test_reader_binds_reservation_quantity_and_limit_to_sealed_intent(
    reservation_harness: _Harness,
    side: SimulatedTradeSide,
    tampered_quantity: Decimal,
    tampered_limit_price: Decimal,
) -> None:
    """A row hash recomputed for changed quantity or price cannot replace the sealed intent."""

    if side is SimulatedTradeSide.SELL:
        _create_position(reservation_harness.account)
    intent = _intent_for(
        reservation_harness,
        side=side,
        key=f"sealed-economics-{side.value}",
    )
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00") if side is SimulatedTradeSide.BUY else None,
        as_of=AS_OF,
    )
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert type(row.pk) is int
    sealed_intent_hash = row.intent_payload_hash
    sealed_plan_hash = row.plan_snapshot_hash
    assert row.quantity == intent.quantity
    assert row.limit_price == intent.price
    assert (tampered_quantity != intent.quantity) != (tampered_limit_price != intent.price)
    tampered_request = OrderReservationRequest(
        account_id=row.account_id,
        security_id=row.security_id,
        idempotency_key=row.idempotency_key,
        side=side,
        quantity=tampered_quantity,
        limit_price=tampered_limit_price,
        asset_type=row.asset_type,
        market=row.market,
        board=row.board,
        fee_budget=row.fee_budget,
    )
    tampered_notional = tampered_request.notional
    fee_policy = fee_policy_from_snapshot(validated_plan_snapshot(row))
    fees = fee_policy.calculate_for(
        asset_type=row.asset_type,
        market=row.market,
        board=row.board,
        side=side,
        amount=tampered_notional,
        as_of=row.reserved_at,
    )
    tampered_request_hash = tampered_request.identity(
        fee_policy_hash=row.fee_policy_hash,
    ).request_payload_hash
    assert tampered_request_hash != row.reservation_request_hash
    if side is SimulatedTradeSide.BUY:
        assert row.fee_budget is not None
        tampered_cash_reserved = tampered_notional + row.fee_budget
    else:
        tampered_cash_reserved = max(fees.total_fee - tampered_notional, Decimal("0.00"))
    tampered_shares_reserved = (
        tampered_quantity if side is SimulatedTradeSide.SELL else Decimal("0.000000")
    )

    # Bypass the model manager deliberately: this simulates a self-consistent out-of-band row.
    with connection.cursor() as cursor:
        cursor.execute(
            'UPDATE "simulated_order_reservation" '
            'SET "quantity" = %s, "limit_price" = %s, "notional" = %s, '
            '"commission_estimate" = %s, "transfer_fee_estimate" = %s, '
            '"stamp_duty_estimate" = %s, "slippage_estimate" = %s, '
            '"fee_estimate" = %s, "cash_reserved" = %s, "shares_reserved" = %s, '
            '"reservation_request_hash" = %s WHERE "id" = %s',
            [
                tampered_quantity,
                tampered_limit_price,
                tampered_notional,
                fees.commission,
                fees.transfer_fee,
                fees.stamp_duty,
                fees.slippage,
                fees.total_fee,
                tampered_cash_reserved,
                tampered_shares_reserved,
                tampered_request_hash,
                row.pk,
            ],
        )

    damaged = SimulatedOrderReservationModel.objects.get(pk=row.pk)
    assert damaged.intent_payload_hash == sealed_intent_hash
    assert damaged.plan_snapshot_hash == sealed_plan_hash
    assert damaged.reservation_request_hash == tampered_request_hash
    assert damaged.quantity == tampered_quantity
    assert damaged.limit_price == tampered_limit_price
    assert damaged.notional == tampered_notional
    assert damaged.fee_estimate == fees.total_fee
    assert damaged.cash_reserved == tampered_cash_reserved
    assert damaged.shares_reserved == tampered_shares_reserved
    assert SimulatedTradeModel.objects.count() == 0

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.repository.find_order(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            idempotency_key=intent.idempotency_key,
        )

    assert blocked.value.code == "ORDER_RESERVATION_SNAPSHOT_INVALID"


@pytest.mark.parametrize(
    ("cash_reserved", "fee_budget"),
    [
        (Decimal("1006.00"), Decimal("5.00")),
        (Decimal("1004.00"), Decimal("5.00")),
        (Decimal("1001.00"), Decimal("1.00")),
    ],
    ids=["excess-reserve", "insufficient-reserve", "budget-below-estimate"],
)
def test_database_constraint_rejects_cash_reserved_that_breaks_buy_budget_conservation(
    reservation_harness: _Harness,
    cash_reserved: Decimal,
    fee_budget: Decimal,
) -> None:
    """A BUY cash hold equals notional plus a budget that covers its fee estimate."""

    intent = _intent_for(reservation_harness, key="cash-reserved-database-conservation")
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    original_cash_reserved = row.cash_reserved
    assert row.fee_budget == Decimal("5.00")
    assert row.fee_estimate > Decimal("1.00")
    assert original_cash_reserved == row.notional + Decimal("5.00")
    assert type(row.pk) is int

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE "simulated_order_reservation" '
                    'SET "cash_reserved" = %s, "fee_budget" = %s WHERE "id" = %s',
                    [cash_reserved, fee_budget, row.pk],
                )

    row.refresh_from_db()
    assert row.cash_reserved == original_cash_reserved
    assert row.fee_budget == Decimal("5.00")


def test_ordinary_buy_preserves_another_orders_cash_hold(
    reservation_harness: _Harness,
) -> None:
    """A BUY cannot spend cash committed by a distinct active order key."""

    hold_intent = _intent_for(reservation_harness, key="ordinary-buy-cash-hold")
    reservation_harness.reserve.execute(
        hold_intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    changed = SimulatedAccountModel.objects.filter(pk=reservation_harness.account.pk).update(
        current_cash=Decimal("1006.00")
    )
    assert changed == 1
    ordinary_intent = _intent_for(reservation_harness, key="ordinary-buy-other-key")

    with pytest.raises(SimulatedTradeExecutionBlocked):
        reservation_harness.preparer.execute(ordinary_intent, as_of=AS_OF)

    reservation_harness.account.refresh_from_db()
    hold = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=hold_intent.idempotency_key,
    )
    assert reservation_harness.account.current_cash == Decimal("1006.00")
    assert hold.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert hold.cash_reserved == Decimal("1005.00")
    assert SimulatedTradeModel.objects.count() == 0
    assert SimulatedOrderReservationModel.objects.count() == 1


def test_ordinary_sell_preserves_another_orders_sellable_share_hold(
    reservation_harness: _Harness,
) -> None:
    """A normal SELL cannot consume sellable shares committed to another hold."""

    position = _create_position(reservation_harness.account)
    hold_intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="ordinary-sell-share-hold",
    )
    reservation_harness.reserve.execute(hold_intent, fee_budget=None, as_of=AS_OF)
    ordinary_intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="ordinary-sell-other-key",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.preparer.execute(ordinary_intent, as_of=AS_OF)

    assert blocked.value.code == "ORDER_RESERVATION_ACTIVE"
    position.refresh_from_db()
    reservation_harness.account.refresh_from_db()
    hold = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=hold_intent.idempotency_key,
    )
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("100.000000")
    assert reservation_harness.account.current_cash == Decimal("100000.00")
    assert hold.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert hold.shares_reserved == Decimal("100.000000")
    assert SimulatedTradeModel.objects.count() == 0


def test_cancelled_reservation_key_cannot_be_reused_by_ordinary_execution(
    reservation_harness: _Harness,
) -> None:
    """A terminal reservation keeps its key even after the resources are released."""

    intent = _intent_for(reservation_harness, key="cancelled-key-retained")
    created = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF + timedelta(minutes=1)),
    )
    cancel.execute(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=intent.idempotency_key,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.preparer.execute(intent, as_of=AS_OF + timedelta(minutes=2))

    assert blocked.value.code == "ORDER_RESERVATION_KEY_RETAINED"
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert row.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert row.cash_released == created.reservation.cash_reserved
    assert SimulatedTradeModel.objects.count() == 0
    assert SimulatedOrderReservationModel.objects.count() == 1


def test_ordinary_execution_blocks_when_only_ledger_asset_code_matches_a_hold(
    reservation_harness: _Harness,
) -> None:
    """A canonical security mismatch cannot hide a SELL hold from the ledger writer."""

    _create_position(reservation_harness.account)
    old_security = "SH.UOW.SECURITY.OLD"
    evidence = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
    )
    old_preparer = _use_case_for_bundle(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        evidence=evidence,
        bundle=_bundle_for_security(old_security),
    )
    old_reserver = ReserveSimulatedOrderUseCase(
        preparer=old_preparer,
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF),
    )
    hold_intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="identity-conflict-security-hold",
        security_id=old_security,
    )
    old_reserver.execute(hold_intent, fee_budget=None, as_of=AS_OF)
    ordinary_intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="identity-conflict-security-trade",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.preparer.execute(ordinary_intent, as_of=AS_OF)

    assert blocked.value.code == "ORDER_RESERVATION_IDENTITY_CONFLICT"
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=hold_intent.asset_code,
    )
    hold = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=hold_intent.idempotency_key,
    )
    assert position.available_quantity == Decimal("100.000000")
    assert hold.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert SimulatedTradeModel.objects.count() == 0


def test_ordinary_execution_blocks_when_only_canonical_security_matches_a_hold(
    reservation_harness: _Harness,
) -> None:
    """A ledger-code mismatch cannot make an existing SELL hold disappear."""

    _create_position(reservation_harness.account)
    hold_intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="identity-conflict-asset-hold",
    )
    reservation_harness.reserve.execute(hold_intent, fee_budget=None, as_of=AS_OF)
    ordinary_intent = replace(
        _intent_for(
            reservation_harness,
            side=SimulatedTradeSide.SELL,
            key="identity-conflict-asset-trade",
        ),
        asset_code="600000.SH.ALIAS",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reservation_harness.preparer.execute(ordinary_intent, as_of=AS_OF)

    assert blocked.value.code == "ORDER_RESERVATION_IDENTITY_CONFLICT"
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=hold_intent.asset_code,
    )
    hold = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=hold_intent.idempotency_key,
    )
    assert position.available_quantity == Decimal("100.000000")
    assert hold.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert SimulatedTradeModel.objects.count() == 0


def test_reservation_insert_failure_rolls_back_due_t_plus_one_release(
    reservation_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed hold insert rolls back share releases performed earlier in its UoW."""

    buy_intent = _intent_for(reservation_harness, key="pending-buy-before-failed-hold")
    reservation_harness.preparer.execute(buy_intent, as_of=AS_OF)
    pending_trade = SimulatedTradeModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=buy_intent.idempotency_key,
    )
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=buy_intent.asset_code,
    )
    assert pending_trade.settlement_status == "pending"
    assert position.available_quantity == Decimal("0.000000")
    reservation_harness.account.refresh_from_db()
    cash_before = reservation_harness.account.current_cash

    release_time = AS_OF + timedelta(days=5)
    evidence = _calendar(
        as_of=release_time,
        open_dates={
            date(2026, 10, 16),
            date(2026, 10, 19),
            date(2026, 10, 20),
            date(2026, 10, 21),
            date(2026, 10, 22),
            date(2026, 10, 23),
        },
        end=date(2026, 10, 23),
    )
    late_preparer, _, _ = _execute_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=release_time,
        evidence=evidence,
    )
    late_reserver = ReserveSimulatedOrderUseCase(
        preparer=late_preparer,
        repository=reservation_harness.repository,
        clock=_Clock(release_time),
    )
    original_save = SimulatedOrderReservationModel.save
    released_before_insert: list[tuple[Decimal, Decimal, str, datetime | None]] = []

    def fail_insert(
        self: SimulatedOrderReservationModel,
        *args: object,
        **kwargs: object,
    ) -> None:
        if kwargs.get("force_insert") is True:
            position.refresh_from_db()
            pending_trade.refresh_from_db()
            released_before_insert.append(
                (
                    position.quantity,
                    position.available_quantity,
                    pending_trade.settlement_status,
                    pending_trade.settlement_released_at,
                )
            )
            raise IntegrityError("injected reservation insert failure")
        original_save(self, *args, **kwargs)

    monkeypatch.setattr(SimulatedOrderReservationModel, "save", fail_insert)
    later_intent = _intent_for(reservation_harness, key="hold-after-due-release")

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        late_reserver.execute(later_intent, fee_budget=Decimal("5.00"), as_of=release_time)

    assert released_before_insert == [
        (
            Decimal("100.000000"),
            Decimal("100.000000"),
            "released",
            release_time,
        )
    ]
    assert blocked.value.code == "ORDER_RESERVATION_STORAGE_CONFLICT"
    reservation_harness.account.refresh_from_db()
    position.refresh_from_db()
    pending_trade.refresh_from_db()
    assert reservation_harness.account.current_cash == cash_before
    assert position.quantity == Decimal("100.000000")
    assert position.available_quantity == Decimal("0.000000")
    assert pending_trade.settlement_status == "pending"
    assert pending_trade.settlement_released_at is None
    assert SimulatedOrderReservationModel.objects.count() == 0
    assert SimulatedTradeModel.objects.count() == 1


@pytest.mark.parametrize(
    "invalid_cash_state",
    [
        {"cash_known": False},
        {"cash_reconciliation_status": "unknown"},
    ],
    ids=["unknown-flag", "non-ledger-status"],
)
def test_database_constraint_rejects_unknown_cash_on_a_simulated_account(
    reservation_harness: _Harness,
    invalid_cash_state: dict[str, object],
) -> None:
    """Persisted checks reject either representation of unknown simulated cash."""

    account = reservation_harness.account
    cash_before = account.current_cash
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SimulatedAccountModel.objects.filter(pk=account.pk).update(**invalid_cash_state)

    account.refresh_from_db()
    assert account.current_cash == cash_before
    assert account.cash_known is True
    assert account.cash_reconciliation_status == "simulated_ledger"


def test_terminal_reservation_history_blocks_both_account_delete_entrypoints(
    reservation_harness: _Harness,
) -> None:
    """Both account deletion paths preserve a cancelled key and its owning account."""

    intent = _intent_for(reservation_harness, key="terminal-history-blocks-delete")
    created = reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF + timedelta(minutes=1)),
    )
    cancel.execute(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=intent.idempotency_key,
    )
    account_before = (
        SimulatedAccountModel.objects.filter(pk=reservation_harness.account.pk).values().get()
    )
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    row_before = SimulatedOrderReservationModel.objects.filter(pk=row.pk).values().get()
    repository = DjangoSimulatedAccountRepository()

    for delete in (
        lambda: repository.delete(reservation_harness.account.pk),
        lambda: repository.delete_account_with_summary(reservation_harness.account.pk),
    ):
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            delete()
        assert blocked.value.code == "ORDER_RESERVATION_HISTORY_RETAINED"
        assert (
            SimulatedAccountModel.objects.filter(pk=reservation_harness.account.pk).values().get()
            == account_before
        )
        assert SimulatedOrderReservationModel.objects.filter(pk=row.pk).values().get() == row_before

    assert row_before["status"] == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert row_before["cash_released"] == created.reservation.cash_reserved


@pytest.mark.parametrize(
    "side",
    [SimulatedTradeSide.BUY, SimulatedTradeSide.SELL],
    ids=["cash-release", "share-release"],
)
def test_instance_save_cannot_cancel_or_revive_a_reservation(
    reservation_harness: _Harness,
    side: SimulatedTradeSide,
) -> None:
    """Only the locked repository may transition a hold or restore a deleted key."""

    if side is SimulatedTradeSide.SELL:
        _create_position(reservation_harness.account)
    intent = _intent_for(
        reservation_harness,
        side=side,
        key=f"instance-save-is-not-a-transition-{side.value}",
    )
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00") if side is SimulatedTradeSide.BUY else None,
        as_of=AS_OF,
    )
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    row.status = SimulatedOrderReservationModel.STATUS_CANCELLED
    row.cancelled_at = AS_OF + timedelta(minutes=1)
    row.cash_released += row.cash_reserved - row.cash_consumed - row.cash_released
    row.shares_released += row.shares_reserved - row.shares_consumed - row.shares_released

    with pytest.raises(ValidationError):
        row.save()

    row.refresh_from_db()
    assert row.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert row.cash_released == Decimal("0.00")
    assert row.shares_released == Decimal("0.000000")
    assert type(row.pk) is int
    with connection.cursor() as cursor:
        cursor.execute(
            'DELETE FROM "simulated_order_reservation" WHERE "id" = %s',
            [row.pk],
        )

    with pytest.raises(ValidationError):
        row.save()
    assert not SimulatedOrderReservationModel.objects.filter(pk=row.pk).exists()


def test_cancel_rejects_clock_before_reservation_without_releasing_resources(
    reservation_harness: _Harness,
) -> None:
    """A cancellation timestamp cannot predate the committed reservation."""

    intent = _intent_for(reservation_harness, key="cancel-clock-before-reserve")
    reservation_harness.reserve.execute(
        intent,
        fee_budget=Decimal("5.00"),
        as_of=AS_OF,
    )
    cancel = CancelSimulatedOrderReservationUseCase(
        repository=reservation_harness.repository,
        clock=_Clock(AS_OF - timedelta(seconds=1)),
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        cancel.execute(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            idempotency_key=intent.idempotency_key,
        )

    assert blocked.value.code == "CLOCK_INVALID"
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    assert row.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert row.cash_released == Decimal("0.00")


def test_model_constraint_validation_resolves_custom_check_columns(
    reservation_harness: _Harness,
) -> None:
    """Django model validation evaluates the custom check against real field values."""

    intent = _intent_for(reservation_harness, key="model-constraint-column-binding")
    reservation_harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    row.validate_constraints()

    row.cash_reserved += Decimal("0.01")
    with pytest.raises(ValidationError):
        row.validate_constraints()


def test_database_constraint_rejects_one_cent_buy_reservation_mismatch(
    reservation_harness: _Harness,
) -> None:
    """A one-cent difference cannot pass the SQLite or PostgreSQL invariant."""

    intent = _intent_for(reservation_harness, key="one-cent-reservation-mismatch")
    reservation_harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    original = row.cash_reserved

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE "simulated_order_reservation" '
                    'SET "cash_reserved" = %s WHERE "id" = %s',
                    [original + Decimal("0.01"), row.pk],
                )

    row.refresh_from_db()
    assert row.cash_reserved == original


def test_database_constraint_rejects_one_micro_share_overfill(
    reservation_harness: _Harness,
) -> None:
    """A one-micro-share overfill cannot pass the quantity-conservation check."""

    _create_position(reservation_harness.account)
    intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="one-micro-share-overfill",
    )
    reservation_harness.reserve.execute(intent, fee_budget=None, as_of=AS_OF)
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    original = row.filled_quantity

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE "simulated_order_reservation" '
                    'SET "filled_quantity" = %s WHERE "id" = %s',
                    [row.quantity + Decimal("0.000001"), row.pk],
                )

    row.refresh_from_db()
    assert row.filled_quantity == original


def test_storage_envelope_keeps_boundary_and_preserves_postgresql_range(
    reservation_harness: _Harness,
) -> None:
    """The SQLite edge is exact while PostgreSQL retains the declared NUMERIC range."""

    intent = _intent_for(reservation_harness, key="storage-envelope-boundary")
    reservation_harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    maximum_money = Decimal("9999999999999.99")
    maximum_sqlite_quantity = Decimal("999999999.999999")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE "simulated_order_reservation" '
                'SET "source_book_cash" = %s, "source_sellable_quantity" = %s '
                'WHERE "id" = %s',
                [maximum_money, maximum_sqlite_quantity, row.pk],
            )
    row.refresh_from_db()
    assert row.source_book_cash == maximum_money
    assert row.source_sellable_quantity == maximum_sqlite_quantity

    beyond_sqlite_quantity = Decimal("1000000000.000000")
    if connection.vendor == "sqlite":
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        'UPDATE "simulated_order_reservation" '
                        'SET "source_sellable_quantity" = %s WHERE "id" = %s',
                        [beyond_sqlite_quantity, row.pk],
                    )
        row.refresh_from_db()
        assert row.source_sellable_quantity == maximum_sqlite_quantity
    else:
        assert connection.vendor == "postgresql"
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    'UPDATE "simulated_order_reservation" '
                    'SET "source_sellable_quantity" = %s WHERE "id" = %s',
                    [beyond_sqlite_quantity, row.pk],
                )
        row.refresh_from_db()
        assert row.source_sellable_quantity == beyond_sqlite_quantity


def test_unknown_raw_position_values_remain_unknown_without_storage_coercion(
    reservation_harness: _Harness,
) -> None:
    """Unknown persisted values are not read as known shares or valuation inputs."""

    position = _create_position(
        reservation_harness.account,
        quantity=Decimal("1000000000.000000"),
        available_quantity=Decimal("1000000000.000000"),
        available_quantity_known=False,
    )
    position.valuation_known = False
    position.save(update_fields=["valuation_known"])

    book = current_order_reservation_book(
        account=reservation_harness.account,
        owner_user_id=reservation_harness.user_id,
        position=position,
        active_rows=[],
        target=None,
        security_id="SH.UOW.SECURITY",
        asset_code="600000.SH",
    )

    assert book.book_cash == Decimal("100000.00")
    assert book.sellable_shares is None


def test_reader_rejects_out_of_envelope_reservation_but_postgresql_keeps_domain_range(
    reservation_harness: _Harness,
) -> None:
    """Readback rejects corrupt SQLite values while PostgreSQL keeps Domain limits."""

    intent = _intent_for(reservation_harness, key="read-envelope-boundary")
    reservation_harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=AS_OF)
    row = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    row.source_sellable_quantity = Decimal("1000000000.000000")

    if connection.vendor == "sqlite":
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            decode_order_reservation(row)
        assert blocked.value.code == "ORDER_RESERVATION_STATE_INVALID"
    else:
        assert connection.vendor == "postgresql"
        decode_order_reservation(row)
