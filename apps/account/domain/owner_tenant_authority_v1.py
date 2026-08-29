"""Immutable owner/tenant authority facts for owner-scoped server reads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)

OWNER = "account"
ARTIFACT_TYPE = "owner_tenant_authority_v1"
SCHEMA = "account.owner_tenant_authority.v1"
PERMISSION = "evidence_read"


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
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(domain: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class OwnerTenantAuthorityV1:
    """One approved immutable owner/tenant authority chain row.

    The Account owner-assignment evidence remains an upstream seal.  This fact
    adds the independently approved tenant and stable owner identities that
    authentication and RBAC cannot establish by themselves.
    """

    authority_id: str
    authority_version: str
    tenant_id: str
    owner_id: str
    account_namespace: str
    account_id: str
    actor_id: str
    actor_user_id: int
    assignment_evidence_id: str
    assignment_evidence_version: str
    assignment_evidence_content_hash: str
    status: str
    approved_by: AccountOwnerAssignmentActor
    approved_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = ARTIFACT_TYPE
    schema: str = SCHEMA
    permission: str = PERMISSION

    def __post_init__(self) -> None:
        if (self.owner, self.artifact_type, self.schema, self.permission) != (
            OWNER,
            ARTIFACT_TYPE,
            SCHEMA,
            PERMISSION,
        ):
            raise ValueError("owner/tenant authority fixed semantics are invalid")
        for name in (
            "authority_id",
            "authority_version",
            "tenant_id",
            "owner_id",
            "account_namespace",
            "account_id",
            "actor_id",
            "assignment_evidence_id",
            "assignment_evidence_version",
        ):
            _token(getattr(self, name), name)
        if type(self.actor_user_id) is not int or self.actor_user_id <= 0:
            raise ValueError("actor_user_id must be an exact positive integer")
        _digest(
            self.assignment_evidence_content_hash,
            "assignment_evidence_content_hash",
        )
        if self.supersedes_content_hash is not None:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")
        if self.status not in {"active", "revoked"}:
            raise ValueError("authority status must be active or revoked")
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be an exact AccountOwnerAssignmentActor")
        self.approved_by.__post_init__()
        if (
            not self.approved_by.is_staff
            or self.approved_by.kind != "human"
            or self.approved_by.role != "owner_tenant_authority_approver"
        ):
            raise ValueError("authority approver must be independent human staff")
        if (
            self.approved_by.actor_id == self.actor_id
            or self.approved_by.user_id == self.actor_user_id
        ):
            raise ValueError("authority owner and approver must be independent")
        for name in ("approved_at", "recorded_at", "valid_until"):
            _aware(getattr(self, name), name)
        if not self.approved_at <= self.recorded_at < self.valid_until:
            raise ValueError("authority clock sequence is invalid")
        expected_identity = _hash(
            "account.owner-tenant-authority.v1/identity", self._identity_payload()
        )
        if self.identity_hash and self.identity_hash != expected_identity:
            raise ValueError("authority identity_hash is invalid")
        object.__setattr__(self, "identity_hash", expected_identity)
        expected_content = _hash(
            "account.owner-tenant-authority.v1/content", self._content_payload()
        )
        if self.content_hash and self.content_hash != expected_content:
            raise ValueError("authority content_hash is invalid")
        object.__setattr__(self, "content_hash", expected_content)

    @property
    def is_root(self) -> bool:
        """Return whether this row starts an authority chain."""

        return self.supersedes_content_hash is None

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the immutable row was recorded by one PIT cutoff."""

        return self.recorded_at <= _aware(as_of, "as_of")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this row is active and unexpired at one PIT cutoff."""

        cutoff = _aware(as_of, "as_of")
        return self.status == "active" and self.recorded_at <= cutoff < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible authority payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "authority_id": self.authority_id,
            "authority_version": self.authority_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "actor_id": self.actor_id,
            "actor_user_id": self.actor_user_id,
            "assignment_evidence_id": self.assignment_evidence_id,
            "assignment_evidence_version": self.assignment_evidence_version,
            "assignment_evidence_content_hash": self.assignment_evidence_content_hash,
            "status": self.status,
            "approved_by": self.approved_by.to_payload(),
            "approved_at": _utc(self.approved_at),
            "recorded_at": _utc(self.recorded_at),
            "valid_until": _utc(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
        }


def validate_owner_tenant_authority_v1_root(value: OwnerTenantAuthorityV1) -> None:
    """Validate an active chain root with no predecessor."""

    if type(value) is not OwnerTenantAuthorityV1:
        raise TypeError("value must be an exact OwnerTenantAuthorityV1")
    value.__post_init__()
    if not value.is_root or value.status != "active":
        raise ValueError("authority root must be active and predecessor-free")


def validate_owner_tenant_authority_v1_successor(
    predecessor: OwnerTenantAuthorityV1,
    successor: OwnerTenantAuthorityV1,
) -> None:
    """Validate an exact CAS successor without identity widening or fallback."""

    if (
        type(predecessor) is not OwnerTenantAuthorityV1
        or type(successor) is not OwnerTenantAuthorityV1
    ):
        raise TypeError("authority chain values must be exact OwnerTenantAuthorityV1")
    predecessor.__post_init__()
    successor.__post_init__()
    if not predecessor.is_current_at(successor.recorded_at):
        raise ValueError("only a current active authority may receive a successor")
    if successor.supersedes_content_hash != predecessor.content_hash:
        raise ValueError("authority successor does not seal the exact predecessor")
    if successor.authority_version == predecessor.authority_version:
        raise ValueError("authority successor version must advance")
    stable_left = (
        predecessor.authority_id,
        predecessor.tenant_id,
        predecessor.owner_id,
        predecessor.account_namespace,
        predecessor.account_id,
        predecessor.actor_id,
        predecessor.actor_user_id,
    )
    stable_right = (
        successor.authority_id,
        successor.tenant_id,
        successor.owner_id,
        successor.account_namespace,
        successor.account_id,
        successor.actor_id,
        successor.actor_user_id,
    )
    if stable_left != stable_right:
        raise ValueError("authority successor cannot widen or substitute scope identity")
    if successor.recorded_at < predecessor.recorded_at:
        raise ValueError("authority successor clock moved backwards")


__all__ = [
    "ARTIFACT_TYPE",
    "OWNER",
    "OwnerTenantAuthorityV1",
    "PERMISSION",
    "SCHEMA",
    "validate_owner_tenant_authority_v1_root",
    "validate_owner_tenant_authority_v1_successor",
]
