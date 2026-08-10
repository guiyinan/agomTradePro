"""Strict typed canonical codec for R2 trial and monitoring ledgers."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.research.application.r2_market_structure_trial_monitoring import (
    R2ExplanatoryTrialEvaluationEvidence,
    R2MonitoringEvaluationEvidence,
)
from apps.research.domain.r2_market_structure_trial_monitoring import (
    R2AuditExplanatoryOutcome,
    R2AuditMetric,
    R2CanonicalPublicationEvidence,
    R2CyclePITEvidence,
    R2EvidenceRef,
    R2ExpectedPeriod,
    R2ExpectedSeriesPeriodEntry,
    R2ExplanatoryMetricKey,
    R2ExplanatoryTrialAssessment,
    R2HolmAdjustedPValue,
    R2MarketCycleDefinition,
    R2MarketStructureTrialPolicy,
    R2MeasureKind,
    R2MeasureSemantic,
    R2MetricRule,
    R2MonitoringAssessment,
    R2MonitoringMetricObservation,
    R2MonitoringRawFact,
    R2MonitoringStatus,
    R2MultipleTestingRule,
    R2PublicationKind,
    R2PublicationProjectionSeal,
    R2PublicationRef,
    R2SeriesPeriodSample,
    R2ThresholdDirection,
    R2TrialBlockerCode,
    R2TrialStatus,
)

_T = TypeVar("_T")


class R2TrialMonitoringCodecError(ValueError):
    """Persisted R2 evidence is incomplete, malformed, or noncanonical."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    R2EvidenceRef,
    R2PublicationRef,
    R2PublicationProjectionSeal,
    R2MeasureSemantic,
    R2ExpectedPeriod,
    R2ExpectedSeriesPeriodEntry,
    R2MarketCycleDefinition,
    R2MetricRule,
    R2MultipleTestingRule,
    R2MarketStructureTrialPolicy,
    R2CanonicalPublicationEvidence,
    R2SeriesPeriodSample,
    R2CyclePITEvidence,
    R2AuditMetric,
    R2AuditExplanatoryOutcome,
    R2HolmAdjustedPValue,
    R2ExplanatoryTrialAssessment,
    R2MonitoringMetricObservation,
    R2MonitoringRawFact,
    R2MonitoringAssessment,
    R2ExplanatoryTrialEvaluationEvidence,
    R2MonitoringEvaluationEvidence,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (
    R2ExplanatoryMetricKey,
    R2MeasureKind,
    R2MonitoringStatus,
    R2PublicationKind,
    R2ThresholdDirection,
    R2TrialBlockerCode,
    R2TrialStatus,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}


def encode_r2_trial_evidence(
    evidence: R2ExplanatoryTrialEvaluationEvidence,
) -> dict[str, object]:
    """Encode one complete, live-validated explanatory trial graph."""

    try:
        if type(evidence) is not R2ExplanatoryTrialEvaluationEvidence:
            raise TypeError("trial evidence type differs")
        validated = evidence.validated_copy()
        return _encode_envelope("research-r2-explanatory-trial-evidence.v1", validated)
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringCodecError("invalid R2 trial evidence") from error


def decode_r2_trial_evidence(payload: object) -> R2ExplanatoryTrialEvaluationEvidence:
    """Strictly restore and replay a complete explanatory trial graph."""

    result = _decode_envelope(
        payload,
        schema="research-r2-explanatory-trial-evidence.v1",
        expected_type=R2ExplanatoryTrialEvaluationEvidence,
    )
    try:
        return result.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringCodecError("R2 trial evidence replay failed") from error


def encode_r2_monitoring_evidence(
    evidence: R2MonitoringEvaluationEvidence,
) -> dict[str, object]:
    """Encode one complete, live-validated monitoring graph."""

    try:
        if type(evidence) is not R2MonitoringEvaluationEvidence:
            raise TypeError("monitoring evidence type differs")
        validated = evidence.validated_copy()
        return _encode_envelope("research-r2-monitoring-evidence.v1", validated)
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringCodecError("invalid R2 monitoring evidence") from error


def decode_r2_monitoring_evidence(payload: object) -> R2MonitoringEvaluationEvidence:
    """Strictly restore and replay a complete monitoring graph."""

    result = _decode_envelope(
        payload,
        schema="research-r2-monitoring-evidence.v1",
        expected_type=R2MonitoringEvaluationEvidence,
    )
    try:
        return result.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringCodecError("R2 monitoring evidence replay failed") from error


def encode_r2_monitoring_fact(fact: R2MonitoringRawFact) -> dict[str, object]:
    """Encode one exact owner raw fact for an assessment-scoped row."""

    return _encode_envelope("research-r2-monitoring-fact.v1", fact)


def decode_r2_monitoring_fact(payload: object) -> R2MonitoringRawFact:
    """Strictly restore one exact monitoring raw fact."""

    return _decode_envelope(
        payload,
        schema="research-r2-monitoring-fact.v1",
        expected_type=R2MonitoringRawFact,
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
        raise R2TrialMonitoringCodecError("R2 trial monitoring codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except R2TrialMonitoringCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R2TrialMonitoringCodecError("R2 typed restore failed") from error
    if type(decoded) is not expected_type:
        raise R2TrialMonitoringCodecError("R2 codec restored the wrong type")
    restored = decoded
    if _encode_envelope(schema, restored) != envelope:
        raise R2TrialMonitoringCodecError("R2 payload is not canonical")
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
            raise R2TrialMonitoringCodecError(f"unregistered R2 dataclass: {type_name}")
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
    raise R2TrialMonitoringCodecError(f"unsupported R2 value: {type(value).__name__}")


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise R2TrialMonitoringCodecError("tagged R2 value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise R2TrialMonitoringCodecError("unknown R2 enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            result = Decimal(text)
        except ArithmeticError as error:
            raise R2TrialMonitoringCodecError("invalid R2 Decimal") from error
        if not result.is_finite() or _decimal_text(result) != text:
            raise R2TrialMonitoringCodecError("noncanonical R2 Decimal")
        return result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            result_datetime = datetime.fromisoformat(text)
        except ValueError as error:
            raise R2TrialMonitoringCodecError("invalid R2 datetime") from error
        if _utc_text(result_datetime) != text:
            raise R2TrialMonitoringCodecError("noncanonical R2 datetime")
        return result_datetime
    if keys == {"$date"}:
        text = _string(tagged["$date"], "date")
        try:
            result_date = date.fromisoformat(text)
        except ValueError as error:
            raise R2TrialMonitoringCodecError("invalid R2 date") from error
        if result_date.isoformat() != text:
            raise R2TrialMonitoringCodecError("noncanonical R2 date")
        return result_date
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise R2TrialMonitoringCodecError("R2 tuple members must be a list")
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise R2TrialMonitoringCodecError("unknown or noncanonical R2 tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise R2TrialMonitoringCodecError("unknown R2 dataclass type")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise R2TrialMonitoringCodecError("R2 dataclass fields must be an object")
    values = cast(dict[str, object], raw_fields)
    target_fields = fields(cast(Any, target_type))
    expected_names = {item.name for item in target_fields}
    if set(values) != expected_names:
        raise R2TrialMonitoringCodecError("R2 dataclass fields are missing or extra")
    decoded = {name: _decode_value(values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    for field_name, field_value in decoded.items():
        if not _matches_type(field_value, hints[field_name]):
            raise R2TrialMonitoringCodecError(f"R2 field type mismatch: {field_name}")
    constructor_values = {item.name: decoded[item.name] for item in target_fields if item.init}
    try:
        constructor = cast(Any, target_type)
        restored = constructor(**constructor_values)
    except (AttributeError, TypeError, ValueError) as error:
        raise R2TrialMonitoringCodecError("R2 dataclass validation failed") from error
    if any(
        getattr(restored, item.name) != decoded[item.name]
        for item in target_fields
        if not item.init
    ):
        raise R2TrialMonitoringCodecError("R2 computed seal validation failed")
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
        raise R2TrialMonitoringCodecError(f"R2 {label} must be an object")
    result = cast(dict[str, object], value)
    if set(result) != expected_keys:
        raise R2TrialMonitoringCodecError(f"R2 {label} keys are missing or extra")
    return result


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R2TrialMonitoringCodecError(f"R2 {label} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R2TrialMonitoringCodecError("R2 Decimal must be finite")
    return format(value, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R2TrialMonitoringCodecError("R2 datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


__all__ = [
    "R2TrialMonitoringCodecError",
    "decode_r2_monitoring_evidence",
    "decode_r2_monitoring_fact",
    "decode_r2_trial_evidence",
    "encode_r2_monitoring_evidence",
    "encode_r2_monitoring_fact",
    "encode_r2_trial_evidence",
]
