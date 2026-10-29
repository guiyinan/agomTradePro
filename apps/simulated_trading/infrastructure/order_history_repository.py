"""Read owner-scoped order reservations and exact persisted fill receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict, cast

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from django.db import DEFAULT_DB_ALIAS, transaction

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.application.order_history import (
    OrderFillHistoryPage,
    OrderHistoryFill,
    OrderHistoryOrder,
    OrderHistoryPage,
)
from apps.simulated_trading.domain.order_reservation import (
    OrderReservation,
    OrderReservationStatus,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_codec import (
    decode_order_reservation,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_row_reader import (
    read_order_reservation_fill_row,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)

_CURSOR_SALT = "simulated-trading.order-history.v1"
_CURSOR_VERSION = 1
_CURSOR_MAX_LENGTH = 4096
_PAGE_LIMIT_MAX = 100


class _CursorPayload(TypedDict):
    """Signed page continuation, narrowed immediately after Django decoding."""

    version: int
    kind: str
    user_id: int
    account_id: int
    order_id: int | None
    last_pk: int
    membership_cutoff: str


class _ActorState(TypedDict):
    """The one user column required by the read-side authorization check."""

    is_active: object


@dataclass(frozen=True, slots=True)
class _CursorState:
    """Validated internal cursor scope for one orders or fills page."""

    last_pk: int | None
    membership_cutoff: datetime


class DjangoOrderHistoryRepository:
    """Lock and read current owner scope without changing order or ledger rows."""

    def __init__(self, *, using: str = DEFAULT_DB_ALIAS) -> None:
        """Select the database alias used for the history query."""

        if type(using) is not str or not using:
            raise SimulatedTradeExecutionInputError("订单历史数据库别名无效")
        self._using = using

    def list_orders(
        self,
        *,
        account_id: int,
        user_id: int,
        limit: int,
        cursor: str | None,
        read_at: datetime,
    ) -> OrderHistoryPage:
        """Return one fixed-membership page, including terminal reservations."""

        self._validate_request(
            account_id=account_id,
            user_id=user_id,
            order_id=None,
            limit=limit,
            cursor=cursor,
            read_at=read_at,
        )
        with transaction.atomic(using=self._using):
            self._lock_owner(account_id=account_id, user_id=user_id)
            state = _cursor_state(
                cursor=cursor,
                kind="orders",
                user_id=user_id,
                account_id=account_id,
                order_id=None,
                read_at=read_at,
            )
            queryset = (
                SimulatedOrderReservationModel._base_manager.using(self._using)
                .select_for_update()
                .filter(
                    account_id=account_id,
                    owner_user_id=user_id,
                    created_at__lte=state.membership_cutoff,
                )
                .order_by("pk")
            )
            if state.last_pk is not None:
                queryset = queryset.filter(pk__gt=state.last_pk)
            rows = list(queryset[: limit + 1])
            has_more = len(rows) > limit
            visible_rows = rows[:limit]
            orders = tuple(self._decode_order(row, user_id=user_id) for row in visible_rows)
            next_cursor = (
                _encode_cursor(
                    kind="orders",
                    user_id=user_id,
                    account_id=account_id,
                    order_id=None,
                    last_pk=visible_rows[-1].pk,
                    membership_cutoff=state.membership_cutoff,
                )
                if has_more and visible_rows
                else None
            )
            return OrderHistoryPage(
                account_id=account_id,
                orders=orders,
                has_more=has_more,
                next_cursor=next_cursor,
                membership_cutoff=state.membership_cutoff,
                read_at=read_at,
            )

    def list_fills(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        limit: int,
        cursor: str | None,
        read_at: datetime,
    ) -> OrderFillHistoryPage:
        """Return retained receipt rows after exact Reservation/Receipt/Trade checks."""

        self._validate_request(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            limit=limit,
            cursor=cursor,
            read_at=read_at,
        )
        with transaction.atomic(using=self._using):
            self._lock_owner(account_id=account_id, user_id=user_id)
            reservation_row = (
                SimulatedOrderReservationModel._base_manager.using(self._using)
                .select_for_update()
                .filter(
                    pk=order_id,
                    account_id=account_id,
                    owner_user_id=user_id,
                )
                .first()
            )
            if reservation_row is None:
                raise SimulatedTradeAccountScopeUnavailable("订单不存在或不属于当前账户所有者")
            decoded_reservation = self._decode_reservation(reservation_row)
            state = _cursor_state(
                cursor=cursor,
                kind="fills",
                user_id=user_id,
                account_id=account_id,
                order_id=order_id,
                read_at=read_at,
            )
            queryset = (
                SimulatedOrderFillReceiptModel._base_manager.using(self._using)
                .select_related("trade")
                .select_for_update()
                .filter(
                    reservation_id=order_id,
                    created_at__lte=state.membership_cutoff,
                )
                .order_by("pk")
            )
            if state.last_pk is not None:
                queryset = queryset.filter(pk__gt=state.last_pk)
            rows = list(queryset[: limit + 1])
            has_more = len(rows) > limit
            visible_rows = rows[:limit]
            fills = tuple(
                self._decode_fill(
                    reservation_row=reservation_row,
                    reservation=decoded_reservation,
                    receipt_row=receipt_row,
                    account_id=account_id,
                    user_id=user_id,
                    read_at=read_at,
                    membership_cutoff=state.membership_cutoff,
                )
                for receipt_row in visible_rows
            )
            next_cursor = (
                _encode_cursor(
                    kind="fills",
                    user_id=user_id,
                    account_id=account_id,
                    order_id=order_id,
                    last_pk=visible_rows[-1].pk,
                    membership_cutoff=state.membership_cutoff,
                )
                if has_more and visible_rows
                else None
            )
            return OrderFillHistoryPage(
                account_id=account_id,
                order_id=order_id,
                fills=fills,
                has_more=has_more,
                next_cursor=next_cursor,
                membership_cutoff=state.membership_cutoff,
                read_at=read_at,
            )

    def _validate_request(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int | None,
        limit: int,
        cursor: str | None,
        read_at: datetime,
    ) -> None:
        """Reject malformed direct calls before opening a database transaction."""

        if (
            type(account_id) is not int
            or account_id <= 0
            or type(user_id) is not int
            or user_id <= 0
            or (order_id is not None and (type(order_id) is not int or order_id <= 0))
            or type(limit) is not int
            or not 1 <= limit <= _PAGE_LIMIT_MAX
            or (
                cursor is not None
                and (
                    type(cursor) is not str
                    or not cursor
                    or len(cursor) > _CURSOR_MAX_LENGTH
                    or any(character.isspace() for character in cursor)
                )
            )
        ):
            raise SimulatedTradeExecutionInputError("订单历史分页参数无效")
        _require_aware(read_at, "read_at")

    def _lock_owner(self, *, account_id: int, user_id: int) -> SimulatedAccountModel:
        """Lock account then actor and revalidate current owner without staff bypass."""

        account = (
            SimulatedAccountModel._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=account_id, account_type="simulated", user_id=user_id)
            .first()
        )
        if type(account) is not SimulatedAccountModel:
            raise SimulatedTradeAccountScopeUnavailable("模拟账户不存在或不属于当前用户")
        actor_query = (
            get_user_model()
            ._base_manager.using(self._using)
            .select_for_update()
            .filter(pk=user_id)
            .values("is_active")
        )
        actor_state: _ActorState | None = cast(_ActorState | None, actor_query.first())
        if (
            type(actor_state) is not dict
            or set(actor_state) != {"is_active"}
            or type(actor_state["is_active"]) is not bool
            or actor_state["is_active"] is not True
        ):
            raise SimulatedTradeAccountScopeUnavailable("当前账户用户不可用")
        if type(account.user_id) is not int or account.user_id != user_id:
            raise SimulatedTradeAccountScopeUnavailable("模拟账户所有者已变化")
        return account

    def _decode_order(
        self,
        row: SimulatedOrderReservationModel,
        *,
        user_id: int,
    ) -> OrderHistoryOrder:
        """Decode one exact reservation before making its public projection."""

        reservation = self._decode_reservation(row)
        if (
            type(row.pk) is not int
            or type(row.asset_code) is not str
            or type(row.asset_name) is not str
            or type(row.owner_user_id) is not int
            or row.owner_user_id != user_id
            or type(row.account_id) is not int
        ):
            raise _reservation_invalid()
        if reservation.identity.account_id != row.account_id:
            raise _reservation_invalid()
        try:
            return OrderHistoryOrder(
                order_id=row.pk,
                asset_code=row.asset_code,
                asset_name=row.asset_name,
                side=reservation.side,
                status=reservation.status,
                quantity=reservation.quantity,
                filled_quantity=reservation.filled_quantity,
                limit_price=reservation.limit_price,
                remaining_cash=reservation.remaining_cash,
                remaining_shares=reservation.remaining_shares,
                reserved_at=reservation.reserved_at,
            )
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise _reservation_invalid() from error

    def _decode_reservation(self, row: SimulatedOrderReservationModel) -> OrderReservation:
        """Decode the complete stored order snapshot and stabilize corruption errors."""

        if type(row) is not SimulatedOrderReservationModel:
            raise _reservation_invalid()
        try:
            reservation = decode_order_reservation(row)
            if type(reservation.status) is not OrderReservationStatus:
                raise ValueError("unknown reservation state")
            return reservation
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise _reservation_invalid() from error

    def _decode_fill(
        self,
        *,
        reservation_row: SimulatedOrderReservationModel,
        reservation: OrderReservation,
        receipt_row: SimulatedOrderFillReceiptModel,
        account_id: int,
        user_id: int,
        read_at: datetime,
        membership_cutoff: datetime,
    ) -> OrderHistoryFill:
        """Verify one persisted receipt against its exact parent and Trade row."""

        if type(receipt_row) is not SimulatedOrderFillReceiptModel:
            raise _receipt_invalid()
        try:
            created_at = _require_aware(receipt_row.created_at, "receipt.created_at")
            if created_at > membership_cutoff or created_at > read_at:
                raise ValueError("receipt was created after its membership/read cutoff")
            trade_row = receipt_row.trade
            decoded = read_order_reservation_fill_row(
                reservation_row=reservation_row,
                receipt_row=receipt_row,
                trade_row=trade_row,
            )
            event = decoded.event
            if (
                decoded.reservation_id != reservation_row.pk
                or decoded.receipt_id != receipt_row.pk
                or decoded.trade_id != receipt_row.trade_id
                or event.account_id != account_id
                or event.user_id != user_id
                or event.order_idempotency_key != reservation.identity.idempotency_key
                or event.asset_code != reservation_row.asset_code
                or event.side is not reservation.side
            ):
                raise ValueError("fill receipt locator differs from its owner-scoped parent")
            return OrderHistoryFill(
                receipt_id=decoded.receipt_id,
                trade_id=decoded.trade_id,
                order_id=decoded.reservation_id,
                fill_sequence=decoded.fill_sequence,
                asset_code=event.asset_code,
                side=event.side,
                quantity=event.quantity,
                price=event.price,
                occurred_at=event.occurred_at,
                recorded_at=created_at,
                observation_basis=event.observation_basis,
                verification_status="single_receipt_verified",
            )
        except SimulatedTradeExecutionBlocked:
            raise
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise _receipt_invalid() from error


def _encode_cursor(
    *,
    kind: str,
    user_id: int,
    account_id: int,
    order_id: int | None,
    last_pk: int,
    membership_cutoff: datetime,
) -> str:
    """Create one scoped signed cursor without exposing order business keys."""

    payload: _CursorPayload = {
        "version": _CURSOR_VERSION,
        "kind": kind,
        "user_id": user_id,
        "account_id": account_id,
        "order_id": order_id,
        "last_pk": last_pk,
        "membership_cutoff": _utc_isoformat(membership_cutoff),
    }
    token = signing.dumps(payload, salt=_CURSOR_SALT, compress=False)
    if len(token) > _CURSOR_MAX_LENGTH:
        raise SimulatedTradeExecutionBlocked(
            "订单历史续页游标无法安全编码",
            code="ORDER_HISTORY_CURSOR_INVALID",
        )
    return token


def _cursor_state(
    *,
    cursor: str | None,
    kind: str,
    user_id: int,
    account_id: int,
    order_id: int | None,
    read_at: datetime,
) -> _CursorState:
    """Decode a server-signed continuation and enforce exact page ownership."""

    if cursor is None:
        return _CursorState(last_pk=None, membership_cutoff=read_at)
    try:
        raw: object = signing.loads(cursor, salt=_CURSOR_SALT)
    except (BadSignature, SignatureExpired, TypeError, ValueError) as error:
        raise _cursor_invalid() from error
    if type(raw) is not dict or set(raw) != {
        "version",
        "kind",
        "user_id",
        "account_id",
        "order_id",
        "last_pk",
        "membership_cutoff",
    }:
        raise _cursor_invalid()
    payload = cast(_CursorPayload, raw)
    if (
        type(payload["version"]) is not int
        or payload["version"] != _CURSOR_VERSION
        or type(payload["kind"]) is not str
        or payload["kind"] != kind
        or type(payload["user_id"]) is not int
        or payload["user_id"] != user_id
        or type(payload["account_id"]) is not int
        or payload["account_id"] != account_id
        or type(payload["order_id"]) is not (int if order_id is not None else type(None))
        or payload["order_id"] != order_id
        or type(payload["last_pk"]) is not int
        or payload["last_pk"] <= 0
        or type(payload["membership_cutoff"]) is not str
    ):
        raise _cursor_invalid()
    try:
        cutoff = datetime.fromisoformat(payload["membership_cutoff"])
        _require_aware(cutoff, "membership_cutoff")
        if _utc_isoformat(cutoff) != payload["membership_cutoff"] or cutoff > read_at:
            raise ValueError("cursor cutoff is noncanonical or in the future")
    except (OverflowError, TypeError, ValueError) as error:
        raise _cursor_invalid() from error
    return _CursorState(last_pk=payload["last_pk"], membership_cutoff=cutoff)


def _require_aware(value: object, field_name: str) -> datetime:
    """Require a timezone-aware datetime without accepting datetime subclasses."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedTradeExecutionInputError(f"{field_name}必须是带时区时间")
    try:
        if value.utcoffset() is None:
            raise ValueError("missing UTC offset")
    except (OverflowError, ValueError) as error:
        raise SimulatedTradeExecutionInputError(f"{field_name}时区无效") from error
    return value


def _utc_isoformat(value: datetime) -> str:
    """Normalize cursor timestamps to one exact UTC representation."""

    return value.astimezone(UTC).isoformat()


def _cursor_invalid() -> SimulatedTradeExecutionInputError:
    """Return the stable client error for an invalid or mismatched cursor."""

    return SimulatedTradeExecutionInputError("订单历史续页游标无效")


def _reservation_invalid() -> SimulatedTradeExecutionBlocked:
    """Return the stable block for an unreadable retained reservation."""

    return SimulatedTradeExecutionBlocked(
        "订单封存数据无法精确核对",
        code="ORDER_HISTORY_RESERVATION_INVALID",
    )


def _receipt_invalid() -> SimulatedTradeExecutionBlocked:
    """Return the stable block for an unreadable Reservation/Receipt/Trade pair."""

    return SimulatedTradeExecutionBlocked(
        "成交回执无法与原订单及交易精确核对",
        code="ORDER_HISTORY_RECEIPT_INVALID",
    )


__all__ = ("DjangoOrderHistoryRepository",)
