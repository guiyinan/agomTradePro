"""Strict canonical codec for Portfolio planning-policy definitions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.portfolio.domain.planning_policy_definition import PlanningPolicyDefinition


class PlanningPolicyDefinitionCodecError(ValueError):
    """A stored planning-policy definition is malformed or non-canonical."""


def encode_planning_policy_definition(
    value: PlanningPolicyDefinition,
) -> dict[str, object]:
    """Encode one complete immutable definition without derived flags."""

    payload = value.to_payload()
    return {key: item for key, item in payload.items() if key != "must_not_execute"}


def decode_planning_policy_definition(payload: object) -> PlanningPolicyDefinition:
    """Restore and revalidate one exact canonical definition."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "policy_id",
            "policy_version",
            "buy_lot_size",
            "fee_rate",
            "slippage_rate",
            "min_rebalance_value",
            "max_asset_weight",
            "max_volume_participation",
            "recorded_at",
            "valid_until",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = PlanningPolicyDefinition(
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            policy_id=_string(data["policy_id"]),
            policy_version=_string(data["policy_version"]),
            buy_lot_size=_positive_integer(data["buy_lot_size"]),
            fee_rate=_decimal(data["fee_rate"]),
            slippage_rate=_decimal(data["slippage_rate"]),
            min_rebalance_value=_decimal(data["min_rebalance_value"]),
            max_asset_weight=_decimal(data["max_asset_weight"]),
            max_volume_participation=_decimal(data["max_volume_participation"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            permission=_string(data["permission"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (PlanningPolicyDefinitionCodecError, TypeError, ValueError) as error:
        raise PlanningPolicyDefinitionCodecError("planning-policy definition is invalid") from error
    if payload != encode_planning_policy_definition(value):
        raise PlanningPolicyDefinitionCodecError("planning-policy definition is non-canonical")
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise PlanningPolicyDefinitionCodecError(
            "planning-policy definition payload shape is invalid"
        )
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _decimal(value: object) -> Decimal:
    text = _string(value)
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise ValueError("expected canonical Decimal text") from error


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


__all__ = [
    "PlanningPolicyDefinitionCodecError",
    "decode_planning_policy_definition",
    "encode_planning_policy_definition",
]
