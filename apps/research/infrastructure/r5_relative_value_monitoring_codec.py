"""Strict typed canonical JSON codec for R5 monitoring ledgers."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.research.application.r5_relative_value_monitoring_persistence import (
    R5MonitoringAssessmentRef,
    R5MonitoringAuditEntry,
)
from apps.research.domain.r5_relative_value_monitoring import (
    R5MonitoringAssessmentStatus,
    R5MonitoringBlockerCode,
    R5MonitoringMetricResult,
    R5PostPromotionMonitoringAssessment,
)
from apps.research.domain.r5_relative_value_monitoring_contracts import (
    R5MonitoringActiveLifecycle,
    R5MonitoringCalendar,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringMetric,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
    R5MonitoringPeriodEntry,
    R5MonitoringPolicy,
    R5MonitoringTarget,
    R5MonitoringThreshold,
    R5MonitoringThresholdDirection,
)
from apps.research.domain.r5_relative_value_monitoring_facts import (
    R5MonitoringPortfolioSourceProjection,
    R5PostPromotionMonitoringFact,
)
from apps.research.domain.r5_relative_value_monitoring_owners import (
    R5MonitoringOwnerRef,
    R5MonitoringOwnerRole,
)

_T = TypeVar("_T")


class R5MonitoringCodecError(ValueError):
    """Persisted R5 monitoring JSON is incomplete or noncanonical."""


_MONITORING_DATACLASS_TYPES: tuple[type[object], ...] = (
    R5MonitoringAssessmentRef,
    R5MonitoringAuditEntry,
    R5MonitoringOwnerRef,
    R5MonitoringPeriodEntry,
    R5MonitoringCalendar,
    R5MonitoringActiveLifecycle,
    R5MonitoringFixedIncomeEvidence,
    R5MonitoringTarget,
    R5MonitoringMetric,
    R5MonitoringThreshold,
    R5MonitoringPolicy,
    R5MonitoringPortfolioSourceProjection,
    R5PostPromotionMonitoringFact,
    R5MonitoringMetricResult,
    R5PostPromotionMonitoringAssessment,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _MONITORING_DATACLASS_TYPES}
_MONITORING_ENUM_TYPES: tuple[type[Enum], ...] = (
    R5MonitoringOwnerRole,
    R5MonitoringMetricKey,
    R5MonitoringMetricUnit,
    R5MonitoringThresholdDirection,
    R5MonitoringAssessmentStatus,
    R5MonitoringBlockerCode,
)
_ENUM_REGISTRY = {item.__name__: item for item in _MONITORING_ENUM_TYPES}


def encode_r5_monitoring_active_lifecycle(
    lifecycle: R5MonitoringActiveLifecycle,
) -> dict[str, object]:
    """Encode the exact active R5 lifecycle projection."""

    return _encode_envelope("research-r5-monitoring-active-lifecycle.v1", lifecycle)


def decode_r5_monitoring_active_lifecycle(payload: object) -> R5MonitoringActiveLifecycle:
    """Strictly restore and validate the exact active lifecycle."""

    return _decode_envelope(
        payload,
        schema="research-r5-monitoring-active-lifecycle.v1",
        expected_type=R5MonitoringActiveLifecycle,
    )


def encode_r5_monitoring_fixed_income(
    evidence: R5MonitoringFixedIncomeEvidence,
) -> dict[str, object]:
    """Encode the exact fixed-income result and owner-seal projection."""

    return _encode_envelope("research-r5-monitoring-fixed-income.v1", evidence)


def decode_r5_monitoring_fixed_income(
    payload: object,
) -> R5MonitoringFixedIncomeEvidence:
    """Strictly restore and validate the fixed-income projection."""

    return _decode_envelope(
        payload,
        schema="research-r5-monitoring-fixed-income.v1",
        expected_type=R5MonitoringFixedIncomeEvidence,
    )


def encode_r5_monitoring_policy(policy: R5MonitoringPolicy) -> dict[str, object]:
    """Encode one exact Research monitoring policy."""

    return _encode_envelope("research-r5-monitoring-policy-codec.v1", policy)


def decode_r5_monitoring_policy(payload: object) -> R5MonitoringPolicy:
    """Strictly restore and live-revalidate one monitoring policy."""

    policy = _decode_envelope(
        payload,
        schema="research-r5-monitoring-policy-codec.v1",
        expected_type=R5MonitoringPolicy,
    )
    try:
        validated = policy.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringCodecError("R5 monitoring policy validation failed") from error
    if validated != policy:
        raise R5MonitoringCodecError("R5 monitoring policy seal differs after validation")
    return policy


def encode_r5_monitoring_period_calendar(
    calendar: R5MonitoringCalendar,
) -> dict[str, object]:
    """Encode one canonical owner-recorded period calendar."""

    return _encode_envelope("research-r5-monitoring-period-calendar-codec.v1", calendar)


def decode_r5_monitoring_period_calendar(
    payload: object,
) -> R5MonitoringCalendar:
    """Strictly restore one canonical owner-recorded period calendar."""

    return _decode_envelope(
        payload,
        schema="research-r5-monitoring-period-calendar-codec.v1",
        expected_type=R5MonitoringCalendar,
    )


def encode_r5_monitoring_fact(
    fact: R5PostPromotionMonitoringFact,
) -> dict[str, object]:
    """Encode one exact independent Portfolio raw fact."""

    return _encode_envelope("research-r5-monitoring-fact-codec.v1", fact)


def decode_r5_monitoring_fact(payload: object) -> R5PostPromotionMonitoringFact:
    """Strictly restore one exact independent Portfolio raw fact."""

    return _decode_envelope(
        payload,
        schema="research-r5-monitoring-fact-codec.v1",
        expected_type=R5PostPromotionMonitoringFact,
    )


def encode_r5_monitoring_assessment(
    assessment: R5PostPromotionMonitoringAssessment,
) -> dict[str, object]:
    """Encode one locally recomputed, research-only assessment."""

    return _encode_envelope("research-r5-monitoring-assessment-codec.v1", assessment)


def decode_r5_monitoring_assessment(payload: object) -> R5PostPromotionMonitoringAssessment:
    """Strictly restore one locally recomputed assessment."""

    return _decode_envelope(
        payload,
        schema="research-r5-monitoring-assessment-codec.v1",
        expected_type=R5PostPromotionMonitoringAssessment,
    )


def encode_r5_monitoring_audit_entry(
    entry: R5MonitoringAuditEntry,
) -> dict[str, object]:
    """Encode one immutable internal-audit snapshot entry."""

    return _encode_envelope("research-r5-monitoring-audit-entry-codec.v1", entry)


def decode_r5_monitoring_audit_entry(payload: object) -> R5MonitoringAuditEntry:
    """Strictly restore one immutable internal-audit snapshot entry."""

    return _decode_envelope(
        payload,
        schema="research-r5-monitoring-audit-entry-codec.v1",
        expected_type=R5MonitoringAuditEntry,
    )


def _encode_envelope(schema: str, value: object) -> dict[str, object]:
    return {"schema": schema, "value": _encode_value(value)}


def _decode_envelope(
    payload: object,
    *,
    schema: str,
    expected_type: type[_T],
) -> _T:
    envelope = _strict_object(payload, {"schema", "value"}, "codec envelope")
    if envelope["schema"] != schema:
        raise R5MonitoringCodecError("R5 monitoring codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except R5MonitoringCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R5MonitoringCodecError("R5 monitoring typed restore failed") from error
    if type(decoded) is not expected_type:
        raise R5MonitoringCodecError("R5 monitoring codec restored the wrong type")
    restored = decoded
    if _encode_envelope(schema, restored) != envelope:
        raise R5MonitoringCodecError("R5 monitoring payload is not canonical")
    return restored


def _encode_value(value: object) -> object:
    if isinstance(value, Enum):
        return {"$enum": type(value).__name__, "$value": value.value}
    if isinstance(value, Decimal):
        return {"$decimal": _decimal_text(value)}
    if isinstance(value, datetime):
        return {"$datetime": _utc_text(value)}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if is_dataclass(value) and not isinstance(value, type):
        type_name = type(value).__name__
        if type_name not in _DATACLASS_REGISTRY:
            raise R5MonitoringCodecError(f"unregistered R5 monitoring type: {type_name}")
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
    raise R5MonitoringCodecError(f"unsupported R5 monitoring value: {type(value).__name__}")


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise R5MonitoringCodecError("tagged R5 monitoring value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise R5MonitoringCodecError("unknown R5 monitoring enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            result = Decimal(text)
        except ArithmeticError as error:
            raise R5MonitoringCodecError("invalid R5 monitoring Decimal") from error
        if not result.is_finite() or _decimal_text(result) != text:
            raise R5MonitoringCodecError("noncanonical R5 monitoring Decimal")
        return result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            result_datetime = datetime.fromisoformat(text)
        except ValueError as error:
            raise R5MonitoringCodecError("invalid R5 monitoring datetime") from error
        if _utc_text(result_datetime) != text:
            raise R5MonitoringCodecError("noncanonical R5 monitoring datetime")
        return result_datetime
    if keys == {"$date"}:
        text = _string(tagged["$date"], "date")
        try:
            result_date = date.fromisoformat(text)
        except ValueError as error:
            raise R5MonitoringCodecError("invalid R5 monitoring date") from error
        if result_date.isoformat() != text:
            raise R5MonitoringCodecError("noncanonical R5 monitoring date")
        return result_date
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise R5MonitoringCodecError("R5 monitoring tuple members must be a list")
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise R5MonitoringCodecError("unknown or noncanonical R5 monitoring tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise R5MonitoringCodecError("unknown R5 monitoring dataclass type")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise R5MonitoringCodecError("R5 monitoring dataclass fields must be an object")
    values = cast(dict[str, object], raw_fields)
    target_fields = fields(cast(Any, target_type))
    expected_names = {item.name for item in target_fields}
    if set(values) != expected_names:
        raise R5MonitoringCodecError("R5 monitoring dataclass fields are missing or extra")
    decoded = {name: _decode_value(values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    for field_name, field_value in decoded.items():
        if not _matches_type(field_value, hints[field_name]):
            raise R5MonitoringCodecError(f"R5 monitoring field type mismatch: {field_name}")
    constructor_values = {item.name: decoded[item.name] for item in target_fields if item.init}
    try:
        constructor = cast(Any, target_type)
        restored = constructor(**constructor_values)
    except (AttributeError, TypeError, ValueError) as error:
        raise R5MonitoringCodecError("R5 monitoring dataclass validation failed") from error
    if any(
        getattr(restored, item.name) != decoded[item.name]
        for item in target_fields
        if not item.init
    ):
        raise R5MonitoringCodecError("R5 monitoring computed seal validation failed")
    return restored


def _matches_type(value: object, expected: object) -> bool:
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin in {types.UnionType, getattr(types, "UnionType", object)}:
        return any(_matches_type(value, item) for item in arguments)
    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return all(_matches_type(item, arguments[0]) for item in value)
        return len(value) == len(arguments) and all(
            _matches_type(item, item_type) for item, item_type in zip(value, arguments, strict=True)
        )
    if expected is type(None):
        return value is None
    if expected is bool:
        return type(value) is bool
    if expected is int:
        return type(value) is int
    if expected is str:
        return type(value) is str
    if expected is datetime:
        return type(value) is datetime
    if expected is date:
        return type(value) is date
    if expected is Decimal:
        return type(value) is Decimal
    return isinstance(expected, type) and isinstance(value, expected)


def _strict_object(
    value: object,
    expected_keys: set[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise R5MonitoringCodecError(f"R5 monitoring {label} must be an object")
    result = cast(dict[str, object], value)
    if set(result) != expected_keys:
        raise R5MonitoringCodecError(f"R5 monitoring {label} keys are missing or extra")
    return result


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R5MonitoringCodecError(f"R5 monitoring {label} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R5MonitoringCodecError("R5 monitoring Decimal must be finite")
    return format(value, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R5MonitoringCodecError("R5 monitoring datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


__all__ = [
    "R5MonitoringCodecError",
    "decode_r5_monitoring_active_lifecycle",
    "decode_r5_monitoring_assessment",
    "decode_r5_monitoring_audit_entry",
    "decode_r5_monitoring_fact",
    "decode_r5_monitoring_fixed_income",
    "decode_r5_monitoring_period_calendar",
    "decode_r5_monitoring_policy",
    "encode_r5_monitoring_active_lifecycle",
    "encode_r5_monitoring_assessment",
    "encode_r5_monitoring_audit_entry",
    "encode_r5_monitoring_fact",
    "encode_r5_monitoring_fixed_income",
    "encode_r5_monitoring_period_calendar",
    "encode_r5_monitoring_policy",
]
