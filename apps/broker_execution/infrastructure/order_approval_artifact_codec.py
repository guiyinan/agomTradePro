"""Strict canonical codec for Broker order approval artifacts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from apps.broker_execution.domain.entities import (
    LiveOrderSide,
    LiveOrderType,
    OrderApprovalSnapshot,
)
from apps.broker_execution.domain.order_approval_artifact import (
    BrokerOrderApprovalActor,
    BrokerOrderApprovalArtifact,
)


class BrokerOrderApprovalArtifactCodecError(ValueError):
    """A stored artifact payload is malformed or non-canonical."""


def encode_broker_order_approval_artifact(
    value: BrokerOrderApprovalArtifact,
) -> dict[str, object]:
    """Encode one complete immutable artifact without derived safety flags."""

    payload = value.to_payload()
    return {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }


def decode_broker_order_approval_artifact(payload: object) -> BrokerOrderApprovalArtifact:
    """Restore and revalidate one complete immutable artifact."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "artifact_id",
            "artifact_version",
            "client_order_id",
            "account_id",
            "order_version",
            "approval_snapshot",
            "approval_digest",
            "approved_by",
            "approved_at",
            "valid_until",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        value = BrokerOrderApprovalArtifact(
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            artifact_id=_string(data["artifact_id"]),
            artifact_version=_string(data["artifact_version"]),
            client_order_id=_string(data["client_order_id"]),
            account_id=_positive_integer(data["account_id"]),
            order_version=_positive_integer(data["order_version"]),
            approval_snapshot=_snapshot(data["approval_snapshot"]),
            approval_digest=_string(data["approval_digest"]),
            approved_by=_actor(data["approved_by"]),
            approved_at=_datetime(data["approved_at"]),
            valid_until=_datetime(data["valid_until"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerOrderApprovalArtifactCodecError, TypeError, ValueError) as error:
        raise BrokerOrderApprovalArtifactCodecError("order approval artifact is invalid") from error
    if payload != encode_broker_order_approval_artifact(value):
        raise BrokerOrderApprovalArtifactCodecError("order approval artifact is non-canonical")
    return value


def _snapshot(payload: object) -> OrderApprovalSnapshot:
    data = _mapping(
        payload,
        {
            "account_id",
            "agent_id",
            "asset_code",
            "market",
            "side",
            "order_type",
            "quantity",
            "limit_price",
            "estimated_amount",
            "expires_at",
            "risk_policy_version",
            "risk_snapshot_json",
            "approval_mode",
            "source_recommendation_ids",
            "source_signal_ids",
        },
    )
    limit_price = data["limit_price"]
    return OrderApprovalSnapshot(
        account_id=_positive_integer(data["account_id"]),
        agent_id=_string(data["agent_id"]),
        asset_code=_string(data["asset_code"]),
        market=_string(data["market"]),
        side=LiveOrderSide(_string(data["side"])),
        order_type=LiveOrderType(_string(data["order_type"])),
        quantity=_decimal(data["quantity"]),
        limit_price=None if limit_price is None else _decimal(limit_price),
        estimated_amount=_decimal(data["estimated_amount"]),
        expires_at=_string(data["expires_at"]),
        risk_policy_version=_string(data["risk_policy_version"]),
        risk_snapshot_json=_string(data["risk_snapshot_json"]),
        approval_mode=_string(data["approval_mode"]),
        source_recommendation_ids=_string_tuple(data["source_recommendation_ids"]),
        source_signal_ids=_string_tuple(data["source_signal_ids"]),
    )


def _actor(payload: object) -> BrokerOrderApprovalActor:
    data = _mapping(payload, {"actor_id", "user_id", "role"})
    return BrokerOrderApprovalActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerOrderApprovalArtifactCodecError("artifact payload shape is invalid")
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
    return Decimal(_string(value))


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise TypeError("expected string array")
    return tuple(cast(list[str], value))


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


__all__ = [
    "BrokerOrderApprovalArtifactCodecError",
    "decode_broker_order_approval_artifact",
    "encode_broker_order_approval_artifact",
]
