"""Strict canonical typed codec for complete persisted R7 research packets."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import NoneType, UnionType
from typing import Union, get_args, get_origin, get_type_hints
from uuid import UUID

from apps.research.domain.r7_research_result_persistence import (
    PersistedR7ResearchResult,
    R7ForecastObservationReference,
    R7ResearchEvidenceGraph,
    R7ResearchInputReceipt,
)
from apps.research.domain.scenario_probability_contracts import (
    CalibrationBinResult,
    CalibrationBlocker,
    ForecastLedgerOutcomeObservation,
    MulticlassCalibrationMetrics,
    ProbabilitySourceCalibrationReport,
    RevisionCalibrationMetrics,
    ScenarioCalibrationReport,
    ScenarioInvalidationEvidence,
)
from apps.research.domain.scenario_research_evidence import (
    ConditionalProbabilityEvidence,
    HistoricalAnalogyAssessment,
    HistoricalAnalogyCandidateEvidence,
    HistoricalAnalogyStudyEvidence,
    MultiPeriodShockEvidence,
    PointInTimeFeatureValue,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
    ResearchEvidenceBlocker,
    ScenarioPathAssessment,
    ScenarioPathStudyEvidence,
    TransitionProbabilityEvidence,
)
from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

_SCHEMA = "research.r7.persisted-research-result.v1"
_ALLOWED_DATACLASSES = frozenset(
    {
        PersistedR7ResearchResult,
        R7ForecastObservationReference,
        R7ResearchEvidenceGraph,
        R7ResearchInputReceipt,
        CalibrationBinResult,
        CalibrationBlocker,
        ForecastLedgerOutcomeObservation,
        MulticlassCalibrationMetrics,
        ProbabilitySourceCalibrationReport,
        RevisionCalibrationMetrics,
        ScenarioCalibrationReport,
        ScenarioInvalidationEvidence,
        ConditionalProbabilityEvidence,
        HistoricalAnalogyAssessment,
        HistoricalAnalogyCandidateEvidence,
        HistoricalAnalogyStudyEvidence,
        MultiPeriodShockEvidence,
        PointInTimeFeatureValue,
        PointInTimeManifestFeature,
        PointInTimeManifestReference,
        ResearchEvidenceBlocker,
        ScenarioPathAssessment,
        ScenarioPathStudyEvidence,
        TransitionProbabilityEvidence,
        ScenarioForecastBinding,
    }
)


class R7ResearchResultCodecError(ValueError):
    """Canonical R7 result payload is malformed or non-canonical."""


def encode_persisted_r7_research_result(
    record: PersistedR7ResearchResult,
) -> dict[str, object]:
    """Encode the complete typed evidence graph and result packet."""

    return {
        "schema": _SCHEMA,
        "body": _encode_value(record, "result"),
    }


def decode_persisted_r7_research_result(payload: object) -> PersistedR7ResearchResult:
    """Strictly restore, revalidate, and byte-canonicalize one packet."""

    envelope = _object(payload, "result envelope")
    _keys(envelope, {"schema", "body"}, "result envelope")
    if envelope["schema"] != _SCHEMA:
        raise R7ResearchResultCodecError("unsupported R7 research result schema")
    try:
        decoded = _decode_as(
            PersistedR7ResearchResult,
            envelope["body"],
            "result body",
        )
    except R7ResearchResultCodecError:
        raise
    except (TypeError, ValueError) as exc:
        raise R7ResearchResultCodecError(str(exc)) from exc
    if not isinstance(decoded, PersistedR7ResearchResult):
        raise R7ResearchResultCodecError("result body has the wrong type")
    if _encode_value(decoded, "result body") != envelope["body"]:
        raise R7ResearchResultCodecError("R7 research result payload is non-canonical")
    return decoded


def _encode_value(value: object, path: str) -> object:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise R7ResearchResultCodecError(f"{path} datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, timedelta):
        microseconds = (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
        return str(microseconds)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise R7ResearchResultCodecError(f"{path} Decimal must be finite")
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, tuple):
        return [_encode_value(item, f"{path}[]") for item in value]
    value_type = type(value)
    if is_dataclass(value) and value_type in _ALLOWED_DATACLASSES:
        return {
            item.name: _encode_value(getattr(value, item.name), f"{path}.{item.name}")
            for item in fields(value)
        }
    raise R7ResearchResultCodecError(f"{path} contains unsupported typed evidence")


def _decode_as(annotation: object, payload: object, path: str) -> object:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        branches = get_args(annotation)
        if payload is None and NoneType in branches:
            return None
        errors: list[str] = []
        for branch in branches:
            if branch is NoneType:
                continue
            try:
                return _decode_as(branch, payload, path)
            except R7ResearchResultCodecError as exc:
                errors.append(str(exc))
        raise R7ResearchResultCodecError(
            f"{path} does not match its declared union: {'; '.join(errors)}"
        )
    if origin is tuple:
        values = _list(payload, path)
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(
                _decode_as(arguments[0], item, f"{path}[{index}]")
                for index, item in enumerate(values)
            )
        if len(values) != len(arguments):
            raise R7ResearchResultCodecError(f"{path} tuple length mismatch")
        return tuple(
            _decode_as(item_type, item, f"{path}[{index}]")
            for index, (item_type, item) in enumerate(zip(arguments, values, strict=True))
        )
    if annotation is NoneType or annotation is None:
        if payload is not None:
            raise R7ResearchResultCodecError(f"{path} must be null")
        return None
    if annotation is datetime:
        return _datetime(payload, path)
    if annotation is timedelta:
        return _timedelta(payload, path)
    if annotation is Decimal:
        return _decimal(payload, path)
    if annotation is UUID:
        return _uuid(payload, path)
    if annotation is str:
        return _string(payload, path)
    if annotation is bool:
        if type(payload) is not bool:
            raise R7ResearchResultCodecError(f"{path} must be boolean")
        return payload
    if annotation is int:
        if type(payload) is not int:
            raise R7ResearchResultCodecError(f"{path} must be integer")
        return payload
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        value = _string(payload, path)
        try:
            return annotation(value)
        except ValueError as exc:
            raise R7ResearchResultCodecError(f"{path} has an unknown enum value") from exc
    if isinstance(annotation, type) and annotation in _ALLOWED_DATACLASSES:
        body = _object(payload, path)
        annotations = get_type_hints(annotation)
        expected = {item.name for item in fields(annotation)}
        _keys(body, expected, path)
        field_values: dict[str, object] = {
            item.name: _decode_as(
                annotations[item.name],
                body[item.name],
                f"{path}.{item.name}",
            )
            for item in fields(annotation)
        }
        try:
            return annotation(**field_values)
        except (TypeError, ValueError) as exc:
            raise R7ResearchResultCodecError(f"{path}: {exc}") from exc
    raise R7ResearchResultCodecError(f"{path} has an unsupported annotation")


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise R7ResearchResultCodecError(f"{path} must be an object with string keys")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise R7ResearchResultCodecError(f"{path} must be a list")
    return value


def _keys(value: dict[str, object], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise R7ResearchResultCodecError(
            f"{path} keys mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _string(value: object, path: str) -> str:
    if type(value) is not str:
        raise R7ResearchResultCodecError(f"{path} must be a string")
    return value


def _datetime(value: object, path: str) -> datetime:
    text = _string(value, path)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise R7ResearchResultCodecError(f"{path} must be ISO datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise R7ResearchResultCodecError(f"{path} must be timezone-aware")
    if parsed.isoformat() != text:
        raise R7ResearchResultCodecError(f"{path} datetime is non-canonical")
    return parsed


def _timedelta(value: object, path: str) -> timedelta:
    text = _string(value, path)
    try:
        microseconds = int(text)
    except ValueError as exc:
        raise R7ResearchResultCodecError(f"{path} duration must be integer microseconds") from exc
    if str(microseconds) != text:
        raise R7ResearchResultCodecError(f"{path} duration is non-canonical")
    return timedelta(microseconds=microseconds)


def _decimal(value: object, path: str) -> Decimal:
    text = _string(value, path)
    try:
        parsed = Decimal(text)
    except InvalidOperation as exc:
        raise R7ResearchResultCodecError(f"{path} must be Decimal text") from exc
    if not parsed.is_finite() or str(parsed) != text:
        raise R7ResearchResultCodecError(f"{path} Decimal is non-canonical")
    return parsed


def _uuid(value: object, path: str) -> UUID:
    text = _string(value, path)
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise R7ResearchResultCodecError(f"{path} must be UUID text") from exc
    if str(parsed) != text:
        raise R7ResearchResultCodecError(f"{path} UUID is non-canonical")
    return parsed


__all__ = [
    "R7ResearchResultCodecError",
    "decode_persisted_r7_research_result",
    "encode_persisted_r7_research_result",
]
