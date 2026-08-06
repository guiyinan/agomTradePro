"""Strict typed canonical JSON codec for Research R4 promotion ledgers."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.portfolio.domain.macro_factor_risk import MacroRiskCandidateKind
from apps.research.application.r4_promotion_decision import (
    R4PromotionDecisionBundle,
    R4PromotionDecisionReceipt,
    R4PromotionVersionRef,
)
from apps.research.application.r4_promotion_lifecycle_evidence import (
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleEventBundle,
)
from apps.research.domain.r4_promotion_decision import (
    R4PromotionDecision,
    R4PromotionDecisionOutcome,
    R4PromotionGateCode,
    R4PromotionGateOutcome,
    R4RelativeMethodEvidence,
)
from apps.research.domain.r4_promotion_evidence import (
    R4PromotionMethodSummaryEvidence,
    R4PromotionR3AttestationEvidence,
    R4PromotionWindowEvidence,
    R4PromotionWindowMetricEvidence,
)
from apps.research.domain.r4_promotion_lifecycle import (
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleAuthorization,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleEventType,
)
from apps.research.domain.r4_promotion_record_seal import R4PromotionPortfolioRecordSeal
from apps.research.domain.r4_promotion_scope_policy import (
    R4PromotionPolicy,
    R4PromotionPolicyStatus,
    R4PromotionScope,
    R4PromotionStudyRegistration,
)
from apps.research.domain.r4_promotion_trial import (
    R4PromotionTrialSeal,
    R4PromotionTrialState,
)

_T = TypeVar("_T")


class R4PromotionCodecError(ValueError):
    """Raised when persisted R4 JSON is incomplete or noncanonical."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    R4PromotionVersionRef,
    R4PromotionScope,
    R4PromotionStudyRegistration,
    R4PromotionPolicy,
    R4PromotionR3AttestationEvidence,
    R4PromotionWindowEvidence,
    R4PromotionWindowMetricEvidence,
    R4PromotionMethodSummaryEvidence,
    R4PromotionPortfolioRecordSeal,
    R4PromotionTrialSeal,
    R4RelativeMethodEvidence,
    R4PromotionGateOutcome,
    R4PromotionDecision,
    R4PromotionDecisionReceipt,
    R4PromotionDecisionBundle,
    R4PromotionDecisionIdentity,
    R4PromotionLifecycleAuthorization,
    ExactR4LifecycleAuthorizationEvidence,
    R4PromotionLifecycleEvent,
    R4PromotionLifecycleEventBundle,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (
    MacroRiskCandidateKind,
    R4PromotionPolicyStatus,
    R4PromotionTrialState,
    R4PromotionDecisionOutcome,
    R4PromotionGateCode,
    R4PromotionLifecycleEventType,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}


def encode_r4_promotion_policy(policy: R4PromotionPolicy) -> dict[str, object]:
    """Encode one exact policy into canonical tagged JSON."""

    return _encode_envelope("research-r4-promotion-policy-codec.v1", policy)


def decode_r4_promotion_policy(payload: object) -> R4PromotionPolicy:
    """Restore and fully validate one exact policy."""

    return _decode_envelope(
        payload,
        schema="research-r4-promotion-policy-codec.v1",
        expected_type=R4PromotionPolicy,
    )


def encode_r4_promotion_decision_bundle(
    bundle: R4PromotionDecisionBundle,
) -> dict[str, object]:
    """Encode one atomic decision and Research receipt bundle."""

    return _encode_envelope("research-r4-promotion-decision-bundle-codec.v1", bundle)


def encode_r4_promotion_decision_receipt(
    receipt: R4PromotionDecisionReceipt,
) -> dict[str, object]:
    """Encode one exact server-claimed Research decision receipt."""

    return _encode_envelope("research-r4-promotion-decision-receipt-codec.v1", receipt)


def decode_r4_promotion_decision_receipt(payload: object) -> R4PromotionDecisionReceipt:
    """Restore one exact server-claimed Research decision receipt."""

    return _decode_envelope(
        payload,
        schema="research-r4-promotion-decision-receipt-codec.v1",
        expected_type=R4PromotionDecisionReceipt,
    )


def decode_r4_promotion_decision_bundle(payload: object) -> R4PromotionDecisionBundle:
    """Restore a fully typed decision and Research receipt bundle."""

    return _decode_envelope(
        payload,
        schema="research-r4-promotion-decision-bundle-codec.v1",
        expected_type=R4PromotionDecisionBundle,
    )


def encode_r4_lifecycle_authorization_evidence(
    evidence: ExactR4LifecycleAuthorizationEvidence,
) -> dict[str, object]:
    """Encode exact authorization plus stable server event clocks."""

    return _encode_envelope(
        "research-r4-lifecycle-authorization-codec.v1",
        evidence,
    )


def decode_r4_lifecycle_authorization_evidence(
    payload: object,
) -> ExactR4LifecycleAuthorizationEvidence:
    """Restore exact authorization and stable server event clocks."""

    return _decode_envelope(
        payload,
        schema="research-r4-lifecycle-authorization-codec.v1",
        expected_type=ExactR4LifecycleAuthorizationEvidence,
    )


def encode_r4_lifecycle_event_bundle(
    bundle: R4PromotionLifecycleEventBundle,
) -> dict[str, object]:
    """Encode one exact lifecycle event and receipt bundle."""

    return _encode_envelope("research-r4-lifecycle-event-bundle-codec.v1", bundle)


def decode_r4_lifecycle_event_bundle(payload: object) -> R4PromotionLifecycleEventBundle:
    """Restore one exact lifecycle event and receipt bundle."""

    return _decode_envelope(
        payload,
        schema="research-r4-lifecycle-event-bundle-codec.v1",
        expected_type=R4PromotionLifecycleEventBundle,
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
        raise R4PromotionCodecError("R4 promotion codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except R4PromotionCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise R4PromotionCodecError("R4 promotion typed restore failed") from error
    if type(decoded) is not expected_type:
        raise R4PromotionCodecError("R4 promotion codec restored the wrong type")
    restored = decoded
    if _encode_envelope(schema, restored) != envelope:
        raise R4PromotionCodecError("R4 promotion payload is not canonical")
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
            raise R4PromotionCodecError(f"unregistered R4 promotion type: {type_name}")
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
    raise R4PromotionCodecError(f"unsupported R4 promotion value: {type(value).__name__}")


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise R4PromotionCodecError("tagged R4 promotion value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise R4PromotionCodecError("unknown R4 promotion enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            decimal_result = Decimal(text)
        except ArithmeticError as error:
            raise R4PromotionCodecError("invalid R4 promotion Decimal") from error
        if _decimal_text(decimal_result) != text:
            raise R4PromotionCodecError("noncanonical R4 promotion Decimal")
        return decimal_result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            datetime_result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise R4PromotionCodecError("invalid R4 promotion datetime") from error
        if _utc_text(datetime_result) != text:
            raise R4PromotionCodecError("noncanonical R4 promotion datetime")
        return datetime_result
    if keys == {"$date"}:
        text = _string(tagged["$date"], "date")
        try:
            date_result = date.fromisoformat(text)
        except ValueError as error:
            raise R4PromotionCodecError("invalid R4 promotion date") from error
        if date_result.isoformat() != text:
            raise R4PromotionCodecError("noncanonical R4 promotion date")
        return date_result
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise R4PromotionCodecError("R4 promotion tuple members must be a list")
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise R4PromotionCodecError("unknown or noncanonical R4 promotion tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise R4PromotionCodecError("unknown R4 promotion dataclass type")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise R4PromotionCodecError("R4 promotion dataclass fields must be an object")
    field_values = cast(dict[str, object], raw_fields)
    expected_names = {item.name for item in fields(cast(Any, target_type))}
    if set(field_values) != expected_names:
        raise R4PromotionCodecError("R4 promotion dataclass fields are missing or extra")
    decoded_fields = {name: _decode_value(field_values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    for field_name, field_value in decoded_fields.items():
        if not _matches_type(field_value, hints[field_name]):
            raise R4PromotionCodecError(f"R4 promotion field type mismatch: {field_name}")
    try:
        constructor = cast(Any, target_type)
        return constructor(**decoded_fields)
    except (TypeError, ValueError) as error:
        raise R4PromotionCodecError("R4 promotion dataclass validation failed") from error


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
        raise R4PromotionCodecError(f"{field_name} must be an object")
    result = cast(dict[str, object], payload)
    if set(result) != expected_keys:
        raise R4PromotionCodecError(f"{field_name} keys are missing or extra")
    return result


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise R4PromotionCodecError(f"{field_name} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R4PromotionCodecError("R4 promotion Decimal must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R4PromotionCodecError("R4 promotion datetime must be aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "R4PromotionCodecError",
    "decode_r4_lifecycle_authorization_evidence",
    "decode_r4_lifecycle_event_bundle",
    "decode_r4_promotion_decision_bundle",
    "decode_r4_promotion_decision_receipt",
    "decode_r4_promotion_policy",
    "encode_r4_lifecycle_authorization_evidence",
    "encode_r4_lifecycle_event_bundle",
    "encode_r4_promotion_decision_bundle",
    "encode_r4_promotion_decision_receipt",
    "encode_r4_promotion_policy",
]
