"""Pure Account-owned raw Django-user authority source v3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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

ARTIFACT_TYPE = "account_user_authority_source_v3"
SCHEMA = "account.user_authority_source.v3"
AUTHORITY_STATES = frozenset({"current", "deactivated"})
TERMINAL_STATES = frozenset({"deactivated"})


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


@dataclass(frozen=True, slots=True)
class AccountUserAuthoritySourceV3:
    """Immutable inactive attestation of one exact Django user authority version."""

    identity: AccountAuthorityRawSourceIdentityV3
    clock: AccountAuthorityRawSourceClockV3
    chain: AccountAuthorityRawSourceChainV3
    user_id: int
    actor_id: str
    is_active: bool
    is_staff: bool
    is_superuser: bool
    authority_state: str
    identity_hash: str = ""
    user_seal: str = ""
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
        """Validate nested primitives, facts, chain root, and every canonical seal."""

        if type(self.identity) is not AccountAuthorityRawSourceIdentityV3:
            raise TypeError("identity must be an exact raw-source identity v3")
        if type(self.clock) is not AccountAuthorityRawSourceClockV3:
            raise TypeError("clock must be an exact raw-source clock v3")
        if type(self.chain) is not AccountAuthorityRawSourceChainV3:
            raise TypeError("chain must be an exact raw-source chain v3")
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
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _token(self.actor_id, "actor_id")
        for name in ("is_active", "is_staff", "is_superuser"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        _token(self.authority_state, "authority_state")
        if self.authority_state not in AUTHORITY_STATES:
            raise ValueError("authority_state is invalid")
        if self.is_active != (self.authority_state == "current"):
            raise ValueError("authority_state and is_active disagree")
        if self.chain.root_claim_hash is not None:
            expected_root = root_claim_hash_for_account_user_authority_source_v3(
                source_id=self.identity.source_id,
                user_id=self.user_id,
                actor_id=self.actor_id,
            )
            if self.chain.root_claim_hash != expected_root:
                raise ValueError("root_claim_hash is invalid")
        self._seal("identity_hash", self._identity_payload())
        self._seal("user_seal", self._user_payload())
        self._seal("facts_seal", self._facts_payload())
        self._seal("clock_seal", self._clock_payload())
        self._seal("chain_seal", self._chain_payload())
        self._seal("fixed_authority_seal", self._fixed_payload())
        self._seal("record_seal", self._record_payload())
        self._seal("content_hash", self._content_payload())

    def _seal(self, name: str, payload: dict[str, object]) -> None:
        expected = domain_hash(f"account-user-authority-v3/{name}", payload)
        observed = getattr(self, name)
        if observed == "":
            object.__setattr__(self, name, expected)
        elif _digest(observed, name) != expected:
            raise ValueError(f"{name} is invalid")

    def _identity_payload(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "artifact_type": self.artifact_type,
            "owner": self.owner,
            "schema": self.schema,
            "source_id": self.identity.source_id,
            "source_version": self.identity.source_version,
            "user_id": self.user_id,
        }

    def _user_payload(self) -> dict[str, object]:
        return {"actor_id": self.actor_id, "user_id": self.user_id}

    def _facts_payload(self) -> dict[str, object]:
        return {
            "authority_state": self.authority_state,
            "is_active": self.is_active,
            "is_staff": self.is_staff,
            "is_superuser": self.is_superuser,
        }

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
            "artifact_type": self.artifact_type,
            "execution_allowed": self.execution_allowed,
            "must_not_execute": self.must_not_execute,
            "owner": self.owner,
            "permission": self.permission,
            "schema": self.schema,
            "status": self.status,
        }

    def _record_payload(self) -> dict[str, object]:
        return {
            "chain_seal": self.chain_seal,
            "clock_seal": self.clock_seal,
            "facts_seal": self.facts_seal,
            "fixed_authority_seal": self.fixed_authority_seal,
            "identity_hash": self.identity_hash,
            "user_seal": self.user_seal,
        }

    def _content_payload(self) -> dict[str, object]:
        return {**self._record_payload(), "record_seal": self.record_seal}

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact historical version was recorded by the cutoff."""

        return bool(self.clock.recorded_at <= _aware(as_of, "as_of"))

    def is_temporally_current_at(self, as_of: datetime) -> bool:
        """Return temporal validity only; this method does not prove ledger headness."""

        cutoff = _aware(as_of, "as_of")
        return (
            self.authority_state == "current"
            and self.is_active
            and self.clock.recorded_at <= cutoff < self.clock.valid_until
        )

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical nested source payload."""

        return {
            "identity": {
                "source_id": self.identity.source_id,
                "source_version": self.identity.source_version,
            },
            "clock": self._clock_payload(),
            "chain": self._chain_payload(),
            "user_id": self.user_id,
            "actor_id": self.actor_id,
            "is_active": self.is_active,
            "is_staff": self.is_staff,
            "is_superuser": self.is_superuser,
            "authority_state": self.authority_state,
            "identity_hash": self.identity_hash,
            "user_seal": self.user_seal,
            "facts_seal": self.facts_seal,
            "clock_seal": self.clock_seal,
            "chain_seal": self.chain_seal,
            "fixed_authority_seal": self.fixed_authority_seal,
            "record_seal": self.record_seal,
            "content_hash": self.content_hash,
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "permission": self.permission,
            "status": self.status,
            "must_not_execute": self.must_not_execute,
            "execution_allowed": self.execution_allowed,
        }


def root_claim_hash_for_account_user_authority_source_v3(
    *, source_id: str, user_id: int, actor_id: str
) -> str:
    """Return the candidate-independent claim for one user authority chain."""

    _token(source_id, "source_id")
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id must be an exact positive integer")
    _token(actor_id, "actor_id")
    return str(
        domain_hash(
            "account-user-authority-v3/root-claim",
            {
                "actor_id": actor_id,
                "artifact_type": ARTIFACT_TYPE,
                "owner": ACCOUNT_AUTHORITY_RAW_SOURCE_OWNER,
                "schema": SCHEMA,
                "source_id": source_id,
                "user_id": user_id,
            },
        )
    )


def validate_account_user_authority_source_v3_successor(
    previous: AccountUserAuthoritySourceV3,
    successor: AccountUserAuthoritySourceV3,
) -> None:
    """Validate one exact adjacent user-authority source version."""

    if (
        type(previous) is not AccountUserAuthoritySourceV3
        or type(successor) is not AccountUserAuthoritySourceV3
    ):
        raise TypeError("user authority predecessor and successor must be exact v3 sources")
    previous.__post_init__()
    successor.__post_init__()
    if previous.authority_state in TERMINAL_STATES:
        raise ValueError("deactivated user authority cannot have a successor")
    if successor.chain.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact user-authority predecessor")
    if (
        successor.identity.source_id,
        successor.user_id,
        successor.actor_id,
    ) != (previous.identity.source_id, previous.user_id, previous.actor_id):
        raise ValueError("successor changed the user-authority chain identity")
    if successor.identity.source_version == previous.identity.source_version:
        raise ValueError("successor source_version must advance")
    if not (
        previous.clock.recorded_at < successor.clock.observed_at <= successor.clock.recorded_at
    ):
        raise ValueError("successor observation and recording clocks must advance")


__all__ = [
    "ARTIFACT_TYPE",
    "AUTHORITY_STATES",
    "AccountUserAuthoritySourceV3",
    "SCHEMA",
    "TERMINAL_STATES",
    "root_claim_hash_for_account_user_authority_source_v3",
    "validate_account_user_authority_source_v3_successor",
]
