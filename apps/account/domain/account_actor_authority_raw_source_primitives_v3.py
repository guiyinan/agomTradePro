"""Shared pure-Domain primitives for Account actor-authority raw sources v3."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER = "account"
ACCOUNT_AUTHORITY_RAW_SOURCE_PERMISSION = "attestation_only"
ACCOUNT_AUTHORITY_RAW_SOURCE_STATUS = "inactive"
ACCOUNT_AUTHORITY_RAW_SOURCE_MUST_NOT_EXECUTE = True
ACCOUNT_AUTHORITY_RAW_SOURCE_EXECUTION_ALLOWED = False


def _token(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an exact timezone-aware datetime")
    return value


def canonical_utc_z(value: datetime) -> str:
    """Return one exact aware datetime in canonical UTC microsecond Z form."""

    return (
        _aware(value, "value")
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def domain_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one exact mapping under an explicit bounded domain separator."""

    _token(domain, "domain")
    if type(payload) is not dict:
        raise TypeError("payload must be an exact dictionary")
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountAuthorityRawSourceIdentityV3:
    """Identify one immutable version of an Account-owned raw authority source."""

    source_id: str
    source_version: str

    def __post_init__(self) -> None:
        """Validate the exact canonical source identity."""

        _token(self.source_id, "source_id")
        _token(self.source_version, "source_version")


@dataclass(frozen=True, slots=True)
class AccountAuthorityRawSourceClockV3:
    """Separate source observation, Account knowledge, and validity clocks."""

    observed_at: datetime
    recorded_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Require an aware non-future observation and a positive validity window."""

        observed_at = _aware(self.observed_at, "observed_at")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if not observed_at <= recorded_at < valid_until:
            raise ValueError("raw authority source clock sequence is invalid")


@dataclass(frozen=True, slots=True)
class AccountAuthorityRawSourceChainV3:
    """Carry exactly one candidate-independent root or predecessor anchor."""

    root_claim_hash: str | None = None
    supersedes_content_hash: str | None = None

    def __post_init__(self) -> None:
        """Validate the root/predecessor XOR and exact digest shapes."""

        is_root = self.root_claim_hash is not None
        has_predecessor = self.supersedes_content_hash is not None
        if is_root == has_predecessor:
            raise ValueError("exactly one root claim or predecessor is required")
        if is_root:
            _digest(self.root_claim_hash, "root_claim_hash")
        else:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")


def validate_account_authority_raw_source_fixed_header_v3(
    *,
    owner: str,
    artifact_type: str,
    schema: str,
    permission: str,
    status: str,
    must_not_execute: bool,
    execution_allowed: bool,
    expected_artifact_type: str,
    expected_schema: str,
) -> None:
    """Validate one concrete raw source's fixed inactive authority boundary."""

    _token(expected_artifact_type, "expected_artifact_type")
    _token(expected_schema, "expected_schema")
    if type(must_not_execute) is not bool:
        raise TypeError("must_not_execute must be an exact boolean")
    if type(execution_allowed) is not bool:
        raise TypeError("execution_allowed must be an exact boolean")
    if (
        owner,
        artifact_type,
        schema,
        permission,
        status,
        must_not_execute,
        execution_allowed,
    ) != (
        ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER,
        expected_artifact_type,
        expected_schema,
        ACCOUNT_AUTHORITY_RAW_SOURCE_PERMISSION,
        ACCOUNT_AUTHORITY_RAW_SOURCE_STATUS,
        ACCOUNT_AUTHORITY_RAW_SOURCE_MUST_NOT_EXECUTE,
        ACCOUNT_AUTHORITY_RAW_SOURCE_EXECUTION_ALLOWED,
    ):
        raise ValueError("raw authority source fixed semantics are invalid")


__all__ = [
    "ACCOUNT_AUTHORITY_RAW_SOURCE_EXECUTION_ALLOWED",
    "ACCOUNT_AUTHORITY_RAW_SOURCE_MUST_NOT_EXECUTE",
    "ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER",
    "ACCOUNT_AUTHORITY_RAW_SOURCE_PERMISSION",
    "ACCOUNT_AUTHORITY_RAW_SOURCE_STATUS",
    "AccountAuthorityRawSourceChainV3",
    "AccountAuthorityRawSourceClockV3",
    "AccountAuthorityRawSourceIdentityV3",
    "canonical_utc_z",
    "domain_hash",
    "validate_account_authority_raw_source_fixed_header_v3",
]
