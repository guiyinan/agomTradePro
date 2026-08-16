"""Strict canonical codec for Account actor-authority source v3 evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_owner_assignment_actor_authority_source_v3 import (
    AccountOwnerAssignmentActorAuthoritySourceV3,
)


class AccountOwnerAssignmentActorAuthoritySourceV3CodecError(ValueError):
    """An authority-source payload is malformed, substituted, or non-canonical."""


def encode_account_owner_assignment_actor_authority_source_v3(
    value: AccountOwnerAssignmentActorAuthoritySourceV3,
) -> dict[str, object]:
    """Encode one complete source including all Domain hashes and seals."""

    if type(value) is not AccountOwnerAssignmentActorAuthoritySourceV3:
        raise TypeError("value must be an exact actor authority source v3")
    value.__post_init__()
    return value.to_payload()


def decode_account_owner_assignment_actor_authority_source_v3(
    payload: object,
) -> AccountOwnerAssignmentActorAuthoritySourceV3:
    """Restore and Domain-revalidate one exact canonical source payload."""

    if type(payload) is not dict:
        raise AccountOwnerAssignmentActorAuthoritySourceV3CodecError(
            "actor authority source must be an exact mapping"
        )
    data = cast(dict[object, object], payload)
    if set(data) != _KEYS or any(type(key) is not str for key in data):
        raise AccountOwnerAssignmentActorAuthoritySourceV3CodecError(
            "actor authority source has a non-canonical shape"
        )
    try:
        values = cast(dict[str, object], data)
        source = AccountOwnerAssignmentActorAuthoritySourceV3(
            source_id=_string(values["source_id"]),
            source_version=_string(values["source_version"]),
            principal_id=_string(values["principal_id"]),
            user_id=_integer(values["user_id"]),
            authentication_context_id=_string(values["authentication_context_id"]),
            authentication_context_version=_string(values["authentication_context_version"]),
            authentication_context_identity_hash=_string(
                values["authentication_context_identity_hash"]
            ),
            authentication_context_content_hash=_string(
                values["authentication_context_content_hash"]
            ),
            user_source_id=_string(values["user_source_id"]),
            user_source_version=_string(values["user_source_version"]),
            user_source_content_hash=_string(values["user_source_content_hash"]),
            rbac_source_id=_string(values["rbac_source_id"]),
            rbac_source_version=_string(values["rbac_source_version"]),
            rbac_source_content_hash=_string(values["rbac_source_content_hash"]),
            actor_id=_string(values["actor_id"]),
            is_authenticated=_boolean(values["is_authenticated"]),
            is_active=_boolean(values["is_active"]),
            is_staff=_boolean(values["is_staff"]),
            is_superuser=_boolean(values["is_superuser"]),
            rbac_role=_string(values["rbac_role"]),
            authority_state=_string(values["authority_state"]),
            principal_authenticated_at=_utc(values["principal_authenticated_at"]),
            principal_valid_until=_utc(values["principal_valid_until"]),
            source_recorded_at=_utc(values["source_recorded_at"]),
            source_valid_until=_utc(values["source_valid_until"]),
            issued_at=_utc(values["issued_at"]),
            recorded_at=_utc(values["recorded_at"]),
            ttl_valid_until=_utc(values["ttl_valid_until"]),
            valid_until=_utc(values["valid_until"]),
            root_claim_hash=_optional_string(values["root_claim_hash"]),
            supersedes_content_hash=_optional_string(values["supersedes_content_hash"]),
            identity_hash=_string(values["identity_hash"]),
            principal_seal=_string(values["principal_seal"]),
            authentication_context_seal=_string(values["authentication_context_seal"]),
            user_seal=_string(values["user_seal"]),
            rbac_seal=_string(values["rbac_seal"]),
            facts_seal=_string(values["facts_seal"]),
            clock_seal=_string(values["clock_seal"]),
            chain_seal=_string(values["chain_seal"]),
            fixed_authority_seal=_string(values["fixed_authority_seal"]),
            record_seal=_string(values["record_seal"]),
            content_hash=_string(values["content_hash"]),
            owner=_string(values["owner"]),
            artifact_type=_string(values["artifact_type"]),
            schema=_string(values["schema"]),
            permission=_string(values["permission"]),
            status=_string(values["status"]),
            must_not_execute=_boolean(values["must_not_execute"]),
            execution_allowed=_boolean(values["execution_allowed"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AccountOwnerAssignmentActorAuthoritySourceV3CodecError(
            "actor authority source is invalid"
        ) from error
    if encode_account_owner_assignment_actor_authority_source_v3(source) != payload:
        raise AccountOwnerAssignmentActorAuthoritySourceV3CodecError(
            "actor authority source is not canonical"
        )
    return source


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("value must be an exact string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise TypeError("value must be an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise TypeError("value must be an exact boolean")
    return value


def _utc(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z") or "." not in text:
        raise ValueError("datetime must use canonical UTC-Z microseconds")
    try:
        parsed = datetime.fromisoformat(f"{text[:-1]}+00:00")
    except ValueError as error:
        raise ValueError("datetime is invalid") from error
    if parsed.tzinfo != UTC or _utc_text(parsed) != text:
        raise ValueError("datetime is not canonical UTC-Z")
    return parsed


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


_KEYS = {
    "source_id",
    "source_version",
    "principal_id",
    "user_id",
    "authentication_context_id",
    "authentication_context_version",
    "authentication_context_identity_hash",
    "authentication_context_content_hash",
    "user_source_id",
    "user_source_version",
    "user_source_content_hash",
    "rbac_source_id",
    "rbac_source_version",
    "rbac_source_content_hash",
    "actor_id",
    "is_authenticated",
    "is_active",
    "is_staff",
    "is_superuser",
    "rbac_role",
    "authority_state",
    "principal_authenticated_at",
    "principal_valid_until",
    "source_recorded_at",
    "source_valid_until",
    "issued_at",
    "recorded_at",
    "ttl_valid_until",
    "valid_until",
    "root_claim_hash",
    "supersedes_content_hash",
    "identity_hash",
    "principal_seal",
    "authentication_context_seal",
    "user_seal",
    "rbac_seal",
    "facts_seal",
    "clock_seal",
    "chain_seal",
    "fixed_authority_seal",
    "record_seal",
    "content_hash",
    "owner",
    "artifact_type",
    "schema",
    "permission",
    "status",
    "must_not_execute",
    "execution_allowed",
}


__all__ = [
    "AccountOwnerAssignmentActorAuthoritySourceV3CodecError",
    "decode_account_owner_assignment_actor_authority_source_v3",
    "encode_account_owner_assignment_actor_authority_source_v3",
]
