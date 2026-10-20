"""Failure-first tests for an atomic persisted partial-fill writer.

These cases exercise a private G2 candidate only. Their source reader is an
explicit test double and does not qualify or activate any production matcher.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, cast

import pytest
from django.db import IntegrityError, connection, models, transaction

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecuteSettlementBoundSimulatedTradeUseCase,
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionResultUnknown,
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.application.order_reservation_fill import (
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    snapshot_digest,
    validated_plan_snapshot,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_initial_position_mark_codec import (
    decode_initial_position_mark_evidence,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _bundle,
    _calendar,
    _Clock,
    _current_v3_plan,
    _IdentityReader,
    _RuleReader,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _reader_rows,
    _Rows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """Return one explicit aware instant for a writer invocation."""

    value: datetime

    def now(self) -> datetime:
        """Return the configured instant without consulting the machine clock."""

        return self.value


@dataclass(slots=True)
class _EventReader:
    """Expose one deterministic local event and record every source read."""

    event: LocalSimulatedFillEventV1
    calls: list[tuple[str, str, datetime]]

    def read_event(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
        as_of: datetime,
    ) -> LocalSimulatedFillEventV1 | None:
        """Return the exact configured event only for its complete locator."""

        self.calls.append((source_namespace, fill_event_id, as_of))
        if (
            account_id != self.event.account_id
            or user_id != self.event.user_id
            or order_idempotency_key != self.event.order_idempotency_key
            or source_namespace != self.event.source_namespace
            or fill_event_id != self.event.source_event_id
        ):
            return None
        return self.event


@dataclass(slots=True)
class _InitialPositionMarkReader:
    """Return one explicitly prepared mark proof and retain every request."""

    proof: InitialPositionMarkProof | None
    calls: list[tuple[str, str, str, str, str, datetime]]

    def read_initial_position_mark(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof | None:
        """Record the exact instrument/cutoff request, then return its fixture."""

        self.calls.append((security_id, asset_code, asset_type, market, board, read_at))
        return self.proof


def _initial_position_mark(
    rows: _Rows,
    *,
    read_at: datetime = _READ_CUTOFF,
    price: Decimal = Decimal("10.2500"),
) -> InitialPositionMarkProof:
    """Build a separate, source-backed mark fixture for a first BUY."""

    observed_at = read_at - timedelta(seconds=10)
    return InitialPositionMarkProof(
        security_id=rows.event.security_id,
        asset_code=rows.event.asset_code,
        asset_type=rows.reservation.asset_type,
        market=rows.reservation.market,
        board=rows.reservation.board,
        price=price,
        source_observed_at=observed_at,
        source_available_at=None,
        read_at=read_at,
        publication_as_of=read_at - timedelta(seconds=2),
        published_at=read_at - timedelta(seconds=1),
        valid_until=observed_at + timedelta(seconds=600),
        freshness_window_seconds=600,
        source_identity="test.independent-current-mark",
        source_record_id="test-mark-record-0001",
        source_content_hash="a" * 64,
        publication_id="test-mark-publication-0001",
        publication_hash="b" * 64,
        policy_identity="test-mark-policy-v1",
        policy_content_hash="c" * 64,
    )


class _ExchangeCalendarReader:
    """Return published evidence only for its exact configured exchange."""

    def __init__(self, evidence: ExecutionCalendarEvidence) -> None:
        self.evidence = evidence
        self.coverage_requests: list[date | None] = []

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence:
        """Validate the exchange and cutoff before returning published evidence."""

        assert exchange == self.evidence.snapshot.exchange
        self.coverage_requests.append(coverage_start)
        self.evidence.validate_for(as_of)
        return self.evidence


@dataclass(frozen=True, slots=True)
class _TwoActiveFills:
    """Keep the exact rows and results for a persisted active two-fill chain."""

    rows: _Rows
    reader: _EventReader
    repository: DjangoSimulatedOrderFillRepository
    first_event: LocalSimulatedFillEventV1
    first_result: SimulatedOrderFillResult
    second_event: LocalSimulatedFillEventV1
    second_result: SimulatedOrderFillResult


@dataclass(frozen=True, slots=True)
class _NoClock:
    """Fail if an exact persisted replay asks for current time."""

    def now(self) -> datetime:
        """Reject any clock access during exact replay."""

        raise AssertionError("exact persisted replay must not read the clock")


def _set_consistent_account_mark(
    account: SimulatedAccountModel,
    *,
    market_value: Decimal,
) -> None:
    """Set the fixture's account aggregate to its explicitly known position mark."""

    account.current_market_value = market_value
    account.total_value = account.current_cash + market_value
    account.save(
        update_fields=[
            "current_market_value",
            "total_value",
            "cash_known",
            "cash_reconciliation_status",
        ]
    )


def _invoke(
    repository: DjangoSimulatedOrderFillRepository,
    event: LocalSimulatedFillEventV1,
    proof: OrderFillSettlementProof,
    *,
    clock: _FixedClock,
) -> SimulatedOrderFillResult:
    """Call the candidate writer with the exact observed source digest."""

    return repository.apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=proof,
        clock=clock,
    )


def _persist_two_active_fills(harness: _Harness) -> _TwoActiveFills:
    """Persist two normal fills while leaving the reservation active."""

    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    rows.reservation.refresh_from_db()
    first_event = replace(
        rows.event,
        quantity=Decimal("10.010000"),
        event_payload_hash="5" * 64,
    )
    reader = _EventReader(first_event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    first_result = _invoke(
        repository,
        first_event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    second_at = first_event.occurred_at + timedelta(seconds=30)
    second_event = replace(
        first_event,
        source_event_id="row-reader-event-0002",
        quantity=Decimal("20.020000"),
        event_payload_hash="6" * 64,
        source_snapshot_id="row-reader-source-snapshot-002",
        source_snapshot_hash="7" * 64,
        occurred_at=second_at,
        source_observed_at=second_at,
        source_available_at=second_at,
        recorded_at=second_at,
    )
    second_proof = build_order_fill_settlement_proof(
        calendar_evidence=rows.proof.calendar_evidence,
        calendar_read_cutoff=_READ_CUTOFF,
        fill_occurred_at=second_at,
        settlement_exchange=rows.proof.settlement_exchange,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )
    reader.event = second_event
    second_result = _invoke(
        repository,
        second_event,
        second_proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert first_result.reservation.status.value == "active"
    assert second_result.reservation.status.value == "active"
    reader.calls.clear()
    return _TwoActiveFills(
        rows=rows,
        reader=reader,
        repository=repository,
        first_event=first_event,
        first_result=first_result,
        second_event=second_event,
        second_result=second_result,
    )


def _ledger_counts(account: SimulatedAccountModel) -> tuple[int, int, int, int, Decimal]:
    """Capture durable financial rows and cash for no-write assertions."""

    return (
        SimulatedTradeModel.objects.filter(account=account).count(),
        SimulatedOrderFillReceiptModel.objects.filter(trade__account=account).count(),
        SimulatedOrderReservationModel.objects.filter(account=account).count(),
        PositionModel.objects.filter(account=account).count(),
        SimulatedAccountModel.objects.get(pk=account.pk).current_cash,
    )


def _first_buy_rows(harness: _Harness) -> _Rows:
    """Prepare a real BUY reservation while keeping the account positionless."""

    rows = _reader_rows(harness)
    _set_consistent_account_mark(harness.account, market_value=Decimal("0.00"))
    assert PositionModel.objects.filter(account=harness.account).count() == 0
    account = SimulatedAccountModel.objects.get(pk=harness.account.pk)
    assert account.cash_known is True
    assert account.cash_reconciliation_status == "simulated_ledger"
    assert account.total_value == account.current_cash
    return rows


def _reservation_unfilled(reservation: SimulatedOrderReservationModel) -> None:
    """Assert a rejected first fill left the frozen parent order untouched."""

    reservation.refresh_from_db()
    assert reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert reservation.filled_quantity == Decimal("0.000000")
    assert reservation.cash_consumed == Decimal("0.00")
    assert reservation.shares_consumed == Decimal("0.000000")
    assert reservation.cash_released == Decimal("0.00")
    assert reservation.shares_released == Decimal("0.000000")


def _account_financial_state(
    account: SimulatedAccountModel,
) -> tuple[Decimal, Decimal, Decimal, int, int, date | None, bool, str]:
    """Return the durable owner-account values affected by a fill."""

    current = SimulatedAccountModel.objects.get(pk=account.pk)
    return (
        current.current_cash,
        current.current_market_value,
        current.total_value,
        current.total_trades,
        current.winning_trades,
        current.last_trade_date,
        current.cash_known,
        current.cash_reconciliation_status,
    )


def _harness_with_source_exchange(harness: _Harness, exchange: str) -> _Harness:
    """Compose a real reservation journey with independently supplied source exchange."""

    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    calendar = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
        exchange=exchange,
    )
    preparer = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=harness.rule_reader,
        identity_reader=_IdentityReader(exchange),
        calendar_reader=_ExchangeCalendarReader(calendar),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(AS_OF),
    )
    reserve = ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=harness.repository,
        clock=_Clock(AS_OF),
    )
    return replace(harness, preparer=preparer, reserve=reserve)


def _harness_with_settlement_lag(
    harness: _Harness,
    *,
    lag_sessions: int,
) -> _Harness:
    """Compose a real reservation journey with an explicit settlement lag."""

    rule_reader = _RuleReader(_bundle(lag=lag_sessions))
    repository = DjangoSimulatedTradeExecutionRepository(using="default")
    calendar = _calendar(
        as_of=AS_OF,
        open_dates={date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)},
        exchange="SH",
    )
    preparer = ExecuteSettlementBoundSimulatedTradeUseCase(
        rule_reader=rule_reader,
        identity_reader=_IdentityReader(),
        calendar_reader=_ExchangeCalendarReader(calendar),
        fee_policy_reader=repository,
        repository=repository,
        clock=_Clock(AS_OF),
    )
    reserve = ReserveSimulatedOrderUseCase(
        preparer=preparer,
        repository=harness.repository,
        clock=_Clock(AS_OF),
    )
    return replace(
        harness,
        preparer=preparer,
        reserve=reserve,
        rule_reader=rule_reader,
    )


def _reseal_reservation_plan(
    reservation: SimulatedOrderReservationModel,
    snapshot: dict[str, object],
) -> str:
    """Persist a deliberately resealed plan corruption for strict writer checks."""

    plan_hash = snapshot_digest(snapshot)
    query = SimulatedOrderReservationModel._base_manager.filter(pk=reservation.pk)
    changed = models.QuerySet.update(
        query,
        plan_snapshot=snapshot,
        plan_snapshot_hash=plan_hash,
    )
    assert changed == 1
    return plan_hash


def _domain_content_hash(payload: dict[str, object]) -> str:
    """Recompute the source Domain's canonical nested content hash for tamper fixtures."""

    body = {key: value for key, value in payload.items() if key != "content_hash"}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_buy_fill_writes_trade_receipt_position_and_reservation_atomically(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A T+1 BUY persists one exact fill without marking from its execution price."""

    del persisted_receipt_schema
    position = _create_position(reservation_harness.account)
    position.cost_basis_known = False
    position.save(update_fields=["cost_basis_known"])
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        using="default",
    )

    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    position.refresh_from_db()
    reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
    account = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert result.replayed is False
    assert (reader.calls and len(reader.calls)) == 1
    assert reservation.filled_quantity == Decimal("10.000000")
    assert trade.quantity == Decimal("10.000000")
    assert receipt.source_event_id == rows.event.source_event_id
    assert receipt.receipt_hash == trade.request_payload_hash
    assert position.quantity == Decimal("110.000000")
    assert position.available_quantity == Decimal("100.000000")
    assert position.current_price == Decimal("10.0000")
    assert position.valuation_known is True
    assert position.cost_basis_known is False
    assert trade.cost_basis_known is False
    assert trade.settlement_status == "pending"
    assert account.current_market_value == Decimal("1100.00")
    assert account.total_value == account.current_cash + account.current_market_value
    assert account.cash_known is True
    assert account.cash_reconciliation_status == "simulated_ledger"


@pytest.mark.parametrize("missing_state", ["position", "valuation", "aggregate"])
def test_unknown_mark_or_missing_position_blocks_before_any_fill_write(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    missing_state: str,
) -> None:
    """The fill price cannot create a valuation or repair an inconsistent account aggregate."""

    del persisted_receipt_schema
    position: PositionModel | None = None
    if missing_state != "position":
        position = _create_position(reservation_harness.account)
        _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    if missing_state == "valuation":
        assert position is not None
        position.valuation_known = False
        position.save(update_fields=["valuation_known"])
    elif missing_state == "aggregate":
        SimulatedAccountModel.objects.filter(pk=reservation_harness.account.pk).update(
            current_market_value=Decimal("999.00"),
            total_value=reservation_harness.account.current_cash + Decimal("999.00"),
        )
    before = _ledger_counts(reservation_harness.account)
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    account_state_before = (
        account_before.current_cash,
        account_before.current_market_value,
        account_before.total_value,
        account_before.cash_known,
        account_before.cash_reconciliation_status,
    )
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        using="default",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(
            repository,
            rows.event,
            rows.proof,
            clock=_FixedClock(_READ_CUTOFF),
        )

    assert _ledger_counts(reservation_harness.account) == before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert (
        account_after.current_cash,
        account_after.current_market_value,
        account_after.total_value,
        account_after.cash_known,
        account_after.cash_reconciliation_status,
    ) == account_state_before
    if position is not None:
        position.refresh_from_db()
        assert position.quantity == Decimal("100.000000")
        if missing_state == "valuation":
            assert position.valuation_known is False


def test_database_cash_knowledge_constraint_rejects_unknown_simulated_cash_without_fill(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The database rejects an impossible unknown-cash state and recovers its connection."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    before = _ledger_counts(reservation_harness.account)
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    account_state_before = (
        account_before.account_type,
        account_before.current_cash,
        account_before.current_market_value,
        account_before.total_value,
        account_before.cash_known,
        account_before.cash_reconciliation_status,
    )
    reservation_state_before = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_consumed,
        rows.reservation.shares_released,
    )

    with transaction.atomic(using="default"):
        with pytest.raises(IntegrityError) as database_error:
            with transaction.atomic(using="default"):
                changed = SimulatedAccountModel.objects.filter(
                    pk=reservation_harness.account.pk
                ).update(
                    cash_known=False,
                    cash_reconciliation_status="unverified",
                )
                assert changed == 1
        cause = database_error.value.__cause__ or database_error.value
        diagnostic = getattr(cause, "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        if isinstance(constraint_name, str) and constraint_name:
            assert constraint_name == "sim_account_cash_knowledge_ck"
        else:
            assert "sim_account_cash_knowledge_ck" in str(cause)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

    assert _ledger_counts(reservation_harness.account) == before
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert (
        account_after.account_type,
        account_after.current_cash,
        account_after.current_market_value,
        account_after.total_value,
        account_after.cash_known,
        account_after.cash_reconciliation_status,
    ) == account_state_before
    rows.reservation.refresh_from_db()
    assert (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_consumed,
        rows.reservation.shares_released,
    ) == reservation_state_before
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )


def test_sell_fill_keeps_unknown_cost_basis_unknown_and_pnl_null(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A real SELL reduces known shares while preserving unknown cost knowledge."""

    del persisted_receipt_schema
    rows = _reader_rows(reservation_harness, side=SimulatedTradeSide.SELL)
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    position.cost_basis_known = None
    position.save(update_fields=["cost_basis_known"])
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")

    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    position.refresh_from_db()
    trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
    account = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert result.replayed is False
    assert position.quantity == Decimal("90.000000")
    assert position.available_quantity == Decimal("90.000000")
    assert position.cost_basis_known is None
    assert trade.cost_basis_known is None
    assert trade.realized_pnl is None
    assert trade.realized_pnl_pct is None
    assert trade.fee_amounts_known is True
    assert position.current_price == Decimal("10.0000")
    assert account.current_market_value == Decimal("900.00")
    assert account.total_value == account.current_cash + account.current_market_value


def test_changed_locked_source_event_blocks_without_mutation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The exact durable event is re-read after locks and must still match."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    changed = replace(rows.event, price=Decimal("9.9900"))
    reader = _EventReader(changed, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert len(reader.calls) == 1
    assert _ledger_counts(reservation_harness.account) == before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0


def test_tampered_prior_receipt_chain_blocks_before_rereading_new_source(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A later fill cannot extend a stored receipt chain that no longer verifies."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    first = _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
    reader.calls.clear()

    SimulatedTradeModel.objects.filter(pk=first.trade_id).update(price=Decimal("9.9900"))
    next_event = replace(
        rows.event,
        source_event_id="row-reader-event-0002",
        event_payload_hash="3" * 64,
    )
    reader.event = next_event
    before = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, next_event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert reader.calls == []
    assert _ledger_counts(reservation_harness.account) == before
    reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    assert reservation.filled_quantity == Decimal("10.000000")
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 1
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 1
    )


def test_exact_terminal_receipt_replays_before_source_or_clock(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An exact FINAL_FILL is replayable after terminal status without new reads."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    event = replace(
        rows.event,
        event_kind=LocalSimulatedFillEventKind.FINAL_FILL,
        quantity=Decimal("100.000000"),
        event_payload_hash="f" * 64,
    )
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    first = _invoke(repository, event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
    reader.calls.clear()

    class _ExplodingClock:
        """Prove replay does not ask for a current clock."""

        def now(self) -> datetime:
            """Fail if an exact receipt replay consults the current clock."""

            raise AssertionError("exact receipt replay must not read the clock")

    replay = repository.apply_fill_event(
        event=event,
        expected_event_payload_hash=event.event_payload_hash,
        settlement_proof=rows.proof,
        clock=_ExplodingClock(),
    )

    assert first.reservation.status.value == "completed"
    assert replay.replayed is True
    assert replay.trade_id == first.trade_id
    assert reader.calls == []
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 1
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 1
    )


def test_receipt_insert_failure_rolls_back_trade_position_account_and_hold(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late receipt failure must not leave any financial or reservation write."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)
    position_before = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    prior_quantity = position_before.quantity

    def fail_receipt_save(
        self: SimulatedOrderFillReceiptModel, *args: object, **kwargs: object
    ) -> None:
        """Force failure after the Trade has been inserted inside the transaction."""

        del self, args, kwargs
        from django.db import IntegrityError

        raise IntegrityError("forced receipt write failure")

    monkeypatch.setattr(SimulatedOrderFillReceiptModel, "save", fail_receipt_save)

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert _ledger_counts(reservation_harness.account) == before
    position_after = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    assert position_after.quantity == prior_quantity
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )


def test_database_receipt_check_failure_rolls_back_and_connection_recovers(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real receipt INSERT constraint error rolls back the full ledger transaction."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(
        reservation_harness.account,
        market_value=Decimal("1000.00"),
    )
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        using="default",
    )
    before_counts = _ledger_counts(reservation_harness.account)
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    account_state_before = (
        account_before.current_cash,
        account_before.current_market_value,
        account_before.total_value,
        account_before.total_trades,
        account_before.winning_trades,
        account_before.last_trade_date,
    )
    position_before = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    position_state_before = (
        position_before.quantity,
        position_before.available_quantity,
        position_before.total_cost,
        position_before.market_value,
        position_before.current_price,
    )
    reservation_state_before = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
    )
    original_save = SimulatedOrderFillReceiptModel.save
    insert_attempts = 0
    database_integrity_errors: list[IntegrityError] = []

    def violate_receipt_sequence_check(
        self: SimulatedOrderFillReceiptModel,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Submit one invalid sequence value through the real ORM INSERT."""

        nonlocal insert_attempts
        if self.pk is None and insert_attempts == 0:
            self.fill_sequence = 0
            insert_attempts += 1
            try:
                original_save(self, *args, **kwargs)
            except IntegrityError as error:
                database_integrity_errors.append(error)
                raise
            raise AssertionError("database accepted fill_sequence=0")
        original_save(self, *args, **kwargs)

    monkeypatch.setattr(
        SimulatedOrderFillReceiptModel,
        "save",
        violate_receipt_sequence_check,
    )

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert insert_attempts == 1
    assert len(database_integrity_errors) == 1
    cause = database_integrity_errors[0].__cause__
    assert cause is not None
    diagnostic = getattr(cause, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if isinstance(constraint_name, str) and constraint_name:
        assert constraint_name == "simfill_sequence_positive_ck"
    else:
        assert "simfill_sequence_positive_ck" in str(cause)

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)

    assert _ledger_counts(reservation_harness.account) == before_counts
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert (
        account_after.current_cash,
        account_after.current_market_value,
        account_after.total_value,
        account_after.total_trades,
        account_after.winning_trades,
        account_after.last_trade_date,
    ) == account_state_before
    position_after = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    assert (
        position_after.quantity,
        position_after.available_quantity,
        position_after.total_cost,
        position_after.market_value,
        position_after.current_price,
    ) == position_state_before
    rows.reservation.refresh_from_db()
    assert (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
    ) == reservation_state_before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )


@pytest.mark.parametrize(
    "side",
    [SimulatedTradeSide.BUY, SimulatedTradeSide.SELL],
    ids=["buy", "sell"],
)
def test_partial_fill_then_cancel_releases_only_the_remaining_hold_once(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    side: SimulatedTradeSide,
) -> None:
    """Persist a partial BUY/SELL, then release only its remaining resources."""

    del persisted_receipt_schema
    if side is SimulatedTradeSide.BUY:
        _create_position(reservation_harness.account)
        _set_consistent_account_mark(
            reservation_harness.account,
            market_value=Decimal("1000.00"),
        )
    rows = _reader_rows(reservation_harness, side=side)
    if side is SimulatedTradeSide.SELL:
        _set_consistent_account_mark(
            reservation_harness.account,
            market_value=Decimal("1000.00"),
        )
    rows.reservation.refresh_from_db()
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        using="default",
    )
    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert result.replayed is False
    assert result.reservation.status.value == "active"

    rows.reservation.refresh_from_db()
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert rows.reservation.filled_quantity == Decimal("10.000000")
    held_cash_before_cancel = (
        rows.reservation.cash_reserved
        - rows.reservation.cash_consumed
        - rows.reservation.cash_released
    )
    held_shares_before_cancel = (
        rows.reservation.shares_reserved
        - rows.reservation.shares_consumed
        - rows.reservation.shares_released
    )
    assert held_cash_before_cancel >= Decimal("0.00")
    assert held_shares_before_cancel >= Decimal("0.000000")
    assert held_cash_before_cancel > Decimal("0.00") or held_shares_before_cancel > Decimal(
        "0.000000"
    )

    account_after_fill = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    account_state_after_fill = (
        account_after_fill.current_cash,
        account_after_fill.current_market_value,
        account_after_fill.total_value,
        account_after_fill.total_trades,
        account_after_fill.winning_trades,
    )
    position_after_fill = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    position_state_after_fill = (
        position_after_fill.quantity,
        position_after_fill.available_quantity,
        position_after_fill.total_cost,
        position_after_fill.market_value,
    )
    trade_id = SimulatedTradeModel.objects.get(account=reservation_harness.account).pk
    receipt_id = SimulatedOrderFillReceiptModel.objects.get(trade_id=trade_id).pk
    consumed_before_cancel = (
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
    )

    cancelled = reservation_harness.repository.cancel_order(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=rows.reservation.idempotency_key,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert cancelled.status.value == "cancelled"
    rows.reservation.refresh_from_db()
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert (
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
    ) == consumed_before_cancel[:3]
    assert rows.reservation.cash_released == consumed_before_cancel[3] + held_cash_before_cancel
    assert rows.reservation.shares_released == consumed_before_cancel[4] + held_shares_before_cancel
    assert (
        rows.reservation.cash_consumed + rows.reservation.cash_released
        == rows.reservation.cash_reserved
    )
    assert (
        rows.reservation.shares_consumed + rows.reservation.shares_released
        == rows.reservation.shares_reserved
    )

    terminal_state = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
        rows.reservation.cancelled_at,
    )
    repeated = reservation_harness.repository.cancel_order(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=rows.reservation.idempotency_key,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert repeated == cancelled
    rows.reservation.refresh_from_db()
    assert (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
        rows.reservation.cancelled_at,
    ) == terminal_state

    account_after_cancel = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert (
        account_after_cancel.current_cash,
        account_after_cancel.current_market_value,
        account_after_cancel.total_value,
        account_after_cancel.total_trades,
        account_after_cancel.winning_trades,
    ) == account_state_after_fill
    position_after_cancel = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    assert (
        position_after_cancel.quantity,
        position_after_cancel.available_quantity,
        position_after_cancel.total_cost,
        position_after_cancel.market_value,
    ) == position_state_after_fill
    assert SimulatedTradeModel.objects.filter(pk=trade_id).count() == 1
    assert SimulatedOrderFillReceiptModel.objects.filter(pk=receipt_id).count() == 1


def test_late_reservation_constraint_failure_rolls_back_written_fill_state(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real late reservation UPDATE check rolls back every earlier fill write."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(
        reservation_harness.account,
        market_value=Decimal("1000.00"),
    )
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        using="default",
    )
    before_counts = _ledger_counts(reservation_harness.account)
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    account_state_before = (
        account_before.current_cash,
        account_before.current_market_value,
        account_before.total_value,
        account_before.total_trades,
        account_before.winning_trades,
        account_before.last_trade_date,
    )
    position_before = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    position_state_before = (
        position_before.quantity,
        position_before.available_quantity,
        position_before.total_cost,
        position_before.market_value,
        position_before.current_price,
    )
    reservation_state_before = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
    )
    original_update = models.QuerySet.update
    reservation_update_attempts = 0
    observed_late_state: list[bool] = []
    database_integrity_errors: list[IntegrityError] = []

    def violate_late_reservation_check(self: Any, **values: Any) -> int:
        """Observe earlier transactional writes, then submit an invalid real UPDATE."""

        nonlocal reservation_update_attempts
        if self.model is SimulatedOrderReservationModel and {
            "filled_quantity",
            "cash_consumed",
            "updated_at",
        }.issubset(values):
            reservation_update_attempts += 1
            trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
            receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
            position_in_transaction = PositionModel.objects.get(pk=position_before.pk)
            account_in_transaction = SimulatedAccountModel.objects.get(
                pk=reservation_harness.account.pk
            )
            reservation_in_transaction = SimulatedOrderReservationModel.objects.get(
                pk=rows.reservation.pk
            )
            assert position_in_transaction.quantity == (
                position_before.quantity + rows.event.quantity
            )
            assert account_in_transaction.current_cash != account_before.current_cash
            assert account_in_transaction.total_trades == account_before.total_trades + 1
            assert reservation_in_transaction.status == reservation_state_before[0]
            assert reservation_in_transaction.filled_quantity == reservation_state_before[1]
            assert reservation_in_transaction.cash_consumed == reservation_state_before[2]
            assert receipt.trade_id == trade.pk
            observed_late_state.append(True)
            invalid_values = dict(values)
            invalid_values["cash_consumed"] = Decimal("-0.01")
            try:
                return original_update(self, **invalid_values)
            except IntegrityError as error:
                database_integrity_errors.append(error)
                raise
            raise AssertionError("database accepted negative cash_consumed")
        return original_update(self, **values)

    monkeypatch.setattr(models.QuerySet, "update", violate_late_reservation_check)

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert reservation_update_attempts == 1
    assert len(observed_late_state) == 1
    assert len(database_integrity_errors) == 1
    cause = database_integrity_errors[0].__cause__
    assert cause is not None
    diagnostic = getattr(cause, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if isinstance(constraint_name, str) and constraint_name:
        assert constraint_name == "simord_amounts_nonnegative_ck"
    else:
        assert "simord_amounts_nonnegative_ck" in str(cause)

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)

    assert _ledger_counts(reservation_harness.account) == before_counts
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert (
        account_after.current_cash,
        account_after.current_market_value,
        account_after.total_value,
        account_after.total_trades,
        account_after.winning_trades,
        account_after.last_trade_date,
    ) == account_state_before
    position_after = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    assert (
        position_after.quantity,
        position_after.available_quantity,
        position_after.total_cost,
        position_after.market_value,
        position_after.current_price,
    ) == position_state_before
    rows.reservation.refresh_from_db()
    assert (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
    ) == reservation_state_before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )


def test_unbound_reader_refuses_new_fill_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An unconfigured reader cannot turn a typed event into an authorized fill."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    before = _ledger_counts(reservation_harness.account)
    repository = DjangoSimulatedOrderFillRepository(event_reader=None, using="default")

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert _ledger_counts(reservation_harness.account) == before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0


def test_sell_reservation_that_exceeds_locked_sellable_balance_blocks(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A position change cannot make a reserved SELL consume unavailable shares."""

    del persisted_receipt_schema
    rows = _reader_rows(reservation_harness, side=SimulatedTradeSide.SELL)
    rows.reservation.refresh_from_db()
    PositionModel.objects.filter(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    ).update(available_quantity=Decimal("5.000000"))
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    before = _ledger_counts(reservation_harness.account)
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        using="default",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert _ledger_counts(reservation_harness.account) == before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0


def test_sell_partial_fee_deficit_cannot_spend_unreserved_account_cash(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A partial's minimum fee deficit stays blocked when G1 reserved no cash."""

    del persisted_receipt_schema
    rows = _reader_rows(reservation_harness, side=SimulatedTradeSide.SELL)
    rows.reservation.refresh_from_db()
    assert rows.reservation.cash_reserved == Decimal("0.00")
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    partial_event = replace(
        rows.event,
        source_event_id="row-reader-small-sell-fill",
        event_payload_hash="4" * 64,
        quantity=Decimal("0.010000"),
    )
    reader = _EventReader(partial_event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)
    prior_position = position.quantity

    with pytest.raises(SimulatedTradeExecutionBlocked) as captured:
        _invoke(repository, partial_event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert captured.value.code == "FILL_EXCEEDS_HELD_CASH"
    assert _ledger_counts(reservation_harness.account) == before
    position.refresh_from_db()
    assert position.quantity == prior_position
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )


@pytest.mark.parametrize(
    "side",
    [SimulatedTradeSide.BUY, SimulatedTradeSide.SELL],
    ids=["fractional-cash-buy", "fractional-share-sell"],
)
def test_decimal_partial_fill_then_cancel_preserves_exact_resource_conservation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    side: SimulatedTradeSide,
) -> None:
    """Real cent/six-place partial economics remain cancellable on every supported DB."""

    del persisted_receipt_schema
    if side is SimulatedTradeSide.BUY:
        _create_position(reservation_harness.account)
    rows = _reader_rows(reservation_harness, side=side)
    _set_consistent_account_mark(
        reservation_harness.account,
        market_value=Decimal("1000.00"),
    )
    rows.reservation.refresh_from_db()
    event = replace(
        rows.event,
        quantity=Decimal("10.010000"),
        event_payload_hash="5" * 64,
    )
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(event, []),
        using="default",
    )

    result = _invoke(
        repository,
        event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert result.replayed is False
    assert result.economics.quantity == Decimal("10.010000")
    assert result.reservation.status.value == "active"
    rows.reservation.refresh_from_db()
    assert rows.reservation.filled_quantity == Decimal("10.010000")
    assert rows.reservation.cash_consumed == result.reservation.cash_consumed
    assert rows.reservation.shares_consumed == result.reservation.shares_consumed

    account = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    account_after_fill = (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        account.total_trades,
        account.winning_trades,
    )
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=event.asset_code,
    )
    position_after_fill = (
        position.quantity,
        position.available_quantity,
        position.total_cost,
        position.market_value,
    )
    trade_ids = tuple(
        SimulatedTradeModel.objects.filter(account=reservation_harness.account)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    receipt_ids = tuple(
        SimulatedOrderFillReceiptModel.objects.filter(trade__account=reservation_harness.account)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    assert len(trade_ids) == 1
    assert len(receipt_ids) == 1

    cancelled = reservation_harness.repository.cancel_order(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        idempotency_key=rows.reservation.idempotency_key,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert cancelled.status.value == "cancelled"
    rows.reservation.refresh_from_db()
    assert rows.reservation.cash_consumed + rows.reservation.cash_released == (
        rows.reservation.cash_reserved
    )
    assert rows.reservation.shares_consumed + rows.reservation.shares_released == (
        rows.reservation.shares_reserved
    )
    assert rows.reservation.filled_quantity == Decimal("10.010000")

    account.refresh_from_db()
    assert (
        account.current_cash,
        account.current_market_value,
        account.total_value,
        account.total_trades,
        account.winning_trades,
    ) == account_after_fill
    position.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.total_cost,
        position.market_value,
    ) == position_after_fill
    assert (
        tuple(
            SimulatedTradeModel.objects.filter(account=reservation_harness.account)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        == trade_ids
    )
    assert (
        tuple(
            SimulatedOrderFillReceiptModel.objects.filter(
                trade__account=reservation_harness.account
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        == receipt_ids
    )


@pytest.mark.parametrize(
    "side",
    [SimulatedTradeSide.BUY, SimulatedTradeSide.SELL],
    ids=["two-fill-buy", "two-fill-sell"],
)
def test_two_persisted_fills_validate_fee_prefix_and_replay_first_event_read_only(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    side: SimulatedTradeSide,
) -> None:
    """Persist two linked FeeV2 fills and release only the terminal unused hold."""

    del persisted_receipt_schema
    if side is SimulatedTradeSide.BUY:
        _create_position(reservation_harness.account)
        _set_consistent_account_mark(
            reservation_harness.account,
            market_value=Decimal("1000.00"),
        )
    rows = _reader_rows(reservation_harness, side=side)
    if side is SimulatedTradeSide.SELL:
        _set_consistent_account_mark(
            reservation_harness.account,
            market_value=Decimal("1000.00"),
        )
    rows.reservation.refresh_from_db()
    cash_before_fills = SimulatedAccountModel.objects.get(
        pk=reservation_harness.account.pk
    ).current_cash

    first_event = replace(
        rows.event,
        quantity=Decimal("10.010000"),
        event_payload_hash="5" * 64,
    )
    reader = _EventReader(first_event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    first_result = _invoke(
        repository,
        first_event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert first_result.replayed is False
    assert first_result.reservation.status.value == "active"

    rows.reservation.refresh_from_db()
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert rows.reservation.filled_quantity == Decimal("10.010000")
    assert rows.reservation.cash_released == Decimal("0.00")
    assert rows.reservation.shares_released == Decimal("0.000000")
    assert rows.reservation.cancelled_at is None

    second_at = first_event.occurred_at + timedelta(seconds=30)
    second_event = replace(
        first_event,
        source_event_id="row-reader-event-0002",
        event_kind=LocalSimulatedFillEventKind.FINAL_FILL,
        quantity=Decimal("20.020000"),
        event_payload_hash="6" * 64,
        source_snapshot_id="row-reader-source-snapshot-002",
        source_snapshot_hash="7" * 64,
        occurred_at=second_at,
        source_observed_at=second_at,
        source_available_at=second_at,
        recorded_at=second_at,
    )
    second_proof = build_order_fill_settlement_proof(
        calendar_evidence=rows.proof.calendar_evidence,
        calendar_read_cutoff=_READ_CUTOFF,
        fill_occurred_at=second_at,
        settlement_exchange=rows.proof.settlement_exchange,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )
    reader.event = second_event
    second_result = _invoke(
        repository,
        second_event,
        second_proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    assert second_result.replayed is False
    assert second_result.reservation.status.value == "cancelled"
    assert second_result.reservation.filled_quantity == Decimal("30.030000")
    rows.reservation.refresh_from_db()
    assert len(reader.calls) == 2
    assert tuple(call[1] for call in reader.calls) == (
        first_event.source_event_id,
        second_event.source_event_id,
    )

    receipt_rows = tuple(
        SimulatedOrderFillReceiptModel.objects.filter(reservation=rows.reservation)
        .select_related("trade")
        .order_by("fill_sequence", "pk")
    )
    assert len(receipt_rows) == 2
    decoded_rows = tuple(
        read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=receipt,
            trade_row=receipt.trade,
        )
        for receipt in receipt_rows
    )
    assert tuple(decoded.fill_sequence for decoded in decoded_rows) == (1, 2)
    first_economics = decoded_rows[0].economics
    second_economics = decoded_rows[1].economics
    assert decoded_rows[0].event.source_event_id == first_event.source_event_id
    assert decoded_rows[1].event.source_event_id == second_event.source_event_id
    assert first_economics.close_order is False
    assert second_economics.close_order is True
    assert first_economics.prior.fill_count == 0
    assert first_economics.prior.cumulative_quantity == Decimal("0.000000")
    assert second_economics.prior == first_economics.cumulative_state
    assert second_economics.cumulative_state.fill_count == 2
    assert second_economics.cumulative_state.cumulative_quantity == Decimal("30.030000")
    assert second_economics.cumulative_state.cumulative_gross == Decimal("300.30")
    assert first_economics.gross_amount == Decimal("100.10")
    assert second_economics.gross_amount == Decimal("200.20")

    fee_components = ("commission", "transfer_fee", "stamp_duty", "slippage", "total_fee")
    for component in fee_components:
        first_cumulative = getattr(first_economics.cumulative_state.cumulative_fees, component)
        first_incremental = getattr(first_economics.incremental_fees, component)
        second_cumulative = getattr(second_economics.cumulative_state.cumulative_fees, component)
        second_incremental = getattr(second_economics.incremental_fees, component)
        second_prior = getattr(second_economics.prior.cumulative_fees, component)
        assert first_cumulative == first_incremental
        assert second_prior == first_cumulative
        assert second_incremental == second_cumulative - second_prior

    rows.reservation.refresh_from_db()
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
    assert rows.reservation.filled_quantity == Decimal("30.030000")
    assert rows.reservation.cancelled_at is not None
    assert rows.reservation.cancelled_at >= rows.reservation.reserved_at
    assert (
        rows.reservation.cash_consumed + rows.reservation.cash_released
        == rows.reservation.cash_reserved
    )
    assert (
        rows.reservation.shares_consumed + rows.reservation.shares_released
        == rows.reservation.shares_reserved
    )
    assert rows.reservation.cash_released == (
        rows.reservation.cash_reserved - rows.reservation.cash_consumed
    )
    assert rows.reservation.shares_released == (
        rows.reservation.shares_reserved - rows.reservation.shares_consumed
    )
    if side is SimulatedTradeSide.BUY:
        expected_cash_consumed = (
            first_economics.gross_amount
            + first_economics.incremental_fees.total_fee
            + second_economics.gross_amount
            + second_economics.incremental_fees.total_fee
        )
        assert rows.reservation.cash_consumed == expected_cash_consumed
        assert rows.reservation.shares_consumed == Decimal("0.000000")
        assert rows.reservation.shares_released == rows.reservation.shares_reserved
    else:
        expected_proceeds = (
            first_economics.gross_amount
            - first_economics.incremental_fees.total_fee
            + second_economics.gross_amount
            - second_economics.incremental_fees.total_fee
        )
        assert rows.reservation.shares_consumed == Decimal("30.030000")
        assert rows.reservation.shares_released == (
            rows.reservation.shares_reserved - Decimal("30.030000")
        )

    account_after_final = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    if side is SimulatedTradeSide.BUY:
        assert cash_before_fills - account_after_final.current_cash == expected_cash_consumed
        expected_position_quantity = Decimal("130.030000")
        expected_available_quantity = Decimal("100.000000")
    else:
        assert account_after_final.current_cash - cash_before_fills == expected_proceeds
        expected_position_quantity = Decimal("69.970000")
        expected_available_quantity = Decimal("69.970000")
    assert account_after_final.total_trades == 2
    position_after_final = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=first_event.asset_code,
    )
    assert position_after_final.quantity == expected_position_quantity
    assert position_after_final.available_quantity == expected_available_quantity

    reservation_state_after_final = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
        rows.reservation.updated_at,
    )
    account_state_after_final = (
        account_after_final.current_cash,
        account_after_final.current_market_value,
        account_after_final.total_value,
        account_after_final.total_trades,
        account_after_final.winning_trades,
    )
    position_state_after_final = (
        position_after_final.quantity,
        position_after_final.available_quantity,
        position_after_final.total_cost,
        position_after_final.market_value,
    )
    ledger_counts_after_final = _ledger_counts(reservation_harness.account)
    first_trade_id = first_result.trade_id
    reader.calls.clear()

    class _NoClock:
        """Fail if an exact earlier receipt replay asks for a new clock value."""

        def now(self) -> datetime:
            """Reject any clock access on the replay path."""

            raise AssertionError("exact first-event replay must not read the clock")

    replayed = repository.apply_fill_event(
        event=first_event,
        expected_event_payload_hash=first_event.event_payload_hash,
        settlement_proof=rows.proof,
        clock=_NoClock(),
    )
    assert replayed.replayed is True
    assert replayed.trade_id == first_trade_id
    assert replayed.economics == first_result.economics
    assert replayed.reservation == second_result.reservation
    assert reader.calls == []
    rows.reservation.refresh_from_db()
    account_after_replay = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    position_after_replay = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=first_event.asset_code,
    )
    assert (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.shares_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_released,
        rows.reservation.updated_at,
    ) == reservation_state_after_final
    assert (
        account_after_replay.current_cash,
        account_after_replay.current_market_value,
        account_after_replay.total_value,
        account_after_replay.total_trades,
        account_after_replay.winning_trades,
    ) == account_state_after_final
    assert (
        position_after_replay.quantity,
        position_after_replay.available_quantity,
        position_after_replay.total_cost,
        position_after_replay.market_value,
    ) == position_state_after_final
    assert _ledger_counts(reservation_harness.account) == ledger_counts_after_final


def test_application_exact_replay_rejects_later_corruption_and_skips_live_readers(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Application replay validates the full stored chain before returning an old fill."""

    del persisted_receipt_schema
    state = _persist_two_active_fills(reservation_harness)
    use_case = ApplySimulatedOrderFillUseCase(
        repository=state.repository,
        clock=_NoClock(),
        source_binding=None,
        settlement_resolver=None,
    )
    command = ApplySimulatedOrderFillCommand(
        account_id=state.first_event.account_id,
        user_id=state.first_event.user_id,
        order_idempotency_key=state.first_event.order_idempotency_key,
        source_namespace=state.first_event.source_namespace,
        fill_event_id=state.first_event.source_event_id,
        expected_event_payload_hash=state.first_event.event_payload_hash,
    )

    valid_replay = use_case.execute(command)
    assert valid_replay.replayed is True
    assert valid_replay.trade_id == state.first_result.trade_id
    assert valid_replay.reservation == state.second_result.reservation
    assert state.reader.calls == []

    second_receipt = SimulatedOrderFillReceiptModel.objects.get(
        reservation=state.rows.reservation,
        source_namespace=state.second_event.source_namespace,
        source_event_id=state.second_event.source_event_id,
    )
    assert second_receipt.trade_id == state.second_result.trade_id
    changed = SimulatedTradeModel.objects.filter(pk=second_receipt.trade_id).update(
        price=Decimal("9.9900")
    )
    assert changed == 1
    ledger_before_replay = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        use_case.execute(command)

    assert state.reader.calls == []
    assert _ledger_counts(reservation_harness.account) == ledger_before_replay


def test_application_exact_replay_does_not_disclose_another_users_fill(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An exact receipt locator remains scoped to the owning simulated account."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    first_result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )
    reader.calls.clear()
    use_case = ApplySimulatedOrderFillUseCase(
        repository=repository,
        clock=_NoClock(),
        source_binding=None,
        settlement_resolver=None,
    )
    wrong_owner_command = ApplySimulatedOrderFillCommand(
        account_id=rows.event.account_id,
        user_id=rows.event.user_id + 1,
        order_idempotency_key=rows.event.order_idempotency_key,
        source_namespace=rows.event.source_namespace,
        fill_event_id=rows.event.source_event_id,
        expected_event_payload_hash=rows.event.event_payload_hash,
    )

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        use_case.execute(wrong_owner_command)

    assert first_result.trade_id > 0
    assert reader.calls == []


def test_writer_accepts_source_exchange_distinct_from_rule_market(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A validated identity may map the SH rule market to its distinct source exchange."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    source_harness = _harness_with_source_exchange(reservation_harness, "SSE")
    rows = _reader_rows(source_harness)
    assert rows.proof.settlement_exchange == "SSE"
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")

    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
    assert result.replayed is False
    assert len(reader.calls) == 1
    assert trade.settlement_market == "SH"
    assert trade.settlement_exchange == "SSE"


@pytest.mark.parametrize("identity_state", ["missing", "exchange-mismatch"])
def test_writer_blocks_unknown_or_calendar_mismatched_identity_before_source_read(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    identity_state: str,
) -> None:
    """A self-sealed calendar cannot replace missing or different identity evidence."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(_harness_with_source_exchange(reservation_harness, "SSE"))
    reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    snapshot = validated_plan_snapshot(reservation)
    if identity_state == "missing":
        snapshot["identity_evidence"] = None
    else:
        identity = cast(dict[str, object], snapshot["identity_evidence"])
        identity["source_exchange"] = "SZSE"
    resealed_hash = _reseal_reservation_plan(reservation, snapshot)
    event = replace(rows.event, plan_snapshot_hash=resealed_hash)
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _invoke(repository, event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert blocked.value.code == "SIMULATED_FILL_PLAN_INVALID"
    assert reader.calls == []
    assert _ledger_counts(reservation_harness.account) == before


@pytest.mark.parametrize(
    "corruption",
    ["bundle-hash", "policy-hash", "policy-bound-rule", "bundle-source-clock"],
)
def test_writer_blocks_resealed_plan_metadata_and_nested_rule_corruption(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    corruption: str,
) -> None:
    """Re-sealing outer and nested JSON hashes cannot detach plan metadata from Domain terms."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    reservation = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    snapshot = validated_plan_snapshot(reservation)
    if corruption == "bundle-hash":
        snapshot["settlement_bundle_hash"] = "f" * 64
    elif corruption == "policy-hash":
        snapshot["settlement_policy_hash"] = "f" * 64
    elif corruption == "policy-bound-rule":
        bundle = cast(dict[str, object], snapshot["execution_bundle"])
        policy = cast(dict[str, object], bundle["settlement_policy_v1"])
        policy["bound_execution_rule_v2_hash"] = "f" * 64
        policy_hash = _domain_content_hash(policy)
        policy["content_hash"] = policy_hash
        bundle_hash = _domain_content_hash(bundle)
        bundle["content_hash"] = bundle_hash
        snapshot["settlement_policy_hash"] = policy_hash
        snapshot["settlement_bundle_hash"] = bundle_hash
    else:
        snapshot["bundle_source_observed_at"] = "2025-01-01T00:00:00Z"
    resealed_hash = _reseal_reservation_plan(reservation, snapshot)
    event = replace(rows.event, plan_snapshot_hash=resealed_hash)
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _invoke(repository, event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert blocked.value.code == "SIMULATED_FILL_PLAN_INVALID"
    assert reader.calls == []
    assert _ledger_counts(reservation_harness.account) == before


def test_writer_accepts_current_reference_v3_plan_with_restricted_nested_v1_source(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Persist a V3 fill without rewriting its restricted nested V1 source facts."""

    del persisted_receipt_schema
    position = _create_position(reservation_harness.account)
    position.cost_basis_known = False
    position.save(update_fields=["cost_basis_known"])
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))

    intent = _intent_for(reservation_harness, key="writer-current-v3-restricted-source")
    execution_repository = DjangoSimulatedTradeExecutionRepository(using="default")
    plan, bundle, identity_evidence = _current_v3_plan(
        repository=execution_repository,
        intent=intent,
        as_of=AS_OF,
        source_exchange="SSE",
    )
    source_evidence = identity_evidence.source_evidence
    assert source_evidence.source_observed_at is None
    assert source_evidence.source_available_at is None
    assert source_evidence.must_not_use_for_decision is True
    assert source_evidence.must_not_execute is True

    reservation_harness.repository.reserve_order(
        plan=plan,
        execution_bundle=bundle,
        fee_budget=Decimal("20.00"),
        clock=_Clock(AS_OF),
    )
    reservation = SimulatedOrderReservationModel.objects.get(
        account=reservation_harness.account,
        idempotency_key=intent.idempotency_key,
    )
    snapshot_before = validated_plan_snapshot(reservation)
    plan_hash_before = reservation.plan_snapshot_hash
    identity_snapshot = cast(dict[str, object], snapshot_before["identity_evidence"])
    nested_source = cast(dict[str, object], identity_snapshot["source_evidence"])
    assert nested_source["source_observed_at"] is None
    assert nested_source["source_available_at"] is None
    assert nested_source["must_not_use_for_decision"] is True
    assert nested_source["must_not_execute"] is True

    occurred_at = AS_OF + timedelta(minutes=1)
    proof = build_order_fill_settlement_proof(
        calendar_evidence=plan.calendar_evidence,
        calendar_read_cutoff=_READ_CUTOFF,
        fill_occurred_at=occurred_at,
        settlement_exchange=source_evidence.source_exchange,
        settlement_lag_sessions=plan.settlement_lag_sessions,
    )
    event = LocalSimulatedFillEventV1(
        source_namespace="writer-v3-local-matcher",
        source_version="event-schema-v1",
        source_event_id="writer-v3-event-0001",
        event_payload_hash="a" * 64,
        source_snapshot_id="writer-v3-source-snapshot-001",
        source_snapshot_hash="b" * 64,
        reservation_id=cast(int, reservation.pk),
        account_id=cast(int, reservation.account_id),
        user_id=cast(int, reservation.owner_user_id),
        order_idempotency_key=reservation.idempotency_key,
        intent_payload_hash=reservation.intent_payload_hash,
        reservation_request_hash=reservation.reservation_request_hash,
        plan_snapshot_hash=reservation.plan_snapshot_hash,
        security_id=reservation.security_id,
        asset_code=reservation.asset_code,
        side=SimulatedTradeSide(reservation.side),
        event_kind=LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        occurred_at=occurred_at,
        source_observed_at=occurred_at,
        source_available_at=occurred_at,
        recorded_at=occurred_at,
    )
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")

    result = _invoke(repository, event, proof, clock=_FixedClock(_READ_CUTOFF))

    reservation.refresh_from_db()
    trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
    assert result.replayed is False
    assert reader.calls == [(event.source_namespace, event.source_event_id, _READ_CUTOFF)]
    assert reservation.filled_quantity == Decimal("10.000000")
    assert trade.quantity == Decimal("10.000000")
    assert receipt.fill_sequence == 1
    assert receipt.receipt_hash == trade.request_payload_hash
    assert reservation.plan_snapshot_hash == plan_hash_before
    assert validated_plan_snapshot(reservation) == snapshot_before
    assert trade.settlement_market == "SH"
    assert trade.settlement_exchange == "SSE"
    assert trade.settlement_plan_binding_version == 4


def test_sqlite_precision_guard_rejects_unsupported_event_before_any_write(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """SQLite blocks an out-of-envelope event before source read or ledger writes."""

    del persisted_receipt_schema
    _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    event = replace(rows.event, quantity=Decimal("1000000000.000001"))
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)
    reservation_before = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_consumed,
        rows.reservation.shares_released,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _invoke(repository, event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert _ledger_counts(reservation_harness.account) == before
    rows.reservation.refresh_from_db()
    assert (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.cash_released,
        rows.reservation.shares_consumed,
        rows.reservation.shares_released,
    ) == reservation_before
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    if connection.vendor == "sqlite":
        assert blocked.value.code == "ORDER_RESERVATION_STORAGE_PRECISION_UNSUPPORTED"
        assert reader.calls == []
    else:
        assert connection.vendor == "postgresql"
        assert blocked.value.code != "ORDER_RESERVATION_STORAGE_PRECISION_UNSUPPORTED"
        assert len(reader.calls) == 1


def test_sqlite_precision_guard_checks_existing_position_and_preserves_postgresql_range(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A stored position above SQLite's share envelope remains valid on PostgreSQL."""

    del persisted_receipt_schema
    position = _create_position(reservation_harness.account)
    _set_consistent_account_mark(reservation_harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    position.quantity = Decimal("1000000000.000001")
    position.available_quantity = Decimal("1000000000.000001")
    position.avg_cost = Decimal("1.0000")
    position.total_cost = Decimal("1000000000.00")
    position.current_price = Decimal("1.0000")
    position.market_value = Decimal("1000000000.00")
    position.unrealized_pnl = Decimal("0.00")
    position.unrealized_pnl_pct = 0.0
    position.save(
        update_fields=[
            "quantity",
            "available_quantity",
            "avg_cost",
            "total_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
        ]
    )
    _set_consistent_account_mark(
        reservation_harness.account,
        market_value=Decimal("1000000000.00"),
    )
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    position.refresh_from_db()
    persisted_quantity_before = position.quantity
    before = _ledger_counts(reservation_harness.account)

    if connection.vendor == "sqlite":
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
        assert blocked.value.code == "ORDER_RESERVATION_STATE_INVALID"
        assert reader.calls == []
        assert _ledger_counts(reservation_harness.account) == before
        position.refresh_from_db()
        assert persisted_quantity_before >= Decimal("1000000000.000000")
        assert position.quantity == persisted_quantity_before
    else:
        assert connection.vendor == "postgresql"
        assert persisted_quantity_before == Decimal("1000000000.000001")
        result = _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
        assert result.replayed is False
        assert len(reader.calls) == 1
        position.refresh_from_db()
        assert position.quantity == Decimal("1000000010.000001")


def test_sqlite_precision_guard_rejects_post_fill_overflow_before_first_write(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """SQLite rejects a prospective quantity overflow while PostgreSQL keeps Domain range."""

    del persisted_receipt_schema
    position = _create_position(reservation_harness.account)
    position.quantity = Decimal("999999999.999999")
    position.available_quantity = Decimal("999999999.999999")
    position.avg_cost = Decimal("1.0000")
    position.total_cost = Decimal("1000000000.00")
    position.current_price = Decimal("1.0000")
    position.market_value = Decimal("1000000000.00")
    position.unrealized_pnl = Decimal("0.00")
    position.unrealized_pnl_pct = 0.0
    position.save(
        update_fields=[
            "quantity",
            "available_quantity",
            "avg_cost",
            "total_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
        ]
    )
    _set_consistent_account_mark(
        reservation_harness.account,
        market_value=Decimal("1000000000.00"),
    )
    rows = _reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")
    before = _ledger_counts(reservation_harness.account)
    reservation_before = (
        rows.reservation.status,
        rows.reservation.filled_quantity,
        rows.reservation.cash_consumed,
        rows.reservation.cash_released,
    )

    if connection.vendor == "sqlite":
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
        assert blocked.value.code == "ORDER_RESERVATION_STORAGE_PRECISION_UNSUPPORTED"
        assert len(reader.calls) == 1
        assert _ledger_counts(reservation_harness.account) == before
        rows.reservation.refresh_from_db()
        assert (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.cash_released,
        ) == reservation_before
        position.refresh_from_db()
        assert position.quantity == Decimal("999999999.999999")
    else:
        assert connection.vendor == "postgresql"
        result = _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
        assert result.replayed is False
        assert len(reader.calls) == 1
        position.refresh_from_db()
        assert position.quantity == Decimal("1000000009.999999")


def test_sqlite_precision_guard_rejects_unsupported_persisted_trade_on_replay(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Exact replay rejects an out-of-envelope stored Trade before returning a receipt."""

    del persisted_receipt_schema
    state = _persist_two_active_fills(reservation_harness)
    second_receipt = SimulatedOrderFillReceiptModel.objects.get(
        reservation=state.rows.reservation,
        source_namespace=state.second_event.source_namespace,
        source_event_id=state.second_event.source_event_id,
    )
    changed = SimulatedTradeModel.objects.filter(pk=second_receipt.trade_id).update(
        quantity=Decimal("1000000000.000001")
    )
    assert changed == 1
    damaged_quantity = SimulatedTradeModel.objects.get(pk=second_receipt.trade_id).quantity
    before = _ledger_counts(reservation_harness.account)
    use_case = ApplySimulatedOrderFillUseCase(
        repository=state.repository,
        clock=_NoClock(),
        source_binding=None,
        settlement_resolver=None,
    )
    command = ApplySimulatedOrderFillCommand(
        account_id=state.first_event.account_id,
        user_id=state.first_event.user_id,
        order_idempotency_key=state.first_event.order_idempotency_key,
        source_namespace=state.first_event.source_namespace,
        fill_event_id=state.first_event.source_event_id,
        expected_event_payload_hash=state.first_event.event_payload_hash,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(command)

    assert _ledger_counts(reservation_harness.account) == before
    assert state.reader.calls == []
    assert SimulatedTradeModel.objects.get(pk=second_receipt.trade_id).quantity == damaged_quantity
    if connection.vendor == "sqlite":
        assert blocked.value.code == "ORDER_RESERVATION_STATE_INVALID"
    else:
        assert connection.vendor == "postgresql"
        assert blocked.value.code != "ORDER_RESERVATION_STORAGE_PRECISION_UNSUPPORTED"


def test_sqlite_precision_guard_preserves_signed_loss_pnl_for_sell_fill(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A valid signed sell loss survives storage-cap checks and exact replay."""

    del persisted_receipt_schema
    rows = _reader_rows(reservation_harness, side=SimulatedTradeSide.SELL)
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    position.cost_basis_known = True
    position.avg_cost = Decimal("11.0000")
    position.total_cost = Decimal("1100.00")
    position.current_price = Decimal("10.0000")
    position.market_value = Decimal("1000.00")
    position.unrealized_pnl = Decimal("-100.00")
    position.unrealized_pnl_pct = -9.090909090909092
    position.save(
        update_fields=[
            "cost_basis_known",
            "avg_cost",
            "total_cost",
            "current_price",
            "market_value",
            "unrealized_pnl",
            "unrealized_pnl_pct",
        ]
    )
    _set_consistent_account_mark(
        reservation_harness.account,
        market_value=Decimal("1000.00"),
    )
    rows.reservation.refresh_from_db()
    reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")

    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert result.replayed is False
    assert trade.realized_pnl is not None
    assert trade.realized_pnl == (trade.amount - trade.total_cost - Decimal("110.00"))
    assert trade.realized_pnl < Decimal("0.00")
    position.refresh_from_db()
    assert position.total_cost == Decimal("990.00")
    assert position.market_value == Decimal("900.00")
    assert position.unrealized_pnl == Decimal("-90.00")
    expected_first_read = (
        rows.event.source_namespace,
        rows.event.source_event_id,
        _READ_CUTOFF,
    )
    assert reader.calls == [expected_first_read]
    reader.calls.clear()

    use_case = ApplySimulatedOrderFillUseCase(
        repository=repository,
        clock=_NoClock(),
        source_binding=None,
        settlement_resolver=None,
    )
    command = ApplySimulatedOrderFillCommand(
        account_id=rows.event.account_id,
        user_id=rows.event.user_id,
        order_idempotency_key=rows.event.order_idempotency_key,
        source_namespace=rows.event.source_namespace,
        fill_event_id=rows.event.source_event_id,
        expected_event_payload_hash=rows.event.event_payload_hash,
    )
    replay = use_case.execute(command)

    trade.refresh_from_db()
    assert replay.replayed is True
    assert replay.trade_id == trade.pk
    assert trade.realized_pnl == (trade.amount - trade.total_cost - Decimal("110.00"))
    assert trade.realized_pnl < Decimal("0.00")
    assert reader.calls == []


def test_cancel_blocks_and_preserves_state_when_second_fill_receipt_is_corrupt(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A broken later receipt cannot make cancellation release a valid-looking hold."""

    del persisted_receipt_schema
    fills = _persist_two_active_fills(reservation_harness)
    reservation = fills.rows.reservation
    reservation.refresh_from_db()
    receipts = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=reservation.pk).order_by(
            "fill_sequence", "pk"
        )
    )
    assert len(receipts) == 2
    assert tuple(receipt.source_event_id for receipt in receipts) == (
        fills.first_event.source_event_id,
        fills.second_event.source_event_id,
    )
    second_receipt = receipts[1]
    replacement_hash = "0" * 64
    if second_receipt.receipt_hash == replacement_hash:
        replacement_hash = "1" * 64
    # Deliberately bypass the append-only application surface. The replacement
    # keeps the DB's 64-lowercase-hex shape valid and corrupts only its seal.
    changed = models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=second_receipt.pk),
        receipt_hash=replacement_hash,
    )
    assert changed == 1

    account_before = (
        SimulatedAccountModel.objects.filter(pk=reservation_harness.account.pk).values().get()
    )
    positions_before = tuple(
        PositionModel.objects.filter(account_id=reservation_harness.account.pk)
        .order_by("pk")
        .values()
    )
    trades_before = tuple(
        SimulatedTradeModel.objects.filter(account_id=reservation_harness.account.pk)
        .order_by("pk")
        .values()
    )
    receipts_before = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=reservation.pk)
        .order_by("fill_sequence", "pk")
        .values()
    )
    reservation_before = (
        SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).values().get()
    )
    assert len(positions_before) == 1
    assert len(trades_before) == 2
    assert len(receipts_before) == 2
    assert receipts_before[1]["receipt_hash"] == replacement_hash
    assert reservation_before["status"] == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert reservation_before["filled_quantity"] == fills.second_result.reservation.filled_quantity
    assert reservation_before["cash_consumed"] == fills.second_result.reservation.cash_consumed
    assert reservation_before["shares_consumed"] == fills.second_result.reservation.shares_consumed

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        reservation_harness.repository.cancel_order(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            idempotency_key=reservation.idempotency_key,
            clock=_FixedClock(_READ_CUTOFF),
        )

    assert raised.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)

    assert (
        SimulatedAccountModel.objects.filter(pk=reservation_harness.account.pk).values().get()
        == account_before
    )
    assert (
        tuple(
            PositionModel.objects.filter(account_id=reservation_harness.account.pk)
            .order_by("pk")
            .values()
        )
        == positions_before
    )
    assert (
        tuple(
            SimulatedTradeModel.objects.filter(account_id=reservation_harness.account.pk)
            .order_by("pk")
            .values()
        )
        == trades_before
    )
    assert (
        tuple(
            SimulatedOrderFillReceiptModel._base_manager.filter(reservation_id=reservation.pk)
            .order_by("fill_sequence", "pk")
            .values()
        )
        == receipts_before
    )
    assert (
        SimulatedOrderReservationModel.objects.filter(pk=reservation.pk).values().get()
        == reservation_before
    )


def test_first_buy_without_position_creates_marked_v2_position_and_proof_driven_pending(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A first BUY uses an independent apply-time mark and the sealed calendar proof."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    cash_before = account_before.current_cash
    mark = _initial_position_mark(rows)
    mark_reader = _InitialPositionMarkReader(mark, [])
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )

    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=rows.event.asset_code,
    )
    reservation_after = SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk)
    trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    fill_cost = rows.economics.gross_amount + rows.economics.incremental_fees.total_fee
    expected_market_value = rows.event.quantity * mark.price
    expected_available = (
        rows.event.quantity
        if rows.proof.expected_release_session == rows.proof.fill_market_session
        else Decimal("0.000000")
    )
    expected_status = (
        "released"
        if rows.proof.expected_release_session == rows.proof.fill_market_session
        else "pending"
    )

    assert result.replayed is False
    assert len(event_reader.calls) == 1
    assert mark_reader.calls == [
        (
            rows.event.security_id,
            rows.event.asset_code,
            rows.reservation.asset_type,
            rows.reservation.market,
            rows.reservation.board,
            _READ_CUTOFF,
        )
    ]
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 1
    assert position.quantity == rows.event.quantity
    assert position.available_quantity == expected_available
    assert position.available_quantity_known is True
    assert position.current_price == mark.price
    assert position.current_price != rows.event.price
    assert position.market_value == expected_market_value
    assert position.total_cost == fill_cost
    with localcontext() as context:
        context.prec = 80
        expected_avg_cost = (fill_cost / rows.event.quantity).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_EVEN,
        )
    assert position.avg_cost == expected_avg_cost
    assert position.unrealized_pnl == expected_market_value - fill_cost
    assert position.cost_basis_known is True
    assert position.valuation_known is True
    assert position.first_buy_date == rows.proof.fill_market_session
    assert trade.amount == rows.economics.gross_amount
    assert trade.total_cost == fill_cost
    assert trade.commission == rows.economics.incremental_fees.commission
    assert trade.transfer_fee == rows.economics.incremental_fees.transfer_fee
    assert trade.stamp_duty == rows.economics.incremental_fees.stamp_duty
    assert trade.slippage == rows.economics.incremental_fees.slippage
    assert trade.settlement_status == expected_status
    assert trade.settlement_release_date == rows.proof.expected_release_session
    assert account_after.current_cash == cash_before - fill_cost
    assert account_after.current_market_value == expected_market_value
    assert account_after.total_value == account_after.current_cash + expected_market_value
    assert account_after.cash_known is True
    assert account_after.cash_reconciliation_status == "simulated_ledger"
    assert receipt.receipt_version == 2
    assert reservation_after.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert reservation_after.filled_quantity == rows.event.quantity
    assert reservation_after.cash_consumed == fill_cost
    assert reservation_after.shares_consumed == Decimal("0.000000")
    assert reservation_after.cash_released == Decimal("0.00")
    assert reservation_after.shares_released == Decimal("0.000000")
    assert type(receipt.initial_position_mark_evidence) is dict
    mark_payload = cast(dict[str, object], receipt.initial_position_mark_evidence)
    assert mark_payload["source_available_at"] is None
    decoded_mark = decode_initial_position_mark_evidence(
        json.dumps(
            mark_payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    assert decoded_mark == mark
    decoded_row = read_order_reservation_fill_row(
        reservation_row=SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk),
        receipt_row=receipt,
        trade_row=trade,
    )
    assert decoded_row.receipt_hash == receipt.receipt_hash
    assert trade.request_payload_hash == receipt.receipt_hash


def test_first_buy_without_position_releases_under_explicit_zero_lag_policy(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An explicit zero-session policy releases a first BUY on its proved session."""

    del persisted_receipt_schema
    harness = _harness_with_settlement_lag(reservation_harness, lag_sessions=0)
    rows = _first_buy_rows(harness)
    assert rows.proof.settlement_lag_sessions == 0
    assert rows.proof.expected_release_session == rows.proof.fill_market_session
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )

    result = _invoke(
        repository,
        rows.event,
        rows.proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    position = PositionModel.objects.get(
        account=harness.account,
        asset_code=rows.event.asset_code,
    )
    trade = SimulatedTradeModel.objects.get(account=harness.account)
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
    assert result.replayed is False
    assert position.quantity == rows.event.quantity
    assert position.available_quantity == rows.event.quantity
    assert position.available_quantity_known is True
    assert trade.settlement_status == "released"
    assert trade.settlement_release_date == rows.proof.expected_release_session
    assert receipt.receipt_version == 2
    assert len(mark_reader.calls) == 1
    decoded_row = read_order_reservation_fill_row(
        reservation_row=SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk),
        receipt_row=receipt,
        trade_row=trade,
    )
    assert decoded_row.receipt_hash == receipt.receipt_hash


def test_first_buy_without_mark_reader_blocks_without_any_ledger_mutation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A missing first-position mark port cannot fall back to the fill price."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        initial_position_mark_reader=None,
        using="default",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
    _reservation_unfilled(rows.reservation)


def test_first_buy_without_published_mark_result_blocks_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A configured mark reader returning no evidence remains unavailable."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)
    mark_reader = _InitialPositionMarkReader(None, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        initial_position_mark_reader=mark_reader,
        using="default",
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert len(mark_reader.calls) == 1
    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
    _reservation_unfilled(rows.reservation)


def test_first_buy_rejects_mark_bound_to_another_instrument_field(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A plausible mark for any different identity field cannot seed this Position."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    mark = _initial_position_mark(rows)
    wrong_values = {
        "security_id": "SH.OTHER.SECURITY",
        "asset_code": "000001.SZ",
        "asset_type": "fund",
        "market": "OTHER_MARKET",
        "board": "OTHER_BOARD",
    }
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)

    for identity_field, wrong_value in wrong_values.items():
        wrong_mark = replace(mark, **{identity_field: wrong_value})
        mark_reader = _InitialPositionMarkReader(wrong_mark, [])
        repository = DjangoSimulatedOrderFillRepository(
            event_reader=_EventReader(rows.event, []),
            initial_position_mark_reader=mark_reader,
            using="default",
        )

        with pytest.raises(SimulatedTradeExecutionBlocked):
            _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

        assert len(mark_reader.calls) == 1
        assert _ledger_counts(reservation_harness.account) == counts_before
        assert _account_financial_state(reservation_harness.account) == account_before
        assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
        _reservation_unfilled(rows.reservation)


def test_first_buy_rejects_expired_mark_even_if_its_reader_returns_typed_proof(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The writer revalidates a typed proof at the exact locked read cutoff."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    expired_mark = _initial_position_mark(rows)
    object.__setattr__(expired_mark, "valid_until", _READ_CUTOFF)
    mark_reader = _InitialPositionMarkReader(expired_mark, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert len(mark_reader.calls) == 1
    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
    _reservation_unfilled(rows.reservation)


def test_first_buy_rejects_event_recorded_after_mark_read_cutoff_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A mark read cannot be used to value an event recorded only afterward."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    late_event = replace(
        rows.event,
        event_payload_hash="d" * 64,
        recorded_at=_READ_CUTOFF + timedelta(seconds=1),
    )
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(late_event, []),
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, late_event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
    _reservation_unfilled(rows.reservation)


@pytest.mark.parametrize(
    "unknown_state",
    ["existing_position_valuation", "account_aggregate"],
    ids=["unknown-existing-position", "inconsistent-zero-position-aggregate"],
)
def test_first_buy_mark_does_not_repair_existing_unknown_valuation_or_aggregate(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    unknown_state: str,
) -> None:
    """A first-position mark cannot overwrite older unknown ledger knowledge."""

    del persisted_receipt_schema
    rows = _reader_rows(reservation_harness)
    if unknown_state == "existing_position_valuation":
        position = _create_position(reservation_harness.account)
        _set_consistent_account_mark(
            reservation_harness.account,
            market_value=Decimal("1000.00"),
        )
        position.valuation_known = False
        position.save(update_fields=["valuation_known"])
    else:
        _set_consistent_account_mark(
            reservation_harness.account,
            market_value=Decimal("1.00"),
        )
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=_EventReader(rows.event, []),
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)
    positions_before = tuple(
        PositionModel.objects.filter(account=reservation_harness.account).order_by("pk").values()
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert mark_reader.calls == []
    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert (
        tuple(
            PositionModel.objects.filter(account=reservation_harness.account)
            .order_by("pk")
            .values()
        )
        == positions_before
    )
    _reservation_unfilled(rows.reservation)


def test_exact_first_buy_v2_replay_skips_clock_and_mark_reader(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A stored V2 first-fill receipt replays before reading the current mark."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    first = _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
    assert first.replayed is False
    assert len(mark_reader.calls) == 1
    event_reads_before = tuple(event_reader.calls)

    replay = repository.apply_fill_event(
        event=rows.event,
        expected_event_payload_hash=rows.event.event_payload_hash,
        settlement_proof=rows.proof,
        clock=_NoClock(),
    )

    assert replay.replayed is True
    assert replay.trade_id == first.trade_id
    assert tuple(event_reader.calls) == event_reads_before
    assert len(mark_reader.calls) == 1
    receipt = SimulatedOrderFillReceiptModel.objects.get(trade_id=first.trade_id)
    assert receipt.receipt_version == 2
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 1


def test_initial_position_save_exception_rolls_back_the_complete_first_buy(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected save exception before SQL preserves the first-buy transaction."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)
    original_save = PositionModel.save
    insert_attempts = 0

    def fail_new_position_save(
        self: PositionModel,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Fail only the first inserted Position after earlier writes are staged."""

        nonlocal insert_attempts
        if self._state.adding and self.account_id == reservation_harness.account.pk:
            insert_attempts += 1
            raise IntegrityError("forced first Position insert failure")
        original_save(self, *args, **kwargs)

    monkeypatch.setattr(PositionModel, "save", fail_new_position_save)

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))

    assert insert_attempts == 1
    assert len(mark_reader.calls) == 1
    assert len(event_reader.calls) == 1
    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )
    _reservation_unfilled(rows.reservation)


def test_position_insert_constraint_failure_rolls_back_first_buy_atomically(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A real NOT NULL failure on Position INSERT rolls back every staged write."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    counts_before = _ledger_counts(reservation_harness.account)
    account_before = _account_financial_state(reservation_harness.account)
    attempted_inserts: list[tuple[str, tuple[str, ...], tuple[object, ...]]] = []
    integrity_failures: list[IntegrityError] = []

    def reject_position_insert(
        execute: Any,
        sql: str,
        params: Any,
        many: bool,
        context: Any,
    ) -> Any:
        """Send the actual Position INSERT to the database with a null owner key."""

        header, separator, remainder = sql.partition("(")
        table_name = PositionModel._meta.db_table.casefold()
        if (
            not separator
            or not sql.lstrip().casefold().startswith("insert into ")
            or table_name not in header.casefold()
        ):
            return execute(sql, params, many, context)
        columns_text, closing, _ = remainder.partition(")")
        if not closing or many:
            raise AssertionError("Position INSERT must use one ordinary parameterized statement")
        columns = tuple(
            column.strip().strip('"[]').replace(chr(96), "").casefold()
            for column in columns_text.split(",")
        )
        if "account_id" not in columns:
            raise AssertionError("Position INSERT omitted its non-null account foreign key")
        if type(params) is tuple:
            changed_params = list(params)
            restore_tuple = True
        elif type(params) is list:
            changed_params = list(params)
            restore_tuple = False
        else:
            raise AssertionError("Position INSERT did not expose a parameter sequence")
        account_index = columns.index("account_id")
        if account_index >= len(changed_params):
            raise AssertionError("Position INSERT account parameter was not bound")
        changed_params[account_index] = None
        final_params = tuple(changed_params) if restore_tuple else changed_params
        attempted_inserts.append((header, columns, tuple(changed_params)))
        try:
            return execute(sql, final_params, many, context)
        except IntegrityError as error:
            integrity_failures.append(error)
            raise

    with connection.execute_wrapper(reject_position_insert):
        with pytest.raises(SimulatedTradeExecutionResultUnknown):
            _invoke(
                repository,
                rows.event,
                rows.proof,
                clock=_FixedClock(_READ_CUTOFF),
            )

    assert len(attempted_inserts) == 1
    insert_header, columns, attempted_params = attempted_inserts[0]
    assert PositionModel._meta.db_table.casefold() in insert_header.casefold()
    assert attempted_params[columns.index("account_id")] is None
    assert len(integrity_failures) == 1
    constraint_message = str(integrity_failures[0]).casefold()
    assert "account_id" in constraint_message
    assert "null" in constraint_message
    assert len(mark_reader.calls) == 1
    assert len(event_reader.calls) == 1
    assert _ledger_counts(reservation_harness.account) == counts_before
    assert _account_financial_state(reservation_harness.account) == account_before
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0
    assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
    assert (
        SimulatedOrderFillReceiptModel.objects.filter(
            trade__account=reservation_harness.account
        ).count()
        == 0
    )
    _reservation_unfilled(rows.reservation)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)


def test_only_first_position_fill_uses_v2_receipt_and_later_fill_uses_v1(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The mark proof is sealed once for creation; later fills keep V1 receipts."""

    del persisted_receipt_schema
    rows = _first_buy_rows(reservation_harness)
    mark_reader = _InitialPositionMarkReader(_initial_position_mark(rows), [])
    event_reader = _EventReader(rows.event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=mark_reader,
        using="default",
    )
    first = _invoke(repository, rows.event, rows.proof, clock=_FixedClock(_READ_CUTOFF))
    second_at = rows.event.occurred_at + timedelta(seconds=30)
    second_event = replace(
        rows.event,
        source_event_id="first-buy-followup-event-0002",
        event_payload_hash="e" * 64,
        source_snapshot_id="first-buy-followup-snapshot-0002",
        source_snapshot_hash="f" * 64,
        occurred_at=second_at,
        source_observed_at=second_at,
        source_available_at=second_at,
        recorded_at=second_at,
    )
    second_proof = build_order_fill_settlement_proof(
        calendar_evidence=rows.proof.calendar_evidence,
        calendar_read_cutoff=_READ_CUTOFF,
        fill_occurred_at=second_at,
        settlement_exchange=rows.proof.settlement_exchange,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )
    event_reader.event = second_event

    second = _invoke(
        repository,
        second_event,
        second_proof,
        clock=_FixedClock(_READ_CUTOFF),
    )

    receipts = tuple(
        SimulatedOrderFillReceiptModel.objects.filter(reservation_id=rows.reservation.pk).order_by(
            "fill_sequence"
        )
    )
    assert first.replayed is False
    assert second.replayed is False
    assert len(receipts) == 2
    assert (receipts[0].receipt_version, receipts[1].receipt_version) == (2, 1)
    assert receipts[0].initial_position_mark_evidence is not None
    assert receipts[1].initial_position_mark_evidence is None
    assert len(mark_reader.calls) == 1
    assert PositionModel.objects.filter(account=reservation_harness.account).count() == 1
    for receipt in receipts:
        trade = SimulatedTradeModel.objects.get(pk=receipt.trade_id)
        row = read_order_reservation_fill_row(
            reservation_row=SimulatedOrderReservationModel.objects.get(pk=rows.reservation.pk),
            receipt_row=receipt,
            trade_row=trade,
        )
        assert row.receipt_hash == receipt.receipt_hash
