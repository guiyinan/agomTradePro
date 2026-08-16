"""Strict canonical codec for Account RBAC authority raw source v3."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
    canonical_utc_z,
)
from apps.account.domain.account_rbac_authority_source_v3 import (
    AccountRbacAuthoritySourceV3,
)


class AccountRbacAuthoritySourceV3CodecError(ValueError):
    """An RBAC authority source payload is malformed or non-canonical."""


def encode_account_rbac_authority_source_v3(
    value: AccountRbacAuthoritySourceV3,
) -> dict[str, object]:
    """Encode one exact Domain-validated RBAC authority source."""

    if type(value) is not AccountRbacAuthoritySourceV3:
        raise TypeError("value must be an exact AccountRbacAuthoritySourceV3")
    value.__post_init__()
    return value.to_payload()


def decode_account_rbac_authority_source_v3(
    payload: object,
) -> AccountRbacAuthoritySourceV3:
    """Decode, revalidate in Domain, and require exact canonical roundtrip."""

    data = _mapping(payload, "RBAC authority source")
    _keys(data, _SOURCE_KEYS, "RBAC authority source")
    identity_data = _mapping(data["identity"], "identity")
    clock_data = _mapping(data["clock"], "clock")
    chain_data = _mapping(data["chain"], "chain")
    _keys(identity_data, _IDENTITY_KEYS, "identity")
    _keys(clock_data, _CLOCK_KEYS, "clock")
    _keys(chain_data, _CHAIN_KEYS, "chain")
    try:
        value = AccountRbacAuthoritySourceV3(
            identity=AccountAuthorityRawSourceIdentityV3(
                source_id=_string(identity_data["source_id"]),
                source_version=_string(identity_data["source_version"]),
            ),
            clock=AccountAuthorityRawSourceClockV3(
                observed_at=_datetime(clock_data["observed_at"]),
                recorded_at=_datetime(clock_data["recorded_at"]),
                valid_until=_datetime(clock_data["valid_until"]),
            ),
            chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=_optional_string(chain_data["root_claim_hash"]),
                supersedes_content_hash=_optional_string(chain_data["supersedes_content_hash"]),
            ),
            user_id=_integer(data["user_id"]),
            actor_id=_string(data["actor_id"]),
            rbac_role=_string(data["rbac_role"]),
            authority_state=_string(data["authority_state"]),
            identity_hash=_string(data["identity_hash"]),
            rbac_seal=_string(data["rbac_seal"]),
            facts_seal=_string(data["facts_seal"]),
            clock_seal=_string(data["clock_seal"]),
            chain_seal=_string(data["chain_seal"]),
            fixed_authority_seal=_string(data["fixed_authority_seal"]),
            record_seal=_string(data["record_seal"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            must_not_execute=_boolean(data["must_not_execute"]),
            execution_allowed=_boolean(data["execution_allowed"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, AccountRbacAuthoritySourceV3CodecError):
            raise
        raise AccountRbacAuthoritySourceV3CodecError(
            "RBAC authority source payload is invalid"
        ) from error
    if encode_account_rbac_authority_source_v3(value) != payload:
        raise AccountRbacAuthoritySourceV3CodecError(
            "RBAC authority source payload is non-canonical"
        )
    return value


_SOURCE_KEYS = {
    "identity",
    "clock",
    "chain",
    "user_id",
    "actor_id",
    "rbac_role",
    "authority_state",
    "identity_hash",
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
_IDENTITY_KEYS = {"source_id", "source_version"}
_CLOCK_KEYS = {"observed_at", "recorded_at", "valid_until"}
_CHAIN_KEYS = {"root_claim_hash", "supersedes_content_hash"}


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountRbacAuthoritySourceV3CodecError(f"{name} must be an exact mapping")
    return cast(dict[str, object], value)


def _keys(value: dict[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise AccountRbacAuthoritySourceV3CodecError(f"{name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountRbacAuthoritySourceV3CodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountRbacAuthoritySourceV3CodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountRbacAuthoritySourceV3CodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountRbacAuthoritySourceV3CodecError(
            "datetime must use canonical UTC microsecond Z form"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountRbacAuthoritySourceV3CodecError("datetime is invalid") from error
    if canonical_utc_z(parsed) != text:
        raise AccountRbacAuthoritySourceV3CodecError("datetime is non-canonical")
    return parsed


__all__ = [
    "AccountRbacAuthoritySourceV3CodecError",
    "decode_account_rbac_authority_source_v3",
    "encode_account_rbac_authority_source_v3",
]
