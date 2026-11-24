"""Read broker trade receipts and validate their original source clocks and economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.broker_execution.application.use_case_errors import BrokerExecutionConflictError

_TRADE_EVENTS = frozenset({"QMT_TRADE", "FAKE_TRADE"})


def _receipt_time(raw: object) -> datetime:
    try:
        instant = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as error:
        raise BrokerExecutionConflictError("Invalid broker report timestamp") from error
    if instant.utcoffset() is None:
        raise BrokerExecutionConflictError("Broker report timestamp requires a timezone")
    return instant.astimezone(UTC)


def _receipt_clock(
    payload: dict[str, Any], occurred_at: datetime, received_at: datetime
) -> tuple[str, str | None]:
    source = payload.get("broker_source_at")
    clock = payload.get("clock_source", "unknown")
    if clock not in ("broker", "agent_observed", "unknown") or occurred_at > received_at:
        raise BrokerExecutionConflictError("Invalid broker report clock or future observation")
    if clock == "broker":
        if _receipt_time(source) != occurred_at:
            raise BrokerExecutionConflictError("Broker source time differs from occurrence")
        return "broker", occurred_at.isoformat()
    if source is not None:
        raise BrokerExecutionConflictError("Unverified broker source time")
    return str(clock), None


def _trade_decimal(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw))
    except InvalidOperation as error:
        raise BrokerExecutionConflictError("Invalid broker trade economics") from error
    if not value.is_finite() or value <= 0:
        raise BrokerExecutionConflictError("Broker fill quantity and price must be positive")
    return value


@dataclass(frozen=True)
class _TradeReceipt:
    account_ref: str | None
    trade_id: str
    quantity: Decimal
    price: Decimal
    occurred_at: datetime
    payload: dict[str, Any]


def _read_trade_receipt(
    fill: object,
    event_type: str,
    occurred_at: datetime,
    received_at: datetime,
    event_payload: dict[str, Any],
) -> _TradeReceipt | None:
    if event_type not in _TRADE_EVENTS:
        if fill is not None and event_type != "UNKNOWN":
            raise BrokerExecutionConflictError("Broker fill requires a trade event")
        return None
    if not isinstance(fill, dict) or not fill.get("broker_trade_id"):
        raise BrokerExecutionConflictError("Broker trade report lacks a trade identity")
    timestamp = _receipt_time(fill.get("occurred_at") or occurred_at)
    payload = dict(fill.get("payload") or {})
    clock_payload = (
        payload if "clock_source" in payload or "broker_source_at" in payload else event_payload
    )
    clock, source = _receipt_clock(clock_payload, timestamp, received_at)
    if (clock, source) != (event_payload["clock_source"], event_payload["broker_source_at"]):
        raise BrokerExecutionConflictError("Fill and event source clocks disagree")
    return _TradeReceipt(
        account_ref=str(fill["broker_account_ref"]) if fill.get("broker_account_ref") else None,
        trade_id=str(fill["broker_trade_id"]),
        quantity=_trade_decimal(fill.get("quantity")),
        price=_trade_decimal(fill.get("price")),
        occurred_at=timestamp,
        payload=payload | {"clock_source": clock, "broker_source_at": source},
    )
