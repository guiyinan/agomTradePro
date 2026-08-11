"""Strict JSON codec for Portfolio R8 monitoring calendar owner inputs."""

from __future__ import annotations

from datetime import datetime

from apps.portfolio.domain._optimization_canonical import utc_text
from apps.portfolio.domain.governed_optimization_monitoring import (
    OptimizationMonitoringPeriod,
)
from apps.portfolio.domain.r8_monitoring_calendar_registry import (
    R8MonitoringCalendarDefinition,
    R8MonitoringCalendarSourceReceipt,
)

_DEFINITION_KEYS = frozenset(
    {
        "definition_version",
        "calendar_id",
        "calendar_version",
        "periods",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)
_PERIOD_KEYS = frozenset({"period_id", "index", "start_at", "end_at"})
_SOURCE_KEYS = frozenset(
    {
        "source_owner",
        "source_receipt_id",
        "source_receipt_version",
        "definition_hash",
        "available_at",
        "valid_until",
        "evidence_ref",
        "content_hash",
    }
)


class R8MonitoringCalendarRegistryCodecError(ValueError):
    """A calendar definition/source payload has invalid shape or content."""


def _exact_dict(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise R8MonitoringCalendarRegistryCodecError(f"{label} must be an exact object")
    return value


def _keys(value: dict[str, object], expected: frozenset[str], label: str) -> None:
    if frozenset(value) != expected:
        raise R8MonitoringCalendarRegistryCodecError(f"{label} keys are invalid")


def _string(value: object, label: str) -> str:
    if type(value) is not str:
        raise R8MonitoringCalendarRegistryCodecError(f"{label} must be a string")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise R8MonitoringCalendarRegistryCodecError(f"{label} must be an exact int")
    return value


def _datetime(value: object, label: str) -> datetime:
    text = _string(value, label)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise R8MonitoringCalendarRegistryCodecError(
            f"{label} must be an ISO datetime"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or utc_text(parsed) != text:
        raise R8MonitoringCalendarRegistryCodecError(
            f"{label} must be canonical timezone-aware UTC text"
        )
    return parsed


def encode_r8_monitoring_calendar_definition(
    value: R8MonitoringCalendarDefinition,
) -> dict[str, object]:
    """Encode one recursively validated definition to canonical JSON values."""

    try:
        definition = value.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringCalendarRegistryCodecError(
            "R8 calendar definition cannot be encoded"
        ) from error
    return {
        "definition_version": definition.definition_version,
        "calendar_id": definition.calendar_id,
        "calendar_version": definition.calendar_version,
        "periods": [
            {
                "period_id": item.period_id,
                "index": item.index,
                "start_at": utc_text(item.start_at),
                "end_at": utc_text(item.end_at),
            }
            for item in definition.periods
        ],
        "available_at": utc_text(definition.available_at),
        "valid_until": utc_text(definition.valid_until),
        "evidence_ref": definition.evidence_ref,
        "content_hash": definition.content_hash,
    }


def decode_r8_monitoring_calendar_definition(
    value: object,
) -> R8MonitoringCalendarDefinition:
    """Decode only the exact complete-membership definition schema."""

    try:
        payload = _exact_dict(value, "R8 calendar definition")
        _keys(payload, _DEFINITION_KEYS, "R8 calendar definition")
        raw_periods = payload["periods"]
        if type(raw_periods) is not list or not raw_periods:
            raise R8MonitoringCalendarRegistryCodecError(
                "R8 calendar periods must be a non-empty exact list"
            )
        periods: list[OptimizationMonitoringPeriod] = []
        for raw_period in raw_periods:
            member = _exact_dict(raw_period, "R8 calendar period")
            _keys(member, _PERIOD_KEYS, "R8 calendar period")
            period = OptimizationMonitoringPeriod(
                period_id=_string(member["period_id"], "period_id"),
                index=_integer(member["index"], "period index"),
                start_at=_datetime(member["start_at"], "period start_at"),
                end_at=_datetime(member["end_at"], "period end_at"),
            )
            periods.append(period)
        definition = R8MonitoringCalendarDefinition.create(
            calendar_id=_string(payload["calendar_id"], "calendar_id"),
            calendar_version=_string(payload["calendar_version"], "calendar_version"),
            periods=tuple(periods),
            available_at=_datetime(payload["available_at"], "available_at"),
            valid_until=_datetime(payload["valid_until"], "valid_until"),
            evidence_ref=_string(payload["evidence_ref"], "evidence_ref"),
        )
        if (
            definition.definition_version
            != _string(payload["definition_version"], "definition_version")
            or definition.content_hash != _string(payload["content_hash"], "content_hash")
        ):
            raise R8MonitoringCalendarRegistryCodecError(
                "R8 calendar definition seal differs"
            )
        return definition
    except R8MonitoringCalendarRegistryCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R8MonitoringCalendarRegistryCodecError(
            "R8 calendar definition payload is invalid"
        ) from error


def encode_r8_monitoring_calendar_source_receipt(
    value: R8MonitoringCalendarSourceReceipt,
) -> dict[str, object]:
    """Encode one recursively validated Portfolio source receipt."""

    try:
        source = value.validated_copy()
    except (AttributeError, TypeError, ValueError) as error:
        raise R8MonitoringCalendarRegistryCodecError(
            "R8 calendar source receipt cannot be encoded"
        ) from error
    return {
        "source_owner": source.source_owner,
        "source_receipt_id": source.source_receipt_id,
        "source_receipt_version": source.source_receipt_version,
        "definition_hash": source.definition_hash,
        "available_at": utc_text(source.available_at),
        "valid_until": utc_text(source.valid_until),
        "evidence_ref": source.evidence_ref,
        "content_hash": source.content_hash,
    }


def decode_r8_monitoring_calendar_source_receipt(
    value: object,
) -> R8MonitoringCalendarSourceReceipt:
    """Decode only the exact Portfolio source-receipt schema."""

    try:
        payload = _exact_dict(value, "R8 calendar source receipt")
        _keys(payload, _SOURCE_KEYS, "R8 calendar source receipt")
        source = R8MonitoringCalendarSourceReceipt.create(
            source_receipt_id=_string(payload["source_receipt_id"], "source_receipt_id"),
            source_receipt_version=_string(
                payload["source_receipt_version"], "source_receipt_version"
            ),
            definition_hash=_string(payload["definition_hash"], "definition_hash"),
            available_at=_datetime(payload["available_at"], "source available_at"),
            valid_until=_datetime(payload["valid_until"], "source valid_until"),
            evidence_ref=_string(payload["evidence_ref"], "source evidence_ref"),
        )
        if (
            source.source_owner != _string(payload["source_owner"], "source_owner")
            or source.content_hash != _string(payload["content_hash"], "content_hash")
        ):
            raise R8MonitoringCalendarRegistryCodecError(
                "R8 calendar source receipt seal differs"
            )
        return source
    except R8MonitoringCalendarRegistryCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise R8MonitoringCalendarRegistryCodecError(
            "R8 calendar source receipt payload is invalid"
        ) from error


__all__ = [
    "R8MonitoringCalendarRegistryCodecError",
    "decode_r8_monitoring_calendar_definition",
    "decode_r8_monitoring_calendar_source_receipt",
    "encode_r8_monitoring_calendar_definition",
    "encode_r8_monitoring_calendar_source_receipt",
]
