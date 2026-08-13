"""Strict canonical codecs for Risk-owned Broker execution policies."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import cast

from apps.risk_center.application.broker_order_execution_policy import (
    BrokerOrderExecutionPolicyActivation,
    BrokerOrderExecutionPolicyActor,
    BrokerOrderExecutionPolicySourceRef,
    BrokerOrderExecutionPolicySourceSnapshot,
)
from apps.risk_center.domain.broker_order_execution_policy import (
    BrokerOrderExecutionRiskControls,
    BrokerOrderExecutionRiskPolicy,
)


class BrokerOrderExecutionPolicyCodecError(ValueError):
    """A persisted execution-policy payload is malformed or non-canonical."""


def encode_broker_order_execution_policy_source(
    value: BrokerOrderExecutionPolicySourceSnapshot,
) -> dict[str, object]:
    """Encode one complete immutable source bundle."""

    return {**value._content_payload(), "content_hash": value.content_hash}


def decode_broker_order_execution_policy_source(
    payload: object,
) -> BrokerOrderExecutionPolicySourceSnapshot:
    """Restore and revalidate one exact source bundle."""

    data = _mapping(
        payload,
        {
            "schema",
            "source_snapshot_id",
            "source_snapshot_version",
            "account_id",
            "controls",
            "sources",
            "recorded_at",
            "valid_until",
            "content_hash",
        },
    )
    sources = _sequence(data["sources"])
    try:
        value = BrokerOrderExecutionPolicySourceSnapshot(
            schema=_string(data["schema"]),
            source_snapshot_id=_string(data["source_snapshot_id"]),
            source_snapshot_version=_string(data["source_snapshot_version"]),
            account_id=_positive_integer(data["account_id"]),
            controls=_decode_controls(data["controls"]),
            sources=tuple(_decode_source_ref(item) for item in sources),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerOrderExecutionPolicyCodecError, TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCodecError("policy source is invalid") from error
    _require_canonical(payload, encode_broker_order_execution_policy_source(value))
    return value


def encode_broker_order_execution_policy(
    value: BrokerOrderExecutionRiskPolicy,
) -> dict[str, object]:
    """Encode one complete immutable policy."""

    return value.to_payload()


def decode_broker_order_execution_policy(payload: object) -> BrokerOrderExecutionRiskPolicy:
    """Restore and revalidate one exact immutable policy."""

    data = _mapping(
        payload,
        {
            "owner",
            "capability",
            "schema",
            "policy_id",
            "policy_version",
            "account_id",
            "controls",
            "source_snapshot_id",
            "source_snapshot_version",
            "source_snapshot_hash",
            "recorded_at",
            "activated_at",
            "valid_until",
            "supersedes_policy_hash",
            "permission_cap",
            "content_hash",
        },
    )
    try:
        value = BrokerOrderExecutionRiskPolicy(
            owner=_string(data["owner"]),
            capability=_string(data["capability"]),
            schema=_string(data["schema"]),
            policy_id=_string(data["policy_id"]),
            policy_version=_string(data["policy_version"]),
            account_id=_positive_integer(data["account_id"]),
            controls=_decode_controls(data["controls"]),
            source_snapshot_id=_string(data["source_snapshot_id"]),
            source_snapshot_version=_string(data["source_snapshot_version"]),
            source_snapshot_hash=_string(data["source_snapshot_hash"]),
            recorded_at=_datetime(data["recorded_at"]),
            activated_at=_datetime(data["activated_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_policy_hash=_optional_string(data["supersedes_policy_hash"]),
            permission_cap=_string(data["permission_cap"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerOrderExecutionPolicyCodecError, TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCodecError("execution policy is invalid") from error
    _require_canonical(payload, encode_broker_order_execution_policy(value))
    return value


def encode_broker_order_execution_policy_activation(
    value: BrokerOrderExecutionPolicyActivation,
) -> dict[str, object]:
    """Encode one actor-bound activation seal and full policy graph."""

    return {
        "schema": value.schema,
        "policy": encode_broker_order_execution_policy(value.policy),
        "activated_by": value.activated_by.to_payload(),
        "recorded_at": _datetime_text(value.recorded_at),
        "content_hash": value.content_hash,
    }


def decode_broker_order_execution_policy_activation(
    payload: object,
) -> BrokerOrderExecutionPolicyActivation:
    """Restore and revalidate one actor-bound activation graph."""

    data = _mapping(
        payload,
        {"schema", "policy", "activated_by", "recorded_at", "content_hash"},
    )
    try:
        value = BrokerOrderExecutionPolicyActivation(
            schema=_string(data["schema"]),
            policy=decode_broker_order_execution_policy(data["policy"]),
            activated_by=_decode_actor(data["activated_by"]),
            recorded_at=_datetime(data["recorded_at"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerOrderExecutionPolicyCodecError, TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCodecError("policy activation is invalid") from error
    _require_canonical(payload, encode_broker_order_execution_policy_activation(value))
    return value


def _decode_controls(payload: object) -> BrokerOrderExecutionRiskControls:
    keys = {
        "max_total_position_pct",
        "max_single_position_pct",
        "max_daily_loss_pct",
        "max_drawdown_pct",
        "max_stop_loss_pct",
        "take_profit_pct",
        "min_cash_pct",
        "force_stop_loss",
        "hard_exclusions",
    }
    data = _mapping(payload, keys)
    exclusions = _sequence(data["hard_exclusions"])
    try:
        value = BrokerOrderExecutionRiskControls(
            max_total_position_pct=_decimal(data["max_total_position_pct"]),
            max_single_position_pct=_decimal(data["max_single_position_pct"]),
            max_daily_loss_pct=_decimal(data["max_daily_loss_pct"]),
            max_drawdown_pct=_decimal(data["max_drawdown_pct"]),
            max_stop_loss_pct=_decimal(data["max_stop_loss_pct"]),
            take_profit_pct=_decimal(data["take_profit_pct"]),
            min_cash_pct=_decimal(data["min_cash_pct"]),
            force_stop_loss=_boolean(data["force_stop_loss"]),
            hard_exclusions=tuple(_string(item) for item in exclusions),
        )
    except (BrokerOrderExecutionPolicyCodecError, TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCodecError("policy controls are invalid") from error
    _require_canonical(payload, value.to_payload())
    return value


def _decode_source_ref(payload: object) -> BrokerOrderExecutionPolicySourceRef:
    data = _mapping(
        payload,
        {
            "source_kind",
            "source_id",
            "source_version",
            "source_content_hash",
            "recorded_at",
            "valid_until",
        },
    )
    try:
        value = BrokerOrderExecutionPolicySourceRef(
            source_kind=_string(data["source_kind"]),
            source_id=_string(data["source_id"]),
            source_version=_string(data["source_version"]),
            source_content_hash=_string(data["source_content_hash"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
        )
    except (BrokerOrderExecutionPolicyCodecError, TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCodecError("policy source ref is invalid") from error
    _require_canonical(payload, value.to_payload())
    return value


def _decode_actor(payload: object) -> BrokerOrderExecutionPolicyActor:
    data = _mapping(payload, {"actor_id", "user_id", "kind", "is_staff"})
    try:
        value = BrokerOrderExecutionPolicyActor(
            actor_id=_string(data["actor_id"]),
            user_id=_positive_integer(data["user_id"]),
            kind=_string(data["kind"]),
            is_staff=_boolean(data["is_staff"]),
        )
    except (BrokerOrderExecutionPolicyCodecError, TypeError, ValueError) as error:
        raise BrokerOrderExecutionPolicyCodecError("policy actor is invalid") from error
    _require_canonical(payload, value.to_payload())
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerOrderExecutionPolicyCodecError("payload shape is invalid")
    return cast(dict[str, object], payload)


def _sequence(value: object) -> list[object]:
    if type(value) is not list:
        raise BrokerOrderExecutionPolicyCodecError("payload sequence is invalid")
    return cast(list[object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise BrokerOrderExecutionPolicyCodecError("payload string is invalid")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise BrokerOrderExecutionPolicyCodecError("payload integer is invalid")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise BrokerOrderExecutionPolicyCodecError("payload boolean is invalid")
    return value


def _decimal(value: object) -> Decimal:
    text = _string(value)
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise BrokerOrderExecutionPolicyCodecError("payload decimal is invalid") from error
    if not result.is_finite():
        raise BrokerOrderExecutionPolicyCodecError("payload decimal is invalid")
    return result


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise BrokerOrderExecutionPolicyCodecError("payload datetime is not canonical UTC")
    try:
        result = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise BrokerOrderExecutionPolicyCodecError("payload datetime is invalid") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise BrokerOrderExecutionPolicyCodecError("payload datetime is naive")
    if _datetime_text(result) != text:
        raise BrokerOrderExecutionPolicyCodecError("payload datetime is not canonical")
    return result


def _datetime_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_canonical(original: object, canonical: dict[str, object]) -> None:
    if original != canonical:
        raise BrokerOrderExecutionPolicyCodecError("payload is not canonical")


__all__ = [
    "BrokerOrderExecutionPolicyCodecError",
    "decode_broker_order_execution_policy",
    "decode_broker_order_execution_policy_activation",
    "decode_broker_order_execution_policy_source",
    "encode_broker_order_execution_policy",
    "encode_broker_order_execution_policy_activation",
    "encode_broker_order_execution_policy_source",
]
