"""Application ordering for locally sourced, durable reservation fills.

These tests exercise only typed use-case orchestration. They do not establish
that any real matcher is qualified, nor do they prove repository transaction
atomicity or PostgreSQL locking.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    PublishedExecutionCalendarReader,
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
    SimulatedTradeExecutionResultUnknown,
    SimulatedTradeIdempotencyConflict,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    ExistingOrderFill,
    LocalSimulatedFillEventKind,
    LocalSimulatedFillEventV1,
    LocalSimulatedFillSourceBinding,
    OrderFillContext,
    OrderFillSettlementResolver,
    SimulatedOrderFillResult,
)
from apps.simulated_trading.application.order_reservation_fill_calendar import (
    OrderFillSettlementCalendarResolver,
)
from apps.simulated_trading.domain.execution_fee_policy_v2 import (
    FeeApplicability,
    FeePolicyAccountScope,
    FeeTransactionCase,
    SimulatedFeePolicyV2,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    CalendarPublicationReference,
    ExchangeCalendarDay,
    ExchangeCalendarSnapshot,
    ExecutionCalendarEvidence,
    RawCalendarReference,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    ExecutionFeeSchedule,
    FeeCalculationPurpose,
    FeeRateStoragePrecision,
    FeeRoundingPolicy,
    SimulatedTradeIntent,
    SimulatedTradeSide,
    TradeFeeBreakdown,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservationBook,
    OrderReservationRequest,
    OrderReservationStatus,
    reserve_order,
)
from apps.simulated_trading.domain.order_reservation_fill import (
    OrderReservationFillAccrual,
    OrderReservationFillRequest,
    prepare_order_reservation_fill,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
    build_order_fill_settlement_proof,
)

AS_OF = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)
ZERO_MONEY = Decimal("0.00")
ZERO_SHARES = Decimal("0.000000")
ZERO_FEES = TradeFeeBreakdown(ZERO_MONEY, ZERO_MONEY, ZERO_MONEY, ZERO_MONEY, ZERO_MONEY)
SOURCE_NAMESPACE = "unit-test-local-matcher"
SOURCE_VERSION = "fixture-v1"
EVENT_HASH = "b" * 64
SNAPSHOT_HASH = "c" * 64
PLAN_HASH = "d" * 64
SETTLEMENT_EXCHANGE = "SSE"
SETTLEMENT_LAG_SESSIONS = 1


def _intent() -> SimulatedTradeIntent:
    """Build a real Domain intent for Application boundary tests."""

    return SimulatedTradeIntent(
        account_id=7,
        user_id=11,
        idempotency_key="fill-order-application-001",
        side=SimulatedTradeSide.BUY,
        security_id="SH.FILL.APP.SECURITY",
        asset_code="600000.SH",
        asset_name="fill application test",
        asset_type="equity",
        market="SH",
        board="MAIN",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        reason="application boundary test",
        signal_id=None,
    )


def _fee_policy() -> SimulatedFeePolicyV2:
    """Build one complete exact-case FeeV2 snapshot for Domain fixtures."""

    schedule = ExecutionFeeSchedule(
        config_id=3,
        asset_type="equity",
        commission_rate_buy=Decimal("0.0003"),
        commission_rate_sell=Decimal("0.0003"),
        min_commission=Decimal("5"),
        stamp_duty_rate=Decimal("0.001"),
        transfer_fee_rate=Decimal("0.00002"),
        min_transfer_fee=Decimal("0"),
        slippage_rate=Decimal("0.001"),
        precision_basis=FeeRateStoragePrecision.DATABASE_BINARY64,
        calculation_purpose=FeeCalculationPurpose.NORMAL_SIM_ESTIMATED,
        rounding_policy=FeeRoundingPolicy.COMPONENT_HALF_EVEN_CENTS_V1,
    )
    cases = tuple(
        FeeTransactionCase(
            asset_type="equity",
            market="SH",
            board="MAIN",
            side=side,
            commission=FeeApplicability.APPLIES,
            transfer_fee=FeeApplicability.APPLIES,
            stamp_duty=FeeApplicability.APPLIES,
            slippage=FeeApplicability.APPLIES,
        )
        for side in (SimulatedTradeSide.BUY, SimulatedTradeSide.SELL)
    )
    return SimulatedFeePolicyV2(
        fee_schedule_v1=schedule,
        policy_id="fill-application-fee-policy",
        policy_version=1,
        account_scope=FeePolicyAccountScope.ALL_SIMULATED_ACCOUNTS,
        effective_from=AS_OF - timedelta(days=1),
        valid_until=AS_OF + timedelta(days=30),
        recorded_at=AS_OF - timedelta(days=1),
        transaction_cases=cases,
    )


def _calendar_evidence(exchange: str = SETTLEMENT_EXCHANGE) -> ExecutionCalendarEvidence:
    """Build complete synthetic published calendar evidence for one test exchange."""

    coverage_start = date(2026, 10, 15)
    coverage_end = date(2026, 10, 20)
    open_dates = frozenset(
        {date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 20)}
    )
    previous_open = date(2026, 10, 14)
    day_rows: list[ExchangeCalendarDay] = []
    current = coverage_start
    while current <= coverage_end:
        is_open = current in open_dates
        day_rows.append(
            ExchangeCalendarDay(
                exchange=exchange,
                calendar_date=current,
                is_open=is_open,
                previous_open_date=previous_open,
            )
        )
        if is_open:
            previous_open = current
        current = date.fromordinal(current.toordinal() + 1)

    response_completed_at = AS_OF - timedelta(hours=2)
    raw_reference = RawCalendarReference(
        payload_id="0f53f9d5-7bc6-4b87-8e16-f5840aa5b301",
        payload_hash="sha256:" + "a" * 64,
        record_digest="sha256:" + "b" * 64,
        body_sha256="c" * 64,
        retained_content_sha256="c" * 64,
        request_scope_sha256="d" * 64,
        original_body_retained=True,
        response_completed_at=response_completed_at,
        provider_name="unit-test-calendar-provider",
        dataset_key="trade_cal",
        transport="direct",
    )
    snapshot_id = "f418fc8b-8843-4cd8-9693-95b67834827b"
    snapshot = ExchangeCalendarSnapshot(
        snapshot_id=snapshot_id,
        exchange=exchange,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        days=tuple(day_rows),
        provider_name="unit-test-calendar-provider",
        raw_reference=raw_reference,
        content_hash="",
        record_digest="",
        first_seen_at=response_completed_at,
        recorded_at=AS_OF - timedelta(hours=1),
        source_published_at=AS_OF - timedelta(hours=3),
    )
    publication = CalendarPublicationReference(
        publication_id="fill-application-calendar-publication",
        member_id=snapshot_id,
        publication_hash="e" * 64,
        fact_content_hash="f" * 64,
        policy_hash="1" * 64,
        published_at=AS_OF - timedelta(minutes=45),
        recorded_at=AS_OF - timedelta(minutes=40),
        reference_valid_from=AS_OF - timedelta(days=1),
        reference_valid_until=AS_OF + timedelta(days=30),
        timezone_name="Asia/Shanghai",
    )
    return ExecutionCalendarEvidence(snapshot=snapshot, publication=publication)


def _settlement_proof(
    *,
    event_occurred_at: datetime = AS_OF,
    settlement_exchange: str = SETTLEMENT_EXCHANGE,
    settlement_lag_sessions: int = SETTLEMENT_LAG_SESSIONS,
) -> OrderFillSettlementProof:
    """Build exact Domain proof values for one application boundary test."""

    return build_order_fill_settlement_proof(
        calendar_evidence=_calendar_evidence(settlement_exchange),
        calendar_read_cutoff=AS_OF,
        fill_occurred_at=event_occurred_at,
        settlement_exchange=settlement_exchange,
        settlement_lag_sessions=settlement_lag_sessions,
    )


@dataclass(frozen=True, slots=True)
class _Scenario:
    """Keep the real Domain objects used to prepare one fake source result."""

    intent: SimulatedTradeIntent
    policy: SimulatedFeePolicyV2
    context: OrderFillContext
    event: LocalSimulatedFillEventV1
    result: SimulatedOrderFillResult


def _scenario(
    *,
    event_kind: LocalSimulatedFillEventKind = LocalSimulatedFillEventKind.FILL,
    source_namespace: str = SOURCE_NAMESPACE,
    event_hash: str = EVENT_HASH,
    replayed: bool = False,
    economics_close_order: bool | None = None,
) -> _Scenario:
    """Build an exact active reservation, typed event, economics, and receipt."""

    intent = _intent()
    policy = _fee_policy()
    request = OrderReservationRequest(
        account_id=intent.account_id,
        security_id=intent.security_id,
        idempotency_key=intent.idempotency_key,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.price,
        asset_type=intent.asset_type,
        market=intent.market,
        board=intent.board,
        fee_budget=Decimal("20.00"),
    )
    book = OrderReservationBook(
        account_id=intent.account_id,
        security_id=intent.security_id,
        book_cash=Decimal("100000.00"),
        withdrawable_cash=None,
        sellable_shares=Decimal("1000.000000"),
        reservations=(),
    )
    reservation = reserve_order(book, request, policy, reserved_at=AS_OF).reservation
    context = OrderFillContext(
        reservation_id=41,
        account_id=intent.account_id,
        owner_user_id=intent.user_id,
        order_idempotency_key=intent.idempotency_key,
        reservation=reservation,
        asset_code=intent.asset_code,
        intent_payload_hash=intent.request_payload_hash,
        plan_snapshot_hash=PLAN_HASH,
        settlement_exchange=SETTLEMENT_EXCHANGE,
        settlement_lag_sessions=SETTLEMENT_LAG_SESSIONS,
    )
    event = LocalSimulatedFillEventV1(
        source_namespace=source_namespace,
        source_version=SOURCE_VERSION,
        source_event_id="matcher-event-0001",
        event_payload_hash=event_hash,
        source_snapshot_id="matcher-snapshot-01",
        source_snapshot_hash=SNAPSHOT_HASH,
        reservation_id=context.reservation_id,
        account_id=context.account_id,
        user_id=context.owner_user_id,
        order_idempotency_key=context.order_idempotency_key,
        intent_payload_hash=context.intent_payload_hash,
        reservation_request_hash=reservation.identity.request_payload_hash,
        plan_snapshot_hash=context.plan_snapshot_hash,
        security_id=reservation.identity.security_id,
        asset_code=context.asset_code,
        side=reservation.side,
        event_kind=event_kind,
        quantity=Decimal("10.000000"),
        price=Decimal("10.0000"),
        occurred_at=AS_OF,
        source_observed_at=AS_OF,
        source_available_at=AS_OF,
        recorded_at=AS_OF,
    )
    close_order = (
        event_kind is LocalSimulatedFillEventKind.FINAL_FILL
        if economics_close_order is None
        else economics_close_order
    )
    economics = prepare_order_reservation_fill(
        OrderReservationFillRequest(
            fill_event_id=event.source_event_id,
            intent=intent,
            stored_intent_payload_hash=intent.request_payload_hash,
            reservation=reservation,
            fee_policy=policy,
            fill_occurred_at=event.occurred_at,
            quantity=event.quantity,
            price=event.price,
            prior=OrderReservationFillAccrual(
                fill_count=0,
                cumulative_quantity=ZERO_SHARES,
                cumulative_gross=ZERO_MONEY,
                cumulative_fees=ZERO_FEES,
            ),
            close_order=close_order,
        )
    )
    current_reservation = reservation.apply_fill(
        filled_quantity=economics.quantity,
        cash_consumed=economics.gross_amount + economics.incremental_fees.total_fee,
        close_order=close_order,
    )
    result = SimulatedOrderFillResult(
        reservation_id=context.reservation_id,
        source_namespace=event.source_namespace,
        source_version=event.source_version,
        event_payload_hash=event.event_payload_hash,
        economics=economics,
        reservation=current_reservation,
        trade_id=501,
        replayed=replayed,
    )
    return _Scenario(intent, policy, context, event, result)


def _command(
    scenario: _Scenario, expected_hash: str | None = EVENT_HASH
) -> ApplySimulatedOrderFillCommand:
    """Address exactly one owner-scoped source event."""

    return ApplySimulatedOrderFillCommand(
        account_id=scenario.intent.account_id,
        user_id=scenario.intent.user_id,
        order_idempotency_key=scenario.intent.idempotency_key,
        source_namespace=scenario.event.source_namespace,
        fill_event_id=scenario.event.source_event_id,
        expected_event_payload_hash=expected_hash,
    )


class _Clock:
    """Return one real-aware fixed instant and record whether it was observed."""

    def __init__(self, value: datetime = AS_OF) -> None:
        self.value = value
        self.calls = 0

    def now(self) -> datetime:
        """Return the configured test instant."""

        self.calls += 1
        return self.value


class _Source:
    """Provide one explicitly injected local-source event for orchestration tests."""

    def __init__(self, event: LocalSimulatedFillEventV1 | None) -> None:
        self.event = event
        self.calls: list[dict[str, object]] = []

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
        """Return the test event without claiming that the source is production-qualified."""

        self.calls.append(
            {
                "account_id": account_id,
                "user_id": user_id,
                "order_idempotency_key": order_idempotency_key,
                "source_namespace": source_namespace,
                "fill_event_id": fill_event_id,
                "as_of": as_of,
            }
        )
        return self.event


class _PublishedCalendarReader(PublishedExecutionCalendarReader):
    """Return exact fixture evidence through the public calendar-reader port."""

    def __init__(self, evidence: ExecutionCalendarEvidence) -> None:
        """Bind one typed published evidence value and record requested scope."""
        self.evidence = evidence
        self.calls: list[dict[str, object]] = []

    def get_effective_execution_calendar(
        self,
        *,
        exchange: str,
        as_of: datetime,
        coverage_start: date | None,
    ) -> ExecutionCalendarEvidence:
        """Record the public reader request and return its exact evidence."""
        self.calls.append({"exchange": exchange, "as_of": as_of, "coverage_start": coverage_start})
        return self.evidence


class _SettlementResolver:
    """Return a staged proof and record the exact values requested by the use case."""

    def __init__(
        self,
        result: object,
        *,
        fail_after_first: bool = False,
    ) -> None:
        self.result = result
        self.fail_after_first = fail_after_first
        self.calls: list[dict[str, object]] = []

    def resolve(
        self,
        *,
        event_occurred_at: datetime,
        settlement_exchange: str,
        settlement_lag_sessions: int,
    ) -> OrderFillSettlementProof | None:
        """Record a call and return the configured proof without external I/O."""

        self.calls.append(
            {
                "event_occurred_at": event_occurred_at,
                "settlement_exchange": settlement_exchange,
                "settlement_lag_sessions": settlement_lag_sessions,
            }
        )
        if self.fail_after_first and len(self.calls) > 1:
            raise AssertionError("calendar resolver must not run during exact recovery")
        return cast(OrderFillSettlementProof | None, self.result)


class _Repository:
    """Fake the two repository seams while preserving their resolution order."""

    def __init__(
        self,
        dispositions: list[ExistingOrderFill | OrderFillContext | None],
        *,
        apply_result: SimulatedOrderFillResult | None = None,
        apply_error: SimulatedTradeExecutionResultUnknown | None = None,
    ) -> None:
        self.dispositions = list(dispositions)
        self.apply_result = apply_result
        self.apply_error = apply_error
        self.resolve_calls: list[dict[str, object]] = []
        self.apply_calls: list[dict[str, object]] = []

    def resolve_fill_request(
        self,
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
    ) -> ExistingOrderFill | OrderFillContext | None:
        """Return each staged result to model a readback boundary."""

        self.resolve_calls.append(
            {
                "account_id": account_id,
                "user_id": user_id,
                "order_idempotency_key": order_idempotency_key,
                "source_namespace": source_namespace,
                "fill_event_id": fill_event_id,
            }
        )
        if not self.dispositions:
            return None
        return self.dispositions.pop(0)

    def apply_fill_event(
        self,
        *,
        event: LocalSimulatedFillEventV1,
        expected_event_payload_hash: str | None,
        settlement_proof: OrderFillSettlementProof,
        clock: object,
    ) -> SimulatedOrderFillResult:
        """Record the event/proof pair and return or raise the configured receipt."""

        self.apply_calls.append(
            {
                "event": event,
                "expected_event_payload_hash": expected_event_payload_hash,
                "settlement_proof": settlement_proof,
                "clock": clock,
            }
        )
        if self.apply_error is not None:
            raise self.apply_error
        if self.apply_result is None:
            raise AssertionError("test fake was not given a persisted result")
        return self.apply_result


class _InterleavingRepository(_Repository):
    """Model the repository's locked second read after a competing transition."""

    def __init__(self, context: OrderFillContext) -> None:
        super().__init__([context])
        self.current_context = context
        self.committed_result: SimulatedOrderFillResult | None = None
        self.locked_exact_event_reads = 0
        self.persisted_trade_count = 0

    def commit_competing_fill(self, result: SimulatedOrderFillResult) -> None:
        """Simulate another caller committing this event and closing the hold."""

        self.committed_result = result
        self.current_context = replace(
            self.current_context,
            reservation=result.reservation,
        )
        self.persisted_trade_count = 1

    def cancel_without_fill(self) -> None:
        """Simulate a competing cancellation that stores no event or Trade."""

        self.current_context = replace(
            self.current_context,
            reservation=self.current_context.reservation.release_remaining(),
        )

    def apply_fill_event(
        self,
        *,
        event: LocalSimulatedFillEventV1,
        expected_event_payload_hash: str | None,
        settlement_proof: OrderFillSettlementProof,
        clock: object,
    ) -> SimulatedOrderFillResult:
        """Re-read an event before the current order terminal-state check."""

        self.apply_calls.append(
            {
                "event": event,
                "expected_event_payload_hash": expected_event_payload_hash,
                "settlement_proof": settlement_proof,
                "clock": clock,
            }
        )
        self.locked_exact_event_reads += 1
        if self.committed_result is not None:
            if self.committed_result.event_payload_hash != event.event_payload_hash:
                raise SimulatedTradeIdempotencyConflict("competing event digest differs")
            return replace(self.committed_result, replayed=True)
        if self.current_context.reservation.status is not OrderReservationStatus.ACTIVE:
            raise SimulatedTradeExecutionBlocked("order became terminal before fill apply")
        raise AssertionError("interleaving test requires a concurrent transition")


class _InterleavingSource(_Source):
    """Commit a competing transition after resolution but before application."""

    def __init__(
        self,
        event: LocalSimulatedFillEventV1,
        *,
        after_resolve: Callable[[], None],
    ) -> None:
        super().__init__(event)
        self.after_resolve = after_resolve

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
        """Trigger the test interleaving after the first owner-scoped lookup."""

        event = super().read_event(
            account_id=account_id,
            user_id=user_id,
            order_idempotency_key=order_idempotency_key,
            source_namespace=source_namespace,
            fill_event_id=fill_event_id,
            as_of=as_of,
        )
        self.after_resolve()
        return event


def _binding(source: _Source) -> LocalSimulatedFillSourceBinding:
    """Bind a test reader to explicit, non-default namespace/version values."""

    return LocalSimulatedFillSourceBinding(
        reader=source,
        source_namespace=SOURCE_NAMESPACE,
        source_version=SOURCE_VERSION,
    )


def _use_case(
    repository: _Repository,
    clock: _Clock,
    binding: LocalSimulatedFillSourceBinding | None,
    *,
    settlement_resolver: OrderFillSettlementResolver | None = None,
    default_settlement_resolver: bool = True,
) -> ApplySimulatedOrderFillUseCase:
    """Build the use case from typed test ports with explicit calendar behavior."""

    selected_resolver = settlement_resolver
    if selected_resolver is None and default_settlement_resolver:
        selected_resolver = _SettlementResolver(_settlement_proof())
    return ApplySimulatedOrderFillUseCase(
        repository=repository,
        source_binding=binding,
        clock=clock,
        settlement_resolver=selected_resolver,
    )


def test_existing_event_replays_before_source_or_current_clock_reads() -> None:
    """Exact stored replay must work when the source is absent and the order is terminal."""

    scenario = _scenario()
    later_reservation = scenario.result.reservation.apply_fill(
        filled_quantity=Decimal("10.000000"), cash_consumed=Decimal("100.20")
    )
    terminal_reservation = later_reservation.release_remaining()
    stored = ExistingOrderFill(
        replace(scenario.result, reservation=terminal_reservation, replayed=False)
    )
    repository = _Repository([stored])
    clock = _Clock(datetime(2026, 10, 20, 0, 0))
    use_case = _use_case(
        repository,
        clock,
        binding=None,
        default_settlement_resolver=False,
    )

    result = use_case.execute(_command(scenario))

    assert result.replayed is True
    assert result.event_payload_hash == scenario.event.event_payload_hash
    assert result.economics.cumulative_state.cumulative_quantity == Decimal("10.000000")
    assert result.reservation.filled_quantity == Decimal("20.000000")
    assert repository.resolve_calls[0]["fill_event_id"] == scenario.event.source_event_id
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_existing_event_replay_preserves_stored_version_after_binding_changes() -> None:
    """Exact namespace/ID replay keeps its stored schema version without current source IO."""

    scenario = _scenario()
    repository = _Repository([ExistingOrderFill(scenario.result)])
    source = _Source(None)
    clock = _Clock()
    changed_binding = LocalSimulatedFillSourceBinding(
        reader=source,
        source_namespace=scenario.event.source_namespace,
        source_version="fixture-v2",
    )

    result = _use_case(repository, clock, changed_binding).execute(_command(scenario))

    assert result.replayed is True
    assert result.source_namespace == SOURCE_NAMESPACE
    assert result.source_version == SOURCE_VERSION
    assert source.calls == []
    assert clock.calls == 0


def test_command_requires_nonempty_namespace_before_repository_or_source_access() -> None:
    """The namespace is a mandatory part of the replay locator, never inferred."""

    scenario = _scenario()
    command = replace(_command(scenario), source_namespace="")
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionInputError):
        _use_case(repository, clock, _binding(source)).execute(command)

    assert repository.resolve_calls == []
    assert source.calls == []
    assert clock.calls == 0


def test_new_event_namespace_matches_reader_before_source_access() -> None:
    """A caller cannot select a namespace different from the injected reader binding."""

    scenario = _scenario()
    command = replace(_command(scenario), source_namespace="other-local-matcher")
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, clock, _binding(source)).execute(command)

    assert repository.resolve_calls[0]["source_namespace"] == command.source_namespace
    assert source.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_same_raw_event_id_in_another_namespace_does_not_replay_this_order() -> None:
    """A namespace-B lookup cannot receive the same raw ID stored under namespace A."""

    scenario = _scenario()
    command = replace(_command(scenario), source_namespace="other-local-matcher")
    repository = _Repository([scenario.context])
    source = _Source(None)
    binding = LocalSimulatedFillSourceBinding(
        reader=source,
        source_namespace=command.source_namespace,
        source_version=SOURCE_VERSION,
    )

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, _Clock(), binding).execute(command)

    assert repository.resolve_calls[0]["source_namespace"] == "other-local-matcher"
    assert repository.resolve_calls[0]["fill_event_id"] == scenario.event.source_event_id
    assert len(source.calls) == 1
    assert source.calls[0]["source_namespace"] == "other-local-matcher"
    assert repository.apply_calls == []


def test_wrong_namespace_receipt_is_not_returned_as_exact_replay() -> None:
    """A repository locator mismatch is result-unknown, never a cross-namespace replay."""

    scenario = _scenario()
    command = replace(_command(scenario), source_namespace="other-local-matcher")
    repository = _Repository([ExistingOrderFill(scenario.result)])
    source = _Source(None)
    binding = LocalSimulatedFillSourceBinding(
        reader=source,
        source_namespace=command.source_namespace,
        source_version=SOURCE_VERSION,
    )
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _use_case(repository, clock, binding).execute(command)

    assert repository.resolve_calls[0]["source_namespace"] == command.source_namespace
    assert source.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


@pytest.mark.parametrize(
    ("expected_hash", "raises"),
    [
        (EVENT_HASH, False),
        ("e" * 64, True),
    ],
)
def test_existing_event_expected_hash_is_checked_without_source_io(
    expected_hash: str, raises: bool
) -> None:
    """A replay either matches its stored source hash or raises a key conflict."""

    scenario = _scenario()
    repository = _Repository([ExistingOrderFill(scenario.result)])
    source = _Source(None)
    clock = _Clock()
    use_case = _use_case(repository, clock, _binding(source))

    if raises:
        with pytest.raises(SimulatedTradeIdempotencyConflict):
            use_case.execute(_command(scenario, expected_hash))
    else:
        result = use_case.execute(_command(scenario, expected_hash))
        assert result.replayed is True
    assert source.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_unknown_owner_scoped_order_blocks_without_reading_source() -> None:
    """An unresolved order cannot be used to query a local matcher event."""

    scenario = _scenario()
    repository = _Repository([None])
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeAccountScopeUnavailable):
        _use_case(repository, clock, _binding(source)).execute(_command(scenario))

    assert source.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_terminal_order_rejects_unseen_event_before_clock_and_source() -> None:
    """A terminal hold with no stored exact event never asks the source for a new fill."""

    scenario = _scenario()
    terminal_context = replace(
        scenario.context,
        reservation=scenario.context.reservation.release_remaining(),
    )
    repository = _Repository([terminal_context])
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, clock, _binding(source)).execute(_command(scenario))

    assert source.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_missing_source_binding_blocks_only_after_replay_lookup() -> None:
    """A new event cannot proceed without a composition-root source binding."""

    scenario = _scenario()
    repository = _Repository([scenario.context])
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, clock, binding=None).execute(_command(scenario))

    assert len(repository.resolve_calls) == 1
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_unavailable_source_event_blocks_without_ledger_apply() -> None:
    """A missing durable event is not synthesized into a fill."""

    scenario = _scenario()
    repository = _Repository([scenario.context])
    source = _Source(None)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, clock, _binding(source)).execute(_command(scenario))

    assert len(source.calls) == 1
    assert source.calls[0]["as_of"] == AS_OF
    assert repository.apply_calls == []
    assert clock.calls == 1


@pytest.mark.parametrize(
    "field_change",
    [
        ("source_namespace", "other-local-matcher"),
        ("source_version", "unsupported-v9"),
    ],
)
def test_event_source_namespace_and_version_must_match_injected_binding(
    field_change: tuple[str, str],
) -> None:
    """Event self-labels cannot replace the explicitly injected source binding."""

    scenario = _scenario()
    field_name, value = field_change
    event = replace(scenario.event, **{field_name: value})
    source = _Source(event)
    repository = _Repository([scenario.context])

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert repository.apply_calls == []


@pytest.mark.parametrize(
    "event_change",
    [
        {"source_event_id": "different-event"},
        {"account_id": 8},
        {"user_id": 12},
        {"order_idempotency_key": "different-order"},
        {"reservation_id": 42},
        {"intent_payload_hash": "f" * 64},
        {"reservation_request_hash": "f" * 64},
        {"plan_snapshot_hash": "f" * 64},
        {"security_id": "OTHER.SECURITY"},
        {"asset_code": "000001.SZ"},
        {"side": SimulatedTradeSide.SELL},
    ],
)
def test_event_must_match_owner_order_and_sealed_context(
    event_change: dict[str, object],
) -> None:
    """Every event scope field is checked before a repository write is attempted."""

    scenario = _scenario()
    event = replace(scenario.event, **event_change)
    source = _Source(event)
    repository = _Repository([scenario.context])

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert repository.apply_calls == []


def test_unknown_event_kind_is_blocked_instead_of_becoming_a_regular_fill(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An UNKNOWN matcher event has a distinct fail-closed path."""

    scenario = _scenario()
    event = replace(scenario.event, event_kind=LocalSimulatedFillEventKind.UNKNOWN)
    source = _Source(event)
    repository = _Repository([scenario.context])

    with caplog.at_level(
        logging.WARNING,
        logger="apps.simulated_trading.application.order_reservation_fill",
    ):
        with pytest.raises(SimulatedTradeExecutionBlocked) as captured:
            _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert captured.value.code == "SIMULATED_FILL_EVENT_KIND_UNKNOWN"
    assert repository.apply_calls == []
    warnings = [
        record
        for record in caplog.records
        if record.name == "apps.simulated_trading.application.order_reservation_fill"
    ]
    assert len(warnings) == 1
    assert getattr(warnings[0], "code", None) == "SIMULATED_FILL_EVENT_KIND_UNKNOWN"
    assert "matcher-event-0001" not in warnings[0].getMessage()
    assert EVENT_HASH not in warnings[0].getMessage()


@pytest.mark.parametrize(
    "clock_field",
    ["occurred_at", "source_observed_at", "source_available_at", "recorded_at"],
)
def test_naive_event_clocks_are_rejected_without_inventing_timing_order(
    clock_field: str,
) -> None:
    """All source clocks must be aware, while their causal ordering belongs to its source contract."""

    scenario = _scenario()
    event = replace(scenario.event, **{clock_field: datetime(2026, 10, 16, 2, 0)})
    source = _Source(event)
    repository = _Repository([scenario.context])

    with pytest.raises(SimulatedTradeExecutionBlocked):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert repository.apply_calls == []


def test_command_expected_hash_must_match_new_source_event_before_apply() -> None:
    """A caller's observed event digest binds the new application attempt."""

    scenario = _scenario()
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)

    with pytest.raises(SimulatedTradeIdempotencyConflict):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario, "e" * 64))

    assert repository.apply_calls == []


def test_valid_partial_event_is_forwarded_without_recomputing_economics() -> None:
    """The Application preserves the reader event and delegates FeeV2 math to Domain/Repository."""

    scenario = _scenario()
    repository = _Repository([scenario.context], apply_result=scenario.result)
    source = _Source(scenario.event)
    clock = _Clock()
    proof = _settlement_proof()
    resolver = _SettlementResolver(proof)

    result = _use_case(repository, clock, _binding(source), settlement_resolver=resolver).execute(
        _command(scenario)
    )

    assert result.economics is scenario.result.economics
    assert result.event_payload_hash == scenario.event.event_payload_hash
    assert result.economics.payload_hash != result.event_payload_hash
    assert repository.apply_calls[0]["event"] is scenario.event
    assert repository.apply_calls[0]["expected_event_payload_hash"] == EVENT_HASH
    assert repository.apply_calls[0]["settlement_proof"] is proof
    assert resolver.calls == [
        {
            "event_occurred_at": scenario.event.occurred_at,
            "settlement_exchange": scenario.context.settlement_exchange,
            "settlement_lag_sessions": scenario.context.settlement_lag_sessions,
        }
    ]
    assert repository.apply_calls[0]["clock"] is clock
    assert clock.calls == 1


@pytest.mark.parametrize(
    ("event_kind", "economics_close_order"),
    (
        (LocalSimulatedFillEventKind.FILL, True),
        (LocalSimulatedFillEventKind.FINAL_FILL, False),
    ),
)
def test_repository_close_flag_must_match_the_exact_fill_kind(
    event_kind: LocalSimulatedFillEventKind,
    economics_close_order: bool,
) -> None:
    """A mismatched receipt is unknown and never returned as a successful fill."""

    scenario = _scenario(
        event_kind=event_kind,
        economics_close_order=economics_close_order,
    )
    repository = _Repository(
        [scenario.context, scenario.context],
        apply_result=scenario.result,
    )
    source = _Source(scenario.event)

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert len(repository.apply_calls) == 1
    assert len(repository.resolve_calls) == 2


def test_final_fill_kind_is_forwarded_and_close_semantics_are_not_a_command_field() -> None:
    """Only the bound event kind can produce the Domain final-fill close flag."""

    scenario = _scenario(event_kind=LocalSimulatedFillEventKind.FINAL_FILL)
    repository = _Repository([scenario.context], apply_result=scenario.result)
    source = _Source(scenario.event)

    result = _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert repository.apply_calls[0]["event"] is scenario.event
    assert result.economics.close_order is True
    assert not hasattr(_command(scenario), "close_order")


def test_invalid_repository_readback_is_reported_as_result_unknown() -> None:
    """A malformed returned receipt is treated as potentially committed, not as a clean block."""

    scenario = _scenario()
    malformed = replace(scenario.result, event_payload_hash="e" * 64)
    repository = _Repository([scenario.context, scenario.context], apply_result=malformed)
    source = _Source(scenario.event)

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert len(repository.resolve_calls) == 2
    assert len(repository.apply_calls) == 1


def test_unknown_commit_replays_only_after_exact_owner_scoped_hash_readback() -> None:
    """An unknown result can recover from an exact persisted event without reading source twice."""

    scenario = _scenario()
    repository = _Repository(
        [scenario.context, ExistingOrderFill(replace(scenario.result, replayed=False))],
        apply_error=SimulatedTradeExecutionResultUnknown("write response lost"),
    )
    source = _Source(scenario.event)
    clock = _Clock()
    resolver = _SettlementResolver(_settlement_proof(), fail_after_first=True)

    result = _use_case(repository, clock, _binding(source), settlement_resolver=resolver).execute(
        _command(scenario)
    )

    assert result.replayed is True
    assert len(resolver.calls) == 1
    assert len(source.calls) == 1
    assert len(repository.resolve_calls) == 2
    assert repository.resolve_calls[1]["source_namespace"] == scenario.event.source_namespace
    assert repository.resolve_calls[1]["fill_event_id"] == scenario.event.source_event_id
    assert len(repository.apply_calls) == 1
    assert clock.calls == 1


def test_unknown_commit_readback_with_same_event_id_and_different_hash_conflicts() -> None:
    """A durable key collision is never treated as a successful replay."""

    scenario = _scenario()
    conflicting_result = replace(scenario.result, event_payload_hash="e" * 64)
    repository = _Repository(
        [scenario.context, ExistingOrderFill(conflicting_result)],
        apply_error=SimulatedTradeExecutionResultUnknown("write response lost"),
    )
    source = _Source(scenario.event)

    with pytest.raises(SimulatedTradeIdempotencyConflict):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert len(repository.resolve_calls) == 2
    assert len(repository.apply_calls) == 1
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("source_namespace", "other-local-matcher"),
        ("source_version", "fixture-v2"),
    ),
)
def test_unknown_commit_readback_requires_original_namespace_and_version(
    field_name: str, value: str
) -> None:
    """Unknown-result recovery cannot accept a same-ID receipt from another source schema."""

    scenario = _scenario()
    mismatched_result = replace(scenario.result, **{field_name: value})
    repository = _Repository(
        [scenario.context, ExistingOrderFill(mismatched_result)],
        apply_error=SimulatedTradeExecutionResultUnknown("write response lost"),
    )
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _use_case(repository, clock, _binding(source)).execute(_command(scenario))

    assert len(source.calls) == 1
    assert source.calls[0]["source_namespace"] == scenario.event.source_namespace
    assert len(repository.resolve_calls) == 2
    assert all(
        call["source_namespace"] == scenario.event.source_namespace
        for call in repository.resolve_calls
    )
    assert len(repository.apply_calls) == 1
    assert clock.calls == 1


def test_unknown_commit_without_exact_readback_remains_unknown_without_new_event_id() -> None:
    """A missing post-commit readback cannot trigger a new event identity or another write."""

    scenario = _scenario()
    repository = _Repository(
        [scenario.context, scenario.context],
        apply_error=SimulatedTradeExecutionResultUnknown("commit outcome unknown"),
    )
    source = _Source(scenario.event)

    with pytest.raises(SimulatedTradeExecutionResultUnknown):
        _use_case(repository, _Clock(), _binding(source)).execute(_command(scenario))

    assert len(source.calls) == 1
    assert source.calls[0]["fill_event_id"] == scenario.event.source_event_id
    assert len(repository.resolve_calls) == 2
    assert len(repository.apply_calls) == 1


@pytest.mark.parametrize("competing_fill", [True, False])
def test_competing_fill_or_cancel_between_resolve_and_apply_is_decided_under_lock(
    competing_fill: bool,
) -> None:
    """A locked event reread replays a fill or rejects a cancel without that event."""

    scenario = _scenario(event_kind=LocalSimulatedFillEventKind.FINAL_FILL)
    repository = _InterleavingRepository(scenario.context)

    def transition() -> None:
        """Apply the competing commit or cancel in the source-read seam."""

        if competing_fill:
            repository.commit_competing_fill(scenario.result)
        else:
            repository.cancel_without_fill()

    source = _InterleavingSource(scenario.event, after_resolve=transition)
    use_case = _use_case(repository, _Clock(), _binding(source))

    if competing_fill:
        result = use_case.execute(_command(scenario))
        assert result.replayed is True
        assert result.trade_id == scenario.result.trade_id
        assert repository.persisted_trade_count == 1
    else:
        with pytest.raises(SimulatedTradeExecutionBlocked):
            use_case.execute(_command(scenario))
        assert repository.persisted_trade_count == 0

    assert repository.locked_exact_event_reads == 1
    assert len(repository.resolve_calls) == 1
    assert len(repository.apply_calls) == 1
    assert repository.apply_calls[0]["event"] is scenario.event


@pytest.mark.parametrize(
    "readback_error_type",
    [SimulatedTradeExecutionBlocked, SimulatedTradeAccountScopeUnavailable],
)
def test_blocked_unknown_readback_preserves_original_error_and_explicit_cause(
    monkeypatch: pytest.MonkeyPatch,
    readback_error_type: type[SimulatedTradeExecutionBlocked],
) -> None:
    """A failed readback cannot erase the original uncertain write's failure chain."""

    scenario = _scenario()
    cause = ValueError("original persisted receipt could not be decoded")
    original_error = SimulatedTradeExecutionResultUnknown("write outcome unknown")
    original_error.__cause__ = cause
    repository = _Repository([scenario.context], apply_error=original_error)
    original_resolve = repository.resolve_fill_request
    read_count = 0

    def resolve_then_block_readback(
        *,
        account_id: int,
        user_id: int,
        order_idempotency_key: str,
        source_namespace: str,
        fill_event_id: str,
    ) -> ExistingOrderFill | OrderFillContext | None:
        """Keep initial context real and refuse only the post-write recovery read."""

        nonlocal read_count
        read_count += 1
        if read_count == 2:
            raise readback_error_type("readback is no longer permitted")
        return original_resolve(
            account_id=account_id,
            user_id=user_id,
            order_idempotency_key=order_idempotency_key,
            source_namespace=source_namespace,
            fill_event_id=fill_event_id,
        )

    monkeypatch.setattr(repository, "resolve_fill_request", resolve_then_block_readback)
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionResultUnknown) as raised:
        _use_case(repository, clock, _binding(source)).execute(_command(scenario))

    assert raised.value is original_error
    assert raised.value.__cause__ is cause
    assert raised.value.effects_indeterminate is True
    assert read_count == 2
    assert len(repository.apply_calls) == len(source.calls) == clock.calls == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("settlement_exchange", ""),
        ("settlement_lag_sessions", True),
        ("settlement_lag_sessions", -1),
        ("settlement_lag_sessions", 1.0),
    ),
)
def test_invalid_sealed_settlement_context_blocks_before_source_or_calendar(
    field_name: str, value: object
) -> None:
    """The sealed plan exchange and lag must be explicit exact context fields."""

    scenario = _scenario()
    context = replace(scenario.context, **{field_name: value})
    repository = _Repository([context])
    source = _Source(scenario.event)
    resolver = _SettlementResolver(_settlement_proof())
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _use_case(
            repository,
            clock,
            _binding(source),
            settlement_resolver=resolver,
        ).execute(_command(scenario))

    assert raised.value.code == "SIMULATED_FILL_CONTEXT_INVALID"
    assert source.calls == []
    assert resolver.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_new_event_without_calendar_resolver_blocks_after_exact_replay_lookup() -> None:
    """New fills require a calendar resolver, while the order lookup still happens first."""

    scenario = _scenario()
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _use_case(
            repository,
            clock,
            _binding(source),
            default_settlement_resolver=False,
        ).execute(_command(scenario))

    assert raised.value.code == "SIMULATED_FILL_SETTLEMENT_UNAVAILABLE"
    assert len(repository.resolve_calls) == 1
    assert source.calls == []
    assert repository.apply_calls == []
    assert clock.calls == 0


def test_calendar_resolver_none_blocks_without_applying_event() -> None:
    """A missing proof is a typed zero-write block, not an inferred session."""

    scenario = _scenario()
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    resolver = _SettlementResolver(None)
    clock = _Clock()

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _use_case(
            repository,
            clock,
            _binding(source),
            settlement_resolver=resolver,
        ).execute(_command(scenario))

    assert raised.value.code == "SIMULATED_FILL_SETTLEMENT_UNAVAILABLE"
    assert len(source.calls) == 1
    assert resolver.calls == [
        {
            "event_occurred_at": scenario.event.occurred_at,
            "settlement_exchange": scenario.context.settlement_exchange,
            "settlement_lag_sessions": scenario.context.settlement_lag_sessions,
        }
    ]
    assert repository.apply_calls == []
    assert clock.calls == 1


def test_calendar_resolver_wrong_exact_type_blocks_without_applying_event() -> None:
    """The Application accepts only the exact typed Domain proof result."""

    scenario = _scenario()
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    resolver = _SettlementResolver({"fill_market_session": "2026-10-16"})

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _use_case(
            repository,
            _Clock(),
            _binding(source),
            settlement_resolver=resolver,
        ).execute(_command(scenario))

    assert raised.value.code == "SIMULATED_FILL_SETTLEMENT_PROOF_INVALID"
    assert len(resolver.calls) == 1
    assert repository.apply_calls == []


@pytest.mark.parametrize("mismatch", ["event_time", "exchange", "lag"])
def test_calendar_proof_must_bind_exact_event_and_sealed_plan(mismatch: str) -> None:
    """A valid proof for a different event instant, exchange, or lag cannot be reused."""

    scenario = _scenario()
    if mismatch == "event_time":
        proof = _settlement_proof(event_occurred_at=AS_OF - timedelta(seconds=1))
    elif mismatch == "exchange":
        proof = _settlement_proof(settlement_exchange="SZ")
    else:
        proof = _settlement_proof(settlement_lag_sessions=0)
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    resolver = _SettlementResolver(proof)

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _use_case(
            repository,
            _Clock(),
            _binding(source),
            settlement_resolver=resolver,
        ).execute(_command(scenario))

    assert raised.value.code == "SIMULATED_FILL_SETTLEMENT_PROOF_INVALID"
    assert resolver.calls == [
        {
            "event_occurred_at": scenario.event.occurred_at,
            "settlement_exchange": scenario.context.settlement_exchange,
            "settlement_lag_sessions": scenario.context.settlement_lag_sessions,
        }
    ]
    assert repository.apply_calls == []


def test_calendar_proof_domain_revalidation_rejects_invalid_evidence() -> None:
    """An exact proof object is revalidated instead of trusting its construction site."""

    scenario = _scenario()
    proof = _settlement_proof()
    object.__setattr__(proof, "calendar_read_cutoff", AS_OF - timedelta(seconds=1))
    repository = _Repository([scenario.context])
    source = _Source(scenario.event)
    resolver = _SettlementResolver(proof)

    with pytest.raises(SimulatedTradeExecutionBlocked) as raised:
        _use_case(
            repository,
            _Clock(),
            _binding(source),
            settlement_resolver=resolver,
        ).execute(_command(scenario))

    assert raised.value.code == "SIMULATED_FILL_SETTLEMENT_PROOF_INVALID"
    assert raised.value.__cause__ is not None
    assert repository.apply_calls == []


def test_use_case_uses_real_calendar_resolver_and_binds_published_proof() -> None:
    """Resolve one actual published-calendar proof through the application use case."""
    scenario = _scenario()
    repository = _Repository([scenario.context], apply_result=scenario.result)
    source = _Source(scenario.event)
    clock = _Clock()
    evidence = _calendar_evidence()
    calendar_reader = _PublishedCalendarReader(evidence)
    resolver = OrderFillSettlementCalendarResolver(calendar_reader=calendar_reader, clock=clock)
    use_case = _use_case(repository, clock, _binding(source), settlement_resolver=resolver)

    result = use_case.execute(_command(scenario))

    assert result is scenario.result
    assert len(repository.apply_calls) == 1
    proof = repository.apply_calls[0]["settlement_proof"]
    assert type(proof) is OrderFillSettlementProof
    assert proof.calendar_evidence is evidence
    assert proof.calendar_read_cutoff == AS_OF
    assert proof.fill_occurred_at == scenario.event.occurred_at == AS_OF
    assert proof.settlement_exchange == scenario.context.settlement_exchange == SETTLEMENT_EXCHANGE
    assert proof.settlement_lag_sessions == scenario.context.settlement_lag_sessions == 1
    assert proof.fill_market_session == date(2026, 10, 16)
    assert proof.expected_release_session == date(2026, 10, 19)
    assert calendar_reader.calls == [
        {
            "exchange": SETTLEMENT_EXCHANGE,
            "as_of": AS_OF,
            "coverage_start": date(2026, 10, 15),
        }
    ]
    assert clock.calls == 2
