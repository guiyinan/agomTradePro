"""Strict canonical codecs for authenticated owner authority v3 records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.application.account_owner_assignment_actor_authority_v3 import (
    CurrentAccountActorAuthorityV3,
)
from apps.account.application.owner_tenant_authority_v3_contracts import (
    PersistedOwnerTenantAuthorityV3,
    PersistedOwnerTenantAuthorityV3Revocation,
)
from apps.account.infrastructure.owner_tenant_authority_v3_codec import (
    decode_owner_tenant_authority_v3,
    decode_owner_tenant_authority_v3_revocation,
    encode_owner_tenant_authority_v3,
    encode_owner_tenant_authority_v3_revocation,
)


class OwnerTenantAuthorityV3RecordCodecError(ValueError):
    """A persisted authenticated owner authority v3 record is malformed."""


_AUTHENTICATION_KEYS = {
    "principal_id",
    "user_id",
    "authentication_context_hash",
    "actor_id",
    "is_authenticated",
    "is_active",
    "is_staff",
    "is_superuser",
    "rbac_role",
    "source_id",
    "source_version",
    "source_content_hash",
    "recorded_at",
    "valid_until",
}
_AUTHORITY_RECORD_KEYS = {"authority", "authentication"}
_REVOCATION_RECORD_KEYS = {"revocation", "authentication"}


def encode_owner_tenant_authority_v3_record(
    value: PersistedOwnerTenantAuthorityV3,
) -> dict[str, object]:
    """Encode one authority v3 value with its approval authentication source."""

    if type(value) is not PersistedOwnerTenantAuthorityV3:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "value must be an exact PersistedOwnerTenantAuthorityV3"
        )
    try:
        value.__post_init__()
        return {
            "authority": encode_owner_tenant_authority_v3(value.authority),
            "authentication": _authentication_payload(value.authentication),
        }
    except OwnerTenantAuthorityV3RecordCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "owner tenant authority v3 record cannot be encoded"
        ) from error


def decode_owner_tenant_authority_v3_record(
    payload: object,
) -> PersistedOwnerTenantAuthorityV3:
    """Decode one exact authenticated authority v3 envelope and roundtrip it."""

    data = _mapping(payload, _AUTHORITY_RECORD_KEYS, "record")
    try:
        value = PersistedOwnerTenantAuthorityV3(
            authority=decode_owner_tenant_authority_v3(data["authority"]),
            authentication=_decode_authentication(data["authentication"]),
        )
        if encode_owner_tenant_authority_v3_record(value) != data:
            raise OwnerTenantAuthorityV3RecordCodecError(
                "owner tenant authority v3 record is non-canonical"
            )
    except OwnerTenantAuthorityV3RecordCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "owner tenant authority v3 record is invalid"
        ) from error
    return value


def encode_owner_tenant_authority_v3_revocation_record(
    value: PersistedOwnerTenantAuthorityV3Revocation,
) -> dict[str, object]:
    """Encode one v3 revocation value with its event authentication source."""

    if type(value) is not PersistedOwnerTenantAuthorityV3Revocation:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "value must be an exact PersistedOwnerTenantAuthorityV3Revocation"
        )
    try:
        value.__post_init__()
        return {
            "revocation": encode_owner_tenant_authority_v3_revocation(value.revocation),
            "authentication": _authentication_payload(value.authentication),
        }
    except OwnerTenantAuthorityV3RecordCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "owner tenant authority v3 revocation record cannot be encoded"
        ) from error


def decode_owner_tenant_authority_v3_revocation_record(
    payload: object,
) -> PersistedOwnerTenantAuthorityV3Revocation:
    """Decode one exact authenticated revocation envelope and roundtrip it."""

    data = _mapping(payload, _REVOCATION_RECORD_KEYS, "revocation record")
    try:
        value = PersistedOwnerTenantAuthorityV3Revocation(
            revocation=decode_owner_tenant_authority_v3_revocation(data["revocation"]),
            authentication=_decode_authentication(data["authentication"]),
        )
        if encode_owner_tenant_authority_v3_revocation_record(value) != data:
            raise OwnerTenantAuthorityV3RecordCodecError(
                "owner tenant authority v3 revocation record is non-canonical"
            )
    except OwnerTenantAuthorityV3RecordCodecError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "owner tenant authority v3 revocation record is invalid"
        ) from error
    return value


def _mapping(value: object, expected: set[str], name: str) -> dict[str, object]:
    """Require one exact string-keyed JSON object with closed-world keys."""

    if type(value) is not dict:
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} must be an exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data) or set(data) != expected:
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} has an invalid canonical shape")
    return data


def _text(value: object, name: str) -> str:
    """Require one exact string scalar."""

    if type(value) is not str:
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} must be an exact string")
    return value


def _integer(value: object, name: str) -> int:
    """Require one exact integer scalar and reject boolean substitutions."""

    if type(value) is not int:
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} must be an exact integer")
    return value


def _boolean(value: object, name: str) -> bool:
    """Require one exact boolean scalar and reject integer substitutions."""

    if type(value) is not bool:
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} must be an exact boolean")
    return value


def _seal(value: object, name: str) -> str:
    """Require one non-empty lowercase SHA-256 digest."""

    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise OwnerTenantAuthorityV3RecordCodecError(
            f"{name} must be a full lowercase SHA-256 seal"
        )
    return text


def _utc_text(value: datetime, name: str) -> str:
    """Encode one exact aware datetime as canonical UTC text with microseconds."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise OwnerTenantAuthorityV3RecordCodecError(
            f"{name} must be an exact timezone-aware datetime"
        )
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clock(value: object, name: str) -> datetime:
    """Decode only canonical UTC ``Z`` text with explicit microseconds."""

    text = _text(value, name)
    if not text.endswith("Z"):
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise OwnerTenantAuthorityV3RecordCodecError(f"{name} is invalid") from error
    if _utc_text(parsed, name) != text:
        raise OwnerTenantAuthorityV3RecordCodecError(
            f"{name} must include canonical UTC microseconds"
        )
    return parsed


def _authentication_payload(
    value: CurrentAccountActorAuthorityV3,
) -> dict[str, object]:
    """Encode all fourteen authenticated source fields without dropping facts."""

    if type(value) is not CurrentAccountActorAuthorityV3:
        raise OwnerTenantAuthorityV3RecordCodecError(
            "authentication must be an exact CurrentAccountActorAuthorityV3"
        )
    value.__post_init__()
    payload = {
        "principal_id": value.principal_id,
        "user_id": value.user_id,
        "authentication_context_hash": value.authentication_context_hash,
        "actor_id": value.actor_id,
        "is_authenticated": value.is_authenticated,
        "is_active": value.is_active,
        "is_staff": value.is_staff,
        "is_superuser": value.is_superuser,
        "rbac_role": value.rbac_role,
        "source_id": value.source_id,
        "source_version": value.source_version,
        "source_content_hash": value.source_content_hash,
        "recorded_at": _utc_text(value.recorded_at, "recorded_at"),
        "valid_until": _utc_text(value.valid_until, "valid_until"),
    }
    _validate_authentication_payload(payload)
    return payload


def _decode_authentication(value: object) -> CurrentAccountActorAuthorityV3:
    """Decode and validate the complete fourteen-field authentication source."""

    data = _mapping(value, _AUTHENTICATION_KEYS, "authentication")
    _validate_authentication_payload(data)
    return CurrentAccountActorAuthorityV3(
        principal_id=_text(data["principal_id"], "principal_id"),
        user_id=_integer(data["user_id"], "user_id"),
        authentication_context_hash=_seal(
            data["authentication_context_hash"], "authentication_context_hash"
        ),
        actor_id=_text(data["actor_id"], "actor_id"),
        is_authenticated=_boolean(data["is_authenticated"], "is_authenticated"),
        is_active=_boolean(data["is_active"], "is_active"),
        is_staff=_boolean(data["is_staff"], "is_staff"),
        is_superuser=_boolean(data["is_superuser"], "is_superuser"),
        rbac_role=_text(data["rbac_role"], "rbac_role"),
        source_id=_text(data["source_id"], "source_id"),
        source_version=_text(data["source_version"], "source_version"),
        source_content_hash=_seal(data["source_content_hash"], "source_content_hash"),
        recorded_at=_clock(data["recorded_at"], "recorded_at"),
        valid_until=_clock(data["valid_until"], "valid_until"),
    )


def _validate_authentication_payload(data: dict[str, object]) -> None:
    """Validate every authentication scalar before DTO construction."""

    _mapping(data, _AUTHENTICATION_KEYS, "authentication")
    for field_name in (
        "principal_id",
        "actor_id",
        "rbac_role",
        "source_id",
        "source_version",
    ):
        _text(data[field_name], field_name)
    _integer(data["user_id"], "user_id")
    for field_name in ("authentication_context_hash", "source_content_hash"):
        _seal(data[field_name], field_name)
    for field_name in ("is_authenticated", "is_active", "is_staff", "is_superuser"):
        _boolean(data[field_name], field_name)
    for field_name in ("recorded_at", "valid_until"):
        _clock(data[field_name], field_name)


__all__ = [
    "OwnerTenantAuthorityV3RecordCodecError",
    "decode_owner_tenant_authority_v3_record",
    "decode_owner_tenant_authority_v3_revocation_record",
    "encode_owner_tenant_authority_v3_record",
    "encode_owner_tenant_authority_v3_revocation_record",
]
