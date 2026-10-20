"""Public reset API contract for retained simulated-order fill history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

import pytest
from django.db.models import Model
from rest_framework.test import APIClient

from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
    SimulatedOrderReservationModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading.test_execution_settlement_uow import (
    AS_OF,
    _Clock,
)
from tests.component.simulated_trading.test_execution_settlement_uow import ledger as ledger
from tests.component.simulated_trading.test_order_reservation_fill_storage import (
    _create_receipt,
    _create_reservation,
    _create_trade,
    _promote_trade_to_v4,
    _receipt_model,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    _Harness,
)
from tests.component.simulated_trading.test_order_reservation_repository import (
    reservation_harness as reservation_harness,
)
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation,
)
from tests.support.isolated_schema import isolated_schema

pytestmark = pytest.mark.django_db(transaction=True)


@dataclass(frozen=True)
class _AccountHistorySnapshot:
    """Capture every persisted field of the account's core financial history."""

    account: tuple[object, ...]
    positions: tuple[tuple[object, ...], ...]
    trades: tuple[tuple[object, ...], ...]
    reservations: tuple[tuple[object, ...], ...]
    receipts: tuple[tuple[object, ...], ...]


def _rows_for_account(
    model: type[Model],
    *,
    lookup: str,
    account_id: int,
) -> tuple[tuple[object, ...], ...]:
    """Read complete persisted rows through an explicit ORM-boundary cast."""

    rows = model._base_manager.filter(**{lookup: account_id}).order_by("pk").values_list()
    return tuple(cast(tuple[object, ...], row) for row in rows)


def _account_history_snapshot(
    *,
    account_id: int,
    receipt_model: type[Model],
) -> _AccountHistorySnapshot:
    """Return all core account, position, trade, order, and receipt row values."""

    account_rows = _rows_for_account(
        SimulatedAccountModel,
        lookup="pk",
        account_id=account_id,
    )
    assert len(account_rows) == 1
    return _AccountHistorySnapshot(
        account=account_rows[0],
        positions=_rows_for_account(
            PositionModel,
            lookup="account_id",
            account_id=account_id,
        ),
        trades=_rows_for_account(
            SimulatedTradeModel,
            lookup="account_id",
            account_id=account_id,
        ),
        reservations=_rows_for_account(
            SimulatedOrderReservationModel,
            lookup="account_id",
            account_id=account_id,
        ),
        receipts=_rows_for_account(
            receipt_model,
            lookup="reservation__account_id",
            account_id=account_id,
        ),
    )


@pytest.mark.parametrize(
    "history_kind",
    ["receipt", "v4_trade"],
    ids=["receipt-history", "v4-trade-history"],
)
def test_owned_reset_api_rejects_retained_fill_history_without_mutation(
    api_client: APIClient,
    reservation_harness: _Harness,
    history_kind: Literal["receipt", "v4_trade"],
) -> None:
    """Both durable fill markers produce the public 422 contract and preserve rows."""

    account = reservation_harness.account
    assert type(account.pk) is int
    assert type(account.user_id) is int
    assert account.user_id == reservation_harness.user_id

    trade = _create_trade(
        reservation_harness,
        key=f"api-reset-fill-trade-{history_kind}",
    )
    reservation = _create_reservation(
        reservation_harness,
        key=f"api-reset-fill-order-{history_kind}",
    )
    receipt_model = _receipt_model()

    with isolated_schema((receipt_model,)):
        if history_kind == "receipt":
            assert trade.settlement_plan_binding_version < 4
            _create_receipt(
                reservation,
                trade,
                namespace="api-reset-history-test",
                event_id=f"api-reset-fill-event-{history_kind}",
            )
        else:
            trade = _promote_trade_to_v4(
                trade,
                reservation,
                namespace="api-reset-history-test",
                event_id=f"api-reset-fill-event-{history_kind}",
            )

        cancelled = reservation_harness.repository.cancel_order(
            account_id=account.pk,
            user_id=reservation_harness.user_id,
            idempotency_key=reservation.idempotency_key,
            clock=_Clock(AS_OF),
        )
        assert cancelled.status.value == "cancelled"

        owner = account.user
        assert owner is not None
        api_client.force_authenticate(user=owner)
        before = _account_history_snapshot(
            account_id=account.pk,
            receipt_model=receipt_model,
        )

        response = api_client.post(
            f"/api/simulated-trading/accounts/{account.pk}/reset/",
            {},
            format="json",
        )

        assert response.status_code == 422
        assert response["Content-Type"].split(";", 1)[0] == "application/json"
        payload = cast(dict[str, object], response.json())
        assert payload["code"] == "ORDER_FILL_HISTORY_RETAINED"
        assert (
            _account_history_snapshot(
                account_id=account.pk,
                receipt_model=receipt_model,
            )
            == before
        )
