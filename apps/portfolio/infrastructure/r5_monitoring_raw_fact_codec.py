"""Strict canonical JSON codec for Portfolio-owned R5 monitoring facts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.portfolio.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringMetric,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
)
from apps.portfolio.domain.r5_relative_value_monitoring_facts import (
    R5MonitoringPortfolioSourceProjection,
    R5PostPromotionMonitoringFact,
)
from apps.portfolio.domain.r5_relative_value_monitoring_owners import (
    R5MonitoringOwnerRef,
    R5MonitoringOwnerRole,
)

_T = TypeVar("_T")


class PortfolioR5MonitoringRawFactCodecError(ValueError):
    """A stored Portfolio raw-fact payload is incomplete or noncanonical."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    R5MonitoringOwnerRef,
    R5MonitoringMetric,
    R5MonitoringPortfolioSourceProjection,
    R5PostPromotionMonitoringFact,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (
    R5MonitoringOwnerRole,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}
_SCHEMA = "portfolio-r5-monitoring-raw-fact-codec.v1"


def encode_portfolio_r5_monitoring_raw_fact(
    fact: R5PostPromotionMonitoringFact,
) -> dict[str, object]:
    """Encode one live-validated fact without weakening Decimal or UTC values."""

    if type(fact) is not R5PostPromotionMonitoringFact:
        raise TypeError("Portfolio R5 monitoring fact type differs")
    canonical = fact.validated_copy()
    if canonical != fact:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring fact differs after validation"
        )
    return {"schema": _SCHEMA, "value": _encode_value(canonical)}


def decode_portfolio_r5_monitoring_raw_fact(
    payload: object,
) -> R5PostPromotionMonitoringFact:
    """Strictly restore one fact and replay all owner and derived-metric seals."""

    envelope = _strict_object(payload, {"schema", "value"}, "raw-fact envelope")
    if envelope["schema"] != _SCHEMA:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring raw-fact schema differs"
        )
    try:
        decoded = _decode_value(envelope["value"])
    except PortfolioR5MonitoringRawFactCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring raw-fact restore failed"
        ) from error
    if type(decoded) is not R5PostPromotionMonitoringFact:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring raw-fact type differs"
        )
    restored = decoded.validated_copy()
    if restored != decoded or encode_portfolio_r5_monitoring_raw_fact(restored) != envelope:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring raw-fact payload is noncanonical"
        )
    return restored


def _encode_value(value: object) -> object:
    if isinstance(value, Enum):
        return {"$enum": type(value).__name__, "$value": value.value}
    if isinstance(value, Decimal):
        return {"$decimal": _decimal_text(value)}
    if isinstance(value, datetime):
        return {"$datetime": _utc_text(value)}
    if is_dataclass(value) and not isinstance(value, type):
        type_name = type(value).__name__
        if type_name not in _DATACLASS_REGISTRY:
            raise PortfolioR5MonitoringRawFactCodecError(
                f"unregistered Portfolio R5 monitoring type: {type_name}"
            )
        return {
            "$type": type_name,
            "$fields": {
                item.name: _encode_value(getattr(value, item.name)) for item in fields(value)
            },
        }
    if isinstance(value, tuple):
        return {"$tuple": [_encode_value(item) for item in value]}
    if value is None or type(value) in {str, int, bool}:
        return value
    raise PortfolioR5MonitoringRawFactCodecError(
        f"unsupported Portfolio R5 monitoring value: {type(value).__name__}"
    )


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise PortfolioR5MonitoringRawFactCodecError(
            "tagged Portfolio R5 monitoring value must be an object"
        )
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise PortfolioR5MonitoringRawFactCodecError("unknown Portfolio R5 monitoring enum")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            result = Decimal(text)
        except ArithmeticError as error:
            raise PortfolioR5MonitoringRawFactCodecError(
                "invalid Portfolio R5 monitoring Decimal"
            ) from error
        if not result.is_finite() or _decimal_text(result) != text:
            raise PortfolioR5MonitoringRawFactCodecError(
                "noncanonical Portfolio R5 monitoring Decimal"
            )
        return result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            result_datetime = datetime.fromisoformat(text)
        except ValueError as error:
            raise PortfolioR5MonitoringRawFactCodecError(
                "invalid Portfolio R5 monitoring datetime"
            ) from error
        if _utc_text(result_datetime) != text:
            raise PortfolioR5MonitoringRawFactCodecError(
                "noncanonical Portfolio R5 monitoring datetime"
            )
        return result_datetime
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise PortfolioR5MonitoringRawFactCodecError(
                "Portfolio R5 monitoring tuple members differ"
            )
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise PortfolioR5MonitoringRawFactCodecError("unknown Portfolio R5 monitoring JSON tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise PortfolioR5MonitoringRawFactCodecError("unknown Portfolio R5 monitoring dataclass")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring dataclass fields differ"
        )
    values = cast(dict[str, object], raw_fields)
    target_fields = fields(cast(Any, target_type))
    expected_names = {item.name for item in target_fields}
    if set(values) != expected_names:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring dataclass shape differs"
        )
    decoded = {name: _decode_value(values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    if any(not _matches_type(decoded[name], hints[name]) for name in expected_names):
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring dataclass field type differs"
        )
    constructor_values = {item.name: decoded[item.name] for item in target_fields if item.init}
    try:
        constructor = cast(Any, target_type)
        restored = constructor(**constructor_values)
    except (AttributeError, TypeError, ValueError) as error:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring dataclass validation failed"
        ) from error
    if any(
        getattr(restored, item.name) != decoded[item.name]
        for item in target_fields
        if not item.init
    ):
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring computed seal differs"
        )
    return restored


def _matches_type(value: object, expected: object) -> bool:
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin is tuple:
        if type(value) is not tuple:
            return False
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return all(_matches_type(item, arguments[0]) for item in value)
        return len(value) == len(arguments) and all(
            _matches_type(item, expected_item)
            for item, expected_item in zip(value, arguments, strict=True)
        )
    if origin is not None:
        return isinstance(value, origin)
    return type(value) is expected


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioR5MonitoringRawFactCodecError(
            "Portfolio R5 monitoring datetime must be timezone-aware"
        )
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise PortfolioR5MonitoringRawFactCodecError(
            f"Portfolio R5 monitoring {label} must be a string"
        )
    return value


def _strict_object(
    payload: object,
    expected_keys: set[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise PortfolioR5MonitoringRawFactCodecError(
            f"Portfolio R5 monitoring {label} must be an object"
        )
    value = cast(dict[str, object], payload)
    if set(value) != expected_keys:
        raise PortfolioR5MonitoringRawFactCodecError(
            f"Portfolio R5 monitoring {label} shape differs"
        )
    return value


__all__ = [
    "PortfolioR5MonitoringRawFactCodecError",
    "decode_portfolio_r5_monitoring_raw_fact",
    "encode_portfolio_r5_monitoring_raw_fact",
]
