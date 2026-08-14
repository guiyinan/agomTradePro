"""Strict canonical codec for Account authentication-context source v3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_authentication_context_source_v3 import (
    AccountAuthenticationContextSourceV3,
)


class AccountAuthenticationContextSourceV3CodecError(ValueError):
    """An authentication-context payload is malformed or non-canonical."""


def encode_account_authentication_context_source_v3(
    value: AccountAuthenticationContextSourceV3,
) -> dict[str, object]:
    """Encode one complete Domain source without dropping nested primitives."""

    if type(value) is not AccountAuthenticationContextSourceV3:
        raise TypeError("value must be an exact authentication-context source v3")
    value.__post_init__()
    return cast(dict[str, object], value.to_payload())


def decode_account_authentication_context_source_v3(
    payload: object,
) -> AccountAuthenticationContextSourceV3:
    """Restore every exact field, Domain-revalidate, and require canonical equality."""

    data = _mapping(payload, "source")
    _keys(data, _SOURCE_KEYS, "source")
    identity_data = _mapping(data["identity"], "identity")
    clock_data = _mapping(data["clock"], "clock")
    chain_data = _mapping(data["chain"], "chain")
    _keys(identity_data, {"source_id", "source_version"}, "identity")
    _keys(clock_data, {"observed_at", "recorded_at", "valid_until"}, "clock")
    _keys(chain_data, {"root_claim_hash", "supersedes_content_hash"}, "chain")
    try:
        value = AccountAuthenticationContextSourceV3(
            identity=AccountAuthorityRawSourceIdentityV3(
                _string(identity_data["source_id"]),
                _string(identity_data["source_version"]),
            ),
            clock=AccountAuthorityRawSourceClockV3(
                _utc(clock_data["observed_at"]),
                _utc(clock_data["recorded_at"]),
                _utc(clock_data["valid_until"]),
            ),
            chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=_optional_string(chain_data["root_claim_hash"]),
                supersedes_content_hash=_optional_string(chain_data["supersedes_content_hash"]),
            ),
            principal_id=_string(data["principal_id"]),
            user_id=_integer(data["user_id"]),
            actor_id=_string(data["actor_id"]),
            is_authenticated=_boolean(data["is_authenticated"]),
            authority_state=_string(data["authority_state"]),
            authenticated_at=_utc(data["authenticated_at"]),
            identity_hash=_string(data["identity_hash"]),
            principal_seal=_string(data["principal_seal"]),
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
        raise AccountAuthenticationContextSourceV3CodecError(
            "authentication-context source is invalid"
        ) from error
    if encode_account_authentication_context_source_v3(value) != payload:
        raise AccountAuthenticationContextSourceV3CodecError(
            "authentication-context source is not canonical"
        )
    return value


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountAuthenticationContextSourceV3CodecError(f"{name} must be an exact mapping")
    raw = cast(dict[object, object], value)
    if any(type(key) is not str for key in raw):
        raise AccountAuthenticationContextSourceV3CodecError(f"{name} keys are invalid")
    return cast(dict[str, object], raw)


def _keys(data: dict[str, object], expected: set[str], name: str) -> None:
    if set(data) != expected:
        raise AccountAuthenticationContextSourceV3CodecError(f"{name} has a non-canonical shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise TypeError("value must be an exact string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


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
        raise ValueError("datetime must use UTC-Z microseconds")
    parsed = datetime.fromisoformat(f"{text[:-1]}+00:00")
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if parsed.tzinfo != UTC or canonical != text:
        raise ValueError("datetime is not canonical UTC-Z")
    return parsed


_SOURCE_KEYS = {
    "identity",
    "clock",
    "chain",
    "principal_id",
    "user_id",
    "actor_id",
    "is_authenticated",
    "authority_state",
    "authenticated_at",
    "identity_hash",
    "principal_seal",
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
    "AccountAuthenticationContextSourceV3CodecError",
    "decode_account_authentication_context_source_v3",
    "encode_account_authentication_context_source_v3",
]
