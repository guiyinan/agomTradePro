"""Native PostgreSQL races for durable simulated fee correction events."""

from __future__ import annotations

import csv
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import DEFAULT_DB_ALIAS, connection, models, transaction
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionBlockedError,
    FeeCorrectionReceipt,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionEvidenceUploadCommand,
)
from apps.simulated_trading.domain.fee_correction import AverageCostReplayResult
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_runtime import (
    build_apply_simulated_fee_correction_use_case,
    build_fee_correction_evidence_upload_use_case,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import AS_OF as AS_OF
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _AccountParentLockWait as _AccountParentLockWait,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _assert_account_parent_lock_wait as _assert_account_parent_lock_wait,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _lock_account_parent as _lock_account_parent,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _submit_worker as _submit_worker,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _wait_for_account_parent_lock as _wait_for_account_parent_lock,
)
from tests.component.simulated_trading.test_order_reservation_concurrency import (
    _WorkerCall as _WorkerCall,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness as _ReservationHarness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _intent_for as _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_CSV_HEADERS = (
    "schema_version",
    "currency_code",
    "source_account_ref",
    "source_trade_ref",
    "asset_code",
    "side",
    "quantity",
    "price",
    "amount",
    "execution_at",
    "source_observed_at",
    "commission",
    "transfer_fee",
    "stamp_duty",
)
_ASSET_CODE = "600000.SH"
_ORIGINAL_COMMISSION = Decimal("0.05")
_REVISED_COMMISSION = Decimal("0.10")
_TRANSFER_FEE = Decimal("0.00")
_STAMP_DUTY = Decimal("0.00")
_SLIPPAGE = Decimal("0.02")
_AMOUNT = Decimal("1000.00")
_QUANTITY = Decimal("100.000000")
_PRICE = Decimal("10.0000")


@dataclass(frozen=True, slots=True)
class _FeeCorrectionFixture:
    """Real persisted legacy ledger rows and the reservation-side writer."""

    reservation: _ReservationHarness
    owner: AbstractBaseUser
    account: SimulatedAccountModel
    trade: SimulatedTradeModel
    position: PositionModel


@dataclass(frozen=True, slots=True)
class _ApplyAttempt:
    """Preserve a real receipt or the stable application rejection code."""

    receipt: FeeCorrectionReceipt | None
    blocked_code: str | None


@pytest.fixture(autouse=True)
def _require_migrated_native_postgres(django_db_use_migrations: bool) -> None:
    """Run backend and lock-catalog claims only against the migrated native PG DB."""

    if not django_db_use_migrations:
        pytest.skip("fee-correction row-lock races require the migrated test database")
    if connection.vendor != "postgresql":
        pytest.skip("fee-correction parent-row lock races require PostgreSQL")
    assert_native_postgres_test_database()


@pytest.fixture
def fee_correction_fixture(
    reservation_harness: _ReservationHarness,
) -> _FeeCorrectionFixture:
    """Seed exact legacy BUY economics and current account-owned evidence policy."""

    owner_model = get_user_model()
    owner = cast(
        AbstractBaseUser,
        owner_model._default_manager.get(pk=reservation_harness.user_id),
    )
    account = reservation_harness.account
    assert type(account.pk) is int
    assert type(owner.pk) is int

    execution_time = AS_OF - timedelta(minutes=30)
    total_cost = _AMOUNT + _ORIGINAL_COMMISSION + _TRANSFER_FEE + _STAMP_DUTY + _SLIPPAGE
    cash_after_buy = account.initial_capital - total_cost
    account.start_date = execution_time.date() - timedelta(days=1)
    account.last_trade_date = execution_time.date()
    account.current_cash = cash_after_buy
    account.current_market_value = _AMOUNT
    account.total_value = cash_after_buy + _AMOUNT
    account.save(
        update_fields=(
            "start_date",
            "last_trade_date",
            "current_cash",
            "current_market_value",
            "total_value",
        )
    )

    trade = SimulatedTradeModel.objects.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Fee correction concurrency fixture",
        asset_type="equity",
        action="buy",
        quantity=_QUANTITY,
        price=_PRICE,
        amount=_AMOUNT,
        commission=_ORIGINAL_COMMISSION,
        transfer_fee=_TRANSFER_FEE,
        stamp_duty=_STAMP_DUTY,
        slippage=_SLIPPAGE,
        total_cost=total_cost,
        fee_amounts_known=True,
        cost_basis_known=True,
        realized_pnl=None,
        realized_pnl_pct=None,
        order_date=execution_time.date(),
        execution_date=execution_time.date(),
        execution_time=execution_time,
        status="executed",
    )
    position = PositionModel.objects.create(
        account=account,
        asset_code=_ASSET_CODE,
        asset_name="Fee correction concurrency fixture",
        asset_type="equity",
        quantity=_QUANTITY,
        available_quantity=_QUANTITY,
        avg_cost=(total_cost / _QUANTITY).quantize(Decimal("0.0001")),
        total_cost=total_cost,
        cost_basis_known=True,
        current_price=_PRICE,
        market_value=_AMOUNT,
        valuation_known=True,
        unrealized_pnl=_AMOUNT - total_cost,
        unrealized_pnl_pct=0.0,
        first_buy_date=execution_time.date(),
    )

    now = timezone.now()
    FeeCorrectionEvidencePolicyModel.objects.create(
        account=account,
        enabled=True,
        allow_operator_attested_upload=True,
        ledger_currency="CNY",
        version=1,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=365),
        updated_by=owner,
    )
    return _FeeCorrectionFixture(
        reservation=reservation_harness,
        owner=owner,
        account=account,
        trade=trade,
        position=position,
    )


def _csv_bytes(
    *,
    account: SimulatedAccountModel,
    trade: SimulatedTradeModel,
    revised_commission: Decimal,
) -> bytes:
    """Build one local evidence row bound to exact persisted trade economics."""

    assert type(account.pk) is int
    assert type(trade.pk) is int
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_CSV_HEADERS)
    writer.writerow(
        (
            OPERATOR_FEE_CSV_SCHEMA,
            "CNY",
            f"account-{account.pk}",
            f"trade-{trade.pk}",
            trade.asset_code,
            trade.action,
            format(trade.quantity, "f"),
            format(trade.price, "f"),
            format(trade.amount, "f"),
            trade.execution_time.isoformat(timespec="microseconds"),
            (trade.execution_time + timedelta(minutes=15)).isoformat(timespec="microseconds"),
            format(revised_commission, ".2f"),
            format(_TRANSFER_FEE, ".2f"),
            format(_STAMP_DUTY, ".2f"),
        )
    )
    return output.getvalue().encode("utf-8")


def _bind_request(
    fixture: _FeeCorrectionFixture,
    *,
    idempotency_key: str,
    revised_commission: Decimal = _REVISED_COMMISSION,
) -> FeeCorrectionRequest:
    """Persist one owner-attested artifact and return its exact correction request."""

    assert type(fixture.account.pk) is int
    assert type(fixture.trade.pk) is int
    receipt = build_fee_correction_evidence_upload_use_case().execute(
        FeeCorrectionEvidenceUploadCommand(
            account_id=fixture.account.pk,
            trade_id=fixture.trade.pk,
            expected_revision=0,
            expected_predecessor_id=None,
            idempotency_key=idempotency_key,
            original_filename=f"{idempotency_key}.csv",
            content=_csv_bytes(
                account=fixture.account,
                trade=fixture.trade,
                revised_commission=revised_commission,
            ),
            attestation_acknowledged=True,
        ),
        principal=fixture.owner,
    )
    return FeeCorrectionRequest(
        account_id=fixture.account.pk,
        trade_id=fixture.trade.pk,
        idempotency_key=idempotency_key,
        expected_revision=0,
        source_locator=receipt.source_locator,
    )


def _attempt_apply(
    request: FeeCorrectionRequest,
    principal: AbstractBaseUser,
) -> _ApplyAttempt:
    """Invoke the production composition and retain business rejection outcomes."""

    try:
        receipt = build_apply_simulated_fee_correction_use_case().execute(
            request,
            principal=principal,
        )
    except FeeCorrectionBlockedError as error:
        return _ApplyAttempt(receipt=None, blocked_code=error.code)
    return _ApplyAttempt(receipt=receipt, blocked_code=None)


def _attempt_from_worker(worker: _WorkerCall) -> _ApplyAttempt:
    """Require the fresh-connection worker to return the typed application result."""

    outcome = worker.future.result(timeout=20)
    assert type(outcome.value) is _ApplyAttempt
    return cast(_ApplyAttempt, outcome.value)


def _model_snapshot(row: models.Model) -> tuple[tuple[str, object], ...]:
    """Capture all concrete persisted fields for immutable-row rollback assertions."""

    return tuple(
        (field.attname, getattr(row, field.attname)) for field in row._meta.concrete_fields
    )


def _current_backend_pid() -> int:
    """Read the blocker backend identity without acquiring an additional row lock."""

    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        row = cursor.fetchone()
    assert row is not None and type(row[0]) is int
    return row[0]


def _assert_pair_waited(
    first: _WorkerCall,
    first_wait: _AccountParentLockWait,
    second: _WorkerCall,
    second_wait: _AccountParentLockWait,
    blocker_pid: int,
) -> None:
    """Require distinct worker backends blocked by the same real account parent."""

    assert len(first.backend_pids) == len(second.backend_pids) == 1
    first_pid = first.backend_pids[0]
    second_pid = second.backend_pids[0]
    assert first_pid != second_pid
    assert first_pid != blocker_pid
    assert second_pid != blocker_pid
    assert blocker_pid in first_wait.blocker_pids
    assert {blocker_pid, first_pid}.intersection(second_wait.blocker_pids)
    _assert_account_parent_lock_wait(first_wait)
    _assert_account_parent_lock_wait(second_wait)


def test_postgres_same_idempotency_key_writes_one_event_across_two_backends(
    fee_correction_fixture: _FeeCorrectionFixture,
) -> None:
    """Two callers blocked at the account row produce one correction and one replay."""

    fixture = fee_correction_fixture
    assert type(fixture.account.pk) is int
    request = _bind_request(fixture, idempotency_key="pg-fee-same-key")
    initial_cash = fixture.account.current_cash
    original_trade = _model_snapshot(fixture.trade)
    original_receipts = tuple(
        _model_snapshot(row)
        for row in SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade_id=fixture.trade.pk)
        .order_by("pk")
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        with transaction.atomic():
            blocker_pid = _lock_account_parent(fixture.account)
            first = _submit_worker(
                executor,
                lambda: _attempt_apply(request, fixture.owner),
            )
            first_wait = _wait_for_account_parent_lock(
                waiter_pid=first.backend_pids[0],
                allowed_blocker_pids=(blocker_pid,),
                future=first.future,
            )
            second = _submit_worker(
                executor,
                lambda: _attempt_apply(request, fixture.owner),
            )
            second_wait = _wait_for_account_parent_lock(
                waiter_pid=second.backend_pids[0],
                allowed_blocker_pids=(blocker_pid, first.backend_pids[0]),
                future=second.future,
            )
            _assert_pair_waited(first, first_wait, second, second_wait, blocker_pid)

        attempts = (_attempt_from_worker(first), _attempt_from_worker(second))

    receipts = tuple(attempt.receipt for attempt in attempts)
    assert all(receipt is not None for receipt in receipts)
    typed_receipts = tuple(cast(FeeCorrectionReceipt, receipt) for receipt in receipts)
    assert sorted(receipt.replayed for receipt in typed_receipts) == [False, True]
    assert typed_receipts[0].event_id == typed_receipts[1].event_id
    assert typed_receipts[0].account_id == typed_receipts[1].account_id == fixture.account.pk
    assert (
        SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .count()
        == 1
    )

    event = SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=fixture.account.pk
    )
    fixture.account.refresh_from_db()
    assert fixture.account.current_cash == initial_cash + event.cash_delta
    assert event.cash_delta == Decimal("-0.05")
    fixture.position.refresh_from_db()
    assert fixture.position.total_cost == fixture.trade.total_cost + Decimal("0.05")
    assert fixture.position.total_cost == Decimal("1000.12")
    assert (
        _model_snapshot(
            SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS).get(pk=fixture.trade.pk)
        )
        == original_trade
    )
    final_receipts = tuple(
        _model_snapshot(row)
        for row in SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade_id=fixture.trade.pk)
        .order_by("pk")
    )
    assert final_receipts == original_receipts == ()


def test_postgres_different_keys_competing_for_one_predecessor_commit_once(
    fee_correction_fixture: _FeeCorrectionFixture,
) -> None:
    """Different keys with the same revision cannot both append a ledger event."""

    fixture = fee_correction_fixture
    assert type(fixture.account.pk) is int
    first_request = _bind_request(fixture, idempotency_key="pg-fee-predecessor-a")
    second_request = _bind_request(fixture, idempotency_key="pg-fee-predecessor-b")
    initial_cash = fixture.account.current_cash

    with ThreadPoolExecutor(max_workers=2) as executor:
        with transaction.atomic():
            blocker_pid = _lock_account_parent(fixture.account)
            first = _submit_worker(
                executor,
                lambda: _attempt_apply(first_request, fixture.owner),
            )
            first_wait = _wait_for_account_parent_lock(
                waiter_pid=first.backend_pids[0],
                allowed_blocker_pids=(blocker_pid,),
                future=first.future,
            )
            second = _submit_worker(
                executor,
                lambda: _attempt_apply(second_request, fixture.owner),
            )
            second_wait = _wait_for_account_parent_lock(
                waiter_pid=second.backend_pids[0],
                allowed_blocker_pids=(blocker_pid, first.backend_pids[0]),
                future=second.future,
            )
            _assert_pair_waited(first, first_wait, second, second_wait, blocker_pid)

        attempts = (_attempt_from_worker(first), _attempt_from_worker(second))

    applied = tuple(attempt for attempt in attempts if attempt.receipt is not None)
    blocked = tuple(attempt for attempt in attempts if attempt.blocked_code is not None)
    assert len(applied) == 1
    assert len(blocked) == 1
    assert blocked[0].blocked_code == "FEE_CORRECTION_REVISION_CONFLICT"
    assert (
        SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .count()
        == 1
    )
    event = SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=fixture.account.pk
    )
    assert event.idempotency_key in {
        first_request.idempotency_key,
        second_request.idempotency_key,
    }
    fixture.account.refresh_from_db()
    assert fixture.account.current_cash == initial_cash + event.cash_delta
    assert event.cash_delta == Decimal("-0.05")
    fixture.position.refresh_from_db()
    assert fixture.position.total_cost == fixture.trade.total_cost + Decimal("0.05")
    assert fixture.position.total_cost == Decimal("1000.12")


def test_postgres_reservation_writer_holds_parent_before_correction_rejects_active_hold(
    fee_correction_fixture: _FeeCorrectionFixture,
) -> None:
    """A real reserve commits its hold before a waiting correction checks the same account."""

    fixture = fee_correction_fixture
    assert type(fixture.account.pk) is int
    request = _bind_request(fixture, idempotency_key="pg-fee-blocked-by-reserve")
    initial_cash = fixture.account.current_cash

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            reserve_result = fixture.reservation.reserve.execute(
                _intent_for(
                    fixture.reservation,
                    key="pg-fee-concurrent-reservation",
                ),
                fee_budget=Decimal("5.00"),
                as_of=AS_OF,
            )
            blocker_pid = _current_backend_pid()
            worker = _submit_worker(
                executor,
                lambda: _attempt_apply(request, fixture.owner),
            )
            wait = _wait_for_account_parent_lock(
                waiter_pid=worker.backend_pids[0],
                allowed_blocker_pids=(blocker_pid,),
                future=worker.future,
            )
            assert wait.wait_event_type == "Lock"
            assert blocker_pid in wait.blocker_pids
            _assert_account_parent_lock_wait(wait)

        attempt = _attempt_from_worker(worker)

    reservation_key = reserve_result.reservation.identity.idempotency_key
    assert reservation_key == "pg-fee-concurrent-reservation"
    reservation_row = SimulatedOrderReservationModel.objects.using(DEFAULT_DB_ALIAS).get(
        account_id=fixture.account.pk,
        idempotency_key=reservation_key,
    )
    assert reservation_row.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert attempt.receipt is None
    assert attempt.blocked_code == "ORDER_RESERVATION_ACTIVE"
    assert (
        SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .count()
        == 0
    )
    fixture.account.refresh_from_db()
    assert fixture.account.current_cash == initial_cash


def test_real_posting_failure_rolls_back_event_and_preserves_trade_and_receipts(
    fee_correction_fixture: _FeeCorrectionFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure after Position save rolls back cash/event while Trade/receipts stay exact."""

    fixture = fee_correction_fixture
    assert type(fixture.account.pk) is int
    request = _bind_request(fixture, idempotency_key="pg-fee-rollback")
    use_case = build_apply_simulated_fee_correction_use_case()
    repository = use_case._repository
    save_position = repository._save_corrected_position
    before_trade = _model_snapshot(fixture.trade)
    before_position = _model_snapshot(fixture.position)
    before_account = _model_snapshot(fixture.account)
    before_receipts = tuple(
        _model_snapshot(row)
        for row in SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade_id=fixture.trade.pk)
        .order_by("pk")
    )

    class _InjectedPostingFailure(RuntimeError):
        pass

    def fail_after_position_save(
        *,
        position: PositionModel | None,
        replay: AverageCostReplayResult,
        using: str,
    ) -> None:
        save_position(position=position, replay=replay, using=using)
        raise _InjectedPostingFailure("rollback after corrected position persistence")

    monkeypatch.setattr(repository, "_save_corrected_position", fail_after_position_save)
    with pytest.raises(_InjectedPostingFailure):
        use_case.execute(request, principal=fixture.owner)

    assert (
        SimulatedFeeCorrectionEventModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(account_id=fixture.account.pk)
        .count()
        == 0
    )
    assert (
        _model_snapshot(
            SimulatedTradeModel.objects.using(DEFAULT_DB_ALIAS).get(pk=fixture.trade.pk)
        )
        == before_trade
    )
    assert (
        _model_snapshot(PositionModel.objects.using(DEFAULT_DB_ALIAS).get(pk=fixture.position.pk))
        == before_position
    )
    assert (
        _model_snapshot(
            SimulatedAccountModel.objects.using(DEFAULT_DB_ALIAS).get(pk=fixture.account.pk)
        )
        == before_account
    )
    after_receipts = tuple(
        _model_snapshot(row)
        for row in SimulatedOrderFillReceiptModel.objects.using(DEFAULT_DB_ALIAS)
        .filter(trade_id=fixture.trade.pk)
        .order_by("pk")
    )
    assert after_receipts == before_receipts == ()
