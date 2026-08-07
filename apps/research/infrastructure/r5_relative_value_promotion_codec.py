"""Strict typed canonical JSON codec for Research R5 promotion ledgers."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.fixed_income.domain.curve_relative_value_contracts import (
    CurveLegRole,
    CurveLegSide,
    CurveRelativeValueBlocker,
    CurveRelativeValueBlockerCode,
    CurveRelativeValueStatus,
    CurveRoleKindPair,
    CurveStrategyKind,
    CurveStrategyTopology,
    CurveTopologyLegSpec,
    KeyRateAnalytics,
    KeyRateNeutralityTolerance,
)
from apps.fixed_income.domain.curve_relative_value_results import (
    CurveLegAssessment,
    CurveLiquidityResultSeal,
    CurveRelativeValueAssessment,
    SignedKeyRateExposure,
)
from apps.fixed_income.domain.entities import CurveKind
from apps.fixed_income.domain.liquidity_premium import (
    LiquidityCostBasis,
    LiquidityCostEntry,
    LiquidityCostRule,
    LiquidityMeasureRole,
    LiquidityPremiumAssessment,
    LiquidityPremiumBlocker,
    LiquidityPremiumBlockerCode,
    LiquidityPremiumComponent,
    LiquidityPremiumRule,
    LiquidityPremiumStatus,
    MarketSpreadSemantics,
)
from apps.fixed_income.domain.rating_migration import (
    RatingBucketCount,
    RatingMigrationAssessment,
    RatingMigrationBlocker,
    RatingMigrationBlockerCode,
    RatingMigrationStatus,
    RatingTerminalKind,
    RatingTransitionRow,
)
from apps.fixed_income.domain.relative_value_assessment import (
    R5Component,
    R5ComponentSeal,
    R5ComponentStatus,
    R5RelativeValueAssessment,
    R5RelativeValueBlocker,
    R5RelativeValueBlockerCode,
    R5RelativeValueStatus,
)
from apps.fixed_income.domain.relative_value_record_seal import (
    R5RelativeValueOwnerRecordSeal,
)
from apps.fixed_income.domain.spread_history import (
    SelectedSpreadObservation,
    SpreadAssessmentStatus,
    SpreadBlocker,
    SpreadBlockerCode,
    SpreadPercentileAssessment,
    SpreadTieConvention,
)
from apps.portfolio.domain.r5_relative_value_outcome import R5PortfolioOutcomeSeal
from apps.research.application.r5_relative_value_promotion_decision import (
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValuePromotionRef,
)
from apps.research.application.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEventBundle,
)
from apps.research.application.r5_relative_value_promotion_persistence import (
    R5PromotionArtifact,
)
from apps.research.domain.r5_relative_value_promotion_decision import (
    R5RelativeValuePromotionDecision,
    R5RelativeValuePromotionDecisionOutcome,
    R5RelativeValuePromotionGateCode,
    R5RelativeValuePromotionGateOutcome,
    R5RelativeValueTrialPerformance,
)
from apps.research.domain.r5_relative_value_promotion_lifecycle import (
    R5RelativeValueDecisionIdentity,
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleEvent,
    R5RelativeValueLifecycleEventType,
)
from apps.research.domain.r5_relative_value_promotion_policy import (
    R5RelativeValuePromotionPolicy,
    R5RelativeValuePromotionPolicyStatus,
    R5RelativeValuePromotionRegistration,
    R5RelativeValuePromotionScope,
)
from apps.research.domain.r5_relative_value_promotion_trial import (
    R5RelativeValuePromotionTrial,
    R5RelativeValuePromotionTrialState,
    R5RelativeValueTrialObservation,
)

_T = TypeVar("_T")


class R5PromotionCodecError(ValueError):
    """Raised when persisted R5 promotion JSON is noncanonical."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    CurveRelativeValueBlocker,
    CurveRoleKindPair,
    CurveStrategyTopology,
    CurveTopologyLegSpec,
    KeyRateAnalytics,
    KeyRateNeutralityTolerance,
    CurveLegAssessment,
    CurveLiquidityResultSeal,
    CurveRelativeValueAssessment,
    SignedKeyRateExposure,
    LiquidityCostEntry,
    LiquidityCostRule,
    LiquidityPremiumAssessment,
    LiquidityPremiumBlocker,
    LiquidityPremiumComponent,
    LiquidityPremiumRule,
    RatingBucketCount,
    RatingMigrationAssessment,
    RatingMigrationBlocker,
    RatingTransitionRow,
    R5ComponentSeal,
    R5RelativeValueAssessment,
    R5RelativeValueBlocker,
    R5RelativeValueOwnerRecordSeal,
    SelectedSpreadObservation,
    SpreadBlocker,
    SpreadPercentileAssessment,
    R5PortfolioOutcomeSeal,
    R5RelativeValuePromotionRef,
    R5RelativeValuePromotionScope,
    R5RelativeValuePromotionRegistration,
    R5RelativeValuePromotionPolicy,
    R5RelativeValueTrialObservation,
    R5RelativeValuePromotionTrial,
    R5RelativeValueTrialPerformance,
    R5RelativeValuePromotionGateOutcome,
    R5RelativeValuePromotionDecision,
    R5RelativeValueDecisionAuthorization,
    R5RelativeValuePromotionDecisionBundle,
    R5RelativeValueDecisionIdentity,
    R5RelativeValueLifecycleAuthorization,
    R5RelativeValueLifecycleAuthorizationEvidence,
    R5RelativeValueLifecycleEvent,
    R5RelativeValueLifecycleEventBundle,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (
    CurveLegRole,
    CurveLegSide,
    CurveRelativeValueBlockerCode,
    CurveRelativeValueStatus,
    CurveStrategyKind,
    CurveKind,
    LiquidityCostBasis,
    LiquidityMeasureRole,
    LiquidityPremiumBlockerCode,
    LiquidityPremiumStatus,
    MarketSpreadSemantics,
    RatingMigrationBlockerCode,
    RatingMigrationStatus,
    RatingTerminalKind,
    R5Component,
    R5ComponentStatus,
    R5RelativeValueBlockerCode,
    R5RelativeValueStatus,
    SpreadAssessmentStatus,
    SpreadBlockerCode,
    SpreadTieConvention,
    R5RelativeValuePromotionPolicyStatus,
    R5RelativeValuePromotionTrialState,
    R5RelativeValuePromotionDecisionOutcome,
    R5RelativeValuePromotionGateCode,
    R5RelativeValueLifecycleEventType,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}


def encode_r5_promotion_artifact(artifact: R5PromotionArtifact) -> dict[str, object]:
    """Encode one policy or trial with an allowlisted tagged schema."""

    return _encode_envelope("research-r5-promotion-artifact-codec.v1", artifact)


def decode_r5_promotion_artifact(payload: object) -> R5PromotionArtifact:
    """Restore one exact policy or trial and reject every other type."""

    decoded = _decode_envelope(
        payload,
        schema="research-r5-promotion-artifact-codec.v1",
    )
    if type(decoded) not in {R5RelativeValuePromotionPolicy, R5RelativeValuePromotionTrial}:
        raise R5PromotionCodecError("R5 artifact codec restored the wrong type")
    return cast(R5PromotionArtifact, decoded)


def encode_r5_decision_authorization(
    authorization: R5RelativeValueDecisionAuthorization,
) -> dict[str, object]:
    """Encode one exact Research decision authorization receipt."""

    return _encode_envelope(
        "research-r5-decision-authorization-codec.v1",
        authorization,
    )


def decode_r5_decision_authorization(
    payload: object,
) -> R5RelativeValueDecisionAuthorization:
    """Restore one exact Research decision authorization receipt."""

    return _decode_exact(
        payload,
        schema="research-r5-decision-authorization-codec.v1",
        expected_type=R5RelativeValueDecisionAuthorization,
    )


def encode_r5_decision_bundle(
    bundle: R5RelativeValuePromotionDecisionBundle,
) -> dict[str, object]:
    """Encode one derived decision and its exact receipt binding."""

    return _encode_envelope("research-r5-decision-bundle-codec.v1", bundle)


def decode_r5_decision_bundle(payload: object) -> R5RelativeValuePromotionDecisionBundle:
    """Restore one fully typed and factory-validated decision bundle."""

    return _decode_exact(
        payload,
        schema="research-r5-decision-bundle-codec.v1",
        expected_type=R5RelativeValuePromotionDecisionBundle,
    )


def encode_r5_lifecycle_authorization_evidence(
    evidence: R5RelativeValueLifecycleAuthorizationEvidence,
) -> dict[str, object]:
    """Encode one lifecycle authorization and exact output commitment."""

    return _encode_envelope(
        "research-r5-lifecycle-authorization-evidence-codec.v1",
        evidence,
    )


def decode_r5_lifecycle_authorization_evidence(
    payload: object,
) -> R5RelativeValueLifecycleAuthorizationEvidence:
    """Restore one lifecycle authorization and output commitment."""

    return _decode_exact(
        payload,
        schema="research-r5-lifecycle-authorization-evidence-codec.v1",
        expected_type=R5RelativeValueLifecycleAuthorizationEvidence,
    )


def encode_r5_lifecycle_event_bundle(
    bundle: R5RelativeValueLifecycleEventBundle,
) -> dict[str, object]:
    """Encode one immutable event and its exact authorization receipt."""

    return _encode_envelope("research-r5-lifecycle-event-bundle-codec.v1", bundle)


def decode_r5_lifecycle_event_bundle(payload: object) -> R5RelativeValueLifecycleEventBundle:
    """Restore one immutable event and its exact authorization receipt."""

    return _decode_exact(
        payload,
        schema="research-r5-lifecycle-event-bundle-codec.v1",
        expected_type=R5RelativeValueLifecycleEventBundle,
    )


def _encode_envelope(schema: str, value: object) -> dict[str, object]:
    return {"schema": schema, "value": _encode_value(value)}


def _decode_exact(
    payload: object,
    *,
    schema: str,
    expected_type: type[_T],
) -> _T:
    decoded = _decode_envelope(payload, schema=schema)
    if type(decoded) is not expected_type:
        raise R5PromotionCodecError("R5 promotion codec restored the wrong type")
    return decoded


def _decode_envelope(payload: object, *, schema: str) -> object:
    envelope = _strict_object(payload, {"schema", "value"}, "codec envelope")
    if envelope["schema"] != schema:
        raise R5PromotionCodecError("R5 promotion codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except R5PromotionCodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise R5PromotionCodecError("R5 promotion typed restore failed") from error
    if _encode_envelope(schema, decoded) != envelope:
        raise R5PromotionCodecError("R5 promotion payload is not canonical")
    return decoded


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
            raise R5PromotionCodecError(f"unregistered R5 promotion type: {type_name}")
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
    raise R5PromotionCodecError(f"unsupported R5 promotion value: {type(value).__name__}")


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise R5PromotionCodecError("tagged R5 promotion value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise R5PromotionCodecError("unknown R5 promotion enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            decimal_result = Decimal(text)
        except ArithmeticError as error:
            raise R5PromotionCodecError("invalid R5 promotion Decimal") from error
        if _decimal_text(decimal_result) != text:
            raise R5PromotionCodecError("noncanonical R5 promotion Decimal")
        return decimal_result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            datetime_result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise R5PromotionCodecError("invalid R5 promotion datetime") from error
        if _utc_text(datetime_result) != text:
            raise R5PromotionCodecError("noncanonical R5 promotion datetime")
        return datetime_result
    if keys == {"$date"}:
        text = _string(tagged["$date"], "date")
        try:
            date_result = date.fromisoformat(text)
        except ValueError as error:
            raise R5PromotionCodecError("invalid R5 promotion date") from error
        if date_result.isoformat() != text:
            raise R5PromotionCodecError("noncanonical R5 promotion date")
        return date_result
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise R5PromotionCodecError("R5 promotion tuple members must be a list")
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise R5PromotionCodecError("unknown or noncanonical R5 promotion tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise R5PromotionCodecError("unknown R5 promotion dataclass type")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise R5PromotionCodecError("R5 promotion dataclass fields must be an object")
    field_values = cast(dict[str, object], raw_fields)
    expected_names = {item.name for item in fields(cast(Any, target_type))}
    if set(field_values) != expected_names:
        raise R5PromotionCodecError("R5 promotion dataclass fields are missing or extra")
    decoded_fields = {name: _decode_value(field_values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    for field_name, field_value in decoded_fields.items():
        if not _matches_type(field_value, hints[field_name]):
            raise R5PromotionCodecError(f"R5 promotion field type mismatch: {field_name}")
    try:
        constructor = cast(Any, target_type)
        return constructor(**decoded_fields)
    except (TypeError, ValueError) as error:
        raise R5PromotionCodecError("R5 promotion dataclass validation failed") from error


def _matches_type(value: object, expected: object) -> bool:
    origin = get_origin(expected)
    arguments = get_args(expected)
    if origin is types.UnionType:
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
        raise R5PromotionCodecError(f"{field_name} must be an object")
    result = cast(dict[str, object], payload)
    if set(result) != expected_keys:
        raise R5PromotionCodecError(f"{field_name} keys are missing or extra")
    return result


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise R5PromotionCodecError(f"{field_name} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R5PromotionCodecError("R5 promotion Decimal must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R5PromotionCodecError("R5 promotion datetime must be aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "R5PromotionCodecError",
    "decode_r5_decision_authorization",
    "decode_r5_decision_bundle",
    "decode_r5_lifecycle_authorization_evidence",
    "decode_r5_lifecycle_event_bundle",
    "decode_r5_promotion_artifact",
    "encode_r5_decision_authorization",
    "encode_r5_decision_bundle",
    "encode_r5_lifecycle_authorization_evidence",
    "encode_r5_lifecycle_event_bundle",
    "encode_r5_promotion_artifact",
]
