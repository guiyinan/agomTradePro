"""Strict codec preserving canonical-v1 Plan order row bytes."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.broker_execution.domain.plan_order_binding import BrokerPlanOrderBinding


class BrokerPlanOrderBindingCodecError(ValueError):
    """A stored Plan-to-Order binding is malformed or non-canonical."""


def encode_broker_plan_order_binding(
    value: BrokerPlanOrderBinding,
) -> dict[str, object]:
    """Encode one binding while retaining exact canonical-v1 row bytes."""

    payload = {
        key: item
        for key, item in value.to_payload().items()
        if key not in {"activation_available", "must_not_execute", "plan_order_payload"}
    }
    payload["plan_order_payload_json"] = value.plan_order_payload_json
    return payload


def decode_broker_plan_order_binding(payload: object) -> BrokerPlanOrderBinding:
    """Restore and revalidate one complete immutable inactive binding."""

    data = _mapping(payload, _PAYLOAD_KEYS)
    try:
        supersedes = data["supersedes_binding_hash"]
        value = BrokerPlanOrderBinding(
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
            binding_id=_string(data["binding_id"]),
            binding_version=_string(data["binding_version"]),
            portfolio_plan_owner=_string(data["portfolio_plan_owner"]),
            portfolio_plan_artifact_type=_string(data["portfolio_plan_artifact_type"]),
            portfolio_plan_id=_string(data["portfolio_plan_id"]),
            portfolio_plan_version=_positive_integer(data["portfolio_plan_version"]),
            portfolio_plan_content_hash=_string(data["portfolio_plan_content_hash"]),
            portfolio_plan_valid_until=_datetime(data["portfolio_plan_valid_until"]),
            portfolio_account_id=_string(data["portfolio_account_id"]),
            portfolio_receipt_owner=_string(data["portfolio_receipt_owner"]),
            portfolio_receipt_capability=_string(data["portfolio_receipt_capability"]),
            portfolio_receipt_id=_string(data["portfolio_receipt_id"]),
            portfolio_receipt_version=_string(data["portfolio_receipt_version"]),
            portfolio_receipt_content_hash=_string(data["portfolio_receipt_content_hash"]),
            portfolio_receipt_valid_until=_datetime(data["portfolio_receipt_valid_until"]),
            portfolio_subject_id=_string(data["portfolio_subject_id"]),
            portfolio_subject_version=_string(data["portfolio_subject_version"]),
            portfolio_subject_content_hash=_string(data["portfolio_subject_content_hash"]),
            plan_order_ordinal=_nonnegative_integer(data["plan_order_ordinal"]),
            plan_order_payload_json=_string(data["plan_order_payload_json"]),
            plan_order_content_hash=_string(data["plan_order_content_hash"]),
            broker_account_id=_positive_integer(data["broker_account_id"]),
            order_artifact_owner=_string(data["order_artifact_owner"]),
            order_artifact_type=_string(data["order_artifact_type"]),
            order_artifact_id=_string(data["order_artifact_id"]),
            order_artifact_version=_string(data["order_artifact_version"]),
            order_artifact_identity_hash=_string(data["order_artifact_identity_hash"]),
            order_artifact_content_hash=_string(data["order_artifact_content_hash"]),
            order_artifact_valid_until=_datetime(data["order_artifact_valid_until"]),
            order_approval_digest=_string(data["order_approval_digest"]),
            order_version=_positive_integer(data["order_version"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_binding_hash=(None if supersedes is None else _string(supersedes)),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerPlanOrderBindingCodecError, TypeError, ValueError) as error:
        raise BrokerPlanOrderBindingCodecError("Plan-to-Order binding is invalid") from error
    if payload != encode_broker_plan_order_binding(value):
        raise BrokerPlanOrderBindingCodecError("Plan-to-Order binding is non-canonical")
    return value


_PAYLOAD_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "permission",
    "blocker_codes",
    "binding_id",
    "binding_version",
    "identity_hash",
    "content_hash",
    "portfolio_plan_owner",
    "portfolio_plan_artifact_type",
    "portfolio_plan_id",
    "portfolio_plan_version",
    "portfolio_plan_content_hash",
    "portfolio_plan_valid_until",
    "portfolio_account_id",
    "portfolio_receipt_owner",
    "portfolio_receipt_capability",
    "portfolio_receipt_id",
    "portfolio_receipt_version",
    "portfolio_receipt_content_hash",
    "portfolio_receipt_valid_until",
    "portfolio_subject_id",
    "portfolio_subject_version",
    "portfolio_subject_content_hash",
    "plan_order_ordinal",
    "plan_order_payload_json",
    "plan_order_content_hash",
    "broker_account_id",
    "order_artifact_owner",
    "order_artifact_type",
    "order_artifact_id",
    "order_artifact_version",
    "order_artifact_identity_hash",
    "order_artifact_content_hash",
    "order_artifact_valid_until",
    "order_approval_digest",
    "order_version",
    "recorded_at",
    "valid_until",
    "supersedes_binding_hash",
}


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerPlanOrderBindingCodecError("binding payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _nonnegative_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise TypeError("expected non-negative integer")
    return value


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
    "BrokerPlanOrderBindingCodecError",
    "decode_broker_plan_order_binding",
    "encode_broker_plan_order_binding",
]
