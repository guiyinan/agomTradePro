"""Pure Account-owned RBAC authority source v3 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    AccountAuthorityRawSourceClockV3,
    AccountAuthorityRawSourceIdentityV3,
    canonical_utc_z,
    domain_hash,
    validate_account_authority_raw_source_fixed_header_v3,
)

ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_ARTIFACT_TYPE = "account_rbac_authority_source_v3"
ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_SCHEMA = "account.rbac_authority_source.v3"
ACCOUNT_RBAC_AUTHORITY_NAMESPACE = "account"
ACCOUNT_RBAC_AUTHORITY_ROLES = frozenset(
    {
        "admin",
        "owner",
        "analyst",
        "investment_manager",
        "trader",
        "risk",
        "read_only",
    }
)
ACCOUNT_RBAC_AUTHORITY_STATES = frozenset({"current", "revoked"})


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


@dataclass(frozen=True, slots=True)
class AccountRbacAuthoritySourceV3:
    """Seal one immutable Account RBAC role observation without execution authority."""

    identity: AccountAuthorityRawSourceIdentityV3
    clock: AccountAuthorityRawSourceClockV3
    chain: AccountAuthorityRawSourceChainV3
    user_id: int
    actor_id: str
    rbac_role: str
    authority_state: str
    identity_hash: str = ""
    rbac_seal: str = ""
    facts_seal: str = ""
    clock_seal: str = ""
    chain_seal: str = ""
    fixed_authority_seal: str = ""
    record_seal: str = ""
    content_hash: str = ""
    owner: str = "account"
    artifact_type: str = ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_ARTIFACT_TYPE
    schema: str = ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_SCHEMA
    permission: str = "attestation_only"
    status: str = "inactive"
    must_not_execute: bool = True
    execution_allowed: bool = False

    def __post_init__(self) -> None:
        """Validate nested primitives, canonical RBAC facts, chain, and seals."""

        validate_account_authority_raw_source_fixed_header_v3(
            owner=self.owner,
            artifact_type=self.artifact_type,
            schema=self.schema,
            permission=self.permission,
            status=self.status,
            must_not_execute=self.must_not_execute,
            execution_allowed=self.execution_allowed,
            expected_artifact_type=ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_ARTIFACT_TYPE,
            expected_schema=ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_SCHEMA,
        )
        if type(self.identity) is not AccountAuthorityRawSourceIdentityV3:
            raise TypeError("identity must be an exact raw source identity v3")
        if type(self.clock) is not AccountAuthorityRawSourceClockV3:
            raise TypeError("clock must be an exact raw source clock v3")
        if type(self.chain) is not AccountAuthorityRawSourceChainV3:
            raise TypeError("chain must be an exact raw source chain v3")
        self.identity.__post_init__()
        self.clock.__post_init__()
        self.chain.__post_init__()
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be an exact positive integer")
        _token(self.actor_id, "actor_id")
        _token(self.rbac_role, "rbac_role")
        if self.rbac_role not in ACCOUNT_RBAC_AUTHORITY_ROLES:
            raise ValueError("rbac_role is not a canonical Account role")
        _token(self.authority_state, "authority_state")
        if self.authority_state not in ACCOUNT_RBAC_AUTHORITY_STATES:
            raise ValueError("authority_state is invalid")
        self._validate_chain()
        self._seal("identity_hash", self._identity_payload())
        self._seal("rbac_seal", self._rbac_payload())
        self._seal("facts_seal", self._facts_payload())
        self._seal("clock_seal", self._clock_payload())
        self._seal("chain_seal", self._chain_payload())
        self._seal("fixed_authority_seal", self._fixed_payload())
        self._seal("record_seal", self._record_payload())
        self._seal("content_hash", self._content_payload())

    def _validate_chain(self) -> None:
        if self.chain.root_claim_hash is None:
            return
        expected = root_claim_hash_for_account_rbac_authority_source_v3(
            source_id=self.identity.source_id,
            user_id=self.user_id,
            actor_id=self.actor_id,
        )
        if self.chain.root_claim_hash != expected:
            raise ValueError("RBAC authority root claim is invalid")

    def _seal(self, name: str, payload: dict[str, object]) -> None:
        expected = domain_hash(f"account-rbac-authority-v3/{name}", payload)
        observed = getattr(self, name)
        if observed == "":
            object.__setattr__(self, name, expected)
        elif _digest(observed, name) != expected:
            raise ValueError(f"{name} is invalid")

    def _root_payload(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "artifact_type": self.artifact_type,
            "authority_namespace": ACCOUNT_RBAC_AUTHORITY_NAMESPACE,
            "owner": self.owner,
            "schema": self.schema,
            "source_id": self.identity.source_id,
            "user_id": self.user_id,
        }

    def _identity_payload(self) -> dict[str, object]:
        return {**self._root_payload(), "source_version": self.identity.source_version}

    def _rbac_payload(self) -> dict[str, object]:
        return {
            "actor_id": self.actor_id,
            "authority_namespace": ACCOUNT_RBAC_AUTHORITY_NAMESPACE,
            "rbac_role": self.rbac_role,
            "user_id": self.user_id,
        }

    def _facts_payload(self) -> dict[str, object]:
        return {"authority_state": self.authority_state}

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
            "rbac_seal": self.rbac_seal,
        }

    def _content_payload(self) -> dict[str, object]:
        return {**self._record_payload(), "record_seal": self.record_seal}

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable version was recorded by the PIT cutoff."""

        canonical_utc_z(as_of)
        return self.clock.recorded_at <= as_of

    def is_temporally_current_at(self, as_of: datetime) -> bool:
        """Return local validity only; this does not prove final-head currentness."""

        if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be an exact timezone-aware datetime")
        return (
            self.authority_state == "current"
            and self.clock.recorded_at <= as_of < self.clock.valid_until
        )

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical nested RBAC source payload."""

        return {
            "identity": {
                "source_id": self.identity.source_id,
                "source_version": self.identity.source_version,
            },
            "clock": self._clock_payload(),
            "chain": self._chain_payload(),
            "user_id": self.user_id,
            "actor_id": self.actor_id,
            "rbac_role": self.rbac_role,
            "authority_state": self.authority_state,
            "identity_hash": self.identity_hash,
            "rbac_seal": self.rbac_seal,
            "facts_seal": self.facts_seal,
            "clock_seal": self.clock_seal,
            "chain_seal": self.chain_seal,
            "fixed_authority_seal": self.fixed_authority_seal,
            "record_seal": self.record_seal,
            "content_hash": self.content_hash,
            **self._fixed_payload(),
        }


def root_claim_hash_for_account_rbac_authority_source_v3(
    *, source_id: str, user_id: int, actor_id: str
) -> str:
    """Return the candidate-independent Account RBAC authority root claim."""

    identity = AccountAuthorityRawSourceIdentityV3(source_id, "root-claim")
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id must be an exact positive integer")
    _token(actor_id, "actor_id")
    return domain_hash(
        "account-rbac-authority-v3/root-claim",
        {
            "actor_id": actor_id,
            "artifact_type": ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_ARTIFACT_TYPE,
            "authority_namespace": ACCOUNT_RBAC_AUTHORITY_NAMESPACE,
            "owner": "account",
            "schema": ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_SCHEMA,
            "source_id": identity.source_id,
            "user_id": user_id,
        },
    )


def validate_account_rbac_authority_source_v3_successor(
    previous: AccountRbacAuthoritySourceV3,
    successor: AccountRbacAuthoritySourceV3,
) -> None:
    """Validate one adjacent non-forking RBAC authority source successor."""

    if (
        type(previous) is not AccountRbacAuthoritySourceV3
        or type(successor) is not AccountRbacAuthoritySourceV3
    ):
        raise TypeError("RBAC authority predecessor and successor must be exact v3 sources")
    previous.__post_init__()
    successor.__post_init__()
    if previous.authority_state == "revoked":
        raise ValueError("revoked RBAC authority cannot have a successor")
    if successor.chain.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact RBAC predecessor")
    if (
        successor.identity.source_id,
        successor.user_id,
        successor.actor_id,
    ) != (previous.identity.source_id, previous.user_id, previous.actor_id):
        raise ValueError("successor changed the RBAC authority root")
    if successor.identity.source_version == previous.identity.source_version:
        raise ValueError("successor source_version must advance")
    if not previous.clock.recorded_at < successor.clock.observed_at:
        raise ValueError("successor observation must follow predecessor recording")


__all__ = [
    "ACCOUNT_RBAC_AUTHORITY_NAMESPACE",
    "ACCOUNT_RBAC_AUTHORITY_ROLES",
    "ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_ARTIFACT_TYPE",
    "ACCOUNT_RBAC_AUTHORITY_SOURCE_V3_SCHEMA",
    "ACCOUNT_RBAC_AUTHORITY_STATES",
    "AccountRbacAuthoritySourceV3",
    "root_claim_hash_for_account_rbac_authority_source_v3",
    "validate_account_rbac_authority_source_v3_successor",
]
