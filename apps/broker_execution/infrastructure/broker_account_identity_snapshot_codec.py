"""Strict canonical codec for Broker account identity snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.broker_execution.domain.broker_account_identity_snapshot import (
    AccountIdentitySourceRef,
    BrokerAccountIdentitySnapshot,
    KeyedBrokerAccountReferenceDigest,
)


class BrokerAccountIdentitySnapshotCodecError(ValueError):
    """A stored identity snapshot payload is malformed or non-canonical."""


def encode_broker_account_identity_snapshot(
    value: BrokerAccountIdentitySnapshot,
) -> dict[str, object]:
    """Encode one complete snapshot without derived safety flags."""

    return {
        key: item
        for key, item in value.to_payload().items()
        if key not in {"activation_available", "must_not_execute"}
    }


def decode_broker_account_identity_snapshot(payload: object) -> BrokerAccountIdentitySnapshot:
    """Restore and revalidate one complete immutable inactive snapshot."""

    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "snapshot_id",
            "snapshot_version",
            "broker_account_namespace",
            "broker_account_id",
            "owner_user_id",
            "account_type",
            "is_active",
            "account_source_ref",
            "binding_revision",
            "binding_owner_user_id",
            "binding_content_hash",
            "agent_id",
            "agent_version",
            "agent_owner_user_id",
            "agent_content_hash",
            "qmt_account_ref_digest",
            "broker_account_category",
            "issued_at",
            "recorded_at",
            "ttl_valid_until",
            "valid_until",
            "supersedes_snapshot_hash",
            "authority_scope",
            "permission",
            "identity_hash",
            "content_hash",
        },
    )
    try:
        source_data = _mapping(
            data["account_source_ref"],
            {
                "owner",
                "artifact_type",
                "source_id",
                "source_version",
                "content_hash",
                "account_namespace",
                "account_id",
                "owner_user_id",
                "account_type",
                "is_active",
                "recorded_at",
                "valid_until",
            },
        )
        digest_data = _mapping(data["qmt_account_ref_digest"], {"algorithm", "key_id", "digest"})
        supersedes = data["supersedes_snapshot_hash"]
        value = BrokerAccountIdentitySnapshot(
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            snapshot_id=_string(data["snapshot_id"]),
            snapshot_version=_string(data["snapshot_version"]),
            broker_account_namespace=_string(data["broker_account_namespace"]),
            broker_account_id=_positive_integer(data["broker_account_id"]),
            owner_user_id=_positive_integer(data["owner_user_id"]),
            account_type=_string(data["account_type"]),
            is_active=_boolean(data["is_active"]),
            account_source_ref=AccountIdentitySourceRef(
                owner=_string(source_data["owner"]),
                artifact_type=_string(source_data["artifact_type"]),
                source_id=_string(source_data["source_id"]),
                source_version=_string(source_data["source_version"]),
                content_hash=_string(source_data["content_hash"]),
                account_namespace=_string(source_data["account_namespace"]),
                account_id=_string(source_data["account_id"]),
                owner_user_id=_positive_integer(source_data["owner_user_id"]),
                account_type=_string(source_data["account_type"]),
                is_active=_boolean(source_data["is_active"]),
                recorded_at=_datetime(source_data["recorded_at"]),
                valid_until=_datetime(source_data["valid_until"]),
            ),
            binding_revision=_positive_integer(data["binding_revision"]),
            binding_owner_user_id=_positive_integer(data["binding_owner_user_id"]),
            binding_content_hash=_string(data["binding_content_hash"]),
            agent_id=_string(data["agent_id"]),
            agent_version=_string(data["agent_version"]),
            agent_owner_user_id=_positive_integer(data["agent_owner_user_id"]),
            agent_content_hash=_string(data["agent_content_hash"]),
            qmt_account_ref_digest=KeyedBrokerAccountReferenceDigest(
                algorithm=_string(digest_data["algorithm"]),
                key_id=_string(digest_data["key_id"]),
                digest=_string(digest_data["digest"]),
            ),
            broker_account_category=_string(data["broker_account_category"]),
            issued_at=_datetime(data["issued_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            ttl_valid_until=_datetime(data["ttl_valid_until"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_snapshot_hash=(None if supersedes is None else _string(supersedes)),
            authority_scope=_string(data["authority_scope"]),
            permission=_string(data["permission"]),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
        )
    except (BrokerAccountIdentitySnapshotCodecError, TypeError, ValueError) as error:
        raise BrokerAccountIdentitySnapshotCodecError(
            "Broker account identity snapshot is invalid"
        ) from error
    if payload != encode_broker_account_identity_snapshot(value):
        raise BrokerAccountIdentitySnapshotCodecError(
            "Broker account identity snapshot is non-canonical"
        )
    return value


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise BrokerAccountIdentitySnapshotCodecError("snapshot payload shape is invalid")
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


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise ValueError("datetime must use canonical UTC Z format")
    result = datetime.fromisoformat(text[:-1] + "+00:00")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return result


__all__ = [
    "BrokerAccountIdentitySnapshotCodecError",
    "decode_broker_account_identity_snapshot",
    "encode_broker_account_identity_snapshot",
]
