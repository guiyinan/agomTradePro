"""Strict typed canonical codec for persisted R5 relative-value graphs."""

from __future__ import annotations

import types
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar, cast, get_args, get_origin, get_type_hints

from apps.fixed_income.application.relative_value_persistence import (
    R5RelativeValueInputReceipt,
    R5RelativeValueResultRecord,
)
from apps.fixed_income.domain import curve_relative_value as curve
from apps.fixed_income.domain import evidence
from apps.fixed_income.domain import liquidity_premium as liquidity
from apps.fixed_income.domain import rating_migration as rating
from apps.fixed_income.domain import relative_value_assessment as composite
from apps.fixed_income.domain import spread_history as spread
from apps.fixed_income.domain.entities import CurveKind

_T = TypeVar("_T")


class R5RelativeValueCodecError(ValueError):
    """Raised when persisted R5 JSON is incomplete, mistyped, or noncanonical."""


_DATACLASS_TYPES: tuple[type[object], ...] = (
    evidence.ExactEvidence,
    spread.SpreadBlocker,
    spread.CalendarPeriod,
    spread.ExpectedObservationCalendar,
    spread.SpreadObservation,
    spread.SpreadPercentilePolicy,
    spread.SpreadPercentileEvidence,
    spread.SelectedSpreadObservation,
    spread.SpreadPercentileAssessment,
    rating.RatingMigrationBlocker,
    rating.RatingTaxonomy,
    rating.RatingCohort,
    rating.RatingMemberTransition,
    rating.RatingMigrationPolicy,
    rating.RatingMigrationEvidence,
    rating.RatingBucketCount,
    rating.RatingTransitionRow,
    rating.RatingMigrationAssessment,
    liquidity.LiquidityPremiumBlocker,
    liquidity.LiquidityMeasure,
    liquidity.LiquidityPremiumRule,
    liquidity.LiquidityCostRule,
    liquidity.LiquidityPremiumPolicy,
    liquidity.LiquidityPremiumEvidence,
    liquidity.LiquidityPremiumComponent,
    liquidity.LiquidityCostEntry,
    liquidity.LiquidityPremiumAssessment,
    curve.CurveRelativeValueBlocker,
    curve.BondMasterEvidence,
    curve.CashFlowEvidence,
    curve.CurveTradingCalendarEvidence,
    curve.CurveCashFundingEvidence,
    curve.KeyRateAnalytics,
    curve.CurveRelativeValueLeg,
    curve.DirectionalCapacityEvidence,
    curve.LiquidityCapacityEvidence,
    curve.CurveRoleKindPair,
    curve.CurveTopologyLegSpec,
    curve.CurveStrategyTopology,
    curve.KeyRateNeutralityTolerance,
    curve.CurveRelativeValuePolicy,
    curve.CurveRelativeValueEvidence,
    curve.SignedKeyRateExposure,
    curve.CurveLiquidityResultSeal,
    curve.CurveLegAssessment,
    curve.CurveRelativeValueAssessment,
    composite.R5RelativeValueBlocker,
    composite.R5RelativeValuePolicySet,
    composite.R5RelativeValueInputSet,
    composite.R5ComponentSeal,
    composite.R5RelativeValueAssessment,
    R5RelativeValueInputReceipt,
    R5RelativeValueResultRecord,
)
_DATACLASS_REGISTRY = {item.__name__: item for item in _DATACLASS_TYPES}
if len(_DATACLASS_REGISTRY) != len(_DATACLASS_TYPES):
    raise RuntimeError("R5 relative-value dataclass codec tags must be unique")

_ENUM_TYPES: tuple[type[Enum], ...] = (
    evidence.EvidenceRole,
    spread.SpreadObservationState,
    spread.SpreadTieConvention,
    spread.TargetSampleConvention,
    spread.RevisionSelection,
    spread.SpreadAssessmentStatus,
    spread.SpreadBlockerCode,
    rating.RatingTerminalKind,
    rating.RatingDenominatorConvention,
    rating.RatingCensoringConvention,
    rating.RatingTerminalSelection,
    rating.RatingMigrationStatus,
    rating.RatingMigrationBlockerCode,
    liquidity.LiquidityMeasureRole,
    liquidity.MarketSpreadSemantics,
    liquidity.LiquidityCostBasis,
    liquidity.LiquidityPremiumStatus,
    liquidity.LiquidityPremiumBlockerCode,
    curve.CurveStrategyKind,
    curve.CurveLegSide,
    curve.CurveLegRole,
    curve.CurveRelativeValueStatus,
    curve.CurveCarryCostSemantics,
    curve.CurveRelativeValueBlockerCode,
    composite.R5Component,
    composite.R5ComponentStatus,
    composite.R5RelativeValueStatus,
    composite.R5RelativeValueBlockerCode,
    CurveKind,
)
_ENUM_REGISTRY = {item.__name__: item for item in _ENUM_TYPES}
if len(_ENUM_REGISTRY) != len(_ENUM_TYPES):
    raise RuntimeError("R5 relative-value enum codec tags must be unique")

_RECEIPT_SCHEMA = "fixed-income-r5-input-receipt-codec.v1"
_RESULT_SCHEMA = "fixed-income-r5-result-record-codec.v1"


def encode_r5_input_receipt(
    receipt: R5RelativeValueInputReceipt,
) -> dict[str, object]:
    """Encode a complete receipt and its input/policy graphs."""

    return _encode_envelope(_RECEIPT_SCHEMA, receipt)


def decode_r5_input_receipt(payload: object) -> R5RelativeValueInputReceipt:
    """Restore every receipt field through typed Domain constructors."""

    return _decode_envelope(
        payload,
        schema=_RECEIPT_SCHEMA,
        expected_type=R5RelativeValueInputReceipt,
    )


def encode_r5_result_record(
    result: R5RelativeValueResultRecord,
) -> dict[str, object]:
    """Encode a complete four-child composite result record."""

    return _encode_envelope(_RESULT_SCHEMA, result)


def decode_r5_result_record(payload: object) -> R5RelativeValueResultRecord:
    """Restore all child/component/composite fields and recompute their seals."""

    return _decode_envelope(
        payload,
        schema=_RESULT_SCHEMA,
        expected_type=R5RelativeValueResultRecord,
    )


def _encode_envelope(schema: str, value: object) -> dict[str, object]:
    return {"schema": schema, "value": _encode_value(value)}


def _decode_envelope(
    payload: object,
    *,
    schema: str,
    expected_type: type[_T],
) -> _T:
    envelope = _strict_object(payload, {"schema", "value"}, "R5 codec envelope")
    if envelope["schema"] != schema:
        raise R5RelativeValueCodecError("R5 relative-value codec schema mismatch")
    try:
        decoded = _decode_value(envelope["value"])
    except R5RelativeValueCodecError:
        raise
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        raise R5RelativeValueCodecError("R5 relative-value typed restore failed") from error
    if type(decoded) is not expected_type:
        raise R5RelativeValueCodecError("R5 relative-value codec restored the wrong root type")
    restored = decoded
    if _encode_envelope(schema, restored) != envelope:
        raise R5RelativeValueCodecError("R5 relative-value payload is not canonical")
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
        if type_name not in _DATACLASS_REGISTRY:
            raise R5RelativeValueCodecError(f"unregistered R5 relative-value type: {type_name}")
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
    raise R5RelativeValueCodecError(f"unsupported R5 relative-value value: {type(value).__name__}")


def _decode_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if not isinstance(value, dict):
        raise R5RelativeValueCodecError("tagged R5 relative-value value must be an object")
    tagged = cast(dict[str, object], value)
    keys = set(tagged)
    if keys == {"$enum", "$value"}:
        enum_name = _string(tagged["$enum"], "enum name")
        enum_type = _ENUM_REGISTRY.get(enum_name)
        if enum_type is None:
            raise R5RelativeValueCodecError("unknown R5 relative-value enum type")
        return enum_type(_string(tagged["$value"], "enum value"))
    if keys == {"$decimal"}:
        text = _string(tagged["$decimal"], "Decimal")
        try:
            decimal_result = Decimal(text)
        except ArithmeticError as error:
            raise R5RelativeValueCodecError("invalid R5 relative-value Decimal") from error
        if _decimal_text(decimal_result) != text:
            raise R5RelativeValueCodecError("noncanonical R5 relative-value Decimal")
        return decimal_result
    if keys == {"$datetime"}:
        text = _string(tagged["$datetime"], "datetime")
        try:
            datetime_result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as error:
            raise R5RelativeValueCodecError("invalid R5 relative-value datetime") from error
        if _utc_text(datetime_result) != text:
            raise R5RelativeValueCodecError("noncanonical R5 relative-value datetime")
        return datetime_result
    if keys == {"$tuple"}:
        members = tagged["$tuple"]
        if not isinstance(members, list):
            raise R5RelativeValueCodecError("R5 relative-value tuple members must be a list")
        return tuple(_decode_value(item) for item in members)
    if keys == {"$type", "$fields"}:
        return _decode_dataclass(tagged)
    raise R5RelativeValueCodecError("unknown or noncanonical R5 relative-value tag")


def _decode_dataclass(tagged: dict[str, object]) -> object:
    type_name = _string(tagged["$type"], "dataclass type")
    target_type = _DATACLASS_REGISTRY.get(type_name)
    if target_type is None:
        raise R5RelativeValueCodecError("unknown R5 relative-value dataclass type")
    raw_fields = tagged["$fields"]
    if not isinstance(raw_fields, dict) or any(not isinstance(key, str) for key in raw_fields):
        raise R5RelativeValueCodecError("R5 relative-value dataclass fields must be an object")
    field_values = cast(dict[str, object], raw_fields)
    expected_names = {item.name for item in fields(cast(Any, target_type))}
    if set(field_values) != expected_names:
        raise R5RelativeValueCodecError("R5 relative-value dataclass fields are missing or extra")
    decoded_fields = {name: _decode_value(field_values[name]) for name in expected_names}
    hints = get_type_hints(target_type)
    for field_name, field_value in decoded_fields.items():
        if not _matches_type(field_value, hints[field_name]):
            raise R5RelativeValueCodecError(f"R5 relative-value field type mismatch: {field_name}")
    try:
        constructor = cast(Any, target_type)
        return constructor(**decoded_fields)
    except (TypeError, ValueError) as error:
        raise R5RelativeValueCodecError("R5 relative-value dataclass validation failed") from error


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
    if expected is Decimal:
        return type(value) is Decimal
    return isinstance(expected, type) and isinstance(value, expected)


def _strict_object(
    payload: object,
    expected_keys: set[str],
    field_name: str,
) -> dict[str, object]:
    if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
        raise R5RelativeValueCodecError(f"{field_name} must be an object")
    result = cast(dict[str, object], payload)
    if set(result) != expected_keys:
        raise R5RelativeValueCodecError(f"{field_name} keys are missing or extra")
    return result


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise R5RelativeValueCodecError(f"{field_name} must be a string")
    return value


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise R5RelativeValueCodecError("R5 relative-value Decimal must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise R5RelativeValueCodecError("R5 relative-value datetime must be aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "R5RelativeValueCodecError",
    "decode_r5_input_receipt",
    "decode_r5_result_record",
    "encode_r5_input_receipt",
    "encode_r5_result_record",
]
