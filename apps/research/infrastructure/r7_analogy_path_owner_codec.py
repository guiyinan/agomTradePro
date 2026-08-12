"""Strict canonical payload codec for the pure R7 analogy/path owner graph."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from apps.research.domain.r7_analogy_path_owner import (
    AnalogyCandidateRawEvidence,
    AnalogyFeatureObservation,
    AnalogyFeatureRule,
    HistoricalAnalogyDefinition,
    HistoricalAnalogyRawSource,
    HistoricalAnalogyReceipt,
    PathExpectedSampleMember,
    PathObservedSampleMember,
    PathSampleResolution,
    PathShockObservation,
    PathShockRule,
    ScenarioPathDefinition,
    ScenarioPathRawSource,
    ScenarioPathReceipt,
)
from apps.research.domain.scenario_probability_contracts import ScenarioResearchScope
from apps.research.domain.scenario_research_evidence import (
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
)


class R7AnalogyPathOwnerCodecError(ValueError):
    """A persisted R7 analogy/path owner payload is malformed or noncanonical."""


_DOMAIN_TYPES = (
    AnalogyCandidateRawEvidence,
    AnalogyFeatureObservation,
    AnalogyFeatureRule,
    HistoricalAnalogyDefinition,
    HistoricalAnalogyRawSource,
    HistoricalAnalogyReceipt,
    PathExpectedSampleMember,
    PathObservedSampleMember,
    PathShockObservation,
    PathShockRule,
    PointInTimeManifestFeature,
    PointInTimeManifestReference,
    ScenarioPathDefinition,
    ScenarioPathRawSource,
    ScenarioPathReceipt,
    ScenarioResearchScope,
)
_TYPES_BY_NAME = {item.__name__: item for item in _DOMAIN_TYPES}


def encode_historical_analogy_definition(
    value: HistoricalAnalogyDefinition,
) -> dict[str, object]:
    """Encode one exact, recursively replayed analogy definition."""

    try:
        if type(value) is not HistoricalAnalogyDefinition:
            raise TypeError("analogy definition type differs")
        return _encode_root(HistoricalAnalogyDefinition.validated_copy(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerCodecError("R7 owner payload cannot be encoded") from error


def decode_historical_analogy_definition(value: object) -> HistoricalAnalogyDefinition:
    """Strictly decode one sealed analogy definition."""

    decoded = _decode_root(value)
    if type(decoded) is not HistoricalAnalogyDefinition:
        raise R7AnalogyPathOwnerCodecError("analogy definition root type differs")
    return HistoricalAnalogyDefinition.validated_copy(decoded)


def encode_historical_analogy_receipt(
    value: HistoricalAnalogyReceipt,
) -> dict[str, object]:
    """Encode one exact analogy definition/raw-source receipt graph."""

    try:
        if type(value) is not HistoricalAnalogyReceipt:
            raise TypeError("analogy receipt type differs")
        return _encode_root(HistoricalAnalogyReceipt.validated_copy(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerCodecError("R7 owner payload cannot be encoded") from error


def decode_historical_analogy_receipt(value: object) -> HistoricalAnalogyReceipt:
    """Strictly decode one analogy receipt without accepting a caller score."""

    decoded = _decode_root(value)
    if type(decoded) is not HistoricalAnalogyReceipt:
        raise R7AnalogyPathOwnerCodecError("analogy receipt root type differs")
    return HistoricalAnalogyReceipt.validated_copy(decoded)


def encode_scenario_path_definition(value: ScenarioPathDefinition) -> dict[str, object]:
    """Encode one exact path expected-membership definition."""

    try:
        if type(value) is not ScenarioPathDefinition:
            raise TypeError("path definition type differs")
        return _encode_root(ScenarioPathDefinition.validated_copy(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerCodecError("R7 owner payload cannot be encoded") from error


def decode_scenario_path_definition(value: object) -> ScenarioPathDefinition:
    """Strictly decode one path definition."""

    decoded = _decode_root(value)
    if type(decoded) is not ScenarioPathDefinition:
        raise R7AnalogyPathOwnerCodecError("path definition root type differs")
    return ScenarioPathDefinition.validated_copy(decoded)


def encode_scenario_path_receipt(value: ScenarioPathReceipt) -> dict[str, object]:
    """Encode one exact raw path receipt graph."""

    try:
        if type(value) is not ScenarioPathReceipt:
            raise TypeError("path receipt type differs")
        return _encode_root(ScenarioPathReceipt.validated_copy(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerCodecError("R7 owner payload cannot be encoded") from error


def decode_scenario_path_receipt(value: object) -> ScenarioPathReceipt:
    """Strictly decode one path receipt without accepting a caller probability."""

    decoded = _decode_root(value)
    if type(decoded) is not ScenarioPathReceipt:
        raise R7AnalogyPathOwnerCodecError("path receipt root type differs")
    return ScenarioPathReceipt.validated_copy(decoded)


def _encode_root(value: object) -> dict[str, object]:
    encoded = _encode(value)
    if type(encoded) is not dict:
        raise R7AnalogyPathOwnerCodecError("R7 owner root encoding is not an object")
    return cast(dict[str, object], encoded)


def _decode_root(value: object) -> object:
    try:
        return _decode(value)
    except (AttributeError, InvalidOperation, KeyError, TypeError, ValueError) as error:
        raise R7AnalogyPathOwnerCodecError("R7 owner payload validation failed") from error


def _encode(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is Decimal:
        return {"__decimal__": _decimal_text(value)}
    if type(value) is datetime:
        return {"__datetime__": _utc_text(value)}
    if type(value) is timedelta:
        return {"__timedelta_us__": _timedelta_microseconds(value)}
    if type(value) is UUID:
        return {"__uuid__": str(value)}
    if type(value) is PathSampleResolution:
        return {"__enum__": "PathSampleResolution", "value": value.value}
    if type(value) is tuple:
        return [_encode(item) for item in value]
    if type(value) in _DOMAIN_TYPES and is_dataclass(value):
        return {
            "__type__": type(value).__name__,
            **{item.name: _encode(getattr(value, item.name)) for item in fields(value)},
        }
    raise TypeError(f"unsupported R7 owner codec type: {type(value).__name__}")


def _decode(value: object) -> object:
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is list:
        return tuple(_decode(item) for item in cast(list[object], value))
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TypeError("R7 owner payload contains an unsupported value")
    payload = cast(dict[str, object], value)
    if "__type__" in payload:
        name = _exact_text(payload["__type__"], "R7 owner type name")
        cls = _TYPES_BY_NAME.get(name)
        if cls is None:
            raise ValueError("R7 owner payload type is not allowed")
        field_names = tuple(item.name for item in fields(cls))
        if frozenset(payload) != frozenset(("__type__", *field_names)):
            raise ValueError("R7 owner payload keys differ")
        constructor = cast(Callable[..., object], cls)
        return constructor(**{name: _decode(payload[name]) for name in field_names})
    if frozenset(payload) == {"__decimal__"}:
        text = _exact_text(payload["__decimal__"], "R7 owner Decimal")
        decimal_value = Decimal(text)
        if not decimal_value.is_finite() or _decimal_text(decimal_value) != text:
            raise ValueError("R7 owner Decimal is not canonical")
        return decimal_value
    if frozenset(payload) == {"__datetime__"}:
        return _parse_utc(payload["__datetime__"])
    if frozenset(payload) == {"__timedelta_us__"}:
        microseconds = payload["__timedelta_us__"]
        if type(microseconds) is not int:
            raise ValueError("R7 owner timedelta microseconds must be an exact integer")
        return timedelta(microseconds=microseconds)
    if frozenset(payload) == {"__uuid__"}:
        text = _exact_text(payload["__uuid__"], "R7 owner UUID")
        uuid_value = UUID(text)
        if str(uuid_value) != text:
            raise ValueError("R7 owner UUID is not canonical")
        return uuid_value
    if frozenset(payload) == {"__enum__", "value"}:
        if _exact_text(payload["__enum__"], "R7 owner enum") != "PathSampleResolution":
            raise ValueError("R7 owner enum type is not allowed")
        return PathSampleResolution(_exact_text(payload["value"], "R7 owner enum value"))
    raise ValueError("R7 owner tagged value keys differ")


def _exact_text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{label} must be an exact non-empty string")
    return value


def _decimal_text(value: Decimal) -> str:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("R7 owner Decimal must be exact and finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("R7 owner datetime must be exact and timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_utc(value: object) -> datetime:
    text = _exact_text(value, "R7 owner datetime")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("R7 owner datetime must be timezone-aware")
    canonical = parsed.astimezone(UTC)
    if text != canonical.isoformat(timespec="microseconds"):
        raise ValueError("R7 owner datetime must use canonical UTC text")
    return canonical


def _timedelta_microseconds(value: timedelta) -> int:
    if type(value) is not timedelta:
        raise ValueError("R7 owner timedelta type differs")
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


__all__ = [
    "R7AnalogyPathOwnerCodecError",
    "decode_historical_analogy_definition",
    "decode_historical_analogy_receipt",
    "decode_scenario_path_definition",
    "decode_scenario_path_receipt",
    "encode_historical_analogy_definition",
    "encode_historical_analogy_receipt",
    "encode_scenario_path_definition",
    "encode_scenario_path_receipt",
]
