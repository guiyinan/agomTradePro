"""Parent-lock, held-resource, and update-identity guards from G1."""

from decimal import Decimal
from typing import Any

from django.db import DEFAULT_DB_ALIAS
from django.db.models import Q

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    _FILL_BINDING_SCHEMA,
    SimulatedTradeModel,
)
from core.exceptions import BusinessLogicError

_ORDER_RESOURCE_POSITION_FIELDS: tuple[str, ...] = (
    "asset_type",
    "quantity",
    "available_quantity",
    "available_quantity_known",
    "avg_cost",
    "total_cost",
    "cost_basis_known",
    "first_buy_date",
    "first_buy_date_known",
)

_ORDER_RESOURCE_DECIMAL_FIELDS: frozenset[str] = frozenset(
    {"quantity", "available_quantity", "avg_cost", "total_cost"}
)

_POSITION_RECORD_IDENTITY_FIELDS: frozenset[str] = frozenset(
    {"account", "account_id", "asset_code", "id", "pk"}
)

_POSITION_RECORD_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {
        "asset_name",
        "asset_type",
        "quantity",
        "available_quantity",
        "available_quantity_known",
        "avg_cost",
        "total_cost",
        "cost_basis_known",
        "current_price",
        "market_value",
        "valuation_known",
        "unrealized_pnl",
        "unrealized_pnl_pct",
        "first_buy_date",
        "first_buy_date_known",
        "last_update_date",
        "signal_id",
        "entry_reason",
        "invalidation_rule_json",
        "invalidation_description",
        "is_invalidated",
        "invalidation_reason",
        "invalidation_checked_at",
    }
)


def _position_order_resources_changed(
    model: PositionModel | None,
    incoming: dict[str, Any],
) -> bool:
    """Detect changes to quantity, sellability, cost, or settlement identity."""

    if model is None:
        return True
    for field_name in _ORDER_RESOURCE_POSITION_FIELDS:
        if field_name not in incoming:
            continue
        stored_value = getattr(model, field_name)
        incoming_value = incoming[field_name]
        if field_name in _ORDER_RESOURCE_DECIMAL_FIELDS:
            try:
                stored_decimal = Decimal(str(stored_value))
                incoming_decimal = Decimal(str(incoming_value))
            except (ArithmeticError, TypeError, ValueError):
                return True
            if not stored_decimal.is_finite() or not incoming_decimal.is_finite():
                return True
            if stored_decimal != incoming_decimal:
                return True
        elif stored_value != incoming_value:
            return True
    return False


def _lock_account_for_order_guard(account_id: int) -> SimulatedAccountModel:
    """Lock the account parent before reading or changing held position resources."""

    return (
        SimulatedAccountModel._default_manager.using(DEFAULT_DB_ALIAS)
        .select_for_update()
        .get(pk=account_id)
    )


def require_no_retained_v4_fill_history(
    *,
    account_id: int,
    asset_code: str,
    using: str,
) -> None:
    """Reject unledgered resource calibration after retained fill evidence.

    The caller must already hold the simulated Account parent lock. Lock related
    reservation rows, then Receipt rows, then scoped Trade markers before the
    caller acquires a Position row. Reservation counters and completed status
    independently retain fill history even if both child markers are absent.
    Receipt membership is checked from both foreign-key sides so a moved or
    corrupt Receipt cannot disappear merely because one locator was rewritten.
    """

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(asset_code) is not str
        or not asset_code
        or type(using) is not str
        or not using
    ):
        raise SimulatedTradeExecutionBlocked(
            "持仓成交历史范围无效",
            code="POSITION_FILL_HISTORY_SCOPE_INVALID",
        )

    reservation_history = tuple(
        SimulatedOrderReservationModel._base_manager.using(using)
        .select_for_update(of=("self",))
        .filter(
            account_id=account_id,
            asset_code=asset_code,
        )
        .filter(
            Q(fill_receipts__isnull=False)
            | Q(filled_quantity__gt=0)
            | Q(cash_consumed__gt=0)
            | Q(shares_consumed__gt=0)
            | Q(status=SimulatedOrderReservationModel.STATUS_COMPLETED)
        )
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    receipts = tuple(
        SimulatedOrderFillReceiptModel._base_manager.using(using)
        .select_for_update(of=("self",))
        .filter(
            Q(reservation__account_id=account_id, reservation__asset_code=asset_code)
            | Q(trade__account_id=account_id, trade__asset_code=asset_code)
        )
        .order_by("pk")
        .only("pk")
    )
    trade_markers = tuple(
        SimulatedTradeModel._base_manager.using(using)
        .select_for_update()
        .filter(account_id=account_id, asset_code=asset_code)
        .filter(
            Q(settlement_plan_binding_version=4)
            | Q(settlement_plan_binding_payload__schema=_FILL_BINDING_SCHEMA)
        )
        .order_by("pk")
        .only("pk")
    )
    if reservation_history or receipts or trade_markers:
        raise SimulatedTradeExecutionBlocked(
            "持仓资源已有保留的成交历史，不能无成交记录校准或删除",
            code="ORDER_FILL_HISTORY_RETAINED",
        )


def _validated_buy_trade_payload(
    *,
    account_id: int,
    asset_code: str,
    trade_payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate legacy BUY scope and normalize its supported account form."""

    error = BusinessLogicError("持仓与成交身份不一致", code="POSITION_TRADE_SCOPE_MISMATCH")
    if (
        type(account_id) is not int
        or account_id <= 0
        or type(asset_code) is not str
        or not asset_code
        or type(trade_payload) is not dict
        or any(type(key) is not str for key in trade_payload)
    ):
        raise error
    if type(trade_payload.get("asset_code")) is not str:
        raise error
    if trade_payload["asset_code"] != asset_code:
        raise error

    has_account_id = "account_id" in trade_payload
    has_account = "account" in trade_payload
    if has_account_id == has_account:
        raise error
    if has_account_id:
        payload_account_id = trade_payload["account_id"]
    else:
        account = trade_payload["account"]
        if type(account) is not SimulatedAccountModel:
            raise error
        payload_account_id = account.pk
    if type(payload_account_id) is not int or payload_account_id != account_id:
        raise error

    normalized_payload = dict(trade_payload)
    normalized_payload.pop("account", None)
    normalized_payload["account_id"] = account_id
    return normalized_payload


def _validate_position_record_defaults(defaults: dict[str, Any]) -> None:
    """Reject identity rewrites and fields outside the repository's update contract."""

    if type(defaults) is not dict:
        raise BusinessLogicError("持仓写入字段无效", code="POSITION_WRITE_FIELDS_INVALID")
    field_names = set(defaults)
    if any(type(field_name) is not str for field_name in field_names):
        raise BusinessLogicError("持仓写入字段无效", code="POSITION_WRITE_FIELDS_INVALID")
    if field_names & _POSITION_RECORD_IDENTITY_FIELDS:
        raise BusinessLogicError("持仓身份不可通过默认字段改写", code="POSITION_IDENTITY_IMMUTABLE")
    if not field_names <= _POSITION_RECORD_DEFAULT_FIELDS:
        raise BusinessLogicError("持仓写入字段无效", code="POSITION_WRITE_FIELDS_INVALID")
