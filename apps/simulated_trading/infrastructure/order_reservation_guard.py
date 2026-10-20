"""Shared row-lock guard for legacy simulated-ledger writers."""

from __future__ import annotations

from decimal import Decimal

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationBook,
)

from .order_reservation_codec import decode_order_reservation
from .order_reservation_models import SimulatedOrderReservationModel


def lock_active_order_reservations(
    *,
    account_id: int,
    using: str,
) -> list[SimulatedOrderReservationModel]:
    """Lock all live holds after the caller has locked the account parent row.

    Every writer that can spend cash or sellable shares uses the account row as
    its first lock. Reservers and legacy execution writers then acquire active
    reservation rows in primary-key order, making the same account lock the
    serialization fence even when the active set is empty.
    """

    return list(
        SimulatedOrderReservationModel._base_manager.using(using)
        .select_for_update()
        .filter(account_id=account_id, status=SimulatedOrderReservationModel.STATUS_ACTIVE)
        .order_by("pk")
    )


def lock_order_reservation_key(
    *,
    account_id: int,
    idempotency_key: str,
    using: str,
) -> SimulatedOrderReservationModel | None:
    """Lock a retained idempotency key after active rows were locked in order."""

    return (
        SimulatedOrderReservationModel._base_manager.using(using)
        .select_for_update()
        .filter(account_id=account_id, idempotency_key=idempotency_key)
        .first()
    )


def lock_legacy_execution_order_resources(
    *,
    account_id: int,
    owner_user_id: int,
    security_id: str,
    asset_code: str,
    idempotency_key: str,
    using: str,
) -> tuple[Decimal, Decimal]:
    """Lock active holds and permanently reject reuse of any retained order key."""

    rows = lock_active_order_reservations(account_id=account_id, using=using)
    if (
        lock_order_reservation_key(
            account_id=account_id,
            idempotency_key=idempotency_key,
            using=using,
        )
        is not None
    ):
        raise SimulatedTradeExecutionBlocked(
            "a retained order reservation already owns this idempotency key",
            code="ORDER_RESERVATION_KEY_RETAINED",
        )
    return active_order_reservation_holds(
        rows,
        account_id=account_id,
        owner_user_id=owner_user_id,
        security_id=security_id,
        asset_code=asset_code,
    )


def require_no_active_order_reservations(*, account_id: int, using: str) -> None:
    """Block an ordinary legacy write while any order owns held resources.

    The caller must already hold the simulated account parent lock. This
    helper deliberately rejects all active holds because the ordinary trade
    path has no fill identity that can consume a specific reservation.
    """

    rows = lock_active_order_reservations(account_id=account_id, using=using)
    if rows:
        raise SimulatedTradeExecutionBlocked(
            "an active order reservation owns cash or sellable shares",
            code="ORDER_RESERVATION_ACTIVE",
        )


def active_order_reservation_holds(
    rows: list[SimulatedOrderReservationModel],
    *,
    account_id: int,
    owner_user_id: int,
    security_id: str,
    asset_code: str,
) -> tuple[Decimal, Decimal]:
    """Validate locked rows and return exact Domain totals for held resources.

    The position ledger is keyed by asset code while order identity is keyed
    by canonical security ID. A mismatch in either spelling blocks rather
    than silently excluding a potentially matching SELL hold.
    """

    if (
        type(rows) is not list
        or type(account_id) is not int
        or account_id <= 0
        or type(owner_user_id) is not int
        or owner_user_id <= 0
        or type(security_id) is not str
        or not security_id
        or type(asset_code) is not str
        or not asset_code
    ):
        raise SimulatedTradeExecutionBlocked(
            "active order reservation scope is invalid",
            code="ORDER_RESERVATION_STATE_INVALID",
        )
    reservations: list[OrderReservation] = []
    for row in rows:
        if (
            row.account_id != account_id
            or row.owner_user_id != owner_user_id
            or row.status != SimulatedOrderReservationModel.STATUS_ACTIVE
        ):
            raise SimulatedTradeExecutionBlocked(
                "active order reservation identity is outside the locked owner scope",
                code="ORDER_RESERVATION_STATE_INVALID",
            )
        same_security = row.security_id == security_id
        same_asset_code = row.asset_code == asset_code
        if same_security != same_asset_code:
            raise SimulatedTradeExecutionBlocked(
                "active reservation security and ledger asset identities disagree",
                code="ORDER_RESERVATION_IDENTITY_CONFLICT",
            )
        reservations.append(decode_order_reservation(row))
    try:
        book = OrderReservationBook(
            account_id=account_id,
            security_id=security_id,
            book_cash=None,
            withdrawable_cash=None,
            sellable_shares=None,
            reservations=tuple(reservations),
        )
        return book.active_held_cash, book.active_held_shares
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "active reservation totals failed exact ledger validation",
            code="ORDER_RESERVATION_STATE_INVALID",
        ) from error
