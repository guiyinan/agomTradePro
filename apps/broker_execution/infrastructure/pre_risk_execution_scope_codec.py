"""Strict canonical codec for Broker pre-Risk execution scopes."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.broker_execution.domain.pre_risk_execution_scope import (
    BrokerPreRiskExecutionScope,
)


class BrokerPreRiskExecutionScopeCodecError(ValueError):
    """A stored pre-Risk scope payload is malformed or non-canonical."""


def encode_broker_pre_risk_execution_scope(
    value: BrokerPreRiskExecutionScope,
) -> dict[str, object]:
    """Encode one complete scope without derived safety flags."""

    payload = value.to_payload()
    return {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }


def decode_broker_pre_risk_execution_scope(
    payload: object,
) -> BrokerPreRiskExecutionScope:
    """Restore and revalidate one complete immutable inactive scope."""

    data = _mapping(
        payload,
        {
            "owner",
            "scope_id",
            "scope_version",
            "broker_account_id",
            "portfolio_account_id",
            "plan_id",
            "plan_version",
            "plan_content_hash",
            "plan_valid_until",
            "portfolio_receipt_id",
            "portfolio_receipt_version",
            "portfolio_receipt_content_hash",
            "portfolio_subject_id",
            "portfolio_subject_version",
            "portfolio_subject_content_hash",
            "portfolio_receipt_valid_until",
            "order_artifact_id",
            "order_artifact_version",
            "order_artifact_content_hash",
            "order_artifact_identity_hash",
            "order_version",
            "order_approval_digest",
            "order_valid_until",
            "order_risk_policy_version",
            "recorded_at",
            "valid_until",
            "supersedes_scope_hash",
            "permission",
            "blocker_codes",
            "content_hash",
        },
    )
    try:
        supersedes = data["supersedes_scope_hash"]
        value = BrokerPreRiskExecutionScope(
            owner=_string(data["owner"]),
            scope_id=_string(data["scope_id"]),
            scope_version=_string(data["scope_version"]),
            broker_account_id=_positive_integer(data["broker_account_id"]),
            portfolio_account_id=_string(data["portfolio_account_id"]),
            plan_id=_string(data["plan_id"]),
            plan_version=_positive_integer(data["plan_version"]),
            plan_content_hash=_string(data["plan_content_hash"]),
            plan_valid_until=_datetime(data["plan_valid_until"]),
            portfolio_receipt_id=_string(data["portfolio_receipt_id"]),
            portfolio_receipt_version=_string(data["portfolio_receipt_version"]),
            portfolio_receipt_content_hash=_string(data["portfolio_receipt_content_hash"]),
            portfolio_subject_id=_string(data["portfolio_subject_id"]),
            portfolio_subject_version=_string(data["portfolio_subject_version"]),
            portfolio_subject_content_hash=_string(data["portfolio_subject_content_hash"]),
            portfolio_receipt_valid_until=_datetime(data["portfolio_receipt_valid_until"]),
            order_artifact_id=_string(data["order_artifact_id"]),
            order_artifact_version=_string(data["order_artifact_version"]),
            order_artifact_content_hash=_string(data["order_artifact_content_hash"]),
            order_artifact_identity_hash=_string(data["order_artifact_identity_hash"]),
            order_version=_positive_integer(data["order_version"]),
            order_approval_digest=_string(data["order_approval_digest"]),
            order_valid_until=_datetime(data["order_valid_until"]),
            order_risk_policy_version=_string(data["order_risk_policy_version"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_scope_hash=(None if supersedes is None else _string(supersedes)),
            permission=_string(data["permission"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerPreRiskExecutionScopeCodecError, TypeError, ValueError) as error:
        raise BrokerPreRiskExecutionScopeCodecError(
            "pre-Risk execution scope is invalid"
        ) from error
    if payload != encode_broker_pre_risk_execution_scope(value):
        raise BrokerPreRiskExecutionScopeCodecError("pre-Risk execution scope is non-canonical")
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerPreRiskExecutionScopeCodecError("scope payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
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
    "BrokerPreRiskExecutionScopeCodecError",
    "decode_broker_pre_risk_execution_scope",
    "encode_broker_pre_risk_execution_scope",
]
