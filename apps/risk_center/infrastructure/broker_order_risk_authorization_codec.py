"""Strict canonical codecs for Broker order risk authorizations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.risk_center.domain.broker_order_risk_authorization import (
    BrokerOrderRiskAuthorizationActor,
    BrokerOrderRiskAuthorizationActorKind,
    BrokerOrderRiskAuthorizationRecord,
    BrokerOrderRiskAuthorizationSubject,
    BrokerOrderRiskScope,
)


class BrokerOrderRiskAuthorizationCodecError(ValueError):
    """A persisted authorization payload is malformed or non-canonical."""


def encode_broker_order_risk_authorization_subject(
    value: BrokerOrderRiskAuthorizationSubject,
) -> dict[str, object]:
    """Encode one complete immutable subject."""

    return {**value._content_payload(), "content_hash": value.content_hash}


def decode_broker_order_risk_authorization_subject(
    payload: object,
) -> BrokerOrderRiskAuthorizationSubject:
    """Restore and revalidate one complete immutable subject."""

    data = _mapping(
        payload,
        {
            "subject_id",
            "subject_version",
            "scope",
            "requested_by",
            "requested_at",
            "valid_until",
            "supersedes_authorization_hash",
            "content_hash",
        },
    )
    try:
        value = BrokerOrderRiskAuthorizationSubject(
            subject_id=_string(data["subject_id"]),
            subject_version=_string(data["subject_version"]),
            scope=_decode_scope(data["scope"]),
            requested_by=_decode_actor(data["requested_by"]),
            requested_at=_datetime(data["requested_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_authorization_hash=_optional_string(data["supersedes_authorization_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerOrderRiskAuthorizationCodecError, TypeError, ValueError) as error:
        raise BrokerOrderRiskAuthorizationCodecError("authorization subject is invalid") from error
    _require_canonical(payload, encode_broker_order_risk_authorization_subject(value))
    return value


def encode_broker_order_risk_authorization_record(
    value: BrokerOrderRiskAuthorizationRecord,
) -> dict[str, object]:
    """Encode one complete immutable authorization graph."""

    return {
        "owner": value.owner,
        "capability": value.capability,
        "authorization_id": value.authorization_id,
        "authorization_version": value.authorization_version,
        "subject": encode_broker_order_risk_authorization_subject(value.subject),
        "permission_cap": value.permission_cap,
        "approved_by": value.approved_by.to_payload(),
        "issued_at": _datetime_text(value.issued_at),
        "valid_until": _datetime_text(value.valid_until),
        "content_hash": value.content_hash,
    }


def decode_broker_order_risk_authorization_record(
    payload: object,
) -> BrokerOrderRiskAuthorizationRecord:
    """Restore and revalidate one complete immutable authorization graph."""

    data = _mapping(
        payload,
        {
            "owner",
            "capability",
            "authorization_id",
            "authorization_version",
            "subject",
            "permission_cap",
            "approved_by",
            "issued_at",
            "valid_until",
            "content_hash",
        },
    )
    try:
        value = BrokerOrderRiskAuthorizationRecord(
            owner=_string(data["owner"]),
            capability=_string(data["capability"]),
            authorization_id=_string(data["authorization_id"]),
            authorization_version=_string(data["authorization_version"]),
            subject=decode_broker_order_risk_authorization_subject(data["subject"]),
            permission_cap=_string(data["permission_cap"]),
            approved_by=_decode_actor(data["approved_by"]),
            issued_at=_datetime(data["issued_at"]),
            valid_until=_datetime(data["valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerOrderRiskAuthorizationCodecError, TypeError, ValueError) as error:
        raise BrokerOrderRiskAuthorizationCodecError("authorization record is invalid") from error
    _require_canonical(payload, encode_broker_order_risk_authorization_record(value))
    return value


def _decode_actor(payload: object) -> BrokerOrderRiskAuthorizationActor:
    data = _mapping(payload, {"actor_id", "kind", "is_staff", "user_id"})
    try:
        value = BrokerOrderRiskAuthorizationActor(
            actor_id=_string(data["actor_id"]),
            kind=BrokerOrderRiskAuthorizationActorKind(_string(data["kind"])),
            is_staff=_boolean(data["is_staff"]),
            user_id=_optional_positive_integer(data["user_id"]),
        )
    except (TypeError, ValueError) as error:
        raise BrokerOrderRiskAuthorizationCodecError("authorization actor is invalid") from error
    _require_canonical(payload, value.to_payload())
    return value


def _decode_scope(payload: object) -> BrokerOrderRiskScope:
    keys = {
        "account_id",
        "execution_scope_id",
        "execution_scope_version",
        "execution_scope_hash",
        "plan_id",
        "plan_version",
        "plan_content_hash",
        "plan_approval_hash",
        "plan_valid_until",
        "order_id",
        "order_version",
        "order_content_hash",
        "order_valid_until",
        "policy_id",
        "policy_version",
        "policy_content_hash",
        "policy_valid_until",
        "execution_scope_valid_until",
        "content_hash",
    }
    data = _mapping(payload, keys)
    try:
        value = BrokerOrderRiskScope(
            account_id=_positive_integer(data["account_id"]),
            execution_scope_id=_string(data["execution_scope_id"]),
            execution_scope_version=_string(data["execution_scope_version"]),
            execution_scope_hash=_string(data["execution_scope_hash"]),
            plan_id=_string(data["plan_id"]),
            plan_version=_string(data["plan_version"]),
            plan_content_hash=_string(data["plan_content_hash"]),
            plan_approval_hash=_string(data["plan_approval_hash"]),
            plan_valid_until=_datetime(data["plan_valid_until"]),
            order_id=_string(data["order_id"]),
            order_version=_string(data["order_version"]),
            order_content_hash=_string(data["order_content_hash"]),
            order_valid_until=_datetime(data["order_valid_until"]),
            policy_id=_string(data["policy_id"]),
            policy_version=_string(data["policy_version"]),
            policy_content_hash=_string(data["policy_content_hash"]),
            policy_valid_until=_datetime(data["policy_valid_until"]),
            execution_scope_valid_until=_datetime(data["execution_scope_valid_until"]),
            content_hash=_string(data["content_hash"]),
        )
    except (TypeError, ValueError) as error:
        raise BrokerOrderRiskAuthorizationCodecError("authorization scope is invalid") from error
    _require_canonical(payload, value.to_payload())
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerOrderRiskAuthorizationCodecError("authorization payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected bool")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _optional_positive_integer(value: object) -> int | None:
    return None if value is None else _positive_integer(value)


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _require_canonical(original: object, canonical: dict[str, object]) -> None:
    if original != canonical:
        raise BrokerOrderRiskAuthorizationCodecError("authorization payload is not canonical")


__all__ = [
    "BrokerOrderRiskAuthorizationCodecError",
    "decode_broker_order_risk_authorization_record",
    "decode_broker_order_risk_authorization_subject",
    "encode_broker_order_risk_authorization_record",
    "encode_broker_order_risk_authorization_subject",
]
