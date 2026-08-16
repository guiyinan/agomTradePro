"""Strict canonical codec for Account user-authority raw source v3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
)
from apps.account.domain.account_user_authority_source_v3 import (
    AccountUserAuthoritySourceV3,
)


class AccountUserAuthoritySourceV3CodecError(ValueError):
    """A user-authority payload is malformed, substituted, or non-canonical."""


def encode_account_user_authority_source_v3(
    value: AccountUserAuthoritySourceV3,
) -> dict[str, object]:
    """Encode one complete canonical user-authority source."""

    if type(value) is not AccountUserAuthoritySourceV3:
        raise TypeError("value must be an exact account user-authority source v3")
    value.__post_init__()
    return value.to_payload()


def decode_account_user_authority_source_v3(payload: object) -> AccountUserAuthoritySourceV3:
    """Restore, Domain-revalidate, and canonical-equality-check one payload."""

    try:
        values = _mapping(payload, _KEYS, "user authority source")
        identity = _mapping(values["identity"], _IDENTITY_KEYS, "identity")
        clock = _mapping(values["clock"], _CLOCK_KEYS, "clock")
        chain = _mapping(values["chain"], _CHAIN_KEYS, "chain")
        source = AccountUserAuthoritySourceV3(
            identity=AccountAuthorityRawSourceIdentityV3(
                source_id=_string(identity["source_id"]),
                source_version=_string(identity["source_version"]),
            ),
            clock=AccountAuthorityRawSourceClockV3(
                observed_at=_utc(clock["observed_at"]),
                recorded_at=_utc(clock["recorded_at"]),
                valid_until=_utc(clock["valid_until"]),
            ),
            chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=_optional_string(chain["root_claim_hash"]),
                supersedes_content_hash=_optional_string(chain["supersedes_content_hash"]),
            ),
            user_id=_integer(values["user_id"]),
            actor_id=_string(values["actor_id"]),
            is_active=_boolean(values["is_active"]),
            is_staff=_boolean(values["is_staff"]),
            is_superuser=_boolean(values["is_superuser"]),
            authority_state=_string(values["authority_state"]),
            identity_hash=_string(values["identity_hash"]),
            user_seal=_string(values["user_seal"]),
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
        raise AccountUserAuthoritySourceV3CodecError(
            "account user-authority source is invalid"
        ) from error
    if encode_account_user_authority_source_v3(source) != payload:
        raise AccountUserAuthoritySourceV3CodecError(
            "account user-authority source is not canonical"
        )
    return source


def _mapping(value: object, keys: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise TypeError(f"{name} must be an exact mapping")
    raw = cast(dict[object, object], value)
    if set(raw) != keys or any(type(key) is not str for key in raw):
        raise ValueError(f"{name} has a non-canonical shape")
    return cast(dict[str, object], raw)


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
    if len(text) != 27 or not text.endswith("Z") or text[19] != ".":
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


_IDENTITY_KEYS = {"source_id", "source_version"}
_CLOCK_KEYS = {"observed_at", "recorded_at", "valid_until"}
_CHAIN_KEYS = {"root_claim_hash", "supersedes_content_hash"}
_KEYS = {
    "identity",
    "clock",
    "chain",
    "user_id",
    "actor_id",
    "is_active",
    "is_staff",
    "is_superuser",
    "authority_state",
    "identity_hash",
    "user_seal",
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
    "AccountUserAuthoritySourceV3CodecError",
    "decode_account_user_authority_source_v3",
    "encode_account_user_authority_source_v3",
]
