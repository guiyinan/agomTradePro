"""Prove the bounded G5 repair against a real persisted V4 fill chain."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import cast

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.historical_sellable_repair import (
    HistoricalSellableRepairCommand,
)
from apps.simulated_trading.application.order_reservation import (
    CancelSimulatedOrderReservationUseCase,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.initial_position_mark import InitialPositionMarkProof
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    build_order_fill_settlement_proof,
)
from apps.simulated_trading.historical_sellable_repair_composition import (
    build_historical_sellable_repair_service,
)
from apps.simulated_trading.infrastructure import (
    historical_sellable_difference_repository as sellable_repository,
)
from apps.simulated_trading.infrastructure.historical_sellable_repair_models import (
    HistoricalSellableRepairJournalModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _LockedFillChain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_repository import (
    DjangoSimulatedOrderFillRepository,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.management.commands import (
    repair_historical_sellable_position as repair_command,
)
from tests.component.simulated_trading import (
    test_execution_settlement_v4_history_guard as v4_history,
)
from tests.component.simulated_trading import (
    test_historical_sellable_difference_report as report_contracts,
)
from tests.component.simulated_trading import (
    test_order_reservation_fill_repository as fill_repository,
)
from tests.component.simulated_trading import test_order_reservation_fill_row_reader as row_reader
from tests.component.simulated_trading import (
    test_order_reservation_repository as reservation_repository,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _calendar,
    _CalendarReader,
    _Clock,
    _IdentityReader,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.native_postgres_database import assert_native_postgres_test_database

REPORT_COMMAND = "report_historical_sellable_differences"
REPAIR_COMMAND = "repair_historical_sellable_position"
ASSET_CODE = "600000.SH"
SECURITY_ID = "SH.UOW.SECURITY"


class _InitialMarkReader:
    """Return the retained V2 mark created by the existing reader fixture."""

    def __init__(self, proof: InitialPositionMarkProof) -> None:
        self.proof = proof

    def read_initial_position_mark(
        self,
        *,
        security_id: str,
        asset_code: str,
        asset_type: str,
        market: str,
        board: str,
        read_at: datetime,
    ) -> InitialPositionMarkProof:
        """Return the exact mark only for the first fill's locked identity."""

        assert security_id == SECURITY_ID
        assert asset_code == ASSET_CODE
        assert asset_type == "equity"
        assert market == "SH"
        assert board == "MAIN"
        assert read_at == self.proof.read_at
        return self.proof


class _MultiDayIdentityReader:
    """Extend only synthetic identity validity for the multi-day settlement case."""

    def __init__(self) -> None:
        self.reader = _IdentityReader()

    def get_execution_instrument_identity(
        self,
        *,
        security_id: str,
        asset_code: str,
        as_of: datetime,
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        """Supply an identity fixture valid through the declared second fill date."""

        evidence = self.reader.get_execution_instrument_identity(
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        return replace(evidence, identity_valid_until=as_of + timedelta(days=10))


def _run_simulated_report(*, user_id: int, account_id: int) -> dict[str, object]:
    """Run the public no-write report mode for the selected native account."""

    stdout = StringIO()
    call_command(
        REPORT_COMMAND,
        user_id=user_id,
        simulated_account_id=account_id,
        stdout=stdout,
    )
    value: object = json.loads(stdout.getvalue())
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _rows(report: dict[str, object]) -> list[dict[str, object]]:
    """Narrow the command's JSON rows for exact accounting assertions."""

    value = report.get("rows")
    assert isinstance(value, list)
    assert len(value) == 1
    row = value[0]
    assert isinstance(row, dict)
    return [cast(dict[str, object], row)]


class _FixedRepositoryTime:
    """Control only the report proof cutoff without changing wall-clock writes."""

    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        """Return a deterministic read cutoff for the fixture's retained calendar."""

        return self.value


def _advance_reservation_clock(
    harness: reservation_repository._Harness,
    cutoff: datetime,
) -> None:
    """Keep the pre-read and account-lock clocks aligned for later reservations."""

    harness.preparer._clock = _Clock(cutoff)
    harness.reserve._clock = _Clock(cutoff)


def _command_from_preview(
    *,
    user_id: int,
    account_id: int,
    target_position_id: int,
    idempotency_key: str,
    row: dict[str, object],
) -> HistoricalSellableRepairCommand:
    """Bind the operator's exact preview cutoff, digest, and cached before-state."""

    cutoff_value = row.get("evidence_cutoff_at")
    proof_hash = row.get("evidence_proof_hash")
    quantity_value = row.get("stored_available_quantity")
    known_value = row.get("stored_available_quantity_known")
    if (
        not isinstance(cutoff_value, str)
        or not isinstance(proof_hash, str)
        or not isinstance(quantity_value, str)
        or not isinstance(known_value, bool)
    ):
        raise AssertionError("the repair preview must expose exact evidence and before-state")
    return HistoricalSellableRepairCommand(
        action="apply",
        user_id=user_id,
        account_id=account_id,
        target_position_id=target_position_id,
        actor_user_id=user_id,
        idempotency_key=idempotency_key,
        preview_evidence_cutoff_at=datetime.fromisoformat(cutoff_value),
        preview_evidence_proof_hash=proof_hash,
        preview_available_quantity=Decimal(quantity_value),
        preview_available_quantity_known=known_value,
    )


def _run_apply_command(command: HistoricalSellableRepairCommand) -> dict[str, object]:
    """Exercise the management command with values copied from the preview."""

    if (
        command.action != "apply"
        or command.preview_evidence_cutoff_at is None
        or command.preview_evidence_proof_hash is None
        or command.preview_available_quantity is None
        or command.preview_available_quantity_known is None
    ):
        raise AssertionError("apply CLI helper requires the full preview tuple")
    stdout = StringIO()
    call_command(
        REPAIR_COMMAND,
        action="apply",
        user_id=command.user_id,
        simulated_account_id=command.account_id,
        target_position_id=command.target_position_id,
        actor_user_id=command.actor_user_id,
        idempotency_key=command.idempotency_key,
        preview_evidence_cutoff_at=command.preview_evidence_cutoff_at,
        preview_evidence_proof_hash=command.preview_evidence_proof_hash,
        preview_available_quantity=command.preview_available_quantity,
        preview_available_quantity_known=command.preview_available_quantity_known,
        stdout=stdout,
    )
    value: object = json.loads(stdout.getvalue())
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def _run_rollback_command(command: HistoricalSellableRepairCommand) -> dict[str, object]:
    """Exercise rollback through the management command with its apply receipt id."""

    if command.action != "rollback" or type(command.apply_event_id) is not int:
        raise AssertionError("rollback CLI helper requires the original apply event id")
    stdout = StringIO()
    call_command(
        REPAIR_COMMAND,
        action="rollback",
        user_id=command.user_id,
        simulated_account_id=command.account_id,
        target_position_id=command.target_position_id,
        actor_user_id=command.actor_user_id,
        idempotency_key=command.idempotency_key,
        apply_event_id=command.apply_event_id,
        stdout=stdout,
    )
    value: object = json.loads(stdout.getvalue())
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


def test_repair_command_rejects_invalid_preview_and_rollback_options_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject malformed command options before composing an application service."""

    monkeypatch.setattr(
        repair_command,
        "build_historical_sellable_repair_service",
        lambda: pytest.fail("invalid command options must not compose the repository"),
    )
    required_options: dict[str, object] = {
        "user_id": 1,
        "simulated_account_id": 1,
        "target_position_id": 1,
        "actor_user_id": 1,
        "idempotency_key": "g5-invalid-command-001",
    }

    with pytest.raises(
        CommandError,
        match="all four values from one read-only preview",
    ):
        call_command(
            REPAIR_COMMAND,
            action="apply",
            **required_options,
            stdout=StringIO(),
        )

    with pytest.raises(
        CommandError,
        match="rollback requires a positive --apply-event-id",
    ):
        call_command(
            REPAIR_COMMAND,
            action="rollback",
            **required_options,
            stdout=StringIO(),
        )

    with pytest.raises(
        CommandError,
        match="preview values apply only to --action apply",
    ):
        call_command(
            REPAIR_COMMAND,
            action="rollback",
            apply_event_id=7,
            preview_available_quantity_known=False,
            **required_options,
            stdout=StringIO(),
        )

    parser = repair_command.Command().create_parser("manage.py", REPAIR_COMMAND)
    with pytest.raises(
        CommandError,
        match="timestamp must include a timezone offset",
    ):
        parser.parse_args(
            [
                "--action",
                "apply",
                "--user-id",
                "1",
                "--simulated-account-id",
                "1",
                "--target-position-id",
                "1",
                "--actor-user-id",
                "1",
                "--idempotency-key",
                "g5-invalid-preview-timestamp",
                "--preview-evidence-cutoff-at",
                "2026-11-02T08:00:00",
                "--preview-evidence-proof-hash",
                "a" * 64,
                "--preview-available-quantity",
                "300.000000",
                "--preview-available-quantity-known",
                "false",
            ]
        )


@pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)
@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="G5 repair account/Position locking requires native PostgreSQL",
)
def test_self_simulated_report_and_repair_replay_and_rollback(
    ledger: object,
    reservation_harness: reservation_repository._Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebuild 100 settled of 300, then prove dry run, replay, and exact rollback."""

    del ledger, persisted_receipt_schema
    assert_native_postgres_test_database()
    harness = reservation_harness
    harness.preparer._identity_reader = _MultiDayIdentityReader()
    original_intent_builder = reservation_repository._intent_for

    def _three_hundred_share_intent(
        selected_harness: reservation_repository._Harness,
        *,
        side: SimulatedTradeSide = SimulatedTradeSide.BUY,
        key: str = "fill-row-reader-order",
    ) -> SimulatedTradeIntent:
        """Reserve a bounded 300-share order under the existing qualified fixture."""

        return original_intent_builder(
            selected_harness,
            side=side,
            key=key,
            quantity=Decimal("300.000000"),
            security_id=SECURITY_ID,
            asset_code=ASSET_CODE,
        )

    with monkeypatch.context() as patch:
        patch.setattr(row_reader, "_intent_for", _three_hundred_share_intent)
        rows = row_reader._reader_rows(harness, include_initial_mark=True)
    assert rows.initial_mark is not None
    initial_mark_reader = _InitialMarkReader(rows.initial_mark)
    first_event = replace(
        rows.event,
        event_kind=row_reader.LocalSimulatedFillEventKind.FILL,
        quantity=Decimal("100.000000"),
        event_payload_hash="f" * 64,
    )
    event_reader = fill_repository._EventReader(first_event, [])
    fill_writer = DjangoSimulatedOrderFillRepository(
        event_reader=event_reader,
        initial_position_mark_reader=initial_mark_reader,
        using="default",
    )
    first_result = fill_repository._invoke(
        fill_writer,
        first_event,
        rows.proof,
        clock=fill_repository._FixedClock(rows.initial_mark.read_at),
    )
    assert first_result.replayed is False
    assert type(first_result.trade_id) is int
    first_trade = SimulatedTradeModel._default_manager.get(pk=first_result.trade_id)
    first_receipt = SimulatedOrderFillReceiptModel._default_manager.get(trade=first_trade)
    history = v4_history._PersistedV4History(
        rows=rows,
        reservation=SimulatedOrderReservationModel._default_manager.get(pk=rows.reservation.pk),
        receipt=first_receipt,
        trade=first_trade,
    )
    release_at = AS_OF + timedelta(days=4)
    assert v4_history._release_v4_history(history, as_of=release_at) == 1
    first_trade.refresh_from_db()

    second_at = release_at + timedelta(minutes=1)
    second_cutoff = second_at + timedelta(minutes=2)
    second_event = replace(
        first_event,
        source_event_id="g5-fill-002",
        source_snapshot_id="g5-source-snapshot-002",
        source_snapshot_hash="2" * 64,
        event_kind=row_reader.LocalSimulatedFillEventKind.FINAL_FILL,
        quantity=Decimal("200.000000"),
        event_payload_hash="e" * 64,
        occurred_at=second_at,
        source_observed_at=second_at,
        source_available_at=second_at,
        recorded_at=second_at,
    )
    second_proof = build_order_fill_settlement_proof(
        calendar_evidence=rows.proof.calendar_evidence,
        calendar_read_cutoff=second_cutoff,
        fill_occurred_at=second_at,
        settlement_exchange=rows.proof.settlement_exchange,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )
    event_reader.event = second_event
    second_result = fill_repository._invoke(
        fill_writer,
        second_event,
        second_proof,
        clock=fill_repository._FixedClock(second_cutoff),
    )
    assert second_result.replayed is False

    position = PositionModel._default_manager.get(
        account=harness.account,
        asset_code=ASSET_CODE,
    )
    assert position.quantity == Decimal("300.000000")
    assert position.available_quantity == Decimal("100.000000")
    assert position.available_quantity_known is True
    second_trade = SimulatedTradeModel._default_manager.get(pk=second_result.trade_id)
    assert first_trade.settlement_status == "released"
    assert second_trade.settlement_status == "pending"
    assert second_trade.settlement_release_session is None
    assert second_trade.settlement_release_date is not None

    post_preview_intent_builder = reservation_repository._intent_for

    def _fifty_share_post_preview_intent(
        selected_harness: reservation_repository._Harness,
        *,
        side: SimulatedTradeSide = SimulatedTradeSide.BUY,
        key: str = "fill-row-reader-order",
    ) -> SimulatedTradeIntent:
        """Create an accepted BUY that remains unfilled across the repair preview."""

        del key
        return post_preview_intent_builder(
            selected_harness,
            side=side,
            key="g5-post-preview-buy-001",
            quantity=Decimal("50.000000"),
            security_id=SECURITY_ID,
            asset_code=ASSET_CODE,
        )

    post_preview_intent = _fifty_share_post_preview_intent(harness)
    post_preview_calendar = _calendar(
        as_of=second_cutoff,
        open_dates={
            date(2026, 10, 16),
            date(2026, 10, 19),
            date(2026, 10, 20),
            date(2026, 10, 21),
            date(2026, 10, 22),
            date(2026, 10, 23),
        },
        exchange=rows.proof.settlement_exchange,
        start=date(2026, 10, 16),
        end=date(2026, 10, 23),
    )
    assert post_preview_calendar.release_session(
        date(2026, 10, 20),
        rows.proof.settlement_lag_sessions,
    ) == date(2026, 10, 22)
    assert post_preview_calendar.release_session(
        date(2026, 10, 21),
        rows.proof.settlement_lag_sessions,
    ) == date(2026, 10, 23)
    harness.preparer._calendar_reader = _CalendarReader(post_preview_calendar)
    _advance_reservation_clock(harness, second_cutoff)
    harness.reserve.execute(
        post_preview_intent,
        fee_budget=Decimal("20.00"),
        as_of=second_cutoff,
    )
    future_reservation = SimulatedOrderReservationModel._default_manager.get(
        account_id=harness.account.pk,
        idempotency_key=post_preview_intent.idempotency_key,
    )
    assert future_reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE

    position.available_quantity = Decimal("300.000000")
    position.available_quantity_known = False
    position.save(update_fields=["available_quantity", "available_quantity_known"])
    with monkeypatch.context() as patch:
        patch.setattr(sellable_repository, "timezone", _FixedRepositoryTime(second_cutoff))
        with report_contracts._capture_write_sql() as report_mutations:
            report = _run_simulated_report(
                user_id=harness.user_id,
                account_id=cast(int, harness.account.pk),
            )
    assert report_mutations == []
    (row,) = _rows(report)
    assert report["source_scope"] == "simulated_position"
    assert report["portfolio_mapping_id"] is None
    assert row["source_position_id"] is None
    assert row["position_mapping_id"] is None
    assert row["ledger_total_quantity"] == "300.000000"
    assert row["ledger_available_quantity"] == "100.000000"
    assert row["active_sell_hold_quantity"] == "0.000000"
    assert row["supported_sellable_quantity"] == "100.000000"
    assert row["repair_available_quantity"] == "100.000000"
    assert row["repair_ready"] is True
    assert row["repair_needed"] is True
    assert position.available_quantity == Decimal("300.000000")
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 0

    account_id = cast(int, harness.account.pk)
    position_id = cast(int, position.pk)
    command = _command_from_preview(
        user_id=harness.user_id,
        account_id=account_id,
        target_position_id=position_id,
        idempotency_key="g5-apply-replay-001",
        row=row,
    )

    position.refresh_from_db()
    position_before_future_preview = (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    )
    future_preview = replace(
        command,
        preview_evidence_cutoff_at=datetime.now(UTC) + timedelta(days=1),
    )
    with report_contracts._capture_write_sql() as future_preview_writes:
        with pytest.raises(
            CommandError,
            match="HISTORICAL_SELLABLE_REPAIR_PREVIEW_INVALID",
        ):
            _run_apply_command(future_preview)
    assert future_preview_writes == []
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 0
    position.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    ) == position_before_future_preview

    original_locked_chain = sellable_repository._locked_fill_chain

    def _unsupported_settlement_chain(
        *,
        reservation_row: SimulatedOrderReservationModel,
        using: str,
    ) -> _LockedFillChain:
        """Return valid V4 receipt rows with one unsupported stored status value."""

        chain = original_locked_chain(reservation_row=reservation_row, using=using)
        for receipt_row, _ in chain.rows:
            if receipt_row.trade_id == second_trade.pk:
                receipt_row.trade.settlement_status = "unrecognized"
        return chain

    position.refresh_from_db()
    position_before_invalid_settlement = (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            sellable_repository,
            "_locked_fill_chain",
            _unsupported_settlement_chain,
        )
        with report_contracts._capture_write_sql() as invalid_settlement_writes:
            with pytest.raises(SimulatedTradeExecutionBlocked) as invalid_settlement:
                build_historical_sellable_repair_service().execute(
                    command=command,
                    database_alias="default",
                )
        assert invalid_settlement.value.code == "HISTORICAL_SELLABLE_LEDGER_INVALID"
        assert "LEDGER_SETTLEMENT_STATUS_INVALID" in str(invalid_settlement.value)
        assert invalid_settlement_writes == []
        assert HistoricalSellableRepairJournalModel._default_manager.count() == 0
        position.refresh_from_db()
        assert (
            position.quantity,
            position.available_quantity,
            position.available_quantity_known,
            position.updated_at,
        ) == position_before_invalid_settlement

    # Build this hold from the supported settled balance; the other 200 shares
    # are still pending and must not make the full 300-share position sellable.
    position.available_quantity = Decimal("100.000000")
    position.available_quantity_known = True
    position.save(update_fields=["available_quantity", "available_quantity_known"])
    preview_change_intent = reservation_repository._intent_for(
        harness,
        side=SimulatedTradeSide.SELL,
        key="g5-preview-proof-change-hold-001",
        quantity=Decimal("10.000000"),
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
    )
    _advance_reservation_clock(harness, second_cutoff)
    harness.reserve.execute(preview_change_intent, fee_budget=None, as_of=second_cutoff)
    position.available_quantity = Decimal("300.000000")
    position.available_quantity_known = False
    position.save(update_fields=["available_quantity", "available_quantity_known"])
    with monkeypatch.context() as patch:
        patch.setattr(sellable_repository, "timezone", _FixedRepositoryTime(second_cutoff))
        changed_proof_report = _run_simulated_report(
            user_id=harness.user_id,
            account_id=account_id,
        )
    (changed_proof_row,) = _rows(changed_proof_report)
    assert changed_proof_row["evidence_proof_hash"] != row["evidence_proof_hash"]
    assert changed_proof_row["active_sell_hold_quantity"] == "10.000000"
    position.refresh_from_db()
    position_before_changed_proof_apply = (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    )
    with report_contracts._capture_write_sql() as changed_proof_writes:
        with pytest.raises(SimulatedTradeExecutionBlocked) as stale_proof:
            build_historical_sellable_repair_service().execute(
                command=command,
                database_alias="default",
            )
    assert stale_proof.value.code == "HISTORICAL_SELLABLE_REPAIR_PREVIEW_STALE"
    assert changed_proof_writes == []
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 0
    position.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    ) == position_before_changed_proof_apply

    cancel_preview_change_hold = CancelSimulatedOrderReservationUseCase(
        repository=harness.repository,
        clock=_Clock(second_cutoff + timedelta(minutes=1)),
    )
    cancel_preview_change_hold.execute(
        account_id=account_id,
        user_id=harness.user_id,
        idempotency_key=preview_change_intent.idempotency_key,
    )
    with monkeypatch.context() as patch:
        patch.setattr(sellable_repository, "timezone", _FixedRepositoryTime(second_cutoff))
        restored_proof_report = _run_simulated_report(
            user_id=harness.user_id,
            account_id=account_id,
        )
    (restored_proof_row,) = _rows(restored_proof_report)
    assert restored_proof_row["evidence_proof_hash"] == row["evidence_proof_hash"]

    position.available_quantity = Decimal("299.000000")
    position.save(update_fields=["available_quantity"])
    with pytest.raises(SimulatedTradeExecutionBlocked) as stale_preview:
        build_historical_sellable_repair_service().execute(
            command=command,
            database_alias="default",
        )
    assert stale_preview.value.code == "HISTORICAL_SELLABLE_REPAIR_PREVIEW_STALE"
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 0
    position.available_quantity = Decimal("300.000000")
    position.available_quantity_known = False
    position.save(update_fields=["available_quantity", "available_quantity_known"])
    updated_at_before_apply = position.updated_at

    first_apply_json = _run_apply_command(command)
    assert first_apply_json["outcome"] == "applied"
    first_apply_event_id_value = first_apply_json.get("journal_event_id")
    assert type(first_apply_event_id_value) is int
    first_apply_event_id = first_apply_event_id_value
    first_apply = HistoricalSellableRepairJournalModel._default_manager.get(pk=first_apply_event_id)
    assert first_apply.before_available_quantity == Decimal("300.000000")
    assert first_apply.before_available_quantity_known is False
    assert first_apply.after_available_quantity == Decimal("100.000000")
    assert first_apply.after_available_quantity_known is True
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 1
    assert first_apply.created_at > first_apply.evidence_cutoff_at
    position.refresh_from_db()
    assert position.available_quantity == Decimal("100.000000")
    assert position.available_quantity_known is True
    assert position.quantity == Decimal("300.000000")
    assert position.updated_at > updated_at_before_apply
    updated_at_after_apply = position.updated_at

    tampered_replay = replace(
        command,
        preview_available_quantity=Decimal("301.000000"),
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as replay_conflict:
        build_historical_sellable_repair_service().execute(
            command=tampered_replay,
            database_alias="default",
        )
    assert replay_conflict.value.code == "HISTORICAL_SELLABLE_REPAIR_IDEMPOTENCY_CONFLICT"
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 1

    replayed_apply = build_historical_sellable_repair_service().execute(
        command=command,
        database_alias="default",
    )
    assert replayed_apply.outcome == "replayed"
    assert replayed_apply.journal_event_id == first_apply_event_id
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 1
    position.refresh_from_db()
    assert position.updated_at == updated_at_after_apply

    rollback_command = HistoricalSellableRepairCommand(
        action="rollback",
        user_id=harness.user_id,
        account_id=account_id,
        target_position_id=position_id,
        actor_user_id=harness.user_id,
        idempotency_key="g5-rollback-replay-001",
        apply_event_id=first_apply_event_id,
    )
    rolled_back = _run_rollback_command(rollback_command)
    assert rolled_back["outcome"] == "rolled_back"
    assert rolled_back["before_available_quantity"] == "100.000000"
    assert rolled_back["after_available_quantity"] == "300.000000"
    assert rolled_back["after_available_quantity_known"] is False
    rollback_event_id_value = rolled_back.get("journal_event_id")
    assert type(rollback_event_id_value) is int
    rollback_event_id = rollback_event_id_value
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 2
    rollback_event = HistoricalSellableRepairJournalModel._default_manager.get(pk=rollback_event_id)
    position.refresh_from_db()
    assert position.available_quantity == Decimal("300.000000")
    assert position.available_quantity_known is False
    assert position.updated_at > first_apply.created_at
    assert rollback_event.created_at >= position.updated_at

    rollback_replay = _run_rollback_command(rollback_command)
    assert rollback_replay["outcome"] == "replayed"
    assert rollback_replay["journal_event_id"] == rollback_event_id
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 2

    with monkeypatch.context() as patch:
        patch.setattr(sellable_repository, "timezone", _FixedRepositoryTime(second_cutoff))
        second_report = _run_simulated_report(
            user_id=harness.user_id,
            account_id=account_id,
        )
    (second_row,) = _rows(second_report)
    second_apply_command = _command_from_preview(
        user_id=harness.user_id,
        account_id=account_id,
        target_position_id=position_id,
        idempotency_key="g5-apply-after-rollback-001",
        row=second_row,
    )
    second_apply_json = _run_apply_command(second_apply_command)
    assert second_apply_json["outcome"] == "applied"
    second_apply_id_value = second_apply_json.get("journal_event_id")
    assert type(second_apply_id_value) is int
    second_apply_event_id = second_apply_id_value
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 3

    post_fill_at = second_cutoff + timedelta(days=1, minutes=5)
    post_fill_cutoff = post_fill_at + timedelta(minutes=2)
    post_fill_event = replace(
        rows.event,
        source_event_id="g5-post-apply-fill-001",
        source_snapshot_id="g5-post-apply-snapshot-001",
        source_snapshot_hash="3" * 64,
        reservation_id=cast(int, future_reservation.pk),
        account_id=cast(int, future_reservation.account_id),
        user_id=cast(int, future_reservation.owner_user_id),
        order_idempotency_key=future_reservation.idempotency_key,
        intent_payload_hash=future_reservation.intent_payload_hash,
        reservation_request_hash=future_reservation.reservation_request_hash,
        plan_snapshot_hash=future_reservation.plan_snapshot_hash,
        security_id=future_reservation.security_id,
        asset_code=future_reservation.asset_code,
        side=SimulatedTradeSide.BUY,
        event_kind=row_reader.LocalSimulatedFillEventKind.FINAL_FILL,
        quantity=Decimal("50.000000"),
        event_payload_hash="4" * 64,
        occurred_at=post_fill_at,
        source_observed_at=post_fill_at,
        source_available_at=post_fill_at,
        recorded_at=post_fill_at,
    )
    post_fill_proof = build_order_fill_settlement_proof(
        calendar_evidence=post_preview_calendar,
        calendar_read_cutoff=post_fill_cutoff,
        fill_occurred_at=post_fill_at,
        settlement_exchange=rows.proof.settlement_exchange,
        settlement_lag_sessions=rows.proof.settlement_lag_sessions,
    )
    post_fill_reader = fill_repository._EventReader(post_fill_event, [])
    post_fill_writer = DjangoSimulatedOrderFillRepository(
        event_reader=post_fill_reader,
        using="default",
    )
    post_fill_result = fill_repository._invoke(
        post_fill_writer,
        post_fill_event,
        post_fill_proof,
        clock=fill_repository._FixedClock(post_fill_cutoff),
    )
    assert post_fill_result.replayed is False
    position.refresh_from_db()
    position_after_trade = (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    )
    assert position_after_trade[:3] == (
        Decimal("350.000000"),
        Decimal("100.000000"),
        True,
    )
    replay_after_trade = build_historical_sellable_repair_service().execute(
        command=second_apply_command,
        database_alias="default",
    )
    assert replay_after_trade.outcome == "replayed"
    assert replay_after_trade.journal_event_id == second_apply_event_id
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 3
    position.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    ) == position_after_trade
    rollback_after_trade = HistoricalSellableRepairCommand(
        action="rollback",
        user_id=harness.user_id,
        account_id=account_id,
        target_position_id=position_id,
        actor_user_id=harness.user_id,
        idempotency_key="g5-rollback-after-trade-001",
        apply_event_id=second_apply_event_id,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as changed_trade:
        build_historical_sellable_repair_service().execute(
            command=rollback_after_trade,
            database_alias="default",
        )
    assert changed_trade.value.code == "HISTORICAL_SELLABLE_LEDGER_INVALID"
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 3
    position.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    ) == position_after_trade

    position.available_quantity = Decimal("350.000000")
    position.available_quantity_known = False
    position.save(update_fields=["available_quantity", "available_quantity_known"])
    with monkeypatch.context() as patch:
        patch.setattr(sellable_repository, "timezone", _FixedRepositoryTime(post_fill_cutoff))
        third_report = _run_simulated_report(
            user_id=harness.user_id,
            account_id=account_id,
        )
    (third_row,) = _rows(third_report)
    third_apply_command = _command_from_preview(
        user_id=harness.user_id,
        account_id=account_id,
        target_position_id=position_id,
        idempotency_key="g5-test-003",
        row=third_row,
    )
    third_apply_json = _run_apply_command(third_apply_command)
    assert third_apply_json["outcome"] == "applied"
    third_apply_id_value = third_apply_json.get("journal_event_id")
    assert type(third_apply_id_value) is int
    third_apply_event_id = third_apply_id_value
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 4
    position.refresh_from_db()
    post_fill_trade = SimulatedTradeModel._default_manager.get(pk=post_fill_result.trade_id)
    second_trade.refresh_from_db()
    assert second_trade.settlement_status == "pending"
    assert second_trade.quantity == Decimal("200.000000")
    assert post_fill_trade.settlement_status == "pending"
    assert post_fill_trade.quantity == Decimal("50.000000")
    assert second_trade.quantity + post_fill_trade.quantity == (
        position.quantity - position.available_quantity
    )
    assert position.quantity == Decimal("350.000000")
    assert position.available_quantity == Decimal("100.000000")
    assert position.available_quantity_known is True
    post_repair_sell_intent = reservation_repository._intent_for(
        harness,
        side=SimulatedTradeSide.SELL,
        key="g5-post-repair-sell-hold-001",
        quantity=Decimal("100.000000"),
        security_id=SECURITY_ID,
        asset_code=ASSET_CODE,
    )
    _advance_reservation_clock(harness, post_fill_cutoff)
    harness.reserve.execute(
        post_repair_sell_intent,
        fee_budget=None,
        as_of=post_fill_cutoff,
    )
    rollback_after_hold = HistoricalSellableRepairCommand(
        action="rollback",
        user_id=harness.user_id,
        account_id=account_id,
        target_position_id=position_id,
        actor_user_id=harness.user_id,
        idempotency_key="g5-rollback-after-hold-001",
        apply_event_id=third_apply_event_id,
    )
    position.refresh_from_db()
    position_before_hold_rollback = (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        build_historical_sellable_repair_service().execute(
            command=rollback_after_hold,
            database_alias="default",
        )
    assert blocked.value.code == "HISTORICAL_SELLABLE_REPAIR_EVIDENCE_CHANGED"
    assert HistoricalSellableRepairJournalModel._default_manager.count() == 4
    position.refresh_from_db()
    assert (
        position.quantity,
        position.available_quantity,
        position.available_quantity_known,
        position.updated_at,
    ) == position_before_hold_rollback
    assert position.available_quantity == Decimal("100.000000")
    assert SimulatedOrderReservationModel._default_manager.filter(
        account=harness.account,
        idempotency_key="g5-post-repair-sell-hold-001",
        status=SimulatedOrderReservationModel.STATUS_ACTIVE,
    ).exists()
