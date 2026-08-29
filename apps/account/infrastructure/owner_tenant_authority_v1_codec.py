"""Strict canonical codec for owner/tenant authority v1."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.owner_tenant_authority_v1 import OwnerTenantAuthorityV1


class OwnerTenantAuthorityV1CodecError(ValueError):
    """An authority payload is malformed, substituted, or non-canonical."""


_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "authority_id",
    "authority_version",
    "tenant_id",
    "owner_id",
    "account_namespace",
    "account_id",
    "actor_id",
    "actor_user_id",
    "assignment_evidence_id",
    "assignment_evidence_version",
    "assignment_evidence_content_hash",
    "status",
    "approved_by",
    "approved_at",
    "recorded_at",
    "valid_until",
    "supersedes_content_hash",
    "permission",
    "identity_hash",
    "content_hash",
}


def encode_owner_tenant_authority_v1(
    value: OwnerTenantAuthorityV1,
) -> dict[str, object]:
    """Encode one complete authority row."""

    if type(value) is not OwnerTenantAuthorityV1:
        raise TypeError("value must be an exact OwnerTenantAuthorityV1")
    return value.to_payload()


def decode_owner_tenant_authority_v1(payload: object) -> OwnerTenantAuthorityV1:
    """Restore every field and require an exact canonical roundtrip."""

    try:
        data = _mapping(payload, "authority")
        if set(data) != _KEYS:
            raise OwnerTenantAuthorityV1CodecError("authority keys are not canonical")
        actor_data = _mapping(data["approved_by"], "approved_by")
        if set(actor_data) != {"actor_id", "user_id", "role", "kind", "is_staff"}:
            raise OwnerTenantAuthorityV1CodecError("approved_by keys are not canonical")
        predecessor = data["supersedes_content_hash"]
        value = OwnerTenantAuthorityV1(
            authority_id=_string(data["authority_id"]),
            authority_version=_string(data["authority_version"]),
            tenant_id=_string(data["tenant_id"]),
            owner_id=_string(data["owner_id"]),
            account_namespace=_string(data["account_namespace"]),
            account_id=_string(data["account_id"]),
            actor_id=_string(data["actor_id"]),
            actor_user_id=_integer(data["actor_user_id"]),
            assignment_evidence_id=_string(data["assignment_evidence_id"]),
            assignment_evidence_version=_string(data["assignment_evidence_version"]),
            assignment_evidence_content_hash=_string(data["assignment_evidence_content_hash"]),
            status=_string(data["status"]),
            approved_by=AccountOwnerAssignmentActor(
                actor_id=_string(actor_data["actor_id"]),
                user_id=_integer(actor_data["user_id"]),
                role=_string(actor_data["role"]),
                kind=_string(actor_data["kind"]),
                is_staff=_boolean(actor_data["is_staff"]),
            ),
            approved_at=_datetime(data["approved_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            supersedes_content_hash=(None if predecessor is None else _string(predecessor)),
            identity_hash=_string(data["identity_hash"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
        )
        if value.to_payload() != cast(dict[str, object], payload):
            raise OwnerTenantAuthorityV1CodecError("authority payload is not canonical")
        return value
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, OwnerTenantAuthorityV1CodecError):
            raise
        raise OwnerTenantAuthorityV1CodecError("authority payload is invalid") from error


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise OwnerTenantAuthorityV1CodecError(f"{name} must be an exact object")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    if type(value) is not str:
        raise OwnerTenantAuthorityV1CodecError("expected an exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise OwnerTenantAuthorityV1CodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise OwnerTenantAuthorityV1CodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise OwnerTenantAuthorityV1CodecError("datetime must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise OwnerTenantAuthorityV1CodecError("datetime is invalid") from error
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise OwnerTenantAuthorityV1CodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "OwnerTenantAuthorityV1CodecError",
    "decode_owner_tenant_authority_v1",
    "encode_owner_tenant_authority_v1",
]
