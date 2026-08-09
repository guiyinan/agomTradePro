"""Strict allow-listed codec for the complete governed R8 input receipt."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import cast

from apps.portfolio.domain._optimization_canonical import decimal_text, utc_text
from apps.portfolio.domain.governed_input_set import (
    ExactPromotionAttestation,
    GovernedOptimizationInputSet,
    OwnerBoundPayloadEvidence,
)
from apps.portfolio.domain.input_payloads import (
    AssetCovariancePayload,
    AssetDecimalValue,
    AssetFactorExposure,
    CashRequirementPayload,
    ExecutionFeedbackPayload,
    ExecutionFeedbackValue,
    ExpectedReturnPayload,
    LiquidityLimitPayload,
    MacroExposurePayload,
    ManualRestrictionsPayload,
    ManualRestrictionValue,
    PositionBoundsPayload,
    PositionBoundValue,
    ScenarioAssetLoss,
    ScenarioLossPayload,
    ScenarioLossVector,
    TransactionCostPayload,
    TurnoverLimitPayload,
)
from apps.portfolio.domain.investable_universe import (
    AssetMarket,
    InvestableUniverseMember,
    InvestableUniverseSnapshot,
)
from apps.portfolio.domain.market_constraints import (
    AShareTradingConstraint,
    BondTradingConstraint,
    CommodityTradingConstraint,
    FundTradingConstraint,
    TradingConstraintsPayload,
)
from apps.portfolio.domain.optimization_input_receipt import (
    GovernedOptimizationInputReceipt,
)
from apps.portfolio.domain.optimizer_inputs import OptimizationInputKind
from apps.portfolio.domain.path_drawdown import (
    DrawdownPathObservation,
    DrawdownRiskBudgetPayload,
)

_DATACLASS_TYPES: tuple[type[object], ...] = (
    AssetDecimalValue,
    AssetFactorExposure,
    PositionBoundValue,
    ManualRestrictionValue,
    ScenarioAssetLoss,
    ScenarioLossVector,
    ExecutionFeedbackValue,
    ExpectedReturnPayload,
    TransactionCostPayload,
    LiquidityLimitPayload,
    MacroExposurePayload,
    AssetCovariancePayload,
    ScenarioLossPayload,
    TurnoverLimitPayload,
    PositionBoundsPayload,
    ManualRestrictionsPayload,
    CashRequirementPayload,
    ExecutionFeedbackPayload,
    InvestableUniverseMember,
    InvestableUniverseSnapshot,
    AShareTradingConstraint,
    FundTradingConstraint,
    BondTradingConstraint,
    CommodityTradingConstraint,
    TradingConstraintsPayload,
    DrawdownPathObservation,
    DrawdownRiskBudgetPayload,
    OwnerBoundPayloadEvidence,
    ExactPromotionAttestation,
    GovernedOptimizationInputSet,
)
_DATACLASS_BY_TAG = {candidate.__name__: candidate for candidate in _DATACLASS_TYPES}
_ENUM_TYPES: tuple[type[Enum], ...] = (AssetMarket, OptimizationInputKind)
_ENUM_BY_TAG = {candidate.__name__: candidate for candidate in _ENUM_TYPES}
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "receipt_id",
        "receipt_version",
        "owner",
        "input_set",
        "evidence_graph_hash",
        "pit_manifest_set_hash",
        "recorded_at",
        "content_hash",
        "research_only",
        "must_not_use_for_decision",
        "must_not_execute",
    }
)


def encode_input_receipt(receipt: GovernedOptimizationInputReceipt) -> dict[str, object]:
    """Encode an exact receipt without dropping any typed graph node."""

    return {
        "schema": "governed-optimization-input-receipt-payload.v1",
        "receipt_id": receipt.receipt_id,
        "receipt_version": receipt.receipt_version,
        "owner": receipt.owner,
        "input_set": _encode_node(receipt.input_set),
        "evidence_graph_hash": receipt.evidence_graph_hash,
        "pit_manifest_set_hash": receipt.pit_manifest_set_hash,
        "recorded_at": utc_text(receipt.recorded_at),
        "content_hash": receipt.content_hash,
        "research_only": receipt.research_only,
        "must_not_use_for_decision": receipt.must_not_use_for_decision,
        "must_not_execute": receipt.must_not_execute,
    }


def decode_input_receipt(payload: object) -> GovernedOptimizationInputReceipt:
    """Strictly rebuild every dataclass and replay all Domain invariants."""

    root = _mapping(payload, "input receipt")
    if frozenset(root) != _TOP_LEVEL_KEYS:
        raise ValueError("input receipt payload keys are not canonical")
    if root["schema"] != "governed-optimization-input-receipt-payload.v1":
        raise ValueError("input receipt payload schema is unsupported")
    input_set = _decode_node(root["input_set"])
    if type(input_set) is not GovernedOptimizationInputSet:
        raise ValueError("input receipt payload lacks a governed input set")
    receipt = GovernedOptimizationInputReceipt(
        receipt_id=_string(root["receipt_id"], "receipt_id"),
        receipt_version=_string(root["receipt_version"], "receipt_version"),
        owner=_string(root["owner"], "owner"),
        input_set=input_set,
        evidence_graph_hash=_string(root["evidence_graph_hash"], "evidence_graph_hash"),
        pit_manifest_set_hash=_string(
            root["pit_manifest_set_hash"],
            "pit_manifest_set_hash",
        ),
        recorded_at=_datetime(root["recorded_at"], "recorded_at"),
        content_hash=_string(root["content_hash"], "content_hash"),
        research_only=_boolean(root["research_only"], "research_only"),
        must_not_use_for_decision=_boolean(
            root["must_not_use_for_decision"],
            "must_not_use_for_decision",
        ),
        must_not_execute=_boolean(root["must_not_execute"], "must_not_execute"),
    )
    if encode_input_receipt(receipt) != root:
        raise ValueError("input receipt payload is not canonically encoded")
    return receipt


def _encode_node(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, Decimal):
        return {"$decimal": decimal_text(value)}
    if isinstance(value, datetime):
        return {"$datetime": utc_text(value)}
    if isinstance(value, Enum):
        enum_type = type(value)
        if enum_type not in _ENUM_TYPES:
            raise ValueError("input receipt contains an unsupported enum")
        return {"$enum": enum_type.__name__, "value": value.value}
    if isinstance(value, tuple):
        return {"$tuple": [_encode_node(item) for item in value]}
    value_type = type(value)
    if value_type in _DATACLASS_TYPES and is_dataclass(value):
        return {
            "$type": value_type.__name__,
            "fields": {
                item.name: _encode_node(getattr(value, item.name)) for item in fields(value)
            },
        }
    raise ValueError(f"input receipt contains unsupported type {value_type.__name__}")


def _decode_node(value: object) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    node = _mapping(value, "typed input node")
    if frozenset(node) == {"$decimal"}:
        return _decimal(node["$decimal"])
    if frozenset(node) == {"$datetime"}:
        return _datetime(node["$datetime"], "typed datetime")
    if frozenset(node) == {"$tuple"}:
        raw_items = node["$tuple"]
        if type(raw_items) is not list:
            raise ValueError("typed tuple payload must be a list")
        return tuple(_decode_node(item) for item in cast(list[object], raw_items))
    if frozenset(node) == {"$enum", "value"}:
        tag = _string(node["$enum"], "enum tag")
        enum_type = _ENUM_BY_TAG.get(tag)
        if enum_type is None:
            raise ValueError("input receipt enum tag is unsupported")
        raw_value = _string(node["value"], "enum value")
        try:
            return enum_type(raw_value)
        except ValueError as exc:
            raise ValueError("input receipt enum value is invalid") from exc
    if frozenset(node) != {"$type", "fields"}:
        raise ValueError("input receipt typed node shape is invalid")
    tag = _string(node["$type"], "dataclass tag")
    dataclass_type = _DATACLASS_BY_TAG.get(tag)
    if dataclass_type is None:
        raise ValueError("input receipt dataclass tag is unsupported")
    if not is_dataclass(dataclass_type):
        raise ValueError("input receipt dataclass registry is invalid")
    raw_fields = _mapping(node["fields"], f"{tag} fields")
    expected_names = tuple(item.name for item in fields(dataclass_type))
    if frozenset(raw_fields) != frozenset(expected_names):
        raise ValueError(f"{tag} fields are not canonical")
    decoded_fields = {name: _decode_node(raw_fields[name]) for name in expected_names}
    constructor = cast(Callable[..., object], dataclass_type)
    try:
        return constructor(**decoded_fields)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{tag} failed strict reconstruction") from exc


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{field_name} must be an object")
    mapping = cast(Mapping[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise ValueError(f"{field_name} keys must be strings")
    return {cast(str, key): item for key, item in mapping.items()}


def _string(value: object, field_name: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a string")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _decimal(value: object) -> Decimal:
    text = _string(value, "typed decimal")
    try:
        result = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("typed decimal is invalid") from exc
    if decimal_text(result) != text:
        raise ValueError("typed decimal is not canonical")
    return result


def _datetime(value: object, field_name: str) -> datetime:
    text = _string(value, field_name)
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} is invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None or utc_text(result) != text:
        raise ValueError(f"{field_name} is not canonical UTC")
    return result


__all__ = ["decode_input_receipt", "encode_input_receipt"]
