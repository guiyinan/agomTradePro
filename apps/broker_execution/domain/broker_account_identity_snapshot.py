"""Broker-owned inactive identity evidence for one live broker account."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

BROKER_ACCOUNT_IDENTITY_SNAPSHOT_OWNER = "broker_execution"
BROKER_ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE = "broker_account_identity_snapshot"
BROKER_ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA = "broker-account-identity-snapshot.v1"
BROKER_ACCOUNT_IDENTITY_SNAPSHOT_AUTHORITY = "identity_evidence_only"
BROKER_ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION = "inactive"
ACCOUNT_IDENTITY_SOURCE_OWNER = "account"
ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE = "account_identity_snapshot"

_KEYED_DIGEST_ALGORITHMS = frozenset({"hmac-sha256", "blake2b-keyed-256"})


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_hash(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountIdentitySourceRef:
    """Exact Account-owned identity source with a bounded validity window."""

    source_id: str
    source_version: str
    content_hash: str
    account_namespace: str
    account_id: str
    owner_user_id: int
    account_type: str
    is_active: bool
    recorded_at: datetime
    valid_until: datetime
    owner: str = ACCOUNT_IDENTITY_SOURCE_OWNER
    artifact_type: str = ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE

    def __post_init__(self) -> None:
        if self.owner != ACCOUNT_IDENTITY_SOURCE_OWNER:
            raise ValueError("account identity source owner is fixed")
        if self.artifact_type != ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE:
            raise ValueError("account identity source artifact_type is fixed")
        _require_token(self.source_id, "source_id")
        _require_token(self.source_version, "source_version")
        _require_hash(self.content_hash, "content_hash")
        _require_token(self.account_namespace, "account_namespace")
        _require_token(self.account_id, "account_id")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("account source owner_user_id must be a positive integer")
        if self.account_type != "real":
            raise ValueError("account source account_type is fixed to real")
        if self.is_active is not True:
            raise ValueError("account source is_active must be the exact boolean true")
        _require_aware(self.recorded_at, "recorded_at")
        _require_aware(self.valid_until, "valid_until")
        if self.recorded_at >= self.valid_until:
            raise ValueError("account identity source validity window is invalid")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact source is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the canonical source identity."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "owner_user_id": self.owner_user_id,
            "account_type": self.account_type,
            "is_active": self.is_active,
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
        }


@dataclass(frozen=True, slots=True)
class KeyedBrokerAccountReferenceDigest:
    """Non-reversible keyed digest of a QMT broker account reference."""

    algorithm: str
    key_id: str
    digest: str

    def __post_init__(self) -> None:
        _require_token(self.algorithm, "algorithm", maximum=32)
        if self.algorithm not in _KEYED_DIGEST_ALGORITHMS:
            raise ValueError("QMT account reference requires an approved keyed digest algorithm")
        _require_token(self.key_id, "key_id")
        _require_hash(self.digest, "digest")

    def to_payload(self) -> dict[str, object]:
        """Return only the keyed digest metadata and digest."""

        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class BrokerAccountIdentitySnapshot:
    """Content-addressed identity evidence that never grants execution permission."""

    snapshot_id: str
    snapshot_version: str
    broker_account_namespace: str
    broker_account_id: int
    owner_user_id: int
    account_type: str
    is_active: bool
    account_source_ref: AccountIdentitySourceRef
    binding_revision: int
    binding_owner_user_id: int
    binding_content_hash: str
    agent_id: str
    agent_version: str
    agent_owner_user_id: int
    agent_content_hash: str
    qmt_account_ref_digest: KeyedBrokerAccountReferenceDigest
    broker_account_category: str
    issued_at: datetime
    recorded_at: datetime
    ttl_valid_until: datetime
    valid_until: datetime
    supersedes_snapshot_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = BROKER_ACCOUNT_IDENTITY_SNAPSHOT_OWNER
    artifact_type: str = BROKER_ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE
    schema: str = BROKER_ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA
    authority_scope: str = BROKER_ACCOUNT_IDENTITY_SNAPSHOT_AUTHORITY
    permission: str = BROKER_ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION

    def __post_init__(self) -> None:
        self._validate_fixed_authority()
        for field_name in (
            "snapshot_id",
            "snapshot_version",
            "broker_account_namespace",
            "agent_id",
            "agent_version",
            "broker_account_category",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.broker_account_id) is not int or self.broker_account_id <= 0:
            raise TypeError("broker_account_id must be an exact positive integer")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be a positive integer")
        if self.account_type != "real":
            raise ValueError("account_type is fixed to real")
        if self.is_active is not True:
            raise ValueError("is_active must be the exact boolean true")
        self._validate_owner_sources()
        self._validate_clocks()
        if self.supersedes_snapshot_hash is not None:
            _require_hash(self.supersedes_snapshot_hash, "supersedes_snapshot_hash")
        expected_identity = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity:
                raise ValueError("broker account identity_hash is invalid")
        expected_content = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content:
                raise ValueError("broker account identity content_hash is invalid")

    def _validate_fixed_authority(self) -> None:
        if self.owner != BROKER_ACCOUNT_IDENTITY_SNAPSHOT_OWNER:
            raise ValueError("broker account identity owner is fixed")
        if self.artifact_type != BROKER_ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE:
            raise ValueError("broker account identity artifact_type is fixed")
        if self.schema != BROKER_ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA:
            raise ValueError("broker account identity schema is fixed")
        if self.authority_scope != BROKER_ACCOUNT_IDENTITY_SNAPSHOT_AUTHORITY:
            raise ValueError("broker account identity authority_scope is fixed")
        if self.permission != BROKER_ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION:
            raise ValueError("broker account identity permission is fixed inactive")

    def _validate_owner_sources(self) -> None:
        if type(self.account_source_ref) is not AccountIdentitySourceRef:
            raise TypeError("account_source_ref must be an exact Account identity source")
        AccountIdentitySourceRef.__post_init__(self.account_source_ref)
        if self.account_source_ref.owner_user_id != self.owner_user_id:
            raise ValueError("Account source owner must equal the Broker account owner")
        if (
            self.account_source_ref.account_type != "real"
            or self.account_source_ref.is_active is not True
        ):
            raise ValueError("Account source must remain exact active real identity evidence")
        if type(self.binding_revision) is not int or self.binding_revision <= 0:
            raise ValueError("binding_revision must be a positive integer")
        for field_name in ("binding_content_hash", "agent_content_hash"):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in ("binding_owner_user_id", "agent_owner_user_id"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
            if value != self.owner_user_id:
                raise ValueError(f"{field_name} must equal the Account owner")
        if type(self.qmt_account_ref_digest) is not KeyedBrokerAccountReferenceDigest:
            raise TypeError("qmt_account_ref_digest must be an exact keyed digest")
        KeyedBrokerAccountReferenceDigest.__post_init__(self.qmt_account_ref_digest)

    def _validate_clocks(self) -> None:
        for field_name in (
            "issued_at",
            "recorded_at",
            "ttl_valid_until",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        expected_valid_until = min(
            self.account_source_ref.valid_until,
            self.ttl_valid_until,
        )
        if (
            self.issued_at > self.recorded_at
            or self.recorded_at >= self.ttl_valid_until
            or self.recorded_at >= self.account_source_ref.valid_until
        ):
            raise ValueError("broker account identity clock sequence is invalid")
        if self.account_source_ref.recorded_at > self.recorded_at:
            raise ValueError("Account identity source is not knowable at the recording clock")
        if self.valid_until != expected_valid_until:
            raise ValueError("valid_until must equal the strict minimum of Account source and TTL")

    @property
    def activation_available(self) -> bool:
        """Remain false because this snapshot is identity evidence only."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because account identity does not authorize an order."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this inactive identity snapshot is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "broker_account_namespace": self.broker_account_namespace,
            "broker_account_id": self.broker_account_id,
            "owner_user_id": self.owner_user_id,
            "account_type": self.account_type,
            "is_active": self.is_active,
            "account_source_ref": self.account_source_ref.to_payload(),
            "binding_revision": self.binding_revision,
            "binding_owner_user_id": self.binding_owner_user_id,
            "binding_content_hash": self.binding_content_hash,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "agent_owner_user_id": self.agent_owner_user_id,
            "agent_content_hash": self.agent_content_hash,
            "qmt_account_ref_digest": self.qmt_account_ref_digest.to_payload(),
            "broker_account_category": self.broker_account_category,
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "ttl_valid_until": _utc_text(self.ttl_valid_until),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_snapshot_hash": self.supersedes_snapshot_hash,
            "authority_scope": self.authority_scope,
            "permission": self.permission,
        }

    def to_payload(self) -> dict[str, object]:
        """Return canonical identity evidence without plaintext Broker references."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_broker_account_identity_snapshot_successor(
    previous: BrokerAccountIdentitySnapshot,
    successor: BrokerAccountIdentitySnapshot,
) -> None:
    """Validate one adjacent snapshot for the same Broker account and owner."""

    if type(previous) is not BrokerAccountIdentitySnapshot:
        raise TypeError("previous must be an exact Broker account identity snapshot")
    if type(successor) is not BrokerAccountIdentitySnapshot:
        raise TypeError("successor must be an exact Broker account identity snapshot")
    BrokerAccountIdentitySnapshot.__post_init__(previous)
    BrokerAccountIdentitySnapshot.__post_init__(successor)
    if successor.supersedes_snapshot_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous snapshot")
    if (
        successor.broker_account_namespace != previous.broker_account_namespace
        or successor.broker_account_id != previous.broker_account_id
        or successor.owner_user_id != previous.owner_user_id
    ):
        raise ValueError("successor changed Broker account identity or owner")
    if successor.binding_revision <= previous.binding_revision:
        raise ValueError("successor binding_revision must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


__all__ = [
    "ACCOUNT_IDENTITY_SOURCE_ARTIFACT_TYPE",
    "ACCOUNT_IDENTITY_SOURCE_OWNER",
    "BROKER_ACCOUNT_IDENTITY_SNAPSHOT_ARTIFACT_TYPE",
    "BROKER_ACCOUNT_IDENTITY_SNAPSHOT_AUTHORITY",
    "BROKER_ACCOUNT_IDENTITY_SNAPSHOT_OWNER",
    "BROKER_ACCOUNT_IDENTITY_SNAPSHOT_PERMISSION",
    "BROKER_ACCOUNT_IDENTITY_SNAPSHOT_SCHEMA",
    "AccountIdentitySourceRef",
    "BrokerAccountIdentitySnapshot",
    "KeyedBrokerAccountReferenceDigest",
    "validate_broker_account_identity_snapshot_successor",
]
