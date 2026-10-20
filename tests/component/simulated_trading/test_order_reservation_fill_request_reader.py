"""Owner-scoped, read-only lookup tests for persisted simulated-order fills."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, models
from django.test.utils import CaptureQueriesContext

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.order_reservation_fill import (
    ExistingOrderFill,
    OrderFillContext,
)
from apps.simulated_trading.domain.execution_settlement_uow import (
    SimulatedTradeIntent,
    SimulatedTradeSide,
)
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_request_reader import (
    DjangoSimulatedOrderFillRequestReader,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from tests.component.simulated_trading import test_order_reservation_fill_row_reader as row_fixtures
from tests.component.simulated_trading import (
    test_order_reservation_repository as reservation_fixtures,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
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

_ORDER_KEY = "fill-row-reader-order"
_SOURCE_NAMESPACE = "row-reader-local-matcher"
_EVENT_ID = "row-reader-event-0001"


@pytest.fixture
def persisted_receipt_schema(reservation_harness: _Harness) -> Iterator[None]:
    """Create only the receipt table after the real account and reservation parents."""

    del reservation_harness
    with isolated_schema((SimulatedOrderFillReceiptModel,)):
        yield None


def _resolve(
    reader: DjangoSimulatedOrderFillRequestReader,
    harness: _Harness,
    *,
    event_id: str = _EVENT_ID,
    user_id: int | None = None,
) -> object:
    """Address one exact owner/account/order/source event locator."""

    account_id = harness.account.pk
    assert type(account_id) is int
    return reader.resolve_fill_request(
        account_id=account_id,
        user_id=harness.user_id if user_id is None else user_id,
        order_idempotency_key=_ORDER_KEY,
        source_namespace=_SOURCE_NAMESPACE,
        fill_event_id=event_id,
    )


def _ten_share_intent(
    harness: _Harness,
    *,
    side: SimulatedTradeSide,
    key: str,
) -> SimulatedTradeIntent:
    """Make the row-reader helper's single test fill a terminal full fill."""

    return reservation_fixtures._intent_for(
        harness,
        side=side,
        key=key,
        quantity=Decimal("10.000000"),
    )


def test_active_miss_returns_context_from_the_sealed_plan_without_writes(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """An active miss decodes the exact parent and exposes only sealed settlement scope."""

    del persisted_receipt_schema
    rows = row_fixtures._reader_rows(reservation_harness)
    rows.reservation.refresh_from_db()
    assert rows.reservation.filled_quantity == Decimal("0.000000")
    assert rows.reservation.cash_consumed == Decimal("0.00")
    reader = DjangoSimulatedOrderFillRequestReader(using="default")

    with CaptureQueriesContext(connection) as captured:
        result = _resolve(reader, reservation_harness)

    assert type(result) is OrderFillContext
    assert result.reservation_id == rows.reservation.pk
    assert result.account_id == reservation_harness.account.pk
    assert result.owner_user_id == reservation_harness.user_id
    assert result.order_idempotency_key == _ORDER_KEY
    assert result.reservation == decode_order_reservation(rows.reservation)
    assert result.asset_code == rows.reservation.asset_code
    assert result.intent_payload_hash == rows.reservation.intent_payload_hash
    assert result.plan_snapshot_hash == rows.reservation.plan_snapshot_hash
    assert result.settlement_exchange == rows.proof.settlement_exchange
    assert result.settlement_lag_sessions == rows.proof.settlement_lag_sessions
    assert result.reservation.status is OrderReservationStatus.ACTIVE
    assert captured.captured_queries
    assert all(
        query["sql"].lstrip().upper().startswith("SELECT") for query in captured.captured_queries
    )


def test_terminal_miss_returns_context_but_inactive_miss_does_not(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """The Application handles terminal status; an inactive account cannot start new work."""

    del persisted_receipt_schema
    rows = row_fixtures._reader_rows(reservation_harness)
    # The shared row helper models a partial fill in memory; this test transitions
    # the persisted initial reservation, so derive cancellation from the DB row.
    rows.reservation.refresh_from_db()
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_ACTIVE
    assert rows.reservation.filled_quantity == Decimal("0.000000")
    assert rows.reservation.cash_consumed == Decimal("0.00")
    assert rows.reservation.shares_consumed == Decimal("0.000000")
    assert rows.reservation.cash_released == Decimal("0.00")
    assert rows.reservation.shares_released == Decimal("0.000000")
    reservation = decode_order_reservation(rows.reservation)
    cancelled = reservation.release_remaining()
    cancelled_at = reservation.reserved_at + timedelta(seconds=1)
    updated = models.QuerySet.update(
        SimulatedOrderReservationModel.objects.filter(pk=rows.reservation.pk),
        status=cancelled.status.value,
        filled_quantity=cancelled.filled_quantity,
        cash_consumed=cancelled.cash_consumed,
        shares_consumed=cancelled.shares_consumed,
        cash_released=cancelled.cash_released,
        shares_released=cancelled.shares_released,
        cancelled_at=cancelled_at,
    )
    assert updated == 1

    reader = DjangoSimulatedOrderFillRequestReader(using="default")
    terminal = _resolve(reader, reservation_harness, event_id="not-yet-receipted")
    assert type(terminal) is OrderFillContext
    assert terminal.reservation.status is OrderReservationStatus.CANCELLED

    account_id = reservation_harness.account.pk
    assert type(account_id) is int
    deactivated = SimulatedAccountModel.objects.filter(pk=account_id).update(is_active=False)
    assert deactivated == 1
    assert _resolve(reader, reservation_harness, event_id="another-unseen-event") is None


def test_exact_receipt_replays_for_inactive_terminal_order_but_not_wrong_owner(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saved exact receipt precedes active/terminal gates while owner scope remains strict."""

    del persisted_receipt_schema
    monkeypatch.setattr(row_fixtures, "_intent_for", _ten_share_intent)
    rows = row_fixtures._persist_reader_rows(row_fixtures._reader_rows(reservation_harness))
    assert rows.reservation.status == SimulatedOrderReservationModel.STATUS_COMPLETED

    account_id = reservation_harness.account.pk
    assert type(account_id) is int
    deactivated = SimulatedAccountModel.objects.filter(pk=account_id).update(is_active=False)
    assert deactivated == 1

    reader = DjangoSimulatedOrderFillRequestReader(using="default")
    replay = _resolve(reader, reservation_harness)
    assert type(replay) is ExistingOrderFill
    assert replay.result.replayed is True
    assert replay.result.reservation_id == rows.reservation.pk
    assert replay.result.trade_id == rows.trade.pk
    assert replay.result.source_namespace == rows.event.source_namespace
    assert replay.result.source_version == rows.event.source_version
    assert replay.result.event_payload_hash == rows.event.event_payload_hash
    assert replay.result.economics == rows.economics
    assert replay.result.reservation.status is OrderReservationStatus.COMPLETED

    hidden = _resolve(
        reader,
        reservation_harness,
        user_id=reservation_harness.user_id + 1,
    )
    assert hidden is None


def test_invalid_persisted_receipt_is_blocked_by_the_strict_row_reader(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A syntactically stored but detached receipt cannot become an exact replay."""

    del persisted_receipt_schema
    rows = row_fixtures._reader_rows(reservation_harness)
    rows.receipt.source_event_payload_hash = "9" * 64
    row_fixtures._persist_reader_rows(rows)

    reader = DjangoSimulatedOrderFillRequestReader(using="default")
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        _resolve(reader, reservation_harness)

    assert error.value.code == "SIMULATED_FILL_RECEIPT_INVALID"
    assert error.value.__cause__ is not None


def test_invalid_parent_plan_hash_blocks_new_context(
    reservation_harness: _Harness,
    persisted_receipt_schema: None,
) -> None:
    """A parent snapshot that no longer matches its seal never supplies exchange or lag."""

    del persisted_receipt_schema
    rows = row_fixtures._reader_rows(reservation_harness)
    updated = models.QuerySet.update(
        SimulatedOrderReservationModel.objects.filter(pk=rows.reservation.pk),
        plan_snapshot_hash="9" * 64,
    )
    assert updated == 1

    reader = DjangoSimulatedOrderFillRequestReader(using="default")
    with pytest.raises(SimulatedTradeExecutionBlocked) as error:
        _resolve(reader, reservation_harness, event_id="not-yet-receipted")

    assert error.value.code == "ORDER_RESERVATION_SNAPSHOT_INVALID"
