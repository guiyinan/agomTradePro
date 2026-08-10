"""Strict typed JSON codec for governed optimization monitoring ledgers."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.portfolio.application.governed_optimization_monitoring_persistence import (
    GovernedOptimizationMonitoringAssessmentRef,
    GovernedOptimizationMonitoringAuditEntry,
)
from apps.portfolio.domain.governed_input_set import ExactPromotionAttestation
from apps.portfolio.domain.governed_optimization_monitoring import (
    GovernedOptimizationMonitoringAssessment,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringPolicy,
    GovernedOptimizationMonitoringTarget,
    GovernedOptimizationMonitoringThreshold,
    MonitoringAssessmentStatus,
    MonitoringBlockerCode,
    MonitoringMetricKey,
    MonitoringMetricResult,
    MonitoringMetricUnit,
    MonitoringSourceOwner,
    MonitoringThresholdDirection,
    OptimizationMonitoringMetricObservation,
    OptimizationMonitoringOwnerMetricPayload,
    OptimizationMonitoringPeriod,
    OptimizationMonitoringPeriodObservation,
    OptimizationMonitoringSourceEvidence,
    OptimizationPromotionSelector,
)

_T = TypeVar("_T")


class GovernedOptimizationMonitoringCodecError(ValueError):
    """Persisted monitoring JSON is incomplete or noncanonical."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    GovernedOptimizationMonitoringAssessmentRef,
    GovernedOptimizationMonitoringAuditEntry,
    ExactPromotionAttestation,
    OptimizationMonitoringOwnerMetricPayload,
    MonitoringMetricResult,
    OptimizationMonitoringPeriod,
    GovernedOptimizationMonitoringCalendar,
    GovernedOptimizationMonitoringThreshold,
    OptimizationPromotionSelector,
    GovernedOptimizationMonitoringTarget,
    GovernedOptimizationMonitoringPolicy,
    OptimizationMonitoringSourceEvidence,
    OptimizationMonitoringMetricObservation,
    OptimizationMonitoringPeriodObservation,
    GovernedOptimizationMonitoringAssessment,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (
    MonitoringMetricKey,
    MonitoringMetricUnit,
    MonitoringThresholdDirection,
    MonitoringSourceOwner,
    MonitoringAssessmentStatus,
    MonitoringBlockerCode,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}


def encode_monitoring_policy(
    policy: GovernedOptimizationMonitoringPolicy,
) -> dict[str, object]:
    """Encode one exact versioned monitoring policy."""

    return _encode_envelope("governed-optimization-monitoring-policy-codec.v1", policy)


def decode_monitoring_policy(payload: object) -> GovernedOptimizationMonitoringPolicy:
    """Restore and live-revalidate one monitoring policy."""

    result = _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-policy-codec.v1",
        expected_type=GovernedOptimizationMonitoringPolicy,
    )
    GovernedOptimizationMonitoringPolicy.__post_init__(result)
    return result


def encode_monitoring_calendar(
    calendar: GovernedOptimizationMonitoringCalendar,
) -> dict[str, object]:
    """Encode exact full period membership and owner clocks."""

    return _encode_envelope(
        "governed-optimization-monitoring-calendar-codec.v1",
        calendar,
    )


def decode_monitoring_calendar(payload: object) -> GovernedOptimizationMonitoringCalendar:
    """Restore exact full period membership and owner clocks."""

    return _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-calendar-codec.v1",
        expected_type=GovernedOptimizationMonitoringCalendar,
    )


def encode_monitoring_promotions(
    promotions: tuple[ExactPromotionAttestation, ...],
) -> dict[str, object]:
    """Encode the ordered exact R3/R4/R5 Promotion graph."""

    return _encode_envelope(
        "governed-optimization-monitoring-promotions-codec.v1",
        promotions,
    )


def decode_monitoring_promotions(
    payload: object,
) -> tuple[ExactPromotionAttestation, ...]:
    """Restore the ordered exact R3/R4/R5 Promotion graph."""

    restored = _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-promotions-codec.v1",
        expected_type=tuple,
    )
    if len(restored) != 3 or any(type(item) is not ExactPromotionAttestation for item in restored):
        raise GovernedOptimizationMonitoringCodecError("monitoring Promotions are incomplete")
    return cast(tuple[ExactPromotionAttestation, ...], restored)


def encode_monitoring_source_evidence(
    evidence: tuple[OptimizationMonitoringSourceEvidence, ...],
) -> dict[str, object]:
    """Encode one owner-specific ordered feedback set."""

    return _encode_envelope(
        "governed-optimization-monitoring-source-evidence-codec.v1",
        evidence,
    )


def decode_monitoring_source_evidence(
    payload: object,
) -> tuple[OptimizationMonitoringSourceEvidence, ...]:
    """Restore one owner-specific ordered feedback set."""

    restored = _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-source-evidence-codec.v1",
        expected_type=tuple,
    )
    if not restored or any(
        type(item) is not OptimizationMonitoringSourceEvidence for item in restored
    ):
        raise GovernedOptimizationMonitoringCodecError("monitoring source evidence is incomplete")
    return cast(tuple[OptimizationMonitoringSourceEvidence, ...], restored)


def encode_monitoring_observation(
    observation: OptimizationMonitoringPeriodObservation,
) -> dict[str, object]:
    """Encode one canonical typed period observation."""

    return _encode_envelope(
        "governed-optimization-monitoring-observation-codec.v1",
        observation,
    )


def decode_monitoring_observation(
    payload: object,
) -> OptimizationMonitoringPeriodObservation:
    """Restore one canonical typed period observation."""

    return _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-observation-codec.v1",
        expected_type=OptimizationMonitoringPeriodObservation,
    )


def encode_monitoring_assessment(
    assessment: GovernedOptimizationMonitoringAssessment,
) -> dict[str, object]:
    """Encode the complete locally recomputed assessment seal."""

    return _encode_envelope(
        "governed-optimization-monitoring-assessment-codec.v1",
        assessment,
    )


def decode_monitoring_assessment(
    payload: object,
) -> GovernedOptimizationMonitoringAssessment:
    """Restore the complete locally recomputed assessment seal."""

    return _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-assessment-codec.v1",
        expected_type=GovernedOptimizationMonitoringAssessment,
    )


def encode_monitoring_audit_entry(
    entry: GovernedOptimizationMonitoringAuditEntry,
) -> dict[str, object]:
    """Encode one immutable internal-audit entry."""

    return _encode_envelope(
        "governed-optimization-monitoring-audit-entry-codec.v1",
        entry,
    )


def decode_monitoring_audit_entry(
    payload: object,
) -> GovernedOptimizationMonitoringAuditEntry:
    """Restore one immutable internal-audit entry."""

    return _decode_envelope(
        payload,
        schema="governed-optimization-monitoring-audit-entry-codec.v1",
        expected_type=GovernedOptimizationMonitoringAuditEntry,
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
        raise GovernedOptimizationMonitoringCodecError("monitoring codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except GovernedOptimizationMonitoringCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringCodecError("monitoring typed restore failed") from exc
    if type(decoded) is not expected_type:
        raise GovernedOptimizationMonitoringCodecError("monitoring codec restored the wrong type")
    restored = decoded
    if _encode_envelope(schema, restored) != envelope:
        raise GovernedOptimizationMonitoringCodecError("monitoring payload is not canonical")
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
        if type(value) not in _DATACLASS_TYPES:
            raise GovernedOptimizationMonitoringCodecError(
                f"unregistered monitoring type: {type_name}"
            )
        return {
            "$type": type_name,
            "$fields": {
                item.name: _encode_value(getattr(value, item.name)) for item in fields(value)
            },
        }
    if type(value) is tuple:
        return {"$tuple": [_encode_value(item) for item in value]}
    if value is None or type(value) in {str, int, bool}:
        return value
    raise GovernedOptimizationMonitoringCodecError(
        f"unsupported monitoring value: {type(value).__name__}"
    )


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is not dict:
        raise GovernedOptimizationMonitoringCodecError("tagged monitoring value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_type = _ENUM_REGISTRY.get(_string(tagged["$enum"], "enum name"))
        if enum_type is None:
            raise GovernedOptimizationMonitoringCodecError("unknown monitoring enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise GovernedOptimizationMonitoringCodecError("invalid monitoring Decimal") from exc
        if not result.is_finite() or _decimal_text(result) != text:
            raise GovernedOptimizationMonitoringCodecError("noncanonical monitoring Decimal")
        return result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            result_datetime = datetime.fromisoformat(text)
        except ValueError as exc:
            raise GovernedOptimizationMonitoringCodecError("invalid monitoring datetime") from exc
        if _utc_text(result_datetime) != text:
            raise GovernedOptimizationMonitoringCodecError("noncanonical monitoring datetime")
        return result_datetime
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if type(members) is not list:
            raise GovernedOptimizationMonitoringCodecError(
                "monitoring tuple members must be a list"
            )
        return tuple(_decode_value(item) for item in cast(list[object], members))
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise GovernedOptimizationMonitoringCodecError("unknown or noncanonical monitoring tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    target_type = _DATACLASS_REGISTRY.get(_string(tagged["$type"], "dataclass type"))
    if target_type is None:
        raise GovernedOptimizationMonitoringCodecError("unknown monitoring dataclass type")
    raw_fields = tagged["$fields"]
    if type(raw_fields) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], raw_fields)
    ):
        raise GovernedOptimizationMonitoringCodecError(
            "monitoring dataclass fields must be an object"
        )
    values = cast(dict[str, object], raw_fields)
    target_fields = fields(cast(Any, target_type))
    expected_names = {item.name for item in target_fields}
    if set(values) != expected_names:
        raise GovernedOptimizationMonitoringCodecError(
            "monitoring dataclass fields are missing or extra"
        )
    decoded = {name: _decode_value(values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    if any(not _matches_type(decoded[name], hints[name]) for name in expected_names):
        raise GovernedOptimizationMonitoringCodecError("monitoring dataclass field type mismatch")
    try:
        constructor = cast(Any, target_type)
        restored = constructor(**decoded)
    except (AttributeError, TypeError, ValueError) as exc:
        raise GovernedOptimizationMonitoringCodecError(
            "monitoring dataclass validation failed"
        ) from exc
    return restored


def _matches_type(value: object, expected: object) -> bool:
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin is types.UnionType:
        return any(_matches_type(value, item) for item in arguments)
    if origin is tuple:
        if type(value) is not tuple:
            return False
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return all(_matches_type(item, arguments[0]) for item in value)
        return len(value) == len(arguments) and all(
            _matches_type(item, item_type) for item, item_type in zip(value, arguments, strict=True)
        )
    if expected is type(None):
        return value is None
    if expected in {bool, int, str, datetime, Decimal}:
        return type(value) is expected
    return isinstance(expected, type) and type(value) is expected


def _strict_object(
    value: object,
    expected_keys: set[str],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict or any(
        type(key) is not str for key in cast(dict[object, object], value)
    ):
        raise GovernedOptimizationMonitoringCodecError(f"monitoring {label} must be an object")
    result = cast(dict[str, object], value)
    if set(result) != expected_keys:
        raise GovernedOptimizationMonitoringCodecError(
            f"monitoring {label} keys are missing or extra"
        )
    return result


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise GovernedOptimizationMonitoringCodecError(f"monitoring {label} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise GovernedOptimizationMonitoringCodecError("monitoring Decimal must be finite")
    return format(value, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise GovernedOptimizationMonitoringCodecError("monitoring datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


__all__ = [
    "GovernedOptimizationMonitoringCodecError",
    "decode_monitoring_assessment",
    "decode_monitoring_audit_entry",
    "decode_monitoring_calendar",
    "decode_monitoring_observation",
    "decode_monitoring_policy",
    "decode_monitoring_promotions",
    "decode_monitoring_source_evidence",
    "encode_monitoring_assessment",
    "encode_monitoring_audit_entry",
    "encode_monitoring_calendar",
    "encode_monitoring_observation",
    "encode_monitoring_policy",
    "encode_monitoring_promotions",
    "encode_monitoring_source_evidence",
]
