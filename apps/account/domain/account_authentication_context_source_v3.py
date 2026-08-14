"""Pure Account authentication-context raw source v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    ACCOUNT_AUTHORITY_RAW_SOURCE_EXECUTION_ALLOWED,
    ACCOUNT_AUTHORITY_RAW_SOURCE_MUST_NOT_EXECUTE,
    ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER,
    ACCOUNT_AUTHORITY_RAW_SOURCE_PERMISSION,
    ACCOUNT_AUTHORITY_RAW_SOURCE_STATUS,
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
    canonical_utc_z,
    domain_hash,
    validate_account_authority_raw_source_fixed_header_v3,
)

ARTIFACT_TYPE = "account_authentication_context_source_v3"
SCHEMA = "account.authentication_context_source.v3"


def _token(value: object, name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")


def _digest(value: object, name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class AccountAuthenticationContextSourceV3:
    """Secret-free immutable authentication fact for one human principal session."""

    identity: AccountAuthorityRawSourceIdentityV3
    clock: AccountAuthorityRawSourceClockV3
    chain: AccountAuthorityRawSourceChainV3
    principal_id: str
    user_id: int
    actor_id: str
    is_authenticated: bool
    authority_state: str
    authenticated_at: datetime
    identity_hash: str = ""
    principal_seal: str = ""
    facts_seal: str = ""
    clock_seal: str = ""
    chain_seal: str = ""
    fixed_authority_seal: str = ""
    record_seal: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER
    artifact_type: str = ARTIFACT_TYPE
    schema: str = SCHEMA
    permission: str = ACCOUNT_AUTHORITY_RAW_SOURCE_PERMISSION
    status: str = ACCOUNT_AUTHORITY_RAW_SOURCE_STATUS
    must_not_execute: bool = ACCOUNT_AUTHORITY_RAW_SOURCE_MUST_NOT_EXECUTE
    execution_allowed: bool = ACCOUNT_AUTHORITY_RAW_SOURCE_EXECUTION_ALLOWED

    def __post_init__(self) -> None:
        """Validate exact facts, chain, fixed semantics, and canonical seals."""

        if (
            type(self.identity) is not AccountAuthorityRawSourceIdentityV3
            or type(self.clock) is not AccountAuthorityRawSourceClockV3
            or type(self.chain) is not AccountAuthorityRawSourceChainV3
        ):
            raise TypeError("identity, clock, and chain must be exact raw-source primitives")
        self.identity.__post_init__()
        self.clock.__post_init__()
        self.chain.__post_init__()
        validate_account_authority_raw_source_fixed_header_v3(
            owner=self.owner,
            artifact_type=self.artifact_type,
            schema=self.schema,
            permission=self.permission,
            status=self.status,
            must_not_execute=self.must_not_execute,
            execution_allowed=self.execution_allowed,
            expected_artifact_type=ARTIFACT_TYPE,
            expected_schema=SCHEMA,
        )
        _token(self.principal_id, "principal_id")
        _token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        if type(self.is_authenticated) is not bool:
            raise TypeError("is_authenticated must be an exact boolean")
        if (self.authority_state, self.is_authenticated) not in {
            ("authenticated", True),
            ("revoked", False),
        }:
            raise ValueError("authentication authority facts disagree")
        if (
            type(self.authenticated_at) is not datetime
            or self.authenticated_at.tzinfo is None
            or self.authenticated_at.utcoffset() is None
            or self.authenticated_at > self.clock.observed_at
        ):
            raise ValueError("authenticated_at must be aware and no later than observed_at")
        if (
            self.chain.root_claim_hash is not None
            and self.chain.root_claim_hash
            != root_claim_hash_for_account_authentication_context_source_v3(
                source_id=self.identity.source_id,
                principal_id=self.principal_id,
                user_id=self.user_id,
                actor_id=self.actor_id,
            )
        ):
            raise ValueError("root claim does not bind the exact authentication principal")
        self._seal("identity_hash", "authentication-context-v3/identity", self._identity_payload())
        self._seal(
            "principal_seal", "authentication-context-v3/principal", self._principal_payload()
        )
        self._seal("facts_seal", "authentication-context-v3/facts", self._facts_payload())
        self._seal("clock_seal", "authentication-context-v3/clock", self._clock_payload())
        self._seal("chain_seal", "authentication-context-v3/chain", self._chain_payload())
        self._seal("fixed_authority_seal", "authentication-context-v3/fixed", self._fixed_payload())
        self._seal("record_seal", "authentication-context-v3/record", self._record_payload())
        self._seal(
            "content_hash",
            "authentication-context-v3/content",
            {**self._record_payload(), "record_seal": self.record_seal},
        )

    def _seal(self, name: str, domain: str, payload: dict[str, object]) -> None:
        expected = domain_hash(domain, payload)
        observed = getattr(self, name)
        if observed == "":
            object.__setattr__(self, name, expected)
        elif observed != expected:
            _digest(observed, name)
            raise ValueError(f"{name} is invalid")

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "source_id": self.identity.source_id,
            "source_version": self.identity.source_version,
            "principal_id": self.principal_id,
            "user_id": self.user_id,
            "actor_id": self.actor_id,
        }

    def _principal_payload(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "user_id": self.user_id,
            "actor_id": self.actor_id,
            "authenticated_at": canonical_utc_z(self.authenticated_at),
        }

    def _facts_payload(self) -> dict[str, object]:
        return {"is_authenticated": self.is_authenticated, "authority_state": self.authority_state}

    def _clock_payload(self) -> dict[str, object]:
        return {
            "observed_at": canonical_utc_z(self.clock.observed_at),
            "recorded_at": canonical_utc_z(self.clock.recorded_at),
            "valid_until": canonical_utc_z(self.clock.valid_until),
        }

    def _chain_payload(self) -> dict[str, object]:
        return {
            "root_claim_hash": self.chain.root_claim_hash,
            "supersedes_content_hash": self.chain.supersedes_content_hash,
        }

    def _fixed_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "permission": self.permission,
            "status": self.status,
            "must_not_execute": self.must_not_execute,
            "execution_allowed": self.execution_allowed,
        }

    def _record_payload(self) -> dict[str, object]:
        return {
            "identity_hash": self.identity_hash,
            "principal_seal": self.principal_seal,
            "facts_seal": self.facts_seal,
            "clock_seal": self.clock_seal,
            "chain_seal": self.chain_seal,
            "fixed_authority_seal": self.fixed_authority_seal,
        }

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return historical PIT knowability by Account recording time."""
        return cast(bool, self.clock.recorded_at <= _aware(as_of))

    def is_temporally_current_at(self, as_of: datetime) -> bool:
        """Return temporal validity only, not ledger-head currentness."""
        cutoff = _aware(as_of)
        return (
            self.authority_state == "authenticated"
            and self.is_authenticated
            and self.clock.recorded_at <= cutoff < self.clock.valid_until
        )

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical secret-free payload."""
        return {
            "identity": {
                "source_id": self.identity.source_id,
                "source_version": self.identity.source_version,
            },
            "clock": self._clock_payload(),
            "chain": self._chain_payload(),
            **self._principal_payload(),
            **self._facts_payload(),
            "identity_hash": self.identity_hash,
            "principal_seal": self.principal_seal,
            "facts_seal": self.facts_seal,
            "clock_seal": self.clock_seal,
            "chain_seal": self.chain_seal,
            "fixed_authority_seal": self.fixed_authority_seal,
            "record_seal": self.record_seal,
            "content_hash": self.content_hash,
            **self._fixed_payload(),
        }


def _aware(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value


def root_claim_hash_for_account_authentication_context_source_v3(
    *, source_id: str, principal_id: str, user_id: int, actor_id: str
) -> str:
    """Return the candidate-independent root claim for one authentication chain."""
    _token(source_id, "source_id")
    _token(principal_id, "principal_id")
    _token(actor_id, "actor_id")
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id must be an exact positive integer")
    return cast(
        str,
        domain_hash(
            "authentication-context-v3/root-claim",
            {
                "owner": ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER,
                "artifact_type": ARTIFACT_TYPE,
                "schema": SCHEMA,
                "source_id": source_id,
                "principal_id": principal_id,
                "user_id": user_id,
                "actor_id": actor_id,
            },
        ),
    )


def validate_account_authentication_context_source_v3_successor(
    previous: AccountAuthenticationContextSourceV3, successor: AccountAuthenticationContextSourceV3
) -> None:
    """Validate one adjacent same-principal authentication-context version."""
    if (
        type(previous) is not AccountAuthenticationContextSourceV3
        or type(successor) is not AccountAuthenticationContextSourceV3
    ):
        raise TypeError("previous and successor must be exact authentication sources")
    previous.__post_init__()
    successor.__post_init__()
    if previous.authority_state == "revoked":
        raise ValueError("revoked authentication is terminal")
    if successor.chain.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind exact predecessor")
    for name in ("source_id",):
        if getattr(successor.identity, name) != getattr(previous.identity, name):
            raise ValueError("successor changed source chain")
    for name in ("principal_id", "user_id", "actor_id"):
        if getattr(successor, name) != getattr(previous, name):
            raise ValueError(f"successor changed {name}")
    if successor.authenticated_at != previous.authenticated_at:
        raise ValueError("successor changed authenticated_at")
    if successor.identity.source_version == previous.identity.source_version:
        raise ValueError("source_version must advance")
    if not previous.clock.recorded_at < successor.clock.observed_at:
        raise ValueError("successor observation must follow predecessor recording")


__all__ = [
    "AccountAuthenticationContextSourceV3",
    "root_claim_hash_for_account_authentication_context_source_v3",
    "validate_account_authentication_context_source_v3_successor",
]
