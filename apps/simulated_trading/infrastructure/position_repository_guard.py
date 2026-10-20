"""Parent-lock, held-resource, and update-identity guards from G1."""

from decimal import Decimal
from typing import Any

from django.db import DEFAULT_DB_ALIAS

from apps.simulated_trading.infrastructure.models import (
    PositionModel,
    SimulatedAccountModel,
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
