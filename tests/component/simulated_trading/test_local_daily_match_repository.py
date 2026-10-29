"""Storage and cancellation contract tests for local daily-match decisions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import connection, transaction

import apps.simulated_trading.local_daily_match_composition as local_daily_match_composition
from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.local_daily_match import (
    LocalDailyMatchCommand,
    LocalDailyMatchEvidenceKind,
    LocalDailyMatchSourceReference,
    QualifiedLocalDailyMatchInput,
    RecordLocalDailyMatchUseCase,
    stable_local_daily_observation_id,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillSourceBinding,
    OrderFillContext,
)
from apps.simulated_trading.application.order_reservation_fill_calendar import (
    OrderFillSettlementCalendarResolver,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
)
from apps.simulated_trading.domain.local_daily_simulation_policy import (
    LocalDailySimulationPolicy,
    LocalDailySimulationPolicyBinding,
    LocalDailySimulationPolicyRuntimeProvenance,
)
from apps.simulated_trading.domain.local_order_matching import (
    LocalMatchLimitState,
    LocalMatchObservation,
    LocalMatchOutcome,
    LocalMatchPriceAdjustment,
    LocalMatchTradingState,
    LocalMatchVolumeUnit,
)
from apps.simulated_trading.infrastructure.account_repository import (
    DjangoSimulatedAccountRepository,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from apps.simulated_trading.infrastructure.local_daily_match_models import (
    LocalDailyMatchModel,
)
from apps.simulated_trading.infrastructure.local_daily_match_repository import (
    DjangoLocalDailyMatchRepository,
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
from apps.simulated_trading.infrastructure.order_reservation_repository import (
    DjangoSimulatedOrderReservationRepository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF as RESERVATION_AS_OF,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    _Clock,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _account_financial_state,
    _ExchangeCalendarReader,
    _initial_position_mark,
    _InitialPositionMarkReader,
    _ledger_counts,
    _reservation_unfilled,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _reader_rows,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
    _intent_for,
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
_AS_OF = datetime(2026, 10, 17, 1, 59, tzinfo=UTC)
_KNOWN_AT = datetime(2026, 10, 17, 1, 30, tzinfo=UTC)
_INTERVAL_END = datetime(2026, 10, 16, 7, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _FixedClock:
    """Return one explicitly configured aware instant for the use case."""

    value: datetime

    def now(self) -> datetime:
        """Return the configured test clock without using the machine time."""

        return self.value


class _QualificationReader:
    """Return the same typed qualified evidence at each exact-cutoff read."""

    def __init__(self, value: QualifiedLocalDailyMatchInput) -> None:
        self.value = value
        self.calls: list[tuple[LocalDailyMatchCommand, datetime]] = []

    def read(
        self,
        *,
        command: LocalDailyMatchCommand,
        context: OrderFillContext,
        as_of: datetime,
    ) -> QualifiedLocalDailyMatchInput:
        """Record both pre-read and locked revalidation calls."""

        del context
        self.calls.append((command, as_of))
        return self.value


def _qualified_input(
    *,
    security_id: str,
    close_price: Decimal,
    as_of: datetime = _AS_OF,
) -> QualifiedLocalDailyMatchInput:
    """Build a typed observation and explicit policy for the fixture session."""

    policy = LocalDailySimulationPolicy(
        schema_version="local-daily-simulation-policy.v1",
        purpose="historical_daily_simulation",
        policy_id="storage-fixture",
        version="1",
        price_publication_key="equity.daily.close",
        provider_configuration_id=1,
        provider_name="fixture",
        instrument_snapshot_id="00000000-0000-4000-8000-000000000001",
        currency="CNY",
        frequency="1d",
        adjustment="none",
        volume_unit="shares",
        participation_rate=Decimal("0.1"),
        share_step=Decimal("1"),
        allowed_qmt_suspend_flags=(0,),
        currency_basis="same_session_stock_basic_capture",
        qmt_status_basis="owner_authenticated_normalized_daily_status",
        limit_price_basis="same_provider_cny_listing_native",
    )
    binding = LocalDailySimulationPolicyBinding(
        policy=policy,
        provenance=LocalDailySimulationPolicyRuntimeProvenance(
            runtime_environment="test",
            profile_id="daily-match-test-profile",
            profile_key="daily-match-test",
            profile_version=1,
            profile_content_hash="a" * 64,
            profile_activated_at=datetime(2026, 10, 15, 0, 0, tzinfo=UTC),
            snapshot_id="daily-match-test-snapshot",
            snapshot_content_hash="b" * 64,
            snapshot_generated_at=datetime(2026, 10, 15, 1, 0, tzinfo=UTC),
            snapshot_effective_from=datetime(2026, 10, 15, 0, 0, tzinfo=UTC),
            read_at=as_of,
        ),
    )
    observation = LocalMatchObservation(
        security_id=security_id,
        session_date=_SESSION,
        observation_id=stable_local_daily_observation_id(security_id, _SESSION),
        observed_at=_INTERVAL_END,
        available_at=_KNOWN_AT,
        close_price=close_price,
        price_adjustment=LocalMatchPriceAdjustment.UNADJUSTED,
        traded_volume=Decimal("1000"),
        volume_unit=LocalMatchVolumeUnit.CANONICAL_SHARES,
        trading_state=LocalMatchTradingState.TRADING,
        limit_state=LocalMatchLimitState.BOUNDED,
        lower_limit_price=Decimal("9"),
        upper_limit_price=Decimal("11"),
    )
    reference = LocalDailyMatchSourceReference(
        kind=LocalDailyMatchEvidenceKind.PRICE_FACT,
        identity="price-fact-17",
        content_hash="c" * 64,
        recorded_at=_KNOWN_AT,
    )
    return QualifiedLocalDailyMatchInput(
        as_of=as_of,
        policy_binding=binding,
        observation=observation,
        evidence=(reference,),
    )


def _command(
    harness: _Harness,
    *,
    operation_key: str,
    order_key: str = "daily-match-order",
) -> LocalDailyMatchCommand:
    """Address the real accepted reservation by its owner and stable order key."""

    assert type(harness.account.pk) is int
    return LocalDailyMatchCommand(
        account_id=harness.account.pk,
        user_id=harness.user_id,
        order_idempotency_key=order_key,
        operation_key=operation_key,
        session_date=_SESSION,
        qmt_binding_id=str(uuid4()),
    )


def _reserve(
    harness: _Harness,
    *,
    order_key: str = "daily-match-order",
) -> SimulatedOrderReservationModel:
    """Create a real accepted order using the established reservation owner."""

    intent = _intent_for(harness, key=order_key, quantity=Decimal("100"))
    harness.reserve.execute(intent, fee_budget=Decimal("5.00"), as_of=RESERVATION_AS_OF)
    return SimulatedOrderReservationModel.objects.get(
        account=harness.account,
        idempotency_key=intent.idempotency_key,
    )


def _record_use_case(
    *,
    reader: _QualificationReader,
) -> RecordLocalDailyMatchUseCase:
    """Compose the production repository with only an explicit local source double."""

    return RecordLocalDailyMatchUseCase(
        repository=DjangoLocalDailyMatchRepository(using="default"),
        qualification_reader=reader,
        clock=_FixedClock(_AS_OF),
    )


def test_matched_operation_is_durable_readable_and_replayed_before_source_reads(
    reservation_harness: _Harness,
) -> None:
    """Persist one matched event without touching cash, holds, positions, or trades."""

    with isolated_schema((LocalDailyMatchModel,)):
        reservation = _reserve(reservation_harness)
        command = _command(reservation_harness, operation_key="daily-match-op-1")
        qualified = _qualified_input(
            security_id=reservation.security_id,
            close_price=Decimal("9.50"),
        )
        reader = _QualificationReader(qualified)
        before = (
            SimulatedTradeModel.objects.filter(account=reservation_harness.account).count(),
            reservation.status,
            reservation.filled_quantity,
            reservation.cash_consumed,
            reservation.shares_consumed,
            reservation.cash_released,
            reservation.shares_released,
            reservation_harness.account.current_cash,
        )

        decision = _record_use_case(reader=reader).execute(command)

        assert decision.result.outcome is LocalMatchOutcome.MATCHED
        assert decision.event is not None
        assert decision.event.observation_basis == "daily_interval_end"
        assert decision.event.source_observed_at is None
        assert decision.event.source_available_at is None
        assert decision.event.occurred_at == _INTERVAL_END
        assert decision.event.interval_end_at == _INTERVAL_END
        assert decision.event.local_known_at == _KNOWN_AT
        assert decision.event.recorded_at == _AS_OF
        assert len(reader.calls) == 2
        stored = LocalDailyMatchModel.objects.get(
            account=reservation_harness.account,
            reservation=reservation,
            operation_key=command.operation_key,
        )
        assert stored.outcome == LocalDailyMatchModel.OUTCOME_MATCHED
        assert stored.observation_id == qualified.observation.observation_id
        assert stored.event_payload

        event_reader = DjangoLocalDailyMatchEventReader(using="default")
        event = event_reader.read_event(
            account_id=command.account_id,
            user_id=command.user_id,
            order_idempotency_key=command.order_idempotency_key,
            source_namespace=decision.event.source_namespace,
            fill_event_id=command.operation_key,
            as_of=_AS_OF,
        )
        assert event == decision.event
        page = event_reader.discover(
            account_id=command.account_id,
            user_id=command.user_id,
            order_idempotency_key=command.order_idempotency_key,
            limit=1,
            cursor=None,
            as_of=_AS_OF,
        )
        assert len(page.items) == 1
        assert page.items[0].event == decision.event
        assert page.has_more is False
        assert page.next_cursor is None
        assert (
            event_reader.read_event(
                account_id=command.account_id,
                user_id=command.user_id,
                order_idempotency_key=command.order_idempotency_key,
                source_namespace=decision.event.source_namespace,
                fill_event_id=command.operation_key,
                as_of=_AS_OF - timedelta(microseconds=1),
            )
            is None
        )

        class _MustNotRead:
            """Fail if an exact operation replay consults current sources."""

            def read(self, **kwargs: object) -> QualifiedLocalDailyMatchInput:
                del kwargs
                raise AssertionError("exact operation replay must not reread source evidence")

        replay = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=_MustNotRead(),
            clock=_FixedClock(_AS_OF),
        ).execute(command)
        reservation.refresh_from_db()
        after = (
            SimulatedTradeModel.objects.filter(account=reservation_harness.account).count(),
            reservation.status,
            reservation.filled_quantity,
            reservation.cash_consumed,
            reservation.shares_consumed,
            reservation.cash_released,
            reservation.shares_released,
            SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk).current_cash,
        )
        assert replay.replayed is True
        assert replay.event == decision.event
        assert after == before
        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            DjangoSimulatedOrderReservationRepository(using="default").cancel_order(
                account_id=command.account_id,
                user_id=command.user_id,
                idempotency_key=command.order_idempotency_key,
                clock=_Clock(_AS_OF),
            )
        assert blocked.value.code == "LOCAL_DAILY_MATCH_PENDING_FILL"


def test_no_match_may_cancel_but_history_blocks_account_reset_and_delete(
    reservation_harness: _Harness,
) -> None:
    """A persisted no-match is not pending capacity but remains durable history."""

    with isolated_schema((LocalDailyMatchModel,)):
        reservation = _reserve(reservation_harness)
        command = _command(reservation_harness, operation_key="daily-match-no-match")
        reader = _QualificationReader(
            _qualified_input(
                security_id=reservation.security_id,
                close_price=Decimal("10.50"),
            )
        )
        decision = _record_use_case(reader=reader).execute(command)

        assert decision.result.outcome is LocalMatchOutcome.NO_MATCH
        assert decision.event is None
        stored = LocalDailyMatchModel.objects.get(
            account=reservation_harness.account,
            reservation=reservation,
            operation_key=command.operation_key,
        )
        assert stored.event_payload is None
        cancelled = DjangoSimulatedOrderReservationRepository(using="default").cancel_order(
            account_id=command.account_id,
            user_id=command.user_id,
            idempotency_key=command.order_idempotency_key,
            clock=_Clock(_AS_OF),
        )
        assert cancelled.status.value == "cancelled"

        accounts = DjangoSimulatedAccountRepository()
        with pytest.raises(SimulatedTradeExecutionBlocked) as reset_blocked:
            accounts.reset_account_with_summary(command.account_id)
        assert reset_blocked.value.code == "ORDER_FILL_HISTORY_RETAINED"
        with pytest.raises(SimulatedTradeExecutionBlocked) as delete_blocked:
            accounts.delete(command.account_id)
        assert delete_blocked.value.code == "ORDER_RESERVATION_HISTORY_RETAINED"
        assert LocalDailyMatchModel.objects.filter(pk=stored.pk).exists()
        assert SimulatedAccountModel.objects.filter(pk=command.account_id).exists()
        assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0


def test_terminal_order_still_checks_unconsumed_match_before_idempotent_cancel(
    reservation_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal status cannot hide a matched event that remains unconsumed."""

    with isolated_schema((LocalDailyMatchModel,)):
        reservation = _reserve(reservation_harness)
        command = _command(reservation_harness, operation_key="daily-match-terminal-pending")
        decision = _record_use_case(
            reader=_QualificationReader(
                _qualified_input(
                    security_id=reservation.security_id,
                    close_price=Decimal("9.50"),
                )
            )
        ).execute(command)
        assert decision.event is not None

        current = reservation_harness.repository.find_order(
            account_id=command.account_id,
            user_id=command.user_id,
            idempotency_key=command.order_idempotency_key,
        )
        assert current is not None
        terminal = current.release_remaining()
        repository = DjangoSimulatedOrderReservationRepository(using="default")
        monkeypatch.setattr(repository, "_decode_model", lambda row: terminal)

        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            repository.cancel_order(
                account_id=command.account_id,
                user_id=command.user_id,
                idempotency_key=command.order_idempotency_key,
                clock=_Clock(_AS_OF),
            )
        assert blocked.value.code == "LOCAL_DAILY_MATCH_PENDING_FILL"


def test_outer_transaction_cannot_claim_a_durable_match_decision(
    reservation_harness: _Harness,
) -> None:
    """A caller rollback cannot erase a decision after the producer reports success."""

    with isolated_schema((LocalDailyMatchModel,)):
        reservation = _reserve(reservation_harness)
        command = _command(reservation_harness, operation_key="daily-match-outer-atomic")
        qualified = _qualified_input(
            security_id=reservation.security_id,
            close_price=Decimal("9.50"),
        )
        reader = _QualificationReader(qualified)
        before = (
            SimulatedTradeModel.objects.filter(account=reservation_harness.account).count(),
            reservation.status,
            reservation.filled_quantity,
            reservation.cash_consumed,
            reservation.shares_consumed,
            reservation_harness.account.current_cash,
        )

        with transaction.atomic():
            with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
                _record_use_case(reader=reader).execute(command)
            assert blocked.value.code == "LOCAL_DAILY_MATCH_DURABLE_TRANSACTION_REQUIRED"
            assert not LocalDailyMatchModel.objects.filter(
                account=reservation_harness.account,
                operation_key=command.operation_key,
            ).exists()

        reservation.refresh_from_db()
        after = (
            SimulatedTradeModel.objects.filter(account=reservation_harness.account).count(),
            reservation.status,
            reservation.filled_quantity,
            reservation.cash_consumed,
            reservation.shares_consumed,
            SimulatedAccountModel.objects.get(pk=reservation_harness.account.pk).current_cash,
        )
        assert after == before
        assert len(reader.calls) == 1


def test_damaged_decision_digest_blocks_event_read(
    reservation_harness: _Harness,
) -> None:
    """Stored source and outcome columns cannot change without invalidating the seal."""

    with isolated_schema((LocalDailyMatchModel,)):
        reservation = _reserve(reservation_harness)
        command = _command(reservation_harness, operation_key="daily-match-damaged")
        qualified = _qualified_input(
            security_id=reservation.security_id,
            close_price=Decimal("9.50"),
        )
        decision = _record_use_case(reader=_QualificationReader(qualified)).execute(command)
        assert decision.event is not None
        stored = LocalDailyMatchModel.objects.get(
            account=reservation_harness.account,
            reservation=reservation,
            operation_key=command.operation_key,
        )
        table = connection.ops.quote_name(LocalDailyMatchModel._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET reason_code = %s WHERE id = %s",
                ["TAMPERED", stored.pk],
            )

        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            DjangoLocalDailyMatchEventReader(using="default").read_event(
                account_id=command.account_id,
                user_id=command.user_id,
                order_idempotency_key=command.order_idempotency_key,
                source_namespace=decision.event.source_namespace,
                fill_event_id=command.operation_key,
                as_of=_AS_OF,
            )
        assert blocked.value.code == "LOCAL_DAILY_MATCH_RECORD_INVALID"


@pytest.mark.parametrize(
    ("column", "value"),
    [("security_id", "OTHER.SECURITY"), ("session_date", date(2026, 10, 15))],
    ids=["security", "session-date"],
)
def test_damaged_scope_column_cannot_hide_capacity_from_another_order(
    reservation_harness: _Harness,
    column: str,
    value: str | date,
) -> None:
    """A tampered scalar scope cannot filter an accepted match out of capacity."""

    with isolated_schema((LocalDailyMatchModel,)):
        first_reservation = _reserve(reservation_harness)
        second_reservation = _reserve(
            reservation_harness,
            order_key="daily-match-order-2",
        )
        first_command = _command(
            reservation_harness,
            operation_key="daily-match-first-order",
        )
        second_command = _command(
            reservation_harness,
            operation_key="daily-match-second-order",
            order_key="daily-match-order-2",
        )
        qualified = _qualified_input(
            security_id=first_reservation.security_id,
            close_price=Decimal("9.50"),
        )
        assert second_reservation.security_id == first_reservation.security_id
        first = _record_use_case(reader=_QualificationReader(qualified)).execute(first_command)
        assert first.event is not None
        stored = LocalDailyMatchModel.objects.get(
            account=reservation_harness.account,
            reservation=first_reservation,
            operation_key=first_command.operation_key,
        )
        assert column in {"security_id", "session_date"}
        table = connection.ops.quote_name(LocalDailyMatchModel._meta.db_table)
        quoted_column = connection.ops.quote_name(column)
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} SET {quoted_column} = %s WHERE id = %s",
                [value, stored.pk],
            )

        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            _record_use_case(reader=_QualificationReader(qualified)).execute(second_command)
        assert blocked.value.code == "LOCAL_DAILY_MATCH_RECORD_INVALID"
        assert not LocalDailyMatchModel.objects.filter(
            reservation=second_reservation,
            operation_key=second_command.operation_key,
        ).exists()


def test_match_at_identity_expiry_is_rejected_without_event_and_can_cancel(
    reservation_harness: _Harness,
) -> None:
    """An expiry-boundary match writes no decision, so its untouched hold can release."""

    expiry_at = RESERVATION_AS_OF + timedelta(days=1)
    with isolated_schema((LocalDailyMatchModel,)):
        reservation = _reserve(reservation_harness)
        sealed_identity = ExecutionInstrumentIdentityEvidenceV1.from_payload(
            reservation.plan_snapshot.get("identity_evidence")
        )
        assert sealed_identity.identity_valid_until == expiry_at
        command = _command(
            reservation_harness,
            operation_key="daily-match-identity-expiry",
        )
        qualified = _qualified_input(
            security_id=reservation.security_id,
            close_price=Decimal("9.50"),
        )
        qualified = replace(
            qualified,
            as_of=expiry_at,
            policy_binding=replace(
                qualified.policy_binding,
                provenance=replace(
                    qualified.policy_binding.provenance,
                    read_at=expiry_at,
                ),
            ),
        )
        ledger_before = _ledger_counts(reservation_harness.account)
        account_before = _account_financial_state(reservation_harness.account)

        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            RecordLocalDailyMatchUseCase(
                repository=DjangoLocalDailyMatchRepository(using="default"),
                qualification_reader=_QualificationReader(qualified),
                clock=_FixedClock(expiry_at),
            ).execute(command)

        assert blocked.value.code == "SIMULATED_FILL_PLAN_INVALID"
        assert not LocalDailyMatchModel.objects.filter(reservation=reservation).exists()
        assert _ledger_counts(reservation_harness.account) == ledger_before
        assert _account_financial_state(reservation_harness.account) == account_before
        _reservation_unfilled(reservation)

        cancelled = reservation_harness.repository.cancel_order(
            account_id=command.account_id,
            user_id=command.user_id,
            idempotency_key=command.order_idempotency_key,
            clock=_FixedClock(expiry_at),
        )
        reservation.refresh_from_db()
        assert cancelled.status.value == "cancelled"
        assert reservation.status == SimulatedOrderReservationModel.STATUS_CANCELLED
        assert reservation.cash_released == reservation.cash_reserved
        assert reservation.shares_released == reservation.shares_reserved
        assert _ledger_counts(reservation_harness.account) == ledger_before
        assert _account_financial_state(reservation_harness.account) == account_before


def test_matched_event_remains_pending_when_current_release_calendar_is_unavailable(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An accepted event stays pending when lock-time release evidence is unavailable."""

    del persisted_receipt_schema
    with isolated_schema((LocalDailyMatchModel,)):
        rows = _reader_rows(reservation_harness)
        rows.reservation.refresh_from_db()
        command = _command(
            reservation_harness,
            operation_key="daily-match-expire-before-apply",
            order_key=rows.reservation.idempotency_key,
        )
        qualification_reader = _QualificationReader(
            _qualified_input(
                security_id=rows.reservation.security_id,
                close_price=Decimal("9.50"),
            )
        )
        decision = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=qualification_reader,
            clock=_FixedClock(_AS_OF),
        ).execute(command)
        event = decision.event
        assert event is not None
        assert event.recorded_at == _AS_OF

        apply_as_of = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
        sealed_identity = ExecutionInstrumentIdentityEvidenceV1.from_payload(
            rows.reservation.plan_snapshot.get("identity_evidence")
        )
        assert sealed_identity.identity_valid_until < apply_as_of
        event_reader = DjangoLocalDailyMatchEventReader(using="default")
        apply_command = ApplySimulatedOrderFillCommand(
            account_id=event.account_id,
            user_id=event.user_id,
            order_idempotency_key=event.order_idempotency_key,
            source_namespace=event.source_namespace,
            fill_event_id=event.source_event_id,
            expected_event_payload_hash=event.event_payload_hash,
        )
        source_binding = LocalSimulatedFillSourceBinding(
            reader=event_reader,
            source_namespace=event.source_namespace,
            source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        )
        settlement_resolver = OrderFillSettlementCalendarResolver(
            calendar_reader=_ExchangeCalendarReader(rows.proof.calendar_evidence),
            clock=_FixedClock(apply_as_of),
        )

        class _MissingCurrentReleaseCalendarReader:
            """Return no current calendar while preserving the sealed event calendar."""

            def __init__(self) -> None:
                self.calls: list[tuple[str, datetime, date | None]] = []

            def get_effective_execution_calendar(
                self,
                *,
                exchange: str,
                as_of: datetime,
                coverage_start: date | None,
            ) -> None:
                self.calls.append((exchange, as_of, coverage_start))
                return None

        current_release_calendar_reader = _MissingCurrentReleaseCalendarReader()
        mark_reader = _InitialPositionMarkReader(
            proof=_initial_position_mark(rows, read_at=apply_as_of),
            calls=[],
        )
        apply_use_case = ApplySimulatedOrderFillUseCase(
            repository=DjangoSimulatedOrderFillRepository(
                event_reader=event_reader,
                initial_position_mark_reader=mark_reader,
                current_calendar_reader=current_release_calendar_reader,
                using="default",
            ),
            clock=_FixedClock(apply_as_of),
            source_binding=source_binding,
            settlement_resolver=settlement_resolver,
        )
        ledger_before = _ledger_counts(reservation_harness.account)
        account_before = _account_financial_state(reservation_harness.account)
        reservation_before = (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        )

        with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
            apply_use_case.execute(apply_command)

        assert blocked.value.code == "SIMULATED_FILL_RELEASE_CALENDAR_UNAVAILABLE"
        assert len(current_release_calendar_reader.calls) == 1
        assert current_release_calendar_reader.calls[0][1] == apply_as_of
        assert mark_reader.calls == []
        assert (
            event_reader.read_event(
                account_id=event.account_id,
                user_id=event.user_id,
                order_idempotency_key=event.order_idempotency_key,
                source_namespace=event.source_namespace,
                fill_event_id=event.source_event_id,
                as_of=apply_as_of,
            )
            == event
        )
        page = event_reader.discover(
            account_id=event.account_id,
            user_id=event.user_id,
            order_idempotency_key=event.order_idempotency_key,
            limit=1,
            cursor=None,
            as_of=apply_as_of,
        )
        assert len(page.items) == 1
        assert page.items[0].event == event
        assert page.has_more is False
        qualification_calls = len(qualification_reader.calls)
        replayed = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=qualification_reader,
            clock=_FixedClock(apply_as_of),
        ).execute(command)
        assert replayed.replayed is True and replayed.event == event
        assert len(qualification_reader.calls) == qualification_calls
        assert (
            SimulatedOrderFillReceiptModel.objects.filter(
                trade__account=reservation_harness.account
            ).count()
            == 0
        )
        assert _ledger_counts(reservation_harness.account) == ledger_before
        assert _account_financial_state(reservation_harness.account) == account_before
        _reservation_unfilled(rows.reservation)
        rows.reservation.refresh_from_db()
        assert (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        ) == reservation_before

        new_command = _command(
            reservation_harness,
            operation_key="daily-match-expired-new-operation",
            order_key=rows.reservation.idempotency_key,
        )
        with pytest.raises(SimulatedTradeIdempotencyConflict):
            RecordLocalDailyMatchUseCase(
                repository=DjangoLocalDailyMatchRepository(using="default"),
                qualification_reader=_QualificationReader(
                    _qualified_input(
                        security_id=rows.reservation.security_id,
                        close_price=Decimal("9.50"),
                        as_of=apply_as_of,
                    )
                ),
                clock=_FixedClock(apply_as_of),
            ).execute(new_command)
        assert LocalDailyMatchModel.objects.filter(reservation=rows.reservation).count() == 1

        # A different trading day must hit the pending guard, not same-day deduplication.
        next_session = date(2026, 10, 19)
        next_as_of = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
        next_known_at = datetime(2026, 10, 20, 1, 30, tzinfo=UTC)
        next_input = _qualified_input(
            security_id=rows.reservation.security_id,
            close_price=Decimal("9.50"),
            as_of=next_as_of,
        )
        next_input = replace(
            next_input,
            observation=replace(
                next_input.observation,
                session_date=next_session,
                observation_id=stable_local_daily_observation_id(
                    rows.reservation.security_id, next_session
                ),
                observed_at=datetime(2026, 10, 19, 7, 0, tzinfo=UTC),
                available_at=next_known_at,
            ),
            evidence=(
                replace(
                    next_input.evidence[0],
                    identity="price-fact-19",
                    content_hash="d" * 64,
                    recorded_at=next_known_at,
                ),
            ),
        )
        with pytest.raises(SimulatedTradeExecutionBlocked) as next_day_blocked:
            RecordLocalDailyMatchUseCase(
                repository=DjangoLocalDailyMatchRepository(using="default"),
                qualification_reader=_QualificationReader(next_input),
                clock=_FixedClock(next_as_of),
            ).execute(replace(new_command, session_date=next_session))
        assert next_day_blocked.value.code == "LOCAL_DAILY_MATCH_PENDING_FILL"
        assert LocalDailyMatchModel.objects.filter(reservation=rows.reservation).count() == 1

        with pytest.raises(SimulatedTradeExecutionBlocked) as cancel_blocked:
            reservation_harness.repository.cancel_order(
                account_id=event.account_id,
                user_id=event.user_id,
                idempotency_key=event.order_idempotency_key,
                clock=_FixedClock(apply_as_of),
            )
        assert cancel_blocked.value.code == "LOCAL_DAILY_MATCH_PENDING_FILL"
        accounts = DjangoSimulatedAccountRepository()
        with pytest.raises(SimulatedTradeExecutionBlocked) as reset_blocked:
            accounts.reset_account_with_summary(event.account_id)
        assert reset_blocked.value.code == "ORDER_RESERVATION_ACTIVE"
        with pytest.raises(SimulatedTradeExecutionBlocked) as delete_blocked:
            accounts.delete(event.account_id)
        assert delete_blocked.value.code == "ORDER_RESERVATION_ACTIVE"
        assert _ledger_counts(reservation_harness.account) == ledger_before
        assert _account_financial_state(reservation_harness.account) == account_before


def test_produced_partial_event_survives_apply_failure_then_replays_and_cancels(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply one retained producer event after mark recovery, then release its remainder."""

    del persisted_receipt_schema
    with isolated_schema((LocalDailyMatchModel,)):
        identity_expiry = datetime(2026, 10, 20, 2, 0, tzinfo=UTC)
        identity_reader = reservation_harness.preparer._identity_reader
        original_identity_read = identity_reader.get_execution_instrument_identity

        def identity_valid_through_apply(
            *,
            security_id: str,
            asset_code: str,
            as_of: datetime,
        ) -> ExecutionInstrumentIdentityEvidenceV1:
            """Seal the accepted test order with an explicit later identity expiry."""

            evidence = original_identity_read(
                security_id=security_id,
                asset_code=asset_code,
                as_of=as_of,
            )
            return replace(evidence, identity_valid_until=identity_expiry)

        monkeypatch.setattr(
            identity_reader,
            "get_execution_instrument_identity",
            identity_valid_through_apply,
        )
        rows = _reader_rows(reservation_harness)
        rows.reservation.refresh_from_db()
        sealed_identity = ExecutionInstrumentIdentityEvidenceV1.from_payload(
            rows.reservation.plan_snapshot.get("identity_evidence")
        )
        assert sealed_identity.identity_valid_until == identity_expiry
        # Apply at a real published open session while the sealed identity is still valid.
        apply_as_of = datetime(2026, 10, 19, 2, 0, tzinfo=UTC)
        command = _command(
            reservation_harness,
            operation_key="daily-match-apply-recovery",
            order_key=rows.reservation.idempotency_key,
        )
        qualified = _qualified_input(
            security_id=rows.reservation.security_id,
            close_price=Decimal("9.50"),
        )
        qualified = replace(
            qualified,
            as_of=apply_as_of,
            policy_binding=replace(
                qualified.policy_binding,
                provenance=replace(
                    qualified.policy_binding.provenance,
                    read_at=apply_as_of,
                ),
            ),
            observation=replace(
                qualified.observation,
                traded_volume=Decimal("100"),
            ),
        )
        qualification_reader = _QualificationReader(qualified)
        producer = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=qualification_reader,
            clock=_FixedClock(apply_as_of),
        )
        decision = producer.execute(command)
        event = decision.event
        assert event is not None
        assert decision.result.outcome is LocalMatchOutcome.MATCHED
        assert event.quantity == Decimal("10.000000")
        assert rows.reservation.filled_quantity == Decimal("0.000000")
        assert SimulatedTradeModel.objects.filter(account=reservation_harness.account).count() == 0
        assert (
            SimulatedOrderFillReceiptModel.objects.filter(
                trade__account=reservation_harness.account
            ).count()
            == 0
        )
        assert PositionModel.objects.filter(account=reservation_harness.account).count() == 0

        event_reader = DjangoLocalDailyMatchEventReader(using="default")
        apply_command = ApplySimulatedOrderFillCommand(
            account_id=event.account_id,
            user_id=event.user_id,
            order_idempotency_key=event.order_idempotency_key,
            source_namespace=event.source_namespace,
            fill_event_id=event.source_event_id,
            expected_event_payload_hash=event.event_payload_hash,
        )
        current_calendar_reader = _ExchangeCalendarReader(rows.proof.calendar_evidence)
        mark_reader = _InitialPositionMarkReader(proof=None, calls=[])

        def current_calendar_reader_factory(
            *,
            dataset_key: str,
            runtime_environment: str,
            read_publication: object | None = None,
        ) -> _ExchangeCalendarReader:
            """Inject only the current-calendar leaf used by the public Apply factory."""

            assert dataset_key == "trade_cal"
            assert runtime_environment == "test"
            assert read_publication is not None
            return current_calendar_reader

        def initial_position_mark_reader_factory(
            *, runtime_environment: str, calendar_dataset_key: str
        ) -> _InitialPositionMarkReader:
            """Inject a typed mark reader so this test can exercise recovery in place."""

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
        apply_use_case = local_daily_match_composition.build_apply_local_daily_match_use_case(
            runtime_environment="test",
            calendar_dataset_key="trade_cal",
            clock=_FixedClock(apply_as_of),
            using="default",
        )

        ledger_before = _ledger_counts(reservation_harness.account)
        account_before = _account_financial_state(reservation_harness.account)
        reservation_before = (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        )
        with pytest.raises(SimulatedTradeExecutionBlocked) as mark_unavailable:
            apply_use_case.execute(apply_command)
        assert mark_unavailable.value.code == "INITIAL_POSITION_MARK_UNAVAILABLE"
        assert len(mark_reader.calls) == 1
        assert _ledger_counts(reservation_harness.account) == ledger_before
        assert _account_financial_state(reservation_harness.account) == account_before
        _reservation_unfilled(rows.reservation)
        rows.reservation.refresh_from_db()
        assert (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        ) == reservation_before
        stored_event = event_reader.read_event(
            account_id=event.account_id,
            user_id=event.user_id,
            order_idempotency_key=event.order_idempotency_key,
            source_namespace=event.source_namespace,
            fill_event_id=event.source_event_id,
            as_of=apply_as_of,
        )
        assert stored_event == event

        mark_reader.proof = _initial_position_mark(rows, read_at=apply_as_of)
        applied = apply_use_case.execute(apply_command)
        assert applied.replayed is False
        assert len(mark_reader.calls) == 2
        assert applied.source_version == LOCAL_DAILY_INTERVAL_SOURCE_VERSION
        assert applied.event_payload_hash == event.event_payload_hash

        rows.reservation.refresh_from_db()
        trade = SimulatedTradeModel.objects.get(account=reservation_harness.account)
        receipt = SimulatedOrderFillReceiptModel.objects.get(trade=trade)
        assert trade.quantity == event.quantity
        assert receipt.source_event_id == event.source_event_id
        assert receipt.source_namespace == event.source_namespace
        assert rows.reservation.filled_quantity == event.quantity
        assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
        decoded = read_order_reservation_fill_row(
            reservation_row=rows.reservation,
            receipt_row=receipt,
            trade_row=trade,
        )
        assert decoded.event == event
        assert decoded.event.observation_basis == "daily_interval_end"
        assert decoded.event.source_observed_at is None

        replay_state = _ledger_counts(reservation_harness.account)

        class _NoClock:
            """Fail if an exact fill receipt replay asks for current time."""

            def now(self) -> datetime:
                raise AssertionError("exact fill replay must not read the clock")

        receipt_replay = local_daily_match_composition.build_apply_local_daily_match_use_case(
            runtime_environment="test",
            calendar_dataset_key="trade_cal",
            clock=_NoClock(),
            using="default",
        ).execute(apply_command)
        assert receipt_replay.replayed is True
        assert receipt_replay.trade_id == applied.trade_id
        assert _ledger_counts(reservation_harness.account) == replay_state

        class _NoQualificationRead:
            """Fail if exact producer-operation replay consults current evidence."""

            def read(self, **kwargs: object) -> QualifiedLocalDailyMatchInput:
                del kwargs
                raise AssertionError("exact producer replay must skip source qualification")

        producer_replay = RecordLocalDailyMatchUseCase(
            repository=DjangoLocalDailyMatchRepository(using="default"),
            qualification_reader=_NoQualificationRead(),
            clock=_NoClock(),
        ).execute(command)
        assert producer_replay.replayed is True
        assert producer_replay.event == event
        assert len(qualification_reader.calls) == 2

        rows.reservation.refresh_from_db()
        remaining_cash_hold = (
            rows.reservation.cash_reserved
            - rows.reservation.cash_consumed
            - rows.reservation.cash_released
        )
        remaining_share_hold = (
            rows.reservation.shares_reserved
            - rows.reservation.shares_consumed
            - rows.reservation.shares_released
        )
        assert remaining_cash_hold > Decimal("0.00")
        assert remaining_share_hold == Decimal("0.000000")
        consumed_before_cancel = (
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        )
        cancelled = reservation_harness.repository.cancel_order(
            account_id=event.account_id,
            user_id=event.user_id,
            idempotency_key=event.order_idempotency_key,
            clock=_FixedClock(apply_as_of),
        )
        rows.reservation.refresh_from_db()
        assert cancelled.status.value == "cancelled"
        assert (
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.shares_consumed,
        ) == consumed_before_cancel[:3]
        assert rows.reservation.cash_released == consumed_before_cancel[3] + remaining_cash_hold
        assert rows.reservation.shares_released == consumed_before_cancel[4]

        terminal_state = (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        )
        repeated_cancel = reservation_harness.repository.cancel_order(
            account_id=event.account_id,
            user_id=event.user_id,
            idempotency_key=event.order_idempotency_key,
            clock=_FixedClock(apply_as_of),
        )
        rows.reservation.refresh_from_db()
        assert repeated_cancel == cancelled
        assert (
            rows.reservation.status,
            rows.reservation.filled_quantity,
            rows.reservation.cash_consumed,
            rows.reservation.cash_released,
            rows.reservation.shares_released,
        ) == terminal_state
