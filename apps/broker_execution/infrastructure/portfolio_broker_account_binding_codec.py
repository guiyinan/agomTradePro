"""Strict canonical codec for Broker/Portfolio namespace bindings."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.broker_execution.domain.portfolio_broker_account_binding import (
    BrokerPortfolioAccountBindingActor,
    BrokerPortfolioAccountNamespaceBinding,
)


class BrokerPortfolioAccountBindingCodecError(ValueError):
    """A stored binding payload is malformed or non-canonical."""


def encode_broker_portfolio_account_binding(
    value: BrokerPortfolioAccountNamespaceBinding,
) -> dict[str, object]:
    """Encode one complete binding without derived safety flags."""

    return {
        key: item
        for key, item in value.to_payload().items()
        if key not in {"activation_available", "must_not_execute"}
    }


def decode_broker_portfolio_account_binding(
    payload: object,
) -> BrokerPortfolioAccountNamespaceBinding:
    """Restore and revalidate one immutable inactive binding."""

    data = _mapping(
        payload,
        {
            "owner",
            "binding_id",
            "binding_version",
            "broker_account_namespace",
            "broker_account_id",
            "portfolio_account_namespace",
            "portfolio_account_id",
            "owner_user_id",
            "account_type",
            "source_accounts_active",
            "broker_source_owner",
            "broker_source_artifact_type",
            "broker_source_id",
            "broker_source_version",
            "broker_source_content_hash",
            "portfolio_source_owner",
            "portfolio_source_artifact_type",
            "portfolio_source_id",
            "portfolio_source_version",
            "portfolio_source_content_hash",
            "asserted_by",
            "issued_at",
            "recorded_at",
            "valid_until",
            "supersedes_binding_hash",
            "permission",
            "blocker_codes",
            "identity_hash",
            "content_hash",
        },
    )
    actor = _mapping(data["asserted_by"], {"actor_id", "user_id", "role", "kind", "is_staff"})
    try:
        supersedes = data["supersedes_binding_hash"]
        value = BrokerPortfolioAccountNamespaceBinding(
            owner=_string(data["owner"]),
            binding_id=_string(data["binding_id"]),
            binding_version=_string(data["binding_version"]),
            broker_account_namespace=_string(data["broker_account_namespace"]),
            broker_account_id=_positive_integer(data["broker_account_id"]),
            portfolio_account_namespace=_string(data["portfolio_account_namespace"]),
            portfolio_account_id=_string(data["portfolio_account_id"]),
            owner_user_id=_positive_integer(data["owner_user_id"]),
            account_type=_string(data["account_type"]),
            source_accounts_active=_boolean(data["source_accounts_active"]),
            broker_source_owner=_string(data["broker_source_owner"]),
            broker_source_artifact_type=_string(data["broker_source_artifact_type"]),
            broker_source_id=_string(data["broker_source_id"]),
            broker_source_version=_string(data["broker_source_version"]),
            broker_source_content_hash=_string(data["broker_source_content_hash"]),
            portfolio_source_owner=_string(data["portfolio_source_owner"]),
            portfolio_source_artifact_type=_string(data["portfolio_source_artifact_type"]),
            portfolio_source_id=_string(data["portfolio_source_id"]),
            portfolio_source_version=_string(data["portfolio_source_version"]),
            portfolio_source_content_hash=_string(data["portfolio_source_content_hash"]),
            asserted_by=BrokerPortfolioAccountBindingActor(
                actor_id=_string(actor["actor_id"]),
                user_id=_positive_integer(actor["user_id"]),
                role=_string(actor["role"]),
                kind=_string(actor["kind"]),
                is_staff=_boolean(actor["is_staff"]),
            ),
            issued_at=_datetime(data["issued_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_binding_hash=(None if supersedes is None else _string(supersedes)),
            permission=_string(data["permission"]),
            blocker_codes=_string_tuple(data["blocker_codes"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerPortfolioAccountBindingCodecError, TypeError, ValueError) as error:
        raise BrokerPortfolioAccountBindingCodecError("binding is invalid") from error
    if payload != encode_broker_portfolio_account_binding(value):
        raise BrokerPortfolioAccountBindingCodecError("binding is non-canonical")
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerPortfolioAccountBindingCodecError("binding payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError("expected positive integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("expected boolean")
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
    "BrokerPortfolioAccountBindingCodecError",
    "decode_broker_portfolio_account_binding",
    "encode_broker_portfolio_account_binding",
]
