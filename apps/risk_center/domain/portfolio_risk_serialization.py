"""Lossless canonical JSON for newly retained portfolio-risk evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TypeAlias, cast

RiskJsonValue: TypeAlias = (
    str | int | bool | None | list["RiskJsonValue"] | dict[str, "RiskJsonValue"]
)


def canonical_portfolio_risk_json(payload: Mapping[str, object]) -> str:
    """Retain Decimal digits and original aware offsets without modifying legacy hashes."""

    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def portfolio_risk_content_hash(payload: Mapping[str, object]) -> str:
    """Hash the exact canonical portfolio-risk evidence representation."""

    return hashlib.sha256(canonical_portfolio_risk_json(payload).encode("utf-8")).hexdigest()


def _json_value(value: object) -> RiskJsonValue:
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("risk evidence cannot contain a non-finite Decimal")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("risk evidence clocks must be timezone-aware")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("risk evidence JSON keys must be strings")
        return {cast(str, key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    raise TypeError("risk evidence must be exact typed data, never floating-point financial values")
