"""Canonical, source-preserving fingerprints for broker facts and balance previews."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

BrokerTradeAction = Literal["buy", "sell"]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class BrokerFactIdentity:
    """Economic identity of one normalized broker execution."""

    broker_trade_key: str
    action: BrokerTradeAction
    asset_code: str
    shares: Decimal
    price: Decimal
    commission: Decimal | None
    stamp_duty: Decimal | None
    transfer_fee: Decimal | None
    traded_at: datetime


def _canonical_decimal(value: Decimal, *, field_name: str, positive: bool = False) -> str:
    """Validate a finite Decimal and serialize it without exponent or trailing zeroes."""

    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{field_name} must not be negative")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_instant(value: datetime) -> str:
    """Serialize an aware instant in UTC without changing its stored source value."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("traded_at must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def broker_fact_set_fingerprint(
    *,
    owner_user_id: int,
    portfolio_id: int,
    source_file_sha256: str,
    facts: tuple[BrokerFactIdentity, ...],
) -> str:
    """Hash the exact source file scope and all normalized economic fact fields."""

    if type(owner_user_id) is not int or owner_user_id <= 0:
        raise ValueError("owner_user_id must be a positive integer")
    if type(portfolio_id) is not int or portfolio_id <= 0:
        raise ValueError("portfolio_id must be a positive integer")
    if type(source_file_sha256) is not str or not _SHA256_RE.fullmatch(source_file_sha256):
        raise ValueError("source_file_sha256 must be a lowercase SHA-256 digest")

    normalized: list[dict[str, str | None]] = []
    seen_keys: set[str] = set()
    for fact in facts:
        if not isinstance(fact, BrokerFactIdentity):
            raise ValueError("facts must contain BrokerFactIdentity records")
        if type(fact.broker_trade_key) is not str or not fact.broker_trade_key:
            raise ValueError("broker_trade_key is required")
        if fact.broker_trade_key in seen_keys:
            raise ValueError("broker_trade_key values must be unique within a fact set")
        seen_keys.add(fact.broker_trade_key)
        if fact.action not in {"buy", "sell"}:
            raise ValueError("action must be buy or sell")
        if type(fact.asset_code) is not str or not fact.asset_code:
            raise ValueError("asset_code is required")

        normalized.append(
            {
                "broker_trade_key": fact.broker_trade_key,
                "action": fact.action,
                "asset_code": fact.asset_code,
                "shares": _canonical_decimal(fact.shares, field_name="shares", positive=True),
                "price": _canonical_decimal(fact.price, field_name="price", positive=True),
                "commission": (
                    _canonical_decimal(fact.commission, field_name="commission")
                    if fact.commission is not None
                    else None
                ),
                "stamp_duty": (
                    _canonical_decimal(fact.stamp_duty, field_name="stamp_duty")
                    if fact.stamp_duty is not None
                    else None
                ),
                "transfer_fee": (
                    _canonical_decimal(fact.transfer_fee, field_name="transfer_fee")
                    if fact.transfer_fee is not None
                    else None
                ),
                "traded_at": _canonical_instant(fact.traded_at),
            }
        )

    normalized.sort(key=lambda item: item["broker_trade_key"] or "")
    payload = {
        "owner_user_id": owner_user_id,
        "portfolio_id": portfolio_id,
        "source_file_sha256": source_file_sha256,
        "facts": normalized,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_float(value: float | None, *, field_name: str) -> str | None:
    """Convert a finite snapshot float to a deterministic decimal string."""

    if value is None:
        return None
    if type(value) not in {float, int} or not math.isfinite(float(value)):
        raise ValueError(f"{field_name} must be a finite number")
    decimal_value = Decimal(str(value))
    return _canonical_decimal(decimal_value, field_name=field_name)
