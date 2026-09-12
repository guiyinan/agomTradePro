"""Strict persistence boundary for source-bound single-owner policy snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.single_owner_authority_policy_v1 import SingleOwnerAuthorityPolicyV1


class SingleOwnerAuthorityPolicyV1CodecError(ValueError):
    """A stored policy contains malformed or noncanonical facts or seals."""


_KEYS = {
    "policy_id",
    "policy_version",
    "tenant_id",
    "owner_id",
    "account_namespace",
    "account_id",
    "owner_user_id",
    "authorization_content_hash",
    "observed_at",
    "valid_from",
    "valid_until",
    "status",
    "identity_hash",
    "content_hash",
    "schema",
    "artifact_type",
    "mode",
}


def _string(value: object) -> str:
    if type(value) is not str:
        raise SingleOwnerAuthorityPolicyV1CodecError("policy field requires an exact string")
    return value


def _integer(value: object) -> int:
    if type(value) is not int:
        raise SingleOwnerAuthorityPolicyV1CodecError("owner_user_id requires an exact integer")
    return value


def _seal(value: object) -> str:
    text = _string(value)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise SingleOwnerAuthorityPolicyV1CodecError("stored policy must contain its complete seal")
    return text


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise SingleOwnerAuthorityPolicyV1CodecError("policy clock must use canonical UTC Z form")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise SingleOwnerAuthorityPolicyV1CodecError("invalid policy clock") from error
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != text:
        raise SingleOwnerAuthorityPolicyV1CodecError("noncanonical policy clock")
    return parsed


def encode_single_owner_authority_policy_v1(
    policy: SingleOwnerAuthorityPolicyV1,
) -> dict[str, object]:
    """Encode exact policy facts without inferring currentness or authentication."""

    if type(policy) is not SingleOwnerAuthorityPolicyV1:
        raise SingleOwnerAuthorityPolicyV1CodecError("policy must have its exact Domain type")
    try:
        _seal(policy.identity_hash)
        _seal(policy.content_hash)
        return policy.to_payload()
    except (TypeError, ValueError) as error:
        raise SingleOwnerAuthorityPolicyV1CodecError("policy cannot be encoded") from error


def decode_single_owner_authority_policy_v1(payload: object) -> SingleOwnerAuthorityPolicyV1:
    """Validate the closed JSON shape, exact types and source-bound canonical seals."""

    if type(payload) is not dict:
        raise SingleOwnerAuthorityPolicyV1CodecError("policy must be an exact mapping")
    data = cast(dict[str, object], payload)
    if any(type(key) is not str for key in data) or set(data) != _KEYS:
        raise SingleOwnerAuthorityPolicyV1CodecError("policy payload has an invalid shape")
    try:
        policy = SingleOwnerAuthorityPolicyV1(
            policy_id=_string(data["policy_id"]),
            policy_version=_string(data["policy_version"]),
            tenant_id=_string(data["tenant_id"]),
            owner_id=_string(data["owner_id"]),
            account_namespace=_string(data["account_namespace"]),
            account_id=_string(data["account_id"]),
            owner_user_id=_integer(data["owner_user_id"]),
            authorization_content_hash=_seal(data["authorization_content_hash"]),
            observed_at=_datetime(data["observed_at"]),
            valid_from=_datetime(data["valid_from"]),
            valid_until=_datetime(data["valid_until"]),
            status=_string(data["status"]),
            identity_hash=_seal(data["identity_hash"]),
            content_hash=_seal(data["content_hash"]),
            schema=_string(data["schema"]),
            artifact_type=_string(data["artifact_type"]),
            mode=_string(data["mode"]),
        )
        if policy.to_payload() != data:
            raise SingleOwnerAuthorityPolicyV1CodecError("policy payload is not canonical")
    except (TypeError, ValueError) as error:
        raise SingleOwnerAuthorityPolicyV1CodecError("invalid sealed policy payload") from error
    return policy
