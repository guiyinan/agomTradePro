"""Exercise expiry-safe application of one durably recorded local match."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

import apps.simulated_trading.infrastructure.order_reservation_fill_repository as fill_repository_module
import apps.simulated_trading.local_daily_match_composition as local_daily_match_composition
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchDecision,
    RecordLocalDailyMatchUseCase,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ApplySimulatedOrderFillCommand,
    LocalSimulatedFillEventV1,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.local_order_matching import LocalMatchOutcome
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
)
from apps.simulated_trading.infrastructure.local_daily_match_codec import (
    event_payload_hash as _daily_event_payload_hash,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
    _build_daily_match_settlement_proof,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
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
    _calendar,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _AS_OF as _PRODUCER_AS_OF,
)
from tests.component.simulated_trading.test_local_daily_match_repository import (
    _account_financial_state,
    _command,
    _FixedClock,
    _ledger_counts,
    _QualificationReader,
    _qualified_input,
    _reserve,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _ExchangeCalendarReader,
    _initial_position_mark,
    _InitialPositionMarkReader,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _reader_rows,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=[
        "apps.simulated_trading",
        "django.contrib.auth",
        "django.contrib.contenttypes",
    ],
)

_SESSION = date(2026, 10, 16)
_APPLY_AT = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
_OPEN_DATES = {
    date(2026, 10, 16),
    date(2026, 10, 19),
    date(2026, 10, 20),
    date(2026, 10, 21),
}
_FUTURE_RECORDED_AT = datetime(2026, 10, 21, 2, 0, tzinfo=UTC)


def _record_match(
    harness: _Harness,
    reservation: SimulatedOrderReservationModel,
    *,
    operation_key: str,
    close_price: Decimal = Decimal("9.50"),
    traded_volume: Decimal = Decimal("100"),
    as_of: datetime = _PRODUCER_AS_OF,
    session_date: date = _SESSION,
) -> tuple[LocalDailyMatchCommand, LocalDailyMatchDecision, _QualificationReader]:
    """Persist one real local decision against a supplied accepted reservation."""

    command = _command(
        harness,
        operation_key=operation_key,
        order_key=reservation.idempotency_key,
    )
    if session_date != command.session_date:
        command = replace(command, session_date=session_date)
    qualified = _qualified_input(
        security_id=reservation.security_id,
        close_price=close_price,
        as_of=as_of,
    )
    if session_date != qualified.observation.session_date:
        interval_end = datetime(
            session_date.year,
            session_date.month,
            session_date.day,
            15,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).astimezone(UTC)
        qualified = replace(
            qualified,
            observation=replace(
                qualified.observation,
                session_date=session_date,
                observation_id=stable_local_daily_observation_id(
                    reservation.security_id,
                    session_date,
                ),
                observed_at=interval_end,
                available_at=interval_end + timedelta(hours=1),
            ),
        )
    qualified = replace(
        qualified,
        observation=replace(
            qualified.observation,
            traded_volume=traded_volume,
        ),
    )
    reader = _QualificationReader(qualified)
    decision = RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using="default"),
        qualification_reader=reader,
        clock=_FixedClock(as_of),
    ).execute(command)
    return command, decision, reader


def _extend_identity_before_reservation(
    harness: _Harness,
    *,
    monkeypatch: pytest.MonkeyPatch,
    valid_until: datetime,
) -> None:
    """Seal a test-only explicit identity window before creating the reservation."""

    identity_reader = harness.preparer._identity_reader
    original_read = identity_reader.get_execution_instrument_identity

    def read_with_explicit_validity(
        *, security_id: str, asset_code: str, as_of: datetime
    ) -> ExecutionInstrumentIdentityEvidenceV1:
        """Return the ordinary fixture identity with a validity sealed at reserve time."""

        evidence = original_read(
            security_id=security_id,
            asset_code=asset_code,
            as_of=as_of,
        )
        return replace(evidence, identity_valid_until=valid_until)

    monkeypatch.setattr(
        identity_reader,
        "get_execution_instrument_identity",
        read_with_explicit_validity,
    )


def _apply_command(event: LocalSimulatedFillEventV1) -> ApplySimulatedOrderFillCommand:
    """Address one exact daily-match event and its original payload hash."""

    return ApplySimulatedOrderFillCommand(
        account_id=event.account_id,
        user_id=event.user_id,
        order_idempotency_key=event.order_idempotency_key,
        source_namespace=event.source_namespace,
        fill_event_id=event.source_event_id,
        expected_event_payload_hash=event.event_payload_hash,
    )


def _event_settlement_proof(
    *, reservation: SimulatedOrderReservationModel, event: LocalSimulatedFillEventV1
) -> OrderFillSettlementProof:
    """Build the exact event-time proof from the reservation's immutable calendar."""

    assert type(reservation.settlement_lag_sessions) is int
    assert type(event.interval_end_at) is datetime
    session_date = event.interval_end_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    return _build_daily_match_settlement_proof(
        reservation_row=reservation,
        event=event,
        session_date=session_date,
        settlement_exchange="SH",
        settlement_lag_sessions=reservation.settlement_lag_sessions,
    )


def _event_for_reservation(
    event: LocalSimulatedFillEventV1,
    reservation: SimulatedOrderReservationModel,
    *,
    source_event_id: str,
    price: Decimal | None = None,
    recorded_at: datetime | None = None,
) -> LocalSimulatedFillEventV1:
    """Build a syntactically valid claimed event while retaining its exact scope."""

    assert type(reservation.pk) is int
    placeholder = replace(
        event,
        source_event_id=source_event_id,
        event_payload_hash="0" * 64,
        reservation_id=reservation.pk,
        account_id=reservation.account_id,
        user_id=reservation.owner_user_id,
        order_idempotency_key=reservation.idempotency_key,
        intent_payload_hash=reservation.intent_payload_hash,
        reservation_request_hash=reservation.reservation_request_hash,
        plan_snapshot_hash=reservation.plan_snapshot_hash,
        security_id=reservation.security_id,
        asset_code=reservation.asset_code,
        side=event.side,
        price=price if price is not None else event.price,
        recorded_at=recorded_at if recorded_at is not None else event.recorded_at,
    )
    return replace(
        placeholder,
        event_payload_hash=_daily_event_payload_hash(placeholder),
    )


def _assert_direct_writer_rejects(
    *,
    account: SimulatedAccountModel,
    reservation: SimulatedOrderReservationModel,
    event: LocalSimulatedFillEventV1,
    expected_code: str = "SIMULATED_FILL_SOURCE_INVALID",
) -> None:
    """Exercise the locked writer and prove a claimed source cannot mutate finance."""

    reservation.refresh_from_db()
    before = _no_write_state(account=account, reservation=reservation)
    source_reader = _EventReader(event, calls=[])
    current_calendar_reader = _ExchangeCalendarReader(
        _calendar(as_of=_APPLY_AT, open_dates=_OPEN_DATES)
    )
    mark_reader = _InitialPositionMarkReader(
        proof=None,
        calls=[],
    )
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=source_reader,
        initial_position_mark_reader=mark_reader,
        current_calendar_reader=current_calendar_reader,
        using="default",
    )
    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        repository.apply_fill_event(
            event=event,
            expected_event_payload_hash=event.event_payload_hash,
            settlement_proof=_event_settlement_proof(reservation=reservation, event=event),
            clock=_FixedClock(_APPLY_AT),
        )
    assert raised.value.code == expected_code
    assert source_reader.calls == []
    assert current_calendar_reader.coverage_requests == []
    assert mark_reader.calls == []
    assert _no_write_state(account=account, reservation=reservation) == before


def _no_write_state(
    *, account: SimulatedAccountModel, reservation: SimulatedOrderReservationModel
) -> tuple[object, ...]:
    """Snapshot the account, ledger and accepted-order resources before a rejection."""

    reservation.refresh_from_db()
    return (
        _ledger_counts(account),
        _account_financial_state(account),
        reservation.status,
        reservation.filled_quantity,
        reservation.cash_consumed,
        reservation.shares_consumed,
        reservation.cash_released,
        reservation.shares_released,
    )


def test_expired_identity_still_applies_original_durable_match_once(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply a pre-expiry match at a later valid session without changing its clocks."""

    del ledger, persisted_receipt_schema
    with isolated_schema((LocalDailyMatchModel,)):
        rows = _reader_rows(reservation_harness)
        rows.reservation.refresh_from_db()
        identity_payload = rows.reservation.plan_snapshot.get("identity_evidence")
        identity = ExecutionInstrumentIdentityEvidenceV1.from_payload(identity_payload)
        assert identity.identity_valid_from <= _PRODUCER_AS_OF < identity.identity_valid_until
        assert identity.identity_valid_until <= _APPLY_AT

        owner = get_user_model().objects.get(pk=reservation_harness.user_id)
        assert owner.is_active is True

        command: LocalDailyMatchCommand = _command(
            reservation_harness,
            operation_key="expired-identity-durable-match",
            order_key=rows.reservation.idempotency_key,
        )
        qualified = _qualified_input(
            security_id=rows.reservation.security_id,
            close_price=Decimal("9.50"),
        )
        qualified = replace(
            qualified,
            observation=replace(
                qualified.observation,
                traded_volume=Decimal("100"),
            ),
        )
        qualification_reader = _QualificationReader(qualified)
        producer = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=qualification_reader,
            clock=_FixedClock(_PRODUCER_AS_OF),
        )

        ledger_before = _ledger_counts(reservation_harness.account)
        financial_before = _account_financial_state(reservation_harness.account)
        decision = producer.execute(command)

        assert decision.result.outcome is LocalMatchOutcome.MATCHED
        event = decision.event
        assert event is not None
        assert event.source_namespace == "simulated-local-daily-match.v1"
        assert event.source_version == LOCAL_DAILY_INTERVAL_SOURCE_VERSION
        assert event.occurred_at == datetime(2026, 10, 16, 7, 0, tzinfo=UTC)
        assert event.interval_end_at == event.occurred_at
        assert event.source_observed_at is None
        assert event.source_available_at is None
        assert event.local_known_at == qualified.observation.available_at
        assert event.recorded_at == _PRODUCER_AS_OF
        assert event.quantity == Decimal("10.000000")
        assert event.price == Decimal("9.50")
        assert len(qualification_reader.calls) == 2
        assert _ledger_counts(reservation_harness.account) == ledger_before
        assert _account_financial_state(reservation_harness.account) == financial_before
        assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0

        retained = DjangoLocalDailyMatchEventReader(using="default").read_event(
            account_id=event.account_id,
            user_id=event.user_id,
            order_idempotency_key=event.order_idempotency_key,
            source_namespace=event.source_namespace,
            fill_event_id=event.source_event_id,
            as_of=_APPLY_AT,
        )
        assert retained == event
        assert (
            LocalDailyMatchModel.objects.filter(
                account=reservation_harness.account,
                reservation=rows.reservation,
                operation_key=command.operation_key,
            ).count()
            == 1
        )

        current_calendar_evidence = _calendar(
            as_of=_APPLY_AT,
            open_dates=_OPEN_DATES,
        )
        current_calendar_reader = _ExchangeCalendarReader(current_calendar_evidence)
        mark_reader = _InitialPositionMarkReader(
            proof=_initial_position_mark(rows, read_at=_APPLY_AT),
            calls=[],
        )

        def current_calendar_reader_factory(
            *,
            dataset_key: str,
            runtime_environment: str,
            read_publication: object | None = None,
        ) -> _ExchangeCalendarReader:
            """Inject a current-cutoff calendar through the public composition seam."""

            assert dataset_key == "trade_cal"
            assert runtime_environment == "test"
            assert read_publication is not None
            return current_calendar_reader

        def initial_position_mark_reader_factory(
            *,
            runtime_environment: str,
            calendar_dataset_key: str,
        ) -> _InitialPositionMarkReader:
            """Inject one qualified first-position mark through the public composition seam."""

            assert runtime_environment == "test"
            assert calendar_dataset_key == "trade_cal"
            return mark_reader

        monkeypatch.setattr(
            local_daily_match_composition,
            "build_current_published_execution_calendar_reader",
            current_calendar_reader_factory,
        )
        monkeypatch.setattr(
            local_daily_match_composition,
            "build_published_initial_position_mark_reader",
            initial_position_mark_reader_factory,
        )
        apply_command = _apply_command(event)
        apply_use_case = local_daily_match_composition.build_apply_local_daily_match_use_case(
            runtime_environment="test",
            calendar_dataset_key="trade_cal",
            clock=_FixedClock(_APPLY_AT),
            using="default",
        )

        applied = apply_use_case.execute(apply_command)

        assert applied.replayed is False
        assert applied.event_payload_hash == event.event_payload_hash
        assert applied.source_namespace == event.source_namespace
        assert applied.source_version == event.source_version
        assert current_calendar_reader.coverage_requests == [_SESSION]
        assert len(mark_reader.calls) == 1
        rows.reservation.refresh_from_db()
        trade = SimulatedTradeModel.objects.get(pk=applied.trade_id)
        receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
        assert trade.execution_time == event.occurred_at
        assert trade.price == event.price
        assert trade.quantity == event.quantity
        assert trade.amount == event.quantity * event.price
        assert receipt.source_event_id == event.source_event_id
        assert receipt.source_event_payload_hash == event.event_payload_hash
        decoded = read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=receipt,
            trade_row=trade,
        )
        assert decoded.event == event
        assert decoded.event.recorded_at == _PRODUCER_AS_OF
        assert decoded.economics.fill_occurred_at == event.occurred_at
        assert decoded.economics.gross_amount == event.quantity * event.price
        assert PositionModel.objects.filter(
            account=reservation_harness.account,
            asset_code=event.asset_code,
        ).exists()
        assert _ledger_counts(reservation_harness.account)[1] == 1

        state_after_fill = _ledger_counts(reservation_harness.account)

        def fail_if_identity_cutoff_is_read(**kwargs: object) -> datetime | None:
            """An exact receipt must bypass source-identity qualification entirely."""

            del kwargs
            raise AssertionError("receipt replay must not revalidate source identity")

        monkeypatch.setattr(
            fill_repository_module,
            "local_daily_match_fill_identity_as_of",
            fail_if_identity_cutoff_is_read,
        )

        class _NoClock:
            """Fail if exact receipt replay asks for a current clock."""

            def now(self) -> datetime:
                raise AssertionError("receipt replay must not read the clock")

        replay = local_daily_match_composition.build_apply_local_daily_match_use_case(
            runtime_environment="test",
            calendar_dataset_key="trade_cal",
            clock=_NoClock(),
            using="default",
        ).execute(apply_command)
        assert replay.replayed is True
        assert replay.trade_id == applied.trade_id
        assert current_calendar_reader.coverage_requests == [_SESSION]
        assert len(mark_reader.calls) == 1
        assert _ledger_counts(reservation_harness.account) == state_after_fill

        rows.reservation.refresh_from_db()
        consumed = (
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
        )
        held_cash = (
            rows.reservation.cash_reserved
            - rows.reservation.cash_consumed
            - rows.reservation.cash_released
        )
        held_shares = (
            rows.reservation.shares_reserved
            - rows.reservation.shares_consumed
            - rows.reservation.shares_released
        )
        assert held_cash > Decimal("0.00") or held_shares > Decimal("0.000000")
        cancelled = reservation_harness.repository.cancel_order(
            account_id=event.account_id,
            user_id=event.user_id,
            idempotency_key=event.order_idempotency_key,
            clock=_FixedClock(_APPLY_AT),
        )
        rows.reservation.refresh_from_db()
        assert cancelled.status.value == "cancelled"
        assert (
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
        ) == consumed
        assert (
            rows.reservation.cash_released
            == rows.reservation.cash_reserved - rows.reservation.cash_consumed
        )
        assert rows.reservation.shares_released == (
            rows.reservation.shares_reserved - rows.reservation.shares_consumed
        )


def test_local_namespace_claims_require_one_exact_persisted_matched_event(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject absent, altered, foreign, no-match, damaged and future local claims."""

    del ledger, persisted_receipt_schema
    with isolated_schema((LocalDailyMatchModel,)):
        rows = _reader_rows(reservation_harness)
        base_reservation = rows.reservation
        base_command = _command(
            reservation_harness,
            operation_key="identity-claim-base-match",
            order_key=base_reservation.idempotency_key,
        )
        qualified = _qualified_input(
            security_id=base_reservation.security_id,
            close_price=Decimal("9.50"),
        )
        qualified = replace(
            qualified,
            observation=replace(
                qualified.observation,
                traded_volume=Decimal("100"),
            ),
        )
        base_reader = _QualificationReader(qualified)
        base_decision = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=base_reader,
            clock=_FixedClock(_PRODUCER_AS_OF),
        ).execute(base_command)
        assert base_decision.result.outcome is LocalMatchOutcome.MATCHED
        base_event = base_decision.event
        assert base_event is not None
        account = reservation_harness.account

        missing_row_claim = _event_for_reservation(
            base_event,
            base_reservation,
            source_event_id="claimed-but-no-persisted-row",
        )
        _assert_direct_writer_rejects(
            account=account,
            reservation=base_reservation,
            event=missing_row_claim,
        )

        _extend_identity_before_reservation(
            reservation_harness,
            monkeypatch=monkeypatch,
            valid_until=datetime(2026, 10, 23, 0, 0, tzinfo=UTC),
        )
        reservation_harness.preparer._calendar_reader.evidence = _calendar(
            as_of=AS_OF,
            open_dates={
                date(2026, 10, 16),
                date(2026, 10, 19),
                date(2026, 10, 20),
                date(2026, 10, 21),
                date(2026, 10, 22),
            },
            end=date(2026, 10, 22),
        )
        other_reservation = _reserve(
            reservation_harness,
            order_key="identity-claim-other-order",
        )
        no_match_command, no_match_decision, _ = _record_match(
            reservation_harness,
            other_reservation,
            operation_key="identity-claim-no-match",
            close_price=Decimal("10.50"),
            as_of=datetime(2026, 10, 20, 2, 0, tzinfo=UTC),
            session_date=date(2026, 10, 19),
        )
        assert no_match_decision.result.outcome is LocalMatchOutcome.NO_MATCH
        assert no_match_decision.event is None
        no_match_claim = _event_for_reservation(
            base_event,
            other_reservation,
            source_event_id=no_match_command.operation_key,
        )
        _assert_direct_writer_rejects(
            account=account,
            reservation=other_reservation,
            event=no_match_claim,
        )

        wrong_scope_claim = _event_for_reservation(
            base_event,
            other_reservation,
            source_event_id=base_command.operation_key,
        )
        _assert_direct_writer_rejects(
            account=account,
            reservation=other_reservation,
            event=wrong_scope_claim,
        )

        replacement_claim = _event_for_reservation(
            base_event,
            base_reservation,
            source_event_id=base_command.operation_key,
            price=Decimal("9.51"),
        )
        _assert_direct_writer_rejects(
            account=account,
            reservation=base_reservation,
            event=replacement_claim,
        )

        stored = LocalDailyMatchModel.objects.get(
            account=account,
            reservation=base_reservation,
            operation_key=base_command.operation_key,
        )
        original_digest = stored.record_digest
        table_name = connection.ops.quote_name(LocalDailyMatchModel._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table_name} SET record_digest = %s WHERE id = %s",
                ("0" * 64, stored.pk),
            )
        try:
            _assert_direct_writer_rejects(
                account=account,
                reservation=base_reservation,
                event=base_event,
            )
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {table_name} SET record_digest = %s WHERE id = %s",
                    (original_digest, stored.pk),
                )

        future_command, future_decision, _ = _record_match(
            reservation_harness,
            other_reservation,
            operation_key="identity-claim-future-record",
            as_of=_FUTURE_RECORDED_AT,
            session_date=date(2026, 10, 20),
        )
        assert future_decision.result.outcome is LocalMatchOutcome.MATCHED
        future_event = future_decision.event
        assert future_event is not None
        assert future_event.recorded_at == _FUTURE_RECORDED_AT
        assert future_event.recorded_at > _APPLY_AT
        assert future_command.session_date == date(2026, 10, 20)
        _assert_direct_writer_rejects(
            account=account,
            reservation=other_reservation,
            event=future_event,
        )


def test_other_daily_namespace_keeps_current_identity_cutoff(
    ledger: tuple[object, SimulatedAccountModel],
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Old daily-format events outside the dedicated namespace get no old-time privilege."""

    del ledger, persisted_receipt_schema
    with isolated_schema((LocalDailyMatchModel,)):
        rows = _reader_rows(reservation_harness)
        identity_payload = rows.reservation.plan_snapshot.get("identity_evidence")
        identity = ExecutionInstrumentIdentityEvidenceV1.from_payload(identity_payload)
        local_known_at = rows.event.occurred_at + timedelta(hours=1)
        generic_daily_event = replace(
            rows.event,
            source_namespace="generic-daily-source",
            source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
            source_event_id="generic-daily-expired-identity-claim",
            event_payload_hash="5" * 64,
            source_observed_at=None,
            source_available_at=None,
            recorded_at=_PRODUCER_AS_OF,
            observation_basis="daily_interval_end",
            interval_end_at=rows.event.occurred_at,
            local_known_at=local_known_at,
        )
        assert generic_daily_event.source_namespace != "simulated-local-daily-match.v1"
        assert generic_daily_event.observation_basis == "daily_interval_end"
        assert generic_daily_event.recorded_at < _APPLY_AT
        assert (
            identity.identity_valid_from
            <= generic_daily_event.recorded_at
            < identity.identity_valid_until
            <= _APPLY_AT
        )
        _assert_direct_writer_rejects(
            account=reservation_harness.account,
            reservation=rows.reservation,
            event=generic_daily_event,
            expected_code="SIMULATED_FILL_PLAN_INVALID",
        )
