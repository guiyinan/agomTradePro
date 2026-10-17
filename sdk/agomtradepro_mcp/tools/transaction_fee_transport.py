"""Narrow JSON and CSV transport rules for transaction fee fields."""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any

_TRANSACTION_FEE_FIELDS: tuple[str, ...] = (
    "commission",
    "slippage",
    "stamp_duty",
    "transfer_fee",
)

_LEGACY_TRANSACTION_EXPORT_COLUMNS: tuple[str, ...] = (
    "id",
    "portfolio",
    "position",
    "action",
    "asset_code",
    "shares",
    "price",
    "notional",
    "commission",
    "traded_at",
    "notes",
)
_TRANSACTION_EXPORT_COLUMNS: tuple[str, ...] = (
    *_LEGACY_TRANSACTION_EXPORT_COLUMNS,
    "slippage",
    "stamp_duty",
    "transfer_fee",
    "commission_known",
    "slippage_known",
    "stamp_duty_known",
    "transfer_fee_known",
)


def _normalize_transaction_number(value: Any, field_name: str, *, allow_zero: bool) -> float:
    """Convert a transaction number while rejecting non-JSON numeric traps."""
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} 不能为空")
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 必须是数字")
    try:
        normalized = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{field_name} 必须是数字") from None
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} 必须是有限数字")
    if allow_zero:
        if normalized < 0:
            raise ValueError(f"{field_name} 必须大于或等于 0")
    elif normalized <= 0:
        raise ValueError(f"{field_name} 必须大于 0")
    return normalized


def _normalize_optional_transaction_fee(row: dict[str, Any], field_name: str) -> str | None:
    """Preserve a validated fee as decimal text without binary-float rounding."""
    value = row.get(field_name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 必须是数字")
    try:
        exact_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field_name} 必须是数字") from None
    if not exact_value.is_finite():
        raise ValueError(f"{field_name} 必须是有限数字")
    if exact_value < 0:
        raise ValueError(f"{field_name} 必须大于或等于 0")
    normalized = _normalize_transaction_number(value, field_name, allow_zero=True)
    if exact_value != 0 and normalized == 0:
        raise ValueError(f"{field_name} 金额超出支持范围，无法保留非零值")
    return str(exact_value)


def _build_transaction_create_payload(portfolio_id: int, row: dict[str, Any]) -> dict[str, Any]:
    """Build a create payload containing only normalized actual fee amounts."""
    payload: dict[str, Any] = {
        "portfolio": portfolio_id,
        "action": row["action"],
        "asset_code": row["asset_code"],
        "shares": row["shares"],
        "price": row["price"],
        "traded_at": row["traded_at"],
        "notes": row["notes"],
    }
    for fee_field in _TRANSACTION_FEE_FIELDS:
        if fee_field in row:
            payload[fee_field] = row[fee_field]
    return payload


def _export_transaction_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    """Hide fee placeholders unless their matching known flag is exactly true."""
    output = {column: row.get(column, "") for column in _LEGACY_TRANSACTION_EXPORT_COLUMNS}
    for fee_field in _TRANSACTION_FEE_FIELDS:
        known = row.get(f"{fee_field}_known")
        output[fee_field] = row.get(fee_field, "") if known is True else ""
        output[f"{fee_field}_known"] = known if known is True or known is False else ""
    return output
