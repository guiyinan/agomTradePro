"""Strict canonical codecs for the owner/tenant authority v2 records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.owner_tenant_authority_v2 import (
    OwnerTenantAuthorityV2,
    OwnerTenantAuthorityV2Revocation,
)
from apps.account.infrastructure.account_owner_assignment_evidence_v4_codec import (
    decode_account_owner_assignment_evidence_v4,
    encode_account_owner_assignment_evidence_v4,
)
from apps.account.infrastructure.single_owner_authority_policy_v1_codec import (
    decode_single_owner_authority_policy_v1,
    encode_single_owner_authority_policy_v1,
)


class OwnerTenantAuthorityV2CodecError(ValueError):
    """A stored owner authority v2 value is malformed or non-canonical."""


_ACTOR_KEYS = {"actor_id", "user_id", "role", "kind", "is_staff"}
_AUTHORITY_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "authority_id",
    "authority_version",
    "assignment_identity_hash",
    "policy_identity_hash",
    "assignment",
    "policy",
    "tenant_id",
    "owner_id",
    "account_namespace",
    "account_id",
    "actor_id",
    "actor_user_id",
    "assignment_evidence_id",
    "assignment_evidence_version",
    "assignment_evidence_content_hash",
    "approved_by",
    "approved_at",
    "recorded_at",
    "valid_until",
    "permission",
    "status",
    "must_not_execute",
    "identity_hash",
    "content_hash",
    "activation_available",
}
_REVOCATION_KEYS = {
    "owner",
    "artifact_type",
    "schema",
    "authority_content_hash",
    "policy_content_hash",
    "revoked_by",
    "revoked_at",
    "recorded_at",
    "reason",
    "permission",
    "status",
    "must_not_execute",
    "identity_hash",
    "content_hash",
    "activation_available",
}
_AUTHORITY_SEAL_FIELDS = (
    "assignment_identity_hash",
    "policy_identity_hash",
    "assignment_evidence_content_hash",
    "identity_hash",
    "content_hash",
)
_REVOCATION_SEAL_FIELDS = (
    "authority_content_hash",
    "policy_content_hash",
    "identity_hash",
    "content_hash",
)


def encode_owner_tenant_authority_v2(
    value: OwnerTenantAuthorityV2,
) -> dict[str, object]:
    """Encode one complete owner authority v2 root with its nested sealed graph."""

    if type(value) is not OwnerTenantAuthorityV2:
        raise OwnerTenantAuthorityV2CodecError("value must be an exact OwnerTenantAuthorityV2")
    try:
        value.__post_init__()
        payload = value.to_payload()
        payload["assignment"] = encode_account_owner_assignment_evidence_v4(value.assignment)
        payload["policy"] = encode_single_owner_authority_policy_v1(value.policy)
        _validate_authority_payload(payload)
        return payload
    except OwnerTenantAuthorityV2CodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV2CodecError(
            "owner tenant authority v2 cannot be encoded"
        ) from error


def decode_owner_tenant_authority_v2(
    payload: object,
) -> OwnerTenantAuthorityV2:
    """Decode one exact v2 root and require complete canonical roundtrip."""

    data = _mapping(payload, "authority")
    _keys(data, _AUTHORITY_KEYS, "authority")
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    try:
        assignment = decode_account_owner_assignment_evidence_v4(data["assignment"])
        policy = decode_single_owner_authority_policy_v1(data["policy"])
        authority = OwnerTenantAuthorityV2(
            authority_id=_text(data["authority_id"], "authority_id"),
            authority_version=_text(data["authority_version"], "authority_version"),
            assignment=assignment,
            policy=policy,
            approved_by=_actor(data["approved_by"], "approved_by"),
            approved_at=_clock(data["approved_at"], "approved_at"),
            recorded_at=_clock(data["recorded_at"], "recorded_at"),
            valid_until=_clock(data["valid_until"], "valid_until"),
            status=_text(data["status"], "status"),
            identity_hash=_seal(data["identity_hash"], "identity_hash"),
            content_hash=_seal(data["content_hash"], "content_hash"),
            owner=_text(data["owner"], "owner"),
            artifact_type=_text(data["artifact_type"], "artifact_type"),
            schema=_text(data["schema"], "schema"),
            permission=_text(data["permission"], "permission"),
        )
        _validate_authority_payload(data)
        if encode_owner_tenant_authority_v2(authority) != data:
            raise OwnerTenantAuthorityV2CodecError(
                "owner tenant authority v2 payload is non-canonical"
            )
    except OwnerTenantAuthorityV2CodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV2CodecError(
            "owner tenant authority v2 payload is invalid"
        ) from error
    return authority


def encode_owner_tenant_authority_v2_revocation(
    value: OwnerTenantAuthorityV2Revocation,
) -> dict[str, object]:
    """Encode one complete immutable owner authority v2 revocation event."""

    if type(value) is not OwnerTenantAuthorityV2Revocation:
        raise OwnerTenantAuthorityV2CodecError(
            "value must be an exact OwnerTenantAuthorityV2Revocation"
        )
    try:
        value.__post_init__()
        payload = value.to_payload()
        _validate_revocation_payload(payload)
        return payload
    except OwnerTenantAuthorityV2CodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV2CodecError(
            "owner tenant authority v2 revocation cannot be encoded"
        ) from error


def decode_owner_tenant_authority_v2_revocation(
    payload: object,
) -> OwnerTenantAuthorityV2Revocation:
    """Decode one exact v2 revocation and require complete canonical roundtrip."""

    data = _mapping(payload, "revocation")
    _keys(data, _REVOCATION_KEYS, "revocation")
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")
    try:
        revocation = OwnerTenantAuthorityV2Revocation(
            authority_content_hash=_seal(data["authority_content_hash"], "authority_content_hash"),
            policy_content_hash=_seal(data["policy_content_hash"], "policy_content_hash"),
            revoked_by=_actor(data["revoked_by"], "revoked_by"),
            revoked_at=_clock(data["revoked_at"], "revoked_at"),
            recorded_at=_clock(data["recorded_at"], "recorded_at"),
            reason=_text(data["reason"], "reason"),
            identity_hash=_seal(data["identity_hash"], "identity_hash"),
            content_hash=_seal(data["content_hash"], "content_hash"),
            owner=_text(data["owner"], "owner"),
            artifact_type=_text(data["artifact_type"], "artifact_type"),
            schema=_text(data["schema"], "schema"),
            permission=_text(data["permission"], "permission"),
            status=_text(data["status"], "status"),
        )
        _validate_revocation_payload(data)
        if encode_owner_tenant_authority_v2_revocation(revocation) != data:
            raise OwnerTenantAuthorityV2CodecError(
                "owner tenant authority v2 revocation payload is non-canonical"
            )
    except OwnerTenantAuthorityV2CodecError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise OwnerTenantAuthorityV2CodecError(
            "owner tenant authority v2 revocation payload is invalid"
        ) from error
    return revocation


def _mapping(value: object, name: str) -> dict[str, object]:
    """Require an exact string-keyed JSON object."""

    if type(value) is not dict:
        raise OwnerTenantAuthorityV2CodecError(f"{name} must be an exact mapping")
    data = cast(dict[str, object], value)
    if any(type(key) is not str for key in data):
        raise OwnerTenantAuthorityV2CodecError(f"{name} keys must be exact strings")
    return data


def _keys(value: dict[str, object], expected: set[str], name: str) -> None:
    """Require a closed-world key set at one payload level."""

    if set(value) != expected:
        raise OwnerTenantAuthorityV2CodecError(f"{name} has an invalid canonical shape")


def _text(value: object, name: str) -> str:
    """Require one exact string scalar."""

    if type(value) is not str:
        raise OwnerTenantAuthorityV2CodecError(f"{name} must be an exact string")
    return value


def _integer(value: object, name: str) -> int:
    """Require one exact integer scalar and reject boolean substitutions."""

    if type(value) is not int:
        raise OwnerTenantAuthorityV2CodecError(f"{name} must be an exact integer")
    return value


def _boolean(value: object, name: str) -> bool:
    """Require one exact boolean scalar and reject integer truthiness."""

    if type(value) is not bool:
        raise OwnerTenantAuthorityV2CodecError(f"{name} must be an exact boolean")
    return value


def _fixed_boolean(value: object, expected: bool, name: str) -> None:
    """Require one execution flag to retain its fixed Domain value."""

    if _boolean(value, name) is not expected:
        raise OwnerTenantAuthorityV2CodecError(f"{name} is fixed")


def _seal(value: object, name: str) -> str:
    """Require one non-empty lowercase SHA-256 digest."""

    text = _text(value, name)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise OwnerTenantAuthorityV2CodecError(f"{name} must be a full lowercase SHA-256 seal")
    return text


def _clock(value: object, name: str) -> datetime:
    """Decode only canonical UTC ``Z`` text with explicit microseconds."""

    text = _text(value, name)
    if not text.endswith("Z"):
        raise OwnerTenantAuthorityV2CodecError(f"{name} must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise OwnerTenantAuthorityV2CodecError(f"{name} is invalid") from error
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != text:
        raise OwnerTenantAuthorityV2CodecError(f"{name} must include canonical UTC microseconds")
    return parsed


def _actor(value: object, name: str) -> AccountOwnerAssignmentActor:
    """Decode and Domain-validate one exact owner actor mapping."""

    data = _mapping(value, name)
    _keys(data, _ACTOR_KEYS, name)
    return AccountOwnerAssignmentActor(
        actor_id=_text(data["actor_id"], f"{name}.actor_id"),
        user_id=_integer(data["user_id"], f"{name}.user_id"),
        role=_text(data["role"], f"{name}.role"),
        kind=_text(data["kind"], f"{name}.kind"),
        is_staff=_boolean(data["is_staff"], f"{name}.is_staff"),
    )


def _validate_authority_payload(data: dict[str, object]) -> None:
    """Validate every authority scalar before or after Domain reconstruction."""

    _keys(data, _AUTHORITY_KEYS, "authority")
    for field_name in _AUTHORITY_SEAL_FIELDS:
        _seal(data[field_name], field_name)
    for field_name in (
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
        "assignment_evidence_id",
        "assignment_evidence_version",
        "permission",
        "status",
    ):
        _text(data[field_name], field_name)
    _integer(data["actor_user_id"], "actor_user_id")
    _actor(data["approved_by"], "approved_by")
    for field_name in ("approved_at", "recorded_at", "valid_until"):
        _clock(data[field_name], field_name)
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")


def _validate_revocation_payload(data: dict[str, object]) -> None:
    """Validate every revocation scalar before or after Domain reconstruction."""

    _keys(data, _REVOCATION_KEYS, "revocation")
    for field_name in _REVOCATION_SEAL_FIELDS:
        _seal(data[field_name], field_name)
    for field_name in ("owner", "artifact_type", "schema", "reason", "permission", "status"):
        _text(data[field_name], field_name)
    _actor(data["revoked_by"], "revoked_by")
    for field_name in ("revoked_at", "recorded_at"):
        _clock(data[field_name], field_name)
    _fixed_boolean(data["activation_available"], False, "activation_available")
    _fixed_boolean(data["must_not_execute"], True, "must_not_execute")


__all__ = [
    "OwnerTenantAuthorityV2CodecError",
    "decode_owner_tenant_authority_v2",
    "decode_owner_tenant_authority_v2_revocation",
    "encode_owner_tenant_authority_v2",
    "encode_owner_tenant_authority_v2_revocation",
]
