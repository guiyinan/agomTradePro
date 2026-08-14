"""Strict canonical codec for actor-bound Account identity snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.account_identity_snapshot import (
    AccountIdentitySnapshotActor,
    PersistedAccountIdentitySnapshot,
)
from apps.account.domain.account_identity_snapshot import AccountIdentitySnapshot


class AccountIdentitySnapshotCodecError(ValueError):
    """A stored Account identity record is malformed or non-canonical."""


def encode_account_identity_snapshot_record(
    value: PersistedAccountIdentitySnapshot,
) -> dict[str, object]:
    """Encode one complete snapshot and its server-authenticated actor."""

    snapshot_payload = value.snapshot.to_payload()
    snapshot = {
        key: item
        for key, item in snapshot_payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }
    actor = value.issued_by
    return {
        "snapshot": snapshot,
        "issued_by": {
            "actor_id": actor.actor_id,
            "user_id": actor.user_id,
            "role": actor.role,
            "kind": actor.kind,
            "is_staff": actor.is_staff,
        },
    }


def decode_account_identity_snapshot_record(
    payload: object,
) -> PersistedAccountIdentitySnapshot:
    """Restore and revalidate one exact actor-bound identity record."""

    data = _mapping(payload, {"snapshot", "issued_by"})
    try:
        record = PersistedAccountIdentitySnapshot(
            snapshot=_snapshot(data["snapshot"]),
            issued_by=_actor(data["issued_by"]),
        )
    except (AccountIdentitySnapshotCodecError, TypeError, ValueError) as error:
        raise AccountIdentitySnapshotCodecError(
            "account identity snapshot record is invalid"
        ) from error
    if payload != encode_account_identity_snapshot_record(record):
        raise AccountIdentitySnapshotCodecError("account identity snapshot record is non-canonical")
    return record


def _snapshot(payload: object) -> AccountIdentitySnapshot:
    data = _mapping(
        payload,
        {
            "owner",
            "artifact_type",
            "schema",
            "source_id",
            "source_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "underlying_unified_account_id",
            "owner_user_id",
            "account_type",
            "is_active",
            "provenance_kind",
            "legacy_default_user_assignment",
            "underlying_source_id",
            "underlying_source_version",
            "underlying_source_content_hash",
            "reclaim_receipt_owner",
            "reclaim_receipt_artifact_type",
            "reclaim_receipt_id",
            "reclaim_receipt_version",
            "reclaim_receipt_content_hash",
            "underlying_source_recorded_at",
            "underlying_source_valid_until",
            "ttl_valid_until",
            "issued_at",
            "recorded_at",
            "valid_until",
            "supersedes_content_hash",
            "permission",
            "status",
            "blocker_codes",
            "identity_hash",
            "content_hash",
        },
    )
    return AccountIdentitySnapshot(
        owner=_string(data["owner"]),
        artifact_type=_string(data["artifact_type"]),
        schema=_string(data["schema"]),
        source_id=_string(data["source_id"]),
        source_version=_string(data["source_version"]),
        account_namespace=_string(data["account_namespace"]),
        account_id=_string(data["account_id"]),
        underlying_unified_account_namespace=_string(data["underlying_unified_account_namespace"]),
        underlying_unified_account_id=_positive_integer(data["underlying_unified_account_id"]),
        owner_user_id=_positive_integer(data["owner_user_id"]),
        account_type=_string(data["account_type"]),
        is_active=_boolean(data["is_active"]),
        provenance_kind=_string(data["provenance_kind"]),
        legacy_default_user_assignment=_boolean(data["legacy_default_user_assignment"]),
        underlying_source_id=_string(data["underlying_source_id"]),
        underlying_source_version=_string(data["underlying_source_version"]),
        underlying_source_content_hash=_string(data["underlying_source_content_hash"]),
        reclaim_receipt_owner=_optional_string(data["reclaim_receipt_owner"]),
        reclaim_receipt_artifact_type=_optional_string(data["reclaim_receipt_artifact_type"]),
        reclaim_receipt_id=_optional_string(data["reclaim_receipt_id"]),
        reclaim_receipt_version=_optional_string(data["reclaim_receipt_version"]),
        reclaim_receipt_content_hash=_optional_string(data["reclaim_receipt_content_hash"]),
        underlying_source_recorded_at=_datetime(data["underlying_source_recorded_at"]),
        underlying_source_valid_until=_datetime(data["underlying_source_valid_until"]),
        ttl_valid_until=_datetime(data["ttl_valid_until"]),
        issued_at=_datetime(data["issued_at"]),
        recorded_at=_datetime(data["recorded_at"]),
        valid_until=_datetime(data["valid_until"]),
        supersedes_content_hash=_optional_string(data["supersedes_content_hash"]),
        permission=_string(data["permission"]),
        status=_string(data["status"]),
        blocker_codes=_string_tuple(data["blocker_codes"]),
        identity_hash=_string(data["identity_hash"]),
        content_hash=_string(data["content_hash"]),
    )


def _actor(payload: object) -> AccountIdentitySnapshotActor:
    data = _mapping(payload, {"actor_id", "user_id", "role", "kind", "is_staff"})
    return AccountIdentitySnapshotActor(
        actor_id=_string(data["actor_id"]),
        user_id=_positive_integer(data["user_id"]),
        role=_string(data["role"]),
        kind=_string(data["kind"]),
        is_staff=_boolean(data["is_staff"]),
    )


def _mapping(payload: object, keys: set[str]) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != keys:
        raise AccountIdentitySnapshotCodecError("identity record payload shape is invalid")
    return cast(dict[str, object], payload)


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("expected string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


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
    "AccountIdentitySnapshotCodecError",
    "decode_account_identity_snapshot_record",
    "encode_account_identity_snapshot_record",
]
