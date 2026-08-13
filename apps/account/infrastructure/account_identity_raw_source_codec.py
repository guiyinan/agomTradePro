"""Strict canonical codec for actor-bound Account raw identity sources."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.application.account_identity_raw_source import (
    AccountIdentityRawSourceActor,
    PersistedAccountIdentityRawSource,
)
from apps.account.domain.account_identity_raw_source import AccountIdentityRawSource


class AccountIdentityRawSourceCodecError(ValueError):
    """A stored Account raw-source record is malformed or non-canonical."""


def encode_account_identity_raw_source_record(
    value: PersistedAccountIdentityRawSource,
) -> dict[str, object]:
    """Encode one complete raw source and its authenticated server actor."""

    PersistedAccountIdentityRawSource.__post_init__(value)
    payload = value.source.to_payload()
    source = {
        key: item
        for key, item in payload.items()
        if key not in {"activation_available", "must_not_execute"}
    }
    actor = value.captured_by
    return {
        "source": source,
        "captured_by": {
            "actor_id": actor.actor_id,
            "user_id": actor.user_id,
            "role": actor.role,
            "kind": actor.kind,
            "is_staff": actor.is_staff,
        },
    }


def decode_account_identity_raw_source_record(
    payload: object,
) -> PersistedAccountIdentityRawSource:
    """Decode and canonical-roundtrip-check one stored raw-source record."""

    envelope = _mapping(payload, "record")
    _exact_keys(envelope, {"source", "captured_by"}, "record")
    source_data = _mapping(envelope["source"], "source")
    actor_data = _mapping(envelope["captured_by"], "captured_by")
    _exact_keys(source_data, _SOURCE_KEYS, "source")
    _exact_keys(actor_data, _ACTOR_KEYS, "captured_by")
    try:
        source = AccountIdentityRawSource(
            source_id=_string(source_data["source_id"]),
            source_version=_string(source_data["source_version"]),
            account_namespace=_string(source_data["account_namespace"]),
            account_id=_string(source_data["account_id"]),
            underlying_unified_account_namespace=_string(
                source_data["underlying_unified_account_namespace"]
            ),
            underlying_unified_account_id=_integer(source_data["underlying_unified_account_id"]),
            owner_user_id=_optional_integer(source_data["owner_user_id"]),
            assignment_state=_string(source_data["assignment_state"]),
            assignment_evidence_owner=_optional_string(source_data["assignment_evidence_owner"]),
            assignment_evidence_artifact_type=_optional_string(
                source_data["assignment_evidence_artifact_type"]
            ),
            assignment_evidence_id=_optional_string(source_data["assignment_evidence_id"]),
            assignment_evidence_version=_optional_string(
                source_data["assignment_evidence_version"]
            ),
            assignment_evidence_content_hash=_optional_string(
                source_data["assignment_evidence_content_hash"]
            ),
            row_source_owner=_string(source_data["row_source_owner"]),
            row_source_artifact_type=_string(source_data["row_source_artifact_type"]),
            row_source_id=_string(source_data["row_source_id"]),
            row_source_version=_string(source_data["row_source_version"]),
            row_source_content_hash=_string(source_data["row_source_content_hash"]),
            observed_at=_datetime(source_data["observed_at"]),
            recorded_at=_datetime(source_data["recorded_at"]),
            row_source_valid_until=_datetime(source_data["row_source_valid_until"]),
            ttl_valid_until=_datetime(source_data["ttl_valid_until"]),
            valid_until=_datetime(source_data["valid_until"]),
            is_active=_boolean(source_data["is_active"]),
            supersedes_content_hash=_optional_string(source_data["supersedes_content_hash"]),
            identity_hash=_string(source_data["identity_hash"]),
            content_hash=_string(source_data["content_hash"]),
            owner=_string(source_data["owner"]),
            artifact_type=_string(source_data["artifact_type"]),
            schema=_string(source_data["schema"]),
            permission=_string(source_data["permission"]),
            status=_string(source_data["status"]),
            blocker_codes=_string_tuple(source_data["blocker_codes"]),
            account_type=_string(source_data["account_type"]),
        )
        actor = AccountIdentityRawSourceActor(
            actor_id=_string(actor_data["actor_id"]),
            user_id=_integer(actor_data["user_id"]),
            role=_string(actor_data["role"]),
            kind=_string(actor_data["kind"]),
            is_staff=_boolean(actor_data["is_staff"]),
        )
        record = PersistedAccountIdentityRawSource(source=source, captured_by=actor)
    except (TypeError, ValueError, KeyError) as error:
        raise AccountIdentityRawSourceCodecError("raw-source payload is invalid") from error
    if encode_account_identity_raw_source_record(record) != payload:
        raise AccountIdentityRawSourceCodecError("raw-source payload is non-canonical")
    return record


_SOURCE_KEYS = {
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
    "assignment_state",
    "assignment_evidence_owner",
    "assignment_evidence_artifact_type",
    "assignment_evidence_id",
    "assignment_evidence_version",
    "assignment_evidence_content_hash",
    "row_source_owner",
    "row_source_artifact_type",
    "row_source_id",
    "row_source_version",
    "row_source_content_hash",
    "observed_at",
    "recorded_at",
    "row_source_valid_until",
    "ttl_valid_until",
    "valid_until",
    "supersedes_content_hash",
    "permission",
    "status",
    "blocker_codes",
    "identity_hash",
    "content_hash",
}
_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountIdentityRawSourceCodecError(f"{field_name} must be an exact mapping")
    return cast(dict[str, object], value)


def _exact_keys(value: dict[str, object], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        raise AccountIdentityRawSourceCodecError(f"{field_name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountIdentityRawSourceCodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountIdentityRawSourceCodecError("expected an exact integer")
    return value


def _optional_integer(value: object) -> int | None:
    return None if value is None else _integer(value)


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountIdentityRawSourceCodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountIdentityRawSourceCodecError("datetime must use canonical UTC Z form")
    parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    if parsed.isoformat().replace("+00:00", "Z") != text:
        raise AccountIdentityRawSourceCodecError("datetime is non-canonical")
    return parsed


def _string_tuple(value: object) -> tuple[str, ...]:
    if type(value) is not list:
        raise AccountIdentityRawSourceCodecError("blocker_codes must be an exact list")
    return tuple(_string(item) for item in cast(list[object], value))


__all__ = [
    "AccountIdentityRawSourceCodecError",
    "decode_account_identity_raw_source_record",
    "encode_account_identity_raw_source_record",
]
