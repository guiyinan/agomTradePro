"""Strict typed canonical JSON codec for Research R1 promotion ledgers."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.research.application.r1_forecast_promotion import (
    ExactR1LifecycleAuthorizationEvidence,
    R1ForecastPromotionDecisionBundle,
    R1PromotionDecisionReceipt,
    R1PromotionLifecycleEventBundle,
    R1PromotionVersionRef,
)
from apps.research.domain.r1_forecast_promotion import (
    R1ForecastPromotionDecision,
    R1ForecastPromotionPolicy,
    R1ForecastTrialPromotionSeal,
    R1PromotionDecisionIdentity,
    R1PromotionDecisionOutcome,
    R1PromotionForecastIdentity,
    R1PromotionGateCode,
    R1PromotionInvalidationEvidence,
    R1PromotionLifecycleAuthorization,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleEventType,
    R1PromotionMetricEvidence,
    R1PromotionPolicyGateOutcome,
    R1PromotionPolicyStatus,
    R1PromotionScope,
    R1PromotionTrialState,
)

_T = TypeVar("_T")


class R1PromotionCodecError(ValueError):
    """Raised when persisted JSON is incomplete, noncanonical or substituted."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    R1PromotionVersionRef,
    R1PromotionScope,
    R1ForecastPromotionPolicy,
    R1PromotionForecastIdentity,
    R1PromotionMetricEvidence,
    R1PromotionInvalidationEvidence,
    R1ForecastTrialPromotionSeal,
    R1PromotionPolicyGateOutcome,
    R1ForecastPromotionDecision,
    R1PromotionDecisionReceipt,
    R1ForecastPromotionDecisionBundle,
    R1PromotionDecisionIdentity,
    R1PromotionLifecycleAuthorization,
    ExactR1LifecycleAuthorizationEvidence,
    R1PromotionLifecycleEvent,
    R1PromotionLifecycleEventBundle,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (
    R1PromotionPolicyStatus,
    R1PromotionTrialState,
    R1PromotionDecisionOutcome,
    R1PromotionGateCode,
    R1PromotionLifecycleEventType,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}


def encode_r1_promotion_policy(policy: R1ForecastPromotionPolicy) -> dict[str, object]:
    """Encode one exact policy into canonical tagged JSON."""

    return _encode_envelope("research-r1-promotion-policy-codec.v1", policy)


def decode_r1_promotion_policy(payload: object) -> R1ForecastPromotionPolicy:
    """Restore and fully validate one exact policy."""

    return _decode_envelope(
        payload,
        schema="research-r1-promotion-policy-codec.v1",
        expected_type=R1ForecastPromotionPolicy,
    )


def encode_r1_promotion_decision_bundle(
    bundle: R1ForecastPromotionDecisionBundle,
) -> dict[str, object]:
    """Encode an atomic decision/owner-receipt bundle."""

    return _encode_envelope("research-r1-promotion-decision-bundle-codec.v1", bundle)


def decode_r1_promotion_decision_bundle(
    payload: object,
) -> R1ForecastPromotionDecisionBundle:
    """Restore a fully typed decision/owner-receipt bundle."""

    return _decode_envelope(
        payload,
        schema="research-r1-promotion-decision-bundle-codec.v1",
        expected_type=R1ForecastPromotionDecisionBundle,
    )


def encode_r1_lifecycle_authorization_evidence(
    evidence: ExactR1LifecycleAuthorizationEvidence,
) -> dict[str, object]:
    """Encode exact authorization plus stable server event clocks."""

    return _encode_envelope("research-r1-lifecycle-authorization-codec.v1", evidence)


def decode_r1_lifecycle_authorization_evidence(
    payload: object,
) -> ExactR1LifecycleAuthorizationEvidence:
    """Restore exact authorization and stable server event clocks."""

    return _decode_envelope(
        payload,
        schema="research-r1-lifecycle-authorization-codec.v1",
        expected_type=ExactR1LifecycleAuthorizationEvidence,
    )


def encode_r1_lifecycle_event_bundle(
    bundle: R1PromotionLifecycleEventBundle,
) -> dict[str, object]:
    """Encode an exact lifecycle event/receipt bundle."""

    return _encode_envelope("research-r1-lifecycle-event-bundle-codec.v1", bundle)


def decode_r1_lifecycle_event_bundle(payload: object) -> R1PromotionLifecycleEventBundle:
    """Restore an exact lifecycle event/receipt bundle."""

    return _decode_envelope(
        payload,
        schema="research-r1-lifecycle-event-bundle-codec.v1",
        expected_type=R1PromotionLifecycleEventBundle,
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
        raise R1PromotionCodecError("R1 promotion codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except R1PromotionCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise R1PromotionCodecError("R1 promotion typed restore failed") from error
    if type(decoded) is not expected_type:
        raise R1PromotionCodecError("R1 promotion codec restored the wrong type")
    restored = decoded
    if _encode_envelope(schema, restored) != envelope:
        raise R1PromotionCodecError("R1 promotion payload is not canonical")
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
            raise R1PromotionCodecError(f"unregistered R1 promotion type: {type_name}")
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
    raise R1PromotionCodecError(f"unsupported R1 promotion value: {type(value).__name__}")


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise R1PromotionCodecError("tagged R1 promotion value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise R1PromotionCodecError("unknown R1 promotion enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            decimal_result = Decimal(text)
        except ArithmeticError as error:
            raise R1PromotionCodecError("invalid R1 promotion Decimal") from error
        if _decimal_text(decimal_result) != text:
            raise R1PromotionCodecError("noncanonical R1 promotion Decimal")
        return decimal_result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            datetime_result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise R1PromotionCodecError("invalid R1 promotion datetime") from error
        if _utc_text(datetime_result) != text:
            raise R1PromotionCodecError("noncanonical R1 promotion datetime")
        return datetime_result
    if keys == {"$date"}:
        text = _string(tagged["$date"], "date")
        try:
            date_result = date.fromisoformat(text)
        except ValueError as error:
            raise R1PromotionCodecError("invalid R1 promotion date") from error
        if date_result.isoformat() != text:
            raise R1PromotionCodecError("noncanonical R1 promotion date")
        return date_result
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise R1PromotionCodecError("R1 promotion tuple members must be a list")
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise R1PromotionCodecError("unknown or noncanonical R1 promotion tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise R1PromotionCodecError("unknown R1 promotion dataclass type")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise R1PromotionCodecError("R1 promotion dataclass fields must be an object")
    field_values = cast(dict[str, object], raw_fields)
    expected_names = {item.name for item in fields(cast(Any, target_type))}
    if set(field_values) != expected_names:
        raise R1PromotionCodecError("R1 promotion dataclass fields are missing or extra")
    decoded_fields = {name: _decode_value(field_values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    for field_name, field_value in decoded_fields.items():
        if not _matches_type(field_value, hints[field_name]):
            raise R1PromotionCodecError(f"R1 promotion field type mismatch: {field_name}")
    try:
        dynamic_constructor = cast(Any, target_type)
        return dynamic_constructor(**decoded_fields)
    except (TypeError, ValueError) as error:
        raise R1PromotionCodecError("R1 promotion dataclass validation failed") from error


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
    payload: object,
    expected_keys: set[str],
    field_name: str,
) -> dict[str, object]:
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise R1PromotionCodecError(f"{field_name} must be an object")
    result = cast(dict[str, object], payload)
    if set(result) != expected_keys:
        raise R1PromotionCodecError(f"{field_name} keys are missing or extra")
    return result


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise R1PromotionCodecError(f"{field_name} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R1PromotionCodecError("R1 promotion Decimal must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R1PromotionCodecError("R1 promotion datetime must be aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "R1PromotionCodecError",
    "decode_r1_lifecycle_authorization_evidence",
    "decode_r1_lifecycle_event_bundle",
    "decode_r1_promotion_decision_bundle",
    "decode_r1_promotion_policy",
    "encode_r1_lifecycle_authorization_evidence",
    "encode_r1_lifecycle_event_bundle",
    "encode_r1_promotion_decision_bundle",
    "encode_r1_promotion_policy",
]
