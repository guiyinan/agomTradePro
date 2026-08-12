"""Strict canonical codec for complete R7 monitoring evidence graphs."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import NoneType, UnionType
from typing import Union, get_args, get_origin, get_type_hints
from uuid import UUID

from apps.research.application.r7_post_promotion_monitoring import (
    R7MonitoringActiveOwnerGraph,
    R7MonitoringEvaluationEvidence,
    R7PostPromotionMonitoringPolicy,
)
from apps.research.application.r7_post_promotion_monitoring_persistence import (
    r7_monitoring_evidence_hash,
)
from apps.research.domain.r7_post_promotion_monitoring import (
    R7ForecastRealizationFact,
    R7ForecastRealizationMember,
    R7ForecastRealizationOwnerRecord,
    R7PostPromotionMonitoringAssessment,
)
from apps.research.domain.r7_post_promotion_monitoring_contracts import (
    R7LifecycleStreamOwnerEvidence,
    R7MonitoringPeriodCalendar,
    R7MonitoringPeriodEntry,
)
from apps.research.infrastructure.r7_research_result_codec import (
    decode_persisted_r7_research_result,
    encode_persisted_r7_research_result,
)
from apps.research.infrastructure.r7_research_result_lifecycle_codec import (
    decode_r7_result_lifecycle_event,
    encode_r7_result_lifecycle_event,
)

_SCHEMA = "research.r7.post-promotion-monitoring-evidence.v1"
_ALLOWED_DATACLASSES = frozenset(
    {
        R7PostPromotionMonitoringPolicy,
        R7LifecycleStreamOwnerEvidence,
        R7MonitoringPeriodCalendar,
        R7MonitoringPeriodEntry,
        R7ForecastRealizationMember,
        R7ForecastRealizationOwnerRecord,
        R7PostPromotionMonitoringAssessment,
    }
)


class R7MonitoringCodecError(ValueError):
    """An R7 monitoring payload is malformed, relaxed, or non-canonical."""


def encode_r7_monitoring_evidence(
    evidence: R7MonitoringEvaluationEvidence,
) -> dict[str, object]:
    """Encode source evidence only; derived active/fact objects are never trusted."""

    try:
        copied = evidence.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R7MonitoringCodecError("R7 monitoring evidence is invalid") from error
    return {
        "schema": _SCHEMA,
        "policy": _encode_value(copied.policy, "policy"),
        "result": encode_persisted_r7_research_result(copied.active_owner_graph.result),
        "lifecycle_stream": [
            encode_r7_result_lifecycle_event(event)
            for event in copied.active_owner_graph.lifecycle_stream
        ],
        "lifecycle_owner_evidence": _encode_value(
            copied.active_owner_graph.lifecycle_owner_evidence,
            "lifecycle_owner_evidence",
        ),
        "calendar": _encode_value(copied.calendar, "calendar"),
        "period": _encode_value(copied.period, "period"),
        "realization_owner_record": _encode_value(
            copied.realization_owner_record,
            "realization_owner_record",
        ),
        "assessment": _encode_value(copied.assessment, "assessment"),
        "evidence_hash": r7_monitoring_evidence_hash(copied),
    }


def decode_r7_monitoring_evidence(payload: object) -> R7MonitoringEvaluationEvidence:
    """Strictly decode source evidence, then replay every derived Domain object."""

    envelope = _object(payload, "R7 monitoring envelope")
    _keys(
        envelope,
        {
            "schema",
            "policy",
            "result",
            "lifecycle_stream",
            "lifecycle_owner_evidence",
            "calendar",
            "period",
            "realization_owner_record",
            "assessment",
            "evidence_hash",
        },
        "R7 monitoring envelope",
    )
    if envelope["schema"] != _SCHEMA:
        raise R7MonitoringCodecError("unsupported R7 monitoring schema")
    try:
        policy = _decode_as(
            R7PostPromotionMonitoringPolicy,
            envelope["policy"],
            "policy",
        )
        result = decode_persisted_r7_research_result(envelope["result"])
        lifecycle_values = _list(envelope["lifecycle_stream"], "lifecycle_stream")
        lifecycle_stream = tuple(
            decode_r7_result_lifecycle_event(item) for item in lifecycle_values
        )
        owner_evidence = _decode_as(
            R7LifecycleStreamOwnerEvidence,
            envelope["lifecycle_owner_evidence"],
            "lifecycle_owner_evidence",
        )
        calendar = _decode_as(
            R7MonitoringPeriodCalendar,
            envelope["calendar"],
            "calendar",
        )
        period = _decode_as(
            R7MonitoringPeriodEntry,
            envelope["period"],
            "period",
        )
        realization_owner = _decode_as(
            R7ForecastRealizationOwnerRecord,
            envelope["realization_owner_record"],
            "realization_owner_record",
        )
        assessment = _decode_as(
            R7PostPromotionMonitoringAssessment,
            envelope["assessment"],
            "assessment",
        )
        if not isinstance(policy, R7PostPromotionMonitoringPolicy):
            raise TypeError("policy has the wrong type")
        if not isinstance(owner_evidence, R7LifecycleStreamOwnerEvidence):
            raise TypeError("lifecycle owner evidence has the wrong type")
        if not isinstance(calendar, R7MonitoringPeriodCalendar):
            raise TypeError("calendar has the wrong type")
        if not isinstance(period, R7MonitoringPeriodEntry):
            raise TypeError("period has the wrong type")
        if not isinstance(realization_owner, R7ForecastRealizationOwnerRecord):
            raise TypeError("realization owner record has the wrong type")
        if not isinstance(assessment, R7PostPromotionMonitoringAssessment):
            raise TypeError("assessment has the wrong type")
        graph = R7MonitoringActiveOwnerGraph(
            result=result,
            lifecycle_stream=lifecycle_stream,
            lifecycle_owner_evidence=owner_evidence,
        ).validated_copy()
        active = graph.active_result()
        calendar.require_exact_member(period)
        realization = R7ForecastRealizationFact.from_owner_record(
            period=period,
            owner_record=realization_owner,
        )
        evidence = R7MonitoringEvaluationEvidence(
            policy=policy,
            active_owner_graph=graph,
            active=active,
            calendar=calendar,
            period=period,
            realization_owner_record=realization_owner,
            realization=realization,
            assessment=assessment,
        ).validated_copy()
    except R7MonitoringCodecError:
        raise
    except Exception as error:  # noqa: BLE001 - strict codec boundary
        raise R7MonitoringCodecError("R7 monitoring payload is invalid") from error
    evidence_hash = _string(envelope["evidence_hash"], "evidence_hash")
    if evidence_hash != r7_monitoring_evidence_hash(evidence):
        raise R7MonitoringCodecError("R7 monitoring evidence hash mismatch")
    if encode_r7_monitoring_evidence(evidence) != envelope:
        raise R7MonitoringCodecError("R7 monitoring payload is non-canonical")
    return evidence


def _encode_value(value: object, path: str) -> object:
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise R7MonitoringCodecError(f"{path} datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise R7MonitoringCodecError(f"{path} Decimal must be finite")
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
    raise R7MonitoringCodecError(f"{path} contains unsupported typed evidence")


def _decode_as(annotation: object, payload: object, path: str) -> object:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        branches = get_args(annotation)
        if payload is None and NoneType in branches:
            return None
        for branch in branches:
            if branch is NoneType:
                continue
            try:
                return _decode_as(branch, payload, path)
            except R7MonitoringCodecError:
                continue
        raise R7MonitoringCodecError(f"{path} does not match its declared union")
    if origin is tuple:
        values = _list(payload, path)
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(
                _decode_as(arguments[0], item, f"{path}[{index}]")
                for index, item in enumerate(values)
            )
        if len(values) != len(arguments):
            raise R7MonitoringCodecError(f"{path} tuple length mismatch")
        return tuple(
            _decode_as(item_type, item, f"{path}[{index}]")
            for index, (item_type, item) in enumerate(zip(arguments, values, strict=True))
        )
    if annotation is datetime:
        return _datetime(payload, path)
    if annotation is Decimal:
        return _decimal(payload, path)
    if annotation is UUID:
        return _uuid(payload, path)
    if annotation is str:
        return _string(payload, path)
    if annotation is bool:
        if type(payload) is not bool:
            raise R7MonitoringCodecError(f"{path} must be boolean")
        return payload
    if annotation is int:
        if type(payload) is not int:
            raise R7MonitoringCodecError(f"{path} must be integer")
        return payload
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        try:
            return annotation(_string(payload, path))
        except ValueError as error:
            raise R7MonitoringCodecError(f"{path} has an unknown enum value") from error
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
        except (TypeError, ValueError) as error:
            raise R7MonitoringCodecError(f"{path} is invalid") from error
    raise R7MonitoringCodecError(f"{path} has an unsupported annotation")


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise R7MonitoringCodecError(f"{path} must be an object with string keys")
    return value


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise R7MonitoringCodecError(f"{path} must be a list")
    return value


def _keys(value: dict[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise R7MonitoringCodecError(f"{path} fields differ from the canonical schema")


def _string(value: object, path: str) -> str:
    if type(value) is not str:
        raise R7MonitoringCodecError(f"{path} must be a string")
    return value


def _datetime(value: object, path: str) -> datetime:
    text = _string(value, path)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R7MonitoringCodecError(f"{path} must be ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != text:
        raise R7MonitoringCodecError(f"{path} datetime is non-canonical")
    return parsed


def _decimal(value: object, path: str) -> Decimal:
    text = _string(value, path)
    try:
        parsed = Decimal(text)
    except InvalidOperation as error:
        raise R7MonitoringCodecError(f"{path} must be Decimal text") from error
    if not parsed.is_finite() or str(parsed) != text:
        raise R7MonitoringCodecError(f"{path} Decimal is non-canonical")
    return parsed


def _uuid(value: object, path: str) -> UUID:
    text = _string(value, path)
    try:
        parsed = UUID(text)
    except ValueError as error:
        raise R7MonitoringCodecError(f"{path} must be UUID text") from error
    if str(parsed) != text:
        raise R7MonitoringCodecError(f"{path} UUID is non-canonical")
    return parsed


__all__ = [
    "R7MonitoringCodecError",
    "decode_r7_monitoring_evidence",
    "encode_r7_monitoring_evidence",
]
