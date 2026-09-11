"""Pure Domain policy facts for the explicit personal single-owner mode.

This module validates a source-bound policy and already-injected participant
facts.  It does not read an authority store, authenticate a user, or grant
owner, tenant, or execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)

OWNER = "account"
ARTIFACT_TYPE = "single_owner_authority_policy_v1"
SCHEMA = "account.single_owner_authority_policy.v1"
MODE = "single_owner"
ACTIVE_STATUS = "active"
REVOKED_STATUS = "revoked"
POLICY_STATUSES = frozenset({ACTIVE_STATUS, REVOKED_STATUS})
CLAIMANT_ROLE = "account_owner_claimant"
APPROVER_ROLE = "account_owner_assignment_approver"


def _token(value: object, name: str) -> str:
    """Validate and return one bounded canonical token."""

    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    """Validate and return one lowercase SHA-256 content digest."""

    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    """Validate one timezone-aware datetime without inventing a clock value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize an aware datetime in canonical UTC microsecond precision."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one canonical payload under an explicit Domain separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class SingleOwnerAuthorityPolicyV1:
    """Immutable server-owned policy facts for one single-owner scope.

    ``authorization_content_hash`` identifies the real declaration or
    configuration source supplied to the repository.  It is deliberately
    treated as source content evidence and never as authentication proof.
    The policy itself only validates injected facts; persistence and authority
    issuance remain outside this pure Domain primitive.
    """

    policy_id: str
    policy_version: str
    tenant_id: str
    owner_id: str
    account_namespace: str
    account_id: str
    owner_user_id: int
    authorization_content_hash: str
    observed_at: datetime
    valid_from: datetime
    valid_until: datetime
    status: str = ACTIVE_STATUS
    identity_hash: str = ""
    content_hash: str = ""
    schema: str = SCHEMA
    artifact_type: str = ARTIFACT_TYPE
    mode: str = MODE

    def __post_init__(self) -> None:
        """Validate fixed semantics, identity, clocks, and canonical hashes."""

        self._validate_fixed_semantics()
        for name in (
            "policy_id",
            "policy_version",
            "tenant_id",
            "owner_id",
            "account_namespace",
            "account_id",
        ):
            _token(getattr(self, name), name)
        if type(self.owner_user_id) is not int:
            raise TypeError("owner_user_id must be an exact positive integer")
        if self.owner_user_id <= 0:
            raise ValueError("owner_user_id must be an exact positive integer")
        _digest(self.authorization_content_hash, "authorization_content_hash")
        for name in ("observed_at", "valid_from", "valid_until"):
            _aware(getattr(self, name), name)
        if not self.valid_from <= self.observed_at < self.valid_until:
            raise ValueError("single-owner policy clock sequence is invalid")

        expected_identity_hash = _hash(
            "account.single-owner-authority-policy.v1/identity",
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "single-owner policy identity_hash is invalid",
        )
        expected_content_hash = _hash(
            "account.single-owner-authority-policy.v1/content",
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "single-owner policy content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject attempts to reinterpret the policy as another artifact or mode."""

        for name, expected in (
            ("schema", SCHEMA),
            ("artifact_type", ARTIFACT_TYPE),
            ("mode", MODE),
        ):
            value = getattr(self, name)
            if type(value) is not str:
                raise TypeError(f"{name} must be an exact string")
            if value != expected:
                raise ValueError(f"single-owner policy {name} is fixed")
        if type(self.status) is not str:
            raise TypeError("status must be an exact string")
        if self.status not in POLICY_STATUSES:
            raise ValueError("single-owner policy status must be active or revoked")

    def _validate_or_set_hash(self, name: str, expected: str, message: str) -> None:
        """Compute omitted hashes and reject every supplied hash mutation."""

        observed = getattr(self, name)
        if type(observed) is not str:
            raise TypeError(f"{name} must be an exact string")
        if observed == "":
            object.__setattr__(self, name, expected)
            return
        if _digest(observed, name) != expected:
            raise ValueError(message)

    def _identity_payload(self) -> dict[str, object]:
        """Return stable policy identity fields used by ``identity_hash``."""

        return {
            "artifact_type": self.artifact_type,
            "mode": self.mode,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "schema": self.schema,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every policy fact covered by ``content_hash``."""

        return {
            **self._identity_payload(),
            "account_id": self.account_id,
            "account_namespace": self.account_namespace,
            "authorization_content_hash": self.authorization_content_hash,
            "owner_id": self.owner_id,
            "owner_user_id": self.owner_user_id,
            "status": self.status,
            "tenant_id": self.tenant_id,
            "valid_from": _utc_text(self.valid_from),
            "valid_until": _utc_text(self.valid_until),
            "observed_at": _utc_text(self.observed_at),
        }

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this active policy covers the supplied aware cutoff."""

        self.__post_init__()
        cutoff = _aware(as_of, "as_of")
        return self.status == ACTIVE_STATUS and self.observed_at <= cutoff < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible policy payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
        }


def validate_single_owner_participants(
    policy: SingleOwnerAuthorityPolicyV1,
    claimant: AccountOwnerAssignmentActor,
    approver: AccountOwnerAssignmentActor,
    as_of: datetime,
) -> None:
    """Validate already-injected same-owner claimant and approver facts.

    Both role projections must describe the exact policy owner and preserve
    the source actors' real ``is_staff`` values.  The function does not look
    up identities, authenticate either actor, or issue any authority.
    """

    if type(policy) is not SingleOwnerAuthorityPolicyV1:
        raise TypeError("policy must be an exact SingleOwnerAuthorityPolicyV1")
    if type(claimant) is not AccountOwnerAssignmentActor:
        raise TypeError("claimant must be an exact AccountOwnerAssignmentActor")
    if type(approver) is not AccountOwnerAssignmentActor:
        raise TypeError("approver must be an exact AccountOwnerAssignmentActor")
    policy.__post_init__()
    claimant.__post_init__()
    approver.__post_init__()
    if not policy.is_current_at(as_of):
        raise ValueError("single-owner policy is not current and active")
    if claimant.role != CLAIMANT_ROLE:
        raise ValueError("claimant role is invalid for single-owner policy")
    if approver.role != APPROVER_ROLE:
        raise ValueError("approver role is invalid for single-owner policy")
    if claimant.actor_id != approver.actor_id:
        raise ValueError("single-owner claimant and approver actor_id must match")
    if claimant.user_id != approver.user_id:
        raise ValueError("single-owner claimant and approver user_id must match")
    if claimant.user_id != policy.owner_user_id:
        raise ValueError("single-owner participants must match policy owner_user_id")
    if claimant.is_staff is not approver.is_staff:
        raise ValueError("single-owner participant staff facts must match")
    if approver.is_staff is not True:
        raise ValueError("single-owner approver must be staff")


def validate_single_owner_policy_successor(
    previous: SingleOwnerAuthorityPolicyV1,
    successor: SingleOwnerAuthorityPolicyV1,
) -> None:
    """Keep policy revisions on one owner/account scope with advancing source time.

    The persistence owner additionally seals and verifies the exact predecessor
    link. A new revision may update authorization or status; it cannot move an
    existing policy chain to another human, tenant, owner or account.
    """

    if type(previous) is not SingleOwnerAuthorityPolicyV1:
        raise TypeError("previous must be an exact SingleOwnerAuthorityPolicyV1")
    if type(successor) is not SingleOwnerAuthorityPolicyV1:
        raise TypeError("successor must be an exact SingleOwnerAuthorityPolicyV1")
    previous.__post_init__()
    successor.__post_init__()
    for name in (
        "policy_id",
        "tenant_id",
        "owner_id",
        "account_namespace",
        "account_id",
        "owner_user_id",
    ):
        if getattr(previous, name) != getattr(successor, name):
            raise ValueError(f"policy successor changed {name}")
    if successor.policy_version == previous.policy_version:
        raise ValueError("policy successor version must advance")
    if successor.observed_at <= previous.observed_at:
        raise ValueError("policy successor observation must advance")


__all__ = [
    "ACTIVE_STATUS",
    "APPROVER_ROLE",
    "ARTIFACT_TYPE",
    "CLAIMANT_ROLE",
    "MODE",
    "OWNER",
    "POLICY_STATUSES",
    "REVOKED_STATUS",
    "SCHEMA",
    "SingleOwnerAuthorityPolicyV1",
    "validate_single_owner_participants",
    "validate_single_owner_policy_successor",
]
