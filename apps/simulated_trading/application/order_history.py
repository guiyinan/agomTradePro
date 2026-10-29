"""Owner-scoped read contracts for retained simulated orders and fill receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
    SimulatedTradeExecutionClock,
    SimulatedTradeExecutionInputError,
)
from apps.simulated_trading.domain.execution_settlement_uow import SimulatedTradeSide
from apps.simulated_trading.domain.order_reservation import OrderReservationStatus

_CURSOR_MAX_LENGTH = 4096
_PAGE_LIMIT_MAX = 100


def _require_aware(value: object, field_name: str) -> datetime:
    """Return an exact aware datetime or reject the repository boundary value."""

    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field_name} must be an aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError(f"{field_name} has no UTC offset")
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} must have a valid UTC offset") from error
    return value


def _require_decimal(value: object, field_name: str) -> Decimal:
    """Return an exact finite Decimal without converting binary floats."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    return value


@dataclass(frozen=True, slots=True)
class OrderHistoryOrder:
    """Safe business projection of one validated reservation, without its key."""

    order_id: int
    asset_code: str
    asset_name: str
    side: SimulatedTradeSide
    status: OrderReservationStatus
    quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal
    remaining_cash: Decimal
    remaining_shares: Decimal
    reserved_at: datetime

    def __post_init__(self) -> None:
        """Require the public order fields to remain exact and well-typed."""

        if type(self.order_id) is not int or self.order_id <= 0:
            raise ValueError("ORDER_HISTORY_ID_INVALID")
        for field_name, text_value, max_length in (
            ("asset_code", self.asset_code, 20),
            ("asset_name", self.asset_name, 100),
        ):
            if type(text_value) is not str or not text_value or len(text_value) > max_length:
                raise ValueError(f"ORDER_HISTORY_{field_name.upper()}_INVALID")
        if type(self.side) is not SimulatedTradeSide:
            raise ValueError("ORDER_HISTORY_SIDE_INVALID")
        if type(self.status) is not OrderReservationStatus:
            raise ValueError("ORDER_HISTORY_STATUS_INVALID")
        for field_name, value in (
            ("quantity", self.quantity),
            ("filled_quantity", self.filled_quantity),
            ("limit_price", self.limit_price),
            ("remaining_cash", self.remaining_cash),
            ("remaining_shares", self.remaining_shares),
        ):
            _require_decimal(value, field_name)
        _require_aware(self.reserved_at, "reserved_at")


@dataclass(frozen=True, slots=True)
class OrderHistoryFill:
    """One receipt whose Reservation/Receipt/Trade row binding was verified."""

    receipt_id: int
    trade_id: int
    order_id: int
    fill_sequence: int
    asset_code: str
    side: SimulatedTradeSide
    quantity: Decimal
    price: Decimal
    occurred_at: datetime
    recorded_at: datetime
    observation_basis: Literal["legacy_source_observed", "daily_interval_end"]
    verification_status: Literal["single_receipt_verified"]

    def __post_init__(self) -> None:
        """Validate receipt identity, exact financial values, and explicit clock basis."""

        for field_name, value in (
            ("receipt_id", self.receipt_id),
            ("trade_id", self.trade_id),
            ("order_id", self.order_id),
            ("fill_sequence", self.fill_sequence),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"ORDER_HISTORY_{field_name.upper()}_INVALID")
        if type(self.asset_code) is not str or not self.asset_code or len(self.asset_code) > 20:
            raise ValueError("ORDER_HISTORY_FILL_ASSET_CODE_INVALID")
        if type(self.side) is not SimulatedTradeSide:
            raise ValueError("ORDER_HISTORY_FILL_SIDE_INVALID")
        _require_decimal(self.quantity, "quantity")
        _require_decimal(self.price, "price")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if type(self.observation_basis) is not str or self.observation_basis not in (
            "legacy_source_observed",
            "daily_interval_end",
        ):
            raise ValueError("ORDER_HISTORY_FILL_OBSERVATION_BASIS_INVALID")
        if type(self.verification_status) is not str or self.verification_status != (
            "single_receipt_verified"
        ):
            raise ValueError("ORDER_HISTORY_FILL_VERIFICATION_STATUS_INVALID")


@dataclass(frozen=True, slots=True)
class OrderHistoryPage:
    """One bounded reservation page with separate member and current-read clocks."""

    account_id: int
    orders: tuple[OrderHistoryOrder, ...]
    has_more: bool
    next_cursor: str | None
    membership_cutoff: datetime
    read_at: datetime

    def __post_init__(self) -> None:
        """Validate page scope and prevent a future membership cutoff."""

        _validate_page(
            account_id=self.account_id,
            items=self.orders,
            has_more=self.has_more,
            next_cursor=self.next_cursor,
            membership_cutoff=self.membership_cutoff,
            read_at=self.read_at,
            item_type=OrderHistoryOrder,
        )


@dataclass(frozen=True, slots=True)
class OrderFillHistoryPage:
    """One bounded receipt page for an exact current-owner reservation."""

    account_id: int
    order_id: int
    fills: tuple[OrderHistoryFill, ...]
    has_more: bool
    next_cursor: str | None
    membership_cutoff: datetime
    read_at: datetime

    def __post_init__(self) -> None:
        """Validate page scope and receipt membership clocks."""

        if type(self.order_id) is not int or self.order_id <= 0:
            raise ValueError("ORDER_HISTORY_ORDER_ID_INVALID")
        _validate_page(
            account_id=self.account_id,
            items=self.fills,
            has_more=self.has_more,
            next_cursor=self.next_cursor,
            membership_cutoff=self.membership_cutoff,
            read_at=self.read_at,
            item_type=OrderHistoryFill,
        )


def _validate_page(
    *,
    account_id: int,
    items: tuple[OrderHistoryOrder, ...] | tuple[OrderHistoryFill, ...],
    has_more: bool,
    next_cursor: str | None,
    membership_cutoff: datetime,
    read_at: datetime,
    item_type: type[OrderHistoryOrder] | type[OrderHistoryFill],
) -> None:
    """Validate shared page structure without erasing its endpoint-specific type."""

    if type(account_id) is not int or account_id <= 0:
        raise ValueError("ORDER_HISTORY_ACCOUNT_ID_INVALID")
    if type(items) is not tuple or any(type(item) is not item_type for item in items):
        raise ValueError("ORDER_HISTORY_PAGE_ITEMS_INVALID")
    for item in items:
        item.__post_init__()
    if type(has_more) is not bool:
        raise ValueError("ORDER_HISTORY_PAGE_FLAG_INVALID")
    if next_cursor is not None and (
        type(next_cursor) is not str
        or not next_cursor
        or len(next_cursor) > _CURSOR_MAX_LENGTH
        or any(character.isspace() for character in next_cursor)
    ):
        raise ValueError("ORDER_HISTORY_PAGE_CURSOR_INVALID")
    if has_more != (next_cursor is not None):
        raise ValueError("ORDER_HISTORY_PAGE_CONTINUATION_INVALID")
    cutoff = _require_aware(membership_cutoff, "membership_cutoff")
    current = _require_aware(read_at, "read_at")
    if cutoff > current:
        raise ValueError("ORDER_HISTORY_MEMBERSHIP_CUTOFF_IN_FUTURE")


class OrderHistoryReader(Protocol):
    """Read current owner orders and their existing exact fill receipts."""

    def list_orders(
        self,
        *,
        account_id: int,
        user_id: int,
        limit: int,
        cursor: str | None,
        read_at: datetime,
    ) -> OrderHistoryPage:
        """Return one validated owner reservation page without writing."""

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
        """Return only existing receipts that pass the exact single-row reader."""


class ReadOrderHistoryUseCase:
    """Validate owner query bounds and execute one source-free history read."""

    def __init__(self, *, reader: OrderHistoryReader, clock: SimulatedTradeExecutionClock) -> None:
        """Inject the owner-scoped persistence reader and a server clock."""

        self._reader = reader
        self._clock = clock

    def read_orders(
        self,
        *,
        account_id: int,
        user_id: int,
        limit: int = 50,
        cursor: str | None = None,
    ) -> OrderHistoryPage:
        """Read all reservation states for the authenticated account owner."""

        _validate_query(
            account_id=account_id,
            user_id=user_id,
            order_id=None,
            limit=limit,
            cursor=cursor,
        )
        read_at = _application_read_at(self._clock)
        page = self._reader.list_orders(
            account_id=account_id,
            user_id=user_id,
            limit=limit,
            cursor=cursor,
            read_at=read_at,
        )
        if type(page) is not OrderHistoryPage:
            raise _repository_result_invalid()
        try:
            page.__post_init__()
            if page.account_id != account_id or page.read_at != read_at:
                raise ValueError("repository changed requested order scope or read clock")
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise _repository_result_invalid() from error
        return page

    def read_fills(
        self,
        *,
        account_id: int,
        user_id: int,
        order_id: int,
        limit: int = 50,
        cursor: str | None = None,
    ) -> OrderFillHistoryPage:
        """Read exact existing receipts without applying events or reading sources."""

        _validate_query(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            limit=limit,
            cursor=cursor,
        )
        read_at = _application_read_at(self._clock)
        page = self._reader.list_fills(
            account_id=account_id,
            user_id=user_id,
            order_id=order_id,
            limit=limit,
            cursor=cursor,
            read_at=read_at,
        )
        if type(page) is not OrderFillHistoryPage:
            raise _repository_result_invalid()
        try:
            page.__post_init__()
            if (
                page.account_id != account_id
                or page.order_id != order_id
                or page.read_at != read_at
            ):
                raise ValueError("repository changed requested fill scope or read clock")
        except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
            raise _repository_result_invalid() from error
        return page


def _validate_query(
    *,
    account_id: int,
    user_id: int,
    order_id: int | None,
    limit: int,
    cursor: str | None,
) -> None:
    """Reject invalid query identities before asking the reader to touch storage."""

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


def _application_read_at(clock: SimulatedTradeExecutionClock) -> datetime:
    """Read and validate one server time for this history response."""

    try:
        read_at = _require_aware(clock.now(), "read_at")
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise SimulatedTradeExecutionBlocked(
            "订单历史读取时钟不可验证",
            code="ORDER_HISTORY_READ_CLOCK_INVALID",
        ) from error
    return read_at


def _repository_result_invalid() -> SimulatedTradeExecutionBlocked:
    """Return the stable error for an invalid history repository result."""

    return SimulatedTradeExecutionBlocked(
        "订单历史读取结果与请求范围无法精确核对",
        code="ORDER_HISTORY_RESULT_INVALID",
    )


__all__ = (
    "OrderFillHistoryPage",
    "OrderHistoryFill",
    "OrderHistoryOrder",
    "OrderHistoryPage",
    "OrderHistoryReader",
    "ReadOrderHistoryUseCase",
)
