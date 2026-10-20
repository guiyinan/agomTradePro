"""Integration contracts for releasing persisted V4 BUY fill shares."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from django.db import IntegrityError, connection, models

from apps.simulated_trading.application.execution_settlement_uow import (
    ExecutionCalendarUnavailable,
    ReleaseDueSimulatedSettlementsUseCase,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation import ReserveSimulatedOrderUseCase
from apps.simulated_trading.application.order_reservation_fill import (
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationResult
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.infrastructure.execution_settlement_uow_repository import (
    DjangoSimulatedTradeExecutionRepository,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading import (
    test_order_reservation_fill_row_reader as _fill_row_reader_test_module,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _calendar,
    _CalendarReader,
    _execute_use_case,
    _intent,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_concurrency import (
    _run_first_then_waiter,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _invoke,
    _NoClock,
    _persist_two_active_fills,
    _TwoActiveFills,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _Rows as _FillRows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.native_postgres_database import (
    assert_native_postgres_test_database,
)

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)


@pytest.fixture
def _require_v4_release_native_postgres(django_db_use_migrations: bool) -> None:
    """Guard only the V4 release race tests that require migrated PostgreSQL."""

    if not django_db_use_migrations:
        pytest.skip("V4 release race tests require the migrated test database")
    if connection.vendor != "postgresql":
        pytest.skip("V4 release race tests require PostgreSQL")
    assert_native_postgres_test_database()


_RELEASE_AT = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
_OPEN_DATES = {
    date(2026, 10, 16),
    date(2026, 10, 19),
    date(2026, 10, 20),
    date(2026, 10, 21),
    date(2026, 10, 22),
    date(2026, 10, 23),
}
_TRADE_RELEASE_FIELDS = frozenset(
    {
        "settlement_status",
        "settlement_released_at",
        "settlement_release_session",
        "settlement_release_calendar_snapshot_id",
        "settlement_release_calendar_content_hash",
        "settlement_release_calendar_record_digest",
        "settlement_release_calendar_publication_id",
        "settlement_release_calendar_publication_hash",
        "settlement_release_calendar_policy_hash",
        "settlement_release_calendar_evidence_hash",
        "settlement_release_calendar_timezone",
        "settlement_release_proof_payload",
        "settlement_release_proof_hash",
    }
)


def _release_evidence(as_of: datetime) -> ExecutionCalendarEvidence:
    """Create complete SH calendar evidence covering each fill and release session."""

    return _calendar(
        as_of=as_of,
        open_dates=set(_OPEN_DATES),
        start=date(2026, 10, 16),
        end=date(2026, 10, 23),
    )


def _release_use_case(
    *,
    account_id: int,
    user_id: int,
    as_of: datetime,
    evidence: ExecutionCalendarEvidence | None,
) -> tuple[ReleaseDueSimulatedSettlementsUseCase, _CalendarReader]:
    """Compose the public release use case with real ledger persistence."""

    reader = _CalendarReader(evidence)
    use_case = ReleaseDueSimulatedSettlementsUseCase(
        calendar_reader=reader,
        repository=DjangoSimulatedTradeExecutionRepository(using="default"),
        clock=_FixedClock(as_of),
    )
    return use_case, reader


def _release(
    *,
    account_id: int,
    user_id: int,
    as_of: datetime,
    evidence: ExecutionCalendarEvidence | None,
    asset_code: str = "600000.SH",
) -> int:
    """Invoke the public owner-scoped release use case once."""

    use_case, _ = _release_use_case(
        account_id=account_id,
        user_id=user_id,
        as_of=as_of,
        evidence=evidence,
    )
    return use_case.execute(
        account_id=account_id,
        user_id=user_id,
        asset_code=asset_code,
        exchange="SH",
    )


def _snapshot(account: SimulatedAccountModel) -> dict[str, object]:
    """Capture all account-scoped financial and immutable fill rows."""

    account_id = cast(int, account.pk)
    return {
        "account": cast(
            dict[str, object],
            SimulatedAccountModel.objects.filter(pk=account_id).values().get(),
        ),
        "positions": tuple(
            cast(dict[str, object], row)
            for row in PositionModel.objects.filter(account_id=account_id).order_by("pk").values()
        ),
        "reservations": tuple(
            cast(dict[str, object], row)
            for row in SimulatedOrderReservationModel.objects.filter(account_id=account_id)
            .order_by("pk")
            .values()
        ),
        "trades": tuple(
            cast(dict[str, object], row)
            for row in SimulatedTradeModel.objects.filter(account_id=account_id)
            .order_by("pk")
            .values()
        ),
        "receipts": tuple(
            cast(dict[str, object], row)
            for row in SimulatedOrderFillReceiptModel._base_manager.filter(
                trade__account_id=account_id
            )
            .order_by("fill_sequence", "pk")
            .values()
        ),
    }


def _assert_only_release_fields_changed(
    before: dict[str, object],
    after: dict[str, object],
    *,
    released_shares: Decimal,
) -> None:
    """Prove release only changes sellable shares and explicit Trade proof fields."""

    assert before["account"] == after["account"]
    assert before["reservations"] == after["reservations"]
    assert before["receipts"] == after["receipts"]
    before_positions = cast(tuple[dict[str, object], ...], before["positions"])
    after_positions = cast(tuple[dict[str, object], ...], after["positions"])
    assert len(before_positions) == len(after_positions) == 1
    position_before = before_positions[0]
    position_after = after_positions[0]
    assert position_after["available_quantity"] == (
        cast(Decimal, position_before["available_quantity"]) + released_shares
    )
    for field_name, value in position_before.items():
        if field_name not in {"available_quantity", "last_update_date"}:
            assert position_after[field_name] == value

    before_trades = cast(tuple[dict[str, object], ...], before["trades"])
    after_trades = cast(tuple[dict[str, object], ...], after["trades"])
    assert len(before_trades) == len(after_trades)
    for trade_before, trade_after in zip(before_trades, after_trades, strict=True):
        for field_name, value in trade_before.items():
            if field_name not in _TRADE_RELEASE_FIELDS:
                assert trade_after[field_name] == value


def _decode_stored_release_proof(trade: SimulatedTradeModel) -> object:
    """Decode the separately sealed proof only after a release committed."""

    from apps.simulated_trading.infrastructure.order_reservation_fill_release_codec import (
        decode_order_fill_settlement_release_proof,
    )

    payload = trade.settlement_release_proof_payload
    proof_hash = trade.settlement_release_proof_hash
    return decode_order_fill_settlement_release_proof(payload, proof_hash=proof_hash)


def _make_due_fills(harness: _Harness) -> _TwoActiveFills:
    """Create two real pending V4 BUY rows from the established FeeV2 fixture."""

    fills = _persist_two_active_fills(harness)
    assert fills.first_result.replayed is False
    assert fills.second_result.replayed is False
    assert fills.rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    return fills


def _fresh_followup_rows(
    harness: _Harness,
    *,
    as_of: datetime,
    lag: int,
    monkeypatch: pytest.MonkeyPatch,
) -> _FillRows:
    """Prepare a second normal reservation while the original prefix is pending."""

    preparer, rule_reader, _ = _execute_use_case(
        account_id=cast(int, harness.account.pk),
        user_id=harness.user_id,
        as_of=as_of,
        evidence=_release_evidence(as_of),
        lag=lag,
    )
    followup_harness = replace(
        harness,
        preparer=preparer,
        reserve=ReserveSimulatedOrderUseCase(
            preparer=preparer,
            repository=harness.repository,
            clock=_FixedClock(as_of),
        ),
        rule_reader=rule_reader,
    )
    monkeypatch.setattr(_fill_row_reader_test_module, "AS_OF", as_of)
    monkeypatch.setattr(_fill_row_reader_test_module, "_EVENT_AT", as_of + timedelta(minutes=1))
    monkeypatch.setattr(_fill_row_reader_test_module, "_READ_CUTOFF", as_of + timedelta(minutes=3))
    original_intent_builder = _fill_row_reader_test_module._intent_for

    def build_followup_intent(
        selected_harness: _Harness,
        *,
        side: SimulatedTradeSide = SimulatedTradeSide.BUY,
        key: str = "fill-row-reader-order",
    ) -> SimulatedTradeIntent:
        """Give the independently prepared follow-up order a distinct key."""

        del key
        return original_intent_builder(
            selected_harness,
            side=side,
            key="fill-row-reader-followup-order",
        )

    monkeypatch.setattr(_fill_row_reader_test_module, "_intent_for", build_followup_intent)
    rows = _fill_row_reader_test_module._reader_rows(followup_harness)
    assert rows.reservation.idempotency_key == "fill-row-reader-followup-order"
    assert rows.proof.settlement_lag_sessions == lag
    return rows


def _original_prefix_snapshot(
    fills: _TwoActiveFills,
) -> tuple[dict[str, object], tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    """Capture the first reservation, its immutable receipts, and its cost rows."""

    reservation_id = cast(int, fills.rows.reservation.pk)
    trade_ids = (
        cast(int, fills.first_result.trade_id),
        cast(int, fills.second_result.trade_id),
    )
    reservation = cast(
        dict[str, object],
        SimulatedOrderReservationModel.objects.filter(pk=reservation_id).values().get(),
    )
    receipts = tuple(
        cast(dict[str, object], row)
        for row in SimulatedOrderFillReceiptModel._base_manager.filter(
            reservation_id=reservation_id
        )
        .order_by("fill_sequence", "pk")
        .values()
    )
    trades = tuple(
        cast(dict[str, object], row)
        for row in SimulatedTradeModel.objects.filter(pk__in=trade_ids).order_by("pk").values()
    )
    return reservation, receipts, trades


def _assert_original_prefix_unchanged(
    before: tuple[dict[str, object], tuple[dict[str, object], ...], tuple[dict[str, object], ...]],
    after: tuple[dict[str, object], tuple[dict[str, object], ...], tuple[dict[str, object], ...]],
) -> None:
    """Keep original reservation/receipts and all non-release Trade facts exact."""

    assert before[0] == after[0]
    assert before[1] == after[1]
    before_trades = before[2]
    after_trades = after[2]
    assert len(before_trades) == len(after_trades) == 2
    for trade_before, trade_after in zip(before_trades, after_trades, strict=True):
        for field_name, value in trade_before.items():
            if field_name not in _TRADE_RELEASE_FIELDS:
                assert trade_after[field_name] == value


def test_v4_release_waits_for_stored_session_lag_and_replay_is_exact(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Release only after two open sessions and retain both original fill chains."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    before = _snapshot(reservation_harness.account)
    trades_before = cast(tuple[dict[str, object], ...], before["trades"])
    assert len(trades_before) == 2
    assert all(row["settlement_status"] == "pending" for row in trades_before)
    assert all(row.get("settlement_release_proof_payload") is None for row in trades_before)
    assert all(row.get("settlement_release_proof_hash") is None for row in trades_before)
    pending_quantity = sum(
        (cast(Decimal, row["quantity"]) for row in trades_before), Decimal("0.000000")
    )
    assert pending_quantity == Decimal("30.030000")

    early_at = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
    early_evidence = _release_evidence(early_at)
    assert (
        _release(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            as_of=early_at,
            evidence=early_evidence,
        )
        == 0
    )
    assert _snapshot(reservation_harness.account) == before

    due_evidence = _release_evidence(_RELEASE_AT)
    assert due_evidence.evidence_hash != fills.rows.proof.calendar_evidence.evidence_hash
    released = _release(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=due_evidence,
    )
    assert released == 2
    after = _snapshot(reservation_harness.account)
    _assert_only_release_fields_changed(before, after, released_shares=pending_quantity)
    after_trades = cast(tuple[dict[str, object], ...], after["trades"])
    assert all(row["settlement_status"] == "released" for row in after_trades)

    source_events = {
        fills.first_event.source_event_id: fills.first_event,
        fills.second_event.source_event_id: fills.second_event,
    }
    for trade in SimulatedTradeModel.objects.filter(account=reservation_harness.account).order_by(
        "pk"
    ):
        receipt = SimulatedOrderFillReceiptModel._base_manager.get(trade_id=trade.pk)
        source_event = source_events[receipt.source_event_id]
        proof = _decode_stored_release_proof(trade)
        assert proof.trade_id == trade.pk
        assert proof.reservation_id == fills.rows.reservation.pk
        assert proof.account_id == reservation_harness.account.pk
        assert proof.user_id == reservation_harness.user_id
        assert proof.receipt_hash == receipt.receipt_hash
        assert proof.security_id == fills.rows.event.security_id
        assert proof.settlement_exchange == "SH"
        assert proof.fill_market_session == date(2026, 10, 16)
        assert proof.settlement_lag_sessions == 2
        assert proof.released_at == _RELEASE_AT
        assert proof.release_session == date(2026, 10, 20)
        assert proof.calendar_evidence == due_evidence
        assert proof.released_at >= source_event.occurred_at
        assert proof.released_at >= trade.execution_time
        assert proof.released_at >= fills.rows.proof.calendar_read_cutoff

    replayed_release = _release(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=due_evidence,
    )
    assert replayed_release == 0
    assert _snapshot(reservation_harness.account) == after

    replay = _invoke(
        fills.repository,
        fills.second_event,
        build_order_fill_settlement_proof(
            calendar_evidence=fills.rows.proof.calendar_evidence,
            calendar_read_cutoff=_READ_CUTOFF,
            fill_occurred_at=fills.second_event.occurred_at,
            settlement_exchange=fills.rows.proof.settlement_exchange,
            settlement_lag_sessions=fills.rows.proof.settlement_lag_sessions,
        ),
        clock=_NoClock(),
    )
    assert replay.replayed is True
    assert replay.trade_id == fills.second_result.trade_id
    assert fills.reader.calls == []
    assert _snapshot(reservation_harness.account) == after


def test_v4_release_wrong_owner_and_missing_calendar_leave_rows_unchanged(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Owner mismatch and absent or uncovered calendar evidence cannot mutate rows."""

    del persisted_receipt_schema
    _make_due_fills(reservation_harness)
    before = _snapshot(reservation_harness.account)
    evidence = _release_evidence(_RELEASE_AT)
    wrong_owner_case, wrong_owner_reader = _release_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id + 1000,
        as_of=_RELEASE_AT,
        evidence=evidence,
    )
    assert (
        wrong_owner_case.execute(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id + 1000,
            asset_code="600000.SH",
            exchange="SH",
        )
        == 0
    )
    assert wrong_owner_reader.coverage_requests == []
    assert _snapshot(reservation_harness.account) == before

    missing_case, _ = _release_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=None,
    )
    with pytest.raises(ExecutionCalendarUnavailable):
        missing_case.execute(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            asset_code="600000.SH",
            exchange="SH",
        )
    assert _snapshot(reservation_harness.account) == before

    uncovered_evidence = _calendar(
        as_of=_RELEASE_AT,
        open_dates={date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)},
        start=date(2026, 10, 20),
        end=date(2026, 10, 22),
    )
    uncovered_case, _ = _release_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=uncovered_evidence,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        uncovered_case.execute(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            asset_code="600000.SH",
            exchange="SH",
        )
    assert blocked.value.code == "SIMULATED_TRADE_EXECUTION_BLOCKED"
    assert _snapshot(reservation_harness.account) == before


def test_v4_release_rejects_a_corrupt_second_receipt_without_partial_release(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """One invalid member in a due V4 chain blocks the whole release batch."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    receipts = tuple(
        SimulatedOrderFillReceiptModel._base_manager.filter(
            reservation_id=fills.rows.reservation.pk
        ).order_by("fill_sequence", "pk")
    )
    assert len(receipts) == 2
    replacement_hash = "0" * 64
    if receipts[1].receipt_hash == replacement_hash:
        replacement_hash = "1" * 64
    changed = models.QuerySet.update(
        SimulatedOrderFillReceiptModel._base_manager.filter(pk=receipts[1].pk),
        receipt_hash=replacement_hash,
    )
    assert changed == 1
    before = _snapshot(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _release(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            as_of=_RELEASE_AT,
            evidence=_release_evidence(_RELEASE_AT),
        )

    assert blocked.value.code == "SIMULATED_FILL_RECEIPT_CHAIN_INVALID"
    assert _snapshot(reservation_harness.account) == before


def test_v4_release_rejects_pending_overcommit_even_when_no_fill_is_due(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Validate all pending shares before due filtering can hide an overcommit."""

    del persisted_receipt_schema
    _make_due_fills(reservation_harness)
    trades = tuple(
        SimulatedTradeModel.objects.filter(account=reservation_harness.account).order_by("pk")
    )
    assert len(trades) == 2
    assert all(trade.settlement_status == "pending" for trade in trades)
    assert all(trade.settlement_lag_sessions == 2 for trade in trades)

    changed = models.QuerySet.update(
        PositionModel._base_manager.filter(
            account=reservation_harness.account,
            asset_code="600000.SH",
        ),
        quantity=Decimal("130.000000"),
    )
    assert changed == 1
    before = _snapshot(reservation_harness.account)
    early_at = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        _release(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            as_of=early_at,
            evidence=_calendar(
                as_of=early_at,
                open_dates={date(2026, 10, 16), date(2026, 10, 19)},
                start=date(2026, 10, 16),
                end=date(2026, 10, 19),
            ),
        )

    assert blocked.value.code == "PENDING_SETTLEMENT_INVALID"
    assert _snapshot(reservation_harness.account) == before


@pytest.mark.parametrize("next_write", ("execute", "reserve"), ids=("execute", "reserve"))
def test_ordinary_write_releases_due_v4_before_continuing_atomically(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    next_write: str,
) -> None:
    """Normal execution and reservation share due V4 release under the account lock."""

    del persisted_receipt_schema
    _make_due_fills(reservation_harness)
    evidence = _release_evidence(_RELEASE_AT)
    executor, _, _ = _execute_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=evidence,
        rule_bundle=reservation_harness.rule_reader.bundle,
    )

    if next_write == "execute":
        receipt = executor.execute(
            _intent(
                user_id=reservation_harness.user_id,
                account_id=reservation_harness.account.pk,
                key="ordinary-after-v4-release",
                quantity=Decimal("1.000000"),
                price=Decimal("10.0000"),
            )
        )
        assert receipt.trade_id > 0
        assert SimulatedTradeModel.objects.get(pk=receipt.trade_id).settlement_status == "pending"
    else:
        reserver = ReserveSimulatedOrderUseCase(
            preparer=executor,
            repository=reservation_harness.repository,
            clock=_FixedClock(_RELEASE_AT),
        )
        result = reserver.execute(
            _intent_for(
                reservation_harness,
                key="ordinary-reserve-after-v4-release",
                quantity=Decimal("1.000000"),
            ),
            fee_budget=Decimal("20.00"),
            as_of=_RELEASE_AT,
        )
        assert result.reservation.status.value == "active"
        assert result.replayed is False

    old_trades = SimulatedTradeModel.objects.filter(
        account=reservation_harness.account,
        settlement_plan_binding_version=4,
    )
    assert old_trades.count() == 2
    assert all(trade.settlement_status == "released" for trade in old_trades)
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    assert position.quantity == (
        Decimal("131.030000") if next_write == "execute" else Decimal("130.030000")
    )
    assert position.available_quantity == Decimal("130.030000")


def test_new_fill_releases_due_v4_prefix_before_persisting_the_next_fill(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Oct20 fill releases the old due prefix after a fresh Oct19 reserve."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    event_at = datetime(2026, 10, 20, 1, 50, tzinfo=UTC)
    # Oct19 is only the first elapsed session for the old Oct16 T+2 prefix.
    # Reserving at 02:00 also keeps the next-day fill and writer clock inside
    # this fresh identity's one-day validity window.
    reserve_at = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
    assert reserve_at < event_at < reserve_at + timedelta(days=1)
    assert event_at + timedelta(minutes=3) < reserve_at + timedelta(days=1)
    prefix_before_reserve = _original_prefix_snapshot(fills)
    followup_rows = _fresh_followup_rows(
        reservation_harness,
        as_of=reserve_at,
        lag=2,
        monkeypatch=monkeypatch,
    )
    prefix_after_reserve = _original_prefix_snapshot(fills)
    assert prefix_after_reserve == prefix_before_reserve
    prefix_trades = tuple(
        SimulatedTradeModel.objects.filter(
            pk__in=(fills.first_result.trade_id, fills.second_result.trade_id)
        ).order_by("pk")
    )
    assert tuple(trade.settlement_status for trade in prefix_trades) == (
        "pending",
        "pending",
    )
    prefix_before = _original_prefix_snapshot(fills)
    position_before = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    cash_before = account_before.current_cash
    cost_before = position_before.total_cost
    market_value_before = account_before.current_market_value
    cutoff = event_at + timedelta(minutes=2)
    evidence = _release_evidence(cutoff)
    event: LocalSimulatedFillEventV1 = cast(
        LocalSimulatedFillEventV1,
        replace(
            followup_rows.event,
            source_event_id="row-reader-event-0003",
            event_payload_hash="8" * 64,
            source_snapshot_id="row-reader-source-snapshot-003",
            source_snapshot_hash="9" * 64,
            quantity=Decimal("1.000000"),
            occurred_at=event_at,
            source_observed_at=event_at,
            source_available_at=event_at,
            recorded_at=event_at,
        ),
    )
    proof = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=cutoff,
        fill_occurred_at=event_at,
        settlement_exchange="SH",
        settlement_lag_sessions=followup_rows.proof.settlement_lag_sessions,
    )
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")

    result = _invoke(
        repository,
        event,
        proof,
        clock=_FixedClock(cutoff + timedelta(minutes=1)),
    )

    assert result.replayed is False
    trades = tuple(
        SimulatedTradeModel.objects.filter(account=reservation_harness.account).order_by("pk")
    )
    assert len(trades) == 3
    assert tuple(trade.settlement_status for trade in trades) == (
        "released",
        "released",
        "pending",
    )
    assert trades[2].pk == result.trade_id
    receipt = SimulatedOrderFillReceiptModel._base_manager.get(trade_id=result.trade_id)
    assert receipt.reservation_id == followup_rows.reservation.pk
    assert receipt.fill_sequence == 1
    # The new sequence-one $10 BUY incurs its own FeeV2 minimum commission.
    assert trades[2].commission == Decimal("1.00")
    assert trades[2].transfer_fee == Decimal("0.00")
    assert trades[2].slippage == Decimal("0.01")
    assert trades[2].total_cost == Decimal("11.01")
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert account_after.current_cash == cash_before - Decimal("11.01")
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code=event.asset_code,
    )
    assert position.quantity == Decimal("131.030000")
    assert position.available_quantity == Decimal("130.030000")
    assert position.total_cost == cost_before + Decimal("11.01")
    assert account_after.current_market_value == market_value_before + Decimal("10.00")
    assert (
        account_after.total_value == account_after.current_cash + account_after.current_market_value
    )
    prefix_after = _original_prefix_snapshot(fills)
    _assert_original_prefix_unchanged(prefix_before, prefix_after)


def test_new_fill_keeps_v4_pending_when_calendar_ends_at_current_session(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh T+0 order releases while the original T+2 prefix remains pending."""

    del persisted_receipt_schema
    fills = _make_due_fills(reservation_harness)
    event_at = datetime(2026, 10, 19, 1, 50, tzinfo=UTC)
    # Keep the normal fresh reservation before the fill while remaining in
    # the Oct19 session; the old Oct16 T+2 prefix is still not due.
    reserve_at = event_at - timedelta(minutes=10)
    assert reserve_at < event_at < reserve_at + timedelta(days=1)
    prefix_before_reserve = _original_prefix_snapshot(fills)
    followup_rows = _fresh_followup_rows(
        reservation_harness,
        as_of=reserve_at,
        lag=0,
        monkeypatch=monkeypatch,
    )
    prefix_after_reserve = _original_prefix_snapshot(fills)
    assert prefix_after_reserve == prefix_before_reserve
    prefix_trades = tuple(
        SimulatedTradeModel.objects.filter(
            pk__in=(fills.first_result.trade_id, fills.second_result.trade_id)
        ).order_by("pk")
    )
    assert tuple(trade.settlement_status for trade in prefix_trades) == (
        "pending",
        "pending",
    )
    prefix_before = _original_prefix_snapshot(fills)
    position_before = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    account_before = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    cash_before = account_before.current_cash
    cost_before = position_before.total_cost
    market_value_before = account_before.current_market_value
    cutoff = event_at + timedelta(minutes=2)
    evidence = _calendar(
        as_of=cutoff,
        open_dates={date(2026, 10, 16), date(2026, 10, 19)},
        start=date(2026, 10, 16),
        end=date(2026, 10, 19),
    )
    event = replace(
        followup_rows.event,
        source_event_id="row-reader-event-0003",
        event_payload_hash="8" * 64,
        source_snapshot_id="row-reader-source-snapshot-003",
        source_snapshot_hash="9" * 64,
        quantity=Decimal("1.000000"),
        occurred_at=event_at,
        source_observed_at=event_at,
        source_available_at=event_at,
        recorded_at=event_at,
    )
    proof = build_order_fill_settlement_proof(
        calendar_evidence=evidence,
        calendar_read_cutoff=cutoff,
        fill_occurred_at=event_at,
        settlement_exchange=followup_rows.proof.settlement_exchange,
        settlement_lag_sessions=followup_rows.proof.settlement_lag_sessions,
    )
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(event_reader=reader, using="default")

    result = _invoke(
        repository,
        event,
        proof,
        clock=_FixedClock(cutoff + timedelta(minutes=1)),
    )

    assert result.replayed is False
    original_trades = tuple(
        SimulatedTradeModel.objects.filter(
            pk__in=(fills.first_result.trade_id, fills.second_result.trade_id)
        ).order_by("pk")
    )
    assert tuple(trade.settlement_status for trade in original_trades) == (
        "pending",
        "pending",
    )
    assert all(trade.settlement_release_proof_payload is None for trade in original_trades)
    assert all(trade.settlement_release_proof_hash is None for trade in original_trades)
    next_trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    assert next_trade.settlement_status == "released"
    receipt = SimulatedOrderFillReceiptModel._base_manager.get(trade_id=result.trade_id)
    assert receipt.reservation_id == followup_rows.reservation.pk
    assert receipt.fill_sequence == 1
    # A separately sealed T+0 order still starts its own sequence-one fee accrual.
    assert next_trade.commission == Decimal("1.00")
    assert next_trade.transfer_fee == Decimal("0.00")
    assert next_trade.slippage == Decimal("0.01")
    assert next_trade.total_cost == Decimal("11.01")
    account_after = SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk)
    assert account_after.current_cash == cash_before - Decimal("11.01")
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    assert position.quantity == Decimal("131.030000")
    assert position.available_quantity == Decimal("101.000000")
    assert position.total_cost == cost_before + Decimal("11.01")
    assert account_after.current_market_value == market_value_before + Decimal("10.00")
    assert (
        account_after.total_value == account_after.current_cash + account_after.current_market_value
    )
    prefix_after = _original_prefix_snapshot(fills)
    _assert_original_prefix_unchanged(prefix_before, prefix_after)


def test_reservation_insert_failure_rolls_back_due_v4_release(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later order-hold failure rolls back the earlier V4 release proof and shares."""

    del persisted_receipt_schema
    _make_due_fills(reservation_harness)
    before = _snapshot(reservation_harness.account)
    executor, _, _ = _execute_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=_release_evidence(_RELEASE_AT),
        rule_bundle=reservation_harness.rule_reader.bundle,
    )
    reserver = ReserveSimulatedOrderUseCase(
        preparer=executor,
        repository=reservation_harness.repository,
        clock=_FixedClock(_RELEASE_AT),
    )
    original_save = SimulatedOrderReservationModel.save
    release_seen_at_insert: list[tuple[Decimal, tuple[str, ...], tuple[str | None, ...]]] = []

    def fail_new_hold(
        self: SimulatedOrderReservationModel,
        *args: object,
        **kwargs: object,
    ) -> None:
        if self.pk is None:
            position = PositionModel.objects.get(
                account=reservation_harness.account,
                asset_code="600000.SH",
            )
            release_rows = tuple(
                SimulatedTradeModel.objects.filter(
                    account_id=reservation_harness.account.pk,
                    settlement_plan_binding_version=4,
                )
                .order_by("pk")
                .values_list("settlement_status", "settlement_release_proof_hash")
            )
            release_seen_at_insert.append(
                (
                    position.available_quantity,
                    tuple(cast(str, status) for status, _ in release_rows),
                    tuple(cast(str | None, proof_hash) for _, proof_hash in release_rows),
                )
            )
            raise IntegrityError("injected later reservation insert failure")
        original_save(self, *args, **kwargs)

    monkeypatch.setattr(SimulatedOrderReservationModel, "save", fail_new_hold)
    intent = _intent_for(
        reservation_harness,
        key="reserve-after-due-v4-release-fails",
        quantity=Decimal("1.000000"),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        reserver.execute(intent, fee_budget=Decimal("20.00"), as_of=_RELEASE_AT)

    assert blocked.value.code == "ORDER_RESERVATION_STORAGE_CONFLICT"
    assert len(release_seen_at_insert) == 1
    released_quantity, release_statuses, release_hashes = release_seen_at_insert[0]
    assert released_quantity == Decimal("130.030000")
    assert release_statuses == ("released", "released")
    assert len(release_hashes) == 2
    assert all(type(proof_hash) is str and len(proof_hash) == 64 for proof_hash in release_hashes)
    assert _snapshot(reservation_harness.account) == before


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="account-row release serialization is verified on native PostgreSQL",
)
def test_postgres_two_v4_release_connections_credit_pending_shares_once(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    _require_v4_release_native_postgres: None,
) -> None:
    """Two callers wait on the account parent and only one persists release proof."""

    del persisted_receipt_schema, _require_v4_release_native_postgres
    _make_due_fills(reservation_harness)
    evidence = _release_evidence(_RELEASE_AT)

    def release() -> int:
        return _release(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            as_of=_RELEASE_AT,
            evidence=evidence,
        )

    pair = _run_first_then_waiter(
        account=reservation_harness.account,
        first_operation=release,
        waiting_operation=release,
        thread_name="v4-release-release-race",
    )
    assert pair.waiter_pid != pair.holder_pid
    assert pair.lock_wait.wait_event_type == "Lock"
    assert pair.holder_pid in pair.lock_wait.blocker_pids
    assert pair.first_result == 2
    assert pair.waiter_outcome.blocked_code is None
    assert pair.waiter_outcome.value == 0
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    assert position.quantity == Decimal("130.030000")
    assert position.available_quantity == Decimal("130.030000")
    assert (
        SimulatedTradeModel.objects.filter(
            account=reservation_harness.account,
            settlement_status="released",
            settlement_release_proof_hash__isnull=False,
        ).count()
        == 2
    )


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="release/sell reservation serialization is verified on native PostgreSQL",
)
def test_postgres_due_v4_release_serializes_before_sell_reservation(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    _require_v4_release_native_postgres: None,
) -> None:
    """A waiting SELL reservation sees exactly the released shares under one parent lock."""

    del persisted_receipt_schema, _require_v4_release_native_postgres
    _make_due_fills(reservation_harness)
    evidence = _release_evidence(_RELEASE_AT)
    executor, _, _ = _execute_use_case(
        account_id=reservation_harness.account.pk,
        user_id=reservation_harness.user_id,
        as_of=_RELEASE_AT,
        evidence=evidence,
        rule_bundle=reservation_harness.rule_reader.bundle,
    )
    reserver = ReserveSimulatedOrderUseCase(
        preparer=executor,
        repository=reservation_harness.repository,
        clock=_FixedClock(_RELEASE_AT),
    )
    sell_intent = _intent_for(
        reservation_harness,
        side=SimulatedTradeSide.SELL,
        key="sell-after-v4-release-race",
        quantity=Decimal("100.000000"),
    )

    def release() -> int:
        return _release(
            account_id=reservation_harness.account.pk,
            user_id=reservation_harness.user_id,
            as_of=_RELEASE_AT,
            evidence=evidence,
        )

    def reserve_sell() -> OrderReservationResult:
        return reserver.execute(sell_intent, fee_budget=None, as_of=_RELEASE_AT)

    pair = _run_first_then_waiter(
        account=reservation_harness.account,
        first_operation=release,
        waiting_operation=reserve_sell,
        thread_name="v4-release-sell-reserve-race",
    )
    assert pair.waiter_pid != pair.holder_pid
    assert pair.lock_wait.wait_event_type == "Lock"
    assert pair.holder_pid in pair.lock_wait.blocker_pids
    assert pair.first_result == 2
    assert pair.waiter_outcome.blocked_code is None
    assert isinstance(pair.waiter_outcome.value, OrderReservationResult)
    assert pair.waiter_outcome.value.reservation.shares_reserved == Decimal("100.000000")
    assert pair.waiter_outcome.value.book.active_held_shares == Decimal("100.000000")
    position = PositionModel.objects.get(
        account=reservation_harness.account,
        asset_code="600000.SH",
    )
    assert position.quantity == Decimal("130.030000")
    assert position.available_quantity == Decimal("130.030000")
    assert pair.waiter_outcome.value.book.active_held_shares <= position.available_quantity
    assert position.available_quantity <= position.quantity
