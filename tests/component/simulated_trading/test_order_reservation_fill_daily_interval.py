"""Exercise the daily-interval clock basis through the existing fill consumer.

The matcher is an injected test double here. These cases verify persistence,
receipt decoding, and exact replay compatibility; they do not qualify a source
or implement the durable producer.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
)
from apps.simulated_trading.application.order_reservation_fill import (
    LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    ApplySimulatedOrderFillCommand,
    ApplySimulatedOrderFillUseCase,
    LocalSimulatedFillEventV1,
    LocalSimulatedFillSourceBinding,
)
from apps.simulated_trading.domain.execution_settlement_calendar import (
    ExecutionCalendarEvidence,
)
from apps.simulated_trading.domain.order_reservation_fill_settlement import (
    OrderFillSettlementProof,
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
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    _EventReader,
    _FixedClock,
    _ledger_counts,
    _NoClock,
    _reservation_unfilled,
    _set_consistent_account_mark,
)
from tests.component.simulated_trading.test_order_reservation_fill_repository import (
    persisted_receipt_schema as persisted_receipt_schema,
)
from tests.component.simulated_trading.test_order_reservation_fill_row_reader import (
    _READ_CUTOFF,
    _reader_rows,
    _Rows,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _create_position,
    _Harness,
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
class _FixtureSettlementResolver:
    """Return the already-built proof for this consumer compatibility test."""

    proof: OrderFillSettlementProof

    def resolve(
        self,
        *,
        event_occurred_at: datetime,
        settlement_exchange: str,
        settlement_lag_sessions: int,
        sealed_calendar_evidence: ExecutionCalendarEvidence | None = None,
    ) -> OrderFillSettlementProof | None:
        """Return only the proof matching the exact event and sealed plan."""

        if (
            event_occurred_at != self.proof.fill_occurred_at
            or settlement_exchange != self.proof.settlement_exchange
            or settlement_lag_sessions != self.proof.settlement_lag_sessions
        ):
            return None
        return self.proof


def _daily_interval_event(rows: _Rows) -> LocalSimulatedFillEventV1:
    """Convert the existing event fixture to its explicit daily interval basis."""

    interval_end_at = rows.event.occurred_at
    return replace(
        rows.event,
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
        event_payload_hash="9" * 64,
        source_observed_at=None,
        source_available_at=None,
        recorded_at=interval_end_at + timedelta(seconds=10),
        observation_basis="daily_interval_end",
        interval_end_at=interval_end_at,
        local_known_at=interval_end_at + timedelta(seconds=5),
    )


def _invalid_daily_interval_event(
    event: LocalSimulatedFillEventV1,
    invalid_basis: str,
) -> LocalSimulatedFillEventV1:
    """Return one exact source-version, basis-pair, or future-clock defect."""

    if invalid_basis == "source_version":
        return replace(event, source_version="local-daily-interval.v2")
    if invalid_basis == "basis":
        return replace(event, observation_basis="legacy_source_observed")
    if invalid_basis == "future_recorded_at":
        return replace(
            event,
            local_known_at=_READ_CUTOFF,
            recorded_at=_READ_CUTOFF + timedelta(seconds=1),
        )
    raise AssertionError(f"unknown daily interval defect: {invalid_basis}")


def _fill_use_case(
    *,
    rows: _Rows,
    reader: _EventReader,
    clock: SimulatedTradeExecutionClock,
    source_binding: LocalSimulatedFillSourceBinding | None,
) -> ApplySimulatedOrderFillUseCase:
    """Compose the real repository with the explicit test-only source reader."""

    repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        using="default",
    )
    return ApplySimulatedOrderFillUseCase(
        repository=repository,
        clock=clock,
        source_binding=source_binding,
        settlement_resolver=_FixtureSettlementResolver(rows.proof),
    )


def _command(event: LocalSimulatedFillEventV1) -> ApplySimulatedOrderFillCommand:
    """Build the exact owner/order/source locator for the fixture event."""

    return ApplySimulatedOrderFillCommand(
        account_id=event.account_id,
        user_id=event.user_id,
        order_idempotency_key=event.order_idempotency_key,
        source_namespace=event.source_namespace,
        fill_event_id=event.source_event_id,
        expected_event_payload_hash=event.event_payload_hash,
    )


def _daily_case(harness: _Harness) -> tuple[_Rows, LocalSimulatedFillEventV1]:
    """Build a real reservation and existing receipt fixture without a matcher."""

    _create_position(harness.account)
    _set_consistent_account_mark(harness.account, market_value=Decimal("1000.00"))
    rows = _reader_rows(harness)
    event = _daily_interval_event(rows)
    return rows, event


def test_daily_interval_fill_persists_receipt_and_replays_without_live_readers(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """Store/read the daily event once, then replay its receipt without the source or clock."""

    del persisted_receipt_schema
    rows, event = _daily_case(reservation_harness)
    reader = _EventReader(event, [])
    binding = LocalSimulatedFillSourceBinding(
        reader=reader,
        source_namespace=event.source_namespace,
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    )
    use_case = _fill_use_case(
        rows=rows,
        reader=reader,
        clock=_FixedClock(_READ_CUTOFF),
        source_binding=binding,
    )

    result = use_case.execute(_command(event))

    assert result.replayed is False
    assert len(reader.calls) == 2
    trade = SimulatedTradeModel.objects.get(pk=result.trade_id)
    receipt = SimulatedOrderFillReceiptModel.objects.select_related(
        "reservation__account",
        "trade__account",
    ).get(trade=trade)
    decoded = read_order_reservation_fill_row(
        reservation_row=receipt.reservation,
        receipt_row=receipt,
        trade_row=trade,
    )
    assert decoded.event == event
    assert decoded.event.observation_basis == "daily_interval_end"
    assert decoded.event.source_observed_at is None
    assert decoded.event.source_available_at is None
    assert decoded.event.occurred_at == decoded.event.interval_end_at
    before_replay = _ledger_counts(reservation_harness.account)
    calls_before_replay = list(reader.calls)

    replay = _fill_use_case(
        rows=rows,
        reader=reader,
        clock=_NoClock(),
        source_binding=None,
    ).execute(_command(event))

    assert replay.replayed is True
    assert replay.trade_id == result.trade_id
    assert _ledger_counts(reservation_harness.account) == before_replay
    assert reader.calls == calls_before_replay


@pytest.mark.parametrize(
    "invalid_basis",
    ("source_version", "basis", "future_recorded_at"),
    ids=("source-version", "basis-pair", "future-recorded-at"),
)
def test_invalid_daily_interval_event_blocks_before_ledger_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    invalid_basis: str,
) -> None:
    """Reject incompatible or future daily clocks without changing financial rows."""

    del persisted_receipt_schema
    rows, event = _daily_case(reservation_harness)
    event = _invalid_daily_interval_event(event, invalid_basis)
    reader = _EventReader(event, [])
    binding = LocalSimulatedFillSourceBinding(
        reader=reader,
        source_namespace=event.source_namespace,
        source_version=LOCAL_DAILY_INTERVAL_SOURCE_VERSION,
    )
    use_case = _fill_use_case(
        rows=rows,
        reader=reader,
        clock=_FixedClock(_READ_CUTOFF),
        source_binding=binding,
    )
    before = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        use_case.execute(_command(event))

    assert blocked.value.code == "SIMULATED_FILL_SOURCE_INVALID"
    assert _ledger_counts(reservation_harness.account) == before
    assert len(reader.calls) == 1
    _reservation_unfilled(rows.reservation)
    assert not SimulatedTradeModel.objects.filter(account=reservation_harness.account).exists()
    assert not SimulatedOrderFillReceiptModel.objects.filter(
        reservation__account=reservation_harness.account
    ).exists()


@pytest.mark.parametrize(
    "invalid_basis",
    ("source_version", "basis", "future_recorded_at"),
    ids=("source-version", "basis-pair", "future-recorded-at"),
)
def test_daily_interval_repository_rejects_invalid_event_under_locks(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    invalid_basis: str,
) -> None:
    """The transactional writer rejects the same malformed events without ledger changes."""

    del persisted_receipt_schema
    rows, event = _daily_case(reservation_harness)
    event = _invalid_daily_interval_event(event, invalid_basis)
    reader = _EventReader(event, [])
    repository = DjangoSimulatedOrderFillRepository(
        event_reader=reader,
        using="default",
    )
    before = _ledger_counts(reservation_harness.account)

    with pytest.raises(SimulatedTradeExecutionBlocked) as blocked:
        repository.apply_fill_event(
            event=event,
            expected_event_payload_hash=event.event_payload_hash,
            settlement_proof=rows.proof,
            clock=_FixedClock(_READ_CUTOFF),
        )

    assert blocked.value.code == "SIMULATED_FILL_SOURCE_INVALID"
    assert _ledger_counts(reservation_harness.account) == before
    assert reader.calls == []
    _reservation_unfilled(rows.reservation)
    assert not SimulatedTradeModel.objects.filter(account=reservation_harness.account).exists()
    assert not SimulatedOrderFillReceiptModel.objects.filter(
        reservation__account=reservation_harness.account
    ).exists()
