"""Explicit long-lived owner/tenant read authority for one Account scope.

The v2 decision is an immutable, independently versioned record over a
complete Account owner-assignment Evidence v4 and its exact policy.  It is
evidence for owner-scoped reads and can never authorize execution.  Durable
latest selection, revocation lookup, current-policy validation, and fresh
authentication are responsibilities of a future Application composition;
this pure Domain module only validates the sealed facts and this record's own
time interval.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_evidence_v4 import (
    AccountOwnerAssignmentEvidenceV4,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
)

OWNER = "account"
ARTIFACT_TYPE = "owner_tenant_authority_v2"
SCHEMA = "account.owner_tenant_authority.v2"
PERMISSION = "evidence_read"
STATUS = "active"
REVOCATION_ARTIFACT_TYPE = "owner_tenant_authority_v2_revocation"
REVOCATION_SCHEMA = "account.owner_tenant_authority.v2.revocation"
REVOCATION_STATUS = "revoked"
APPROVER_ROLE = "owner_tenant_authority_approver"
REVOKER_ROLE = "owner_tenant_authority_revoker"
MUST_NOT_EXECUTE = True

AUTHORITY_V2_IDENTITY_HASH_DOMAIN = "account.owner-tenant-authority.v2/identity"
AUTHORITY_V2_CONTENT_HASH_DOMAIN = "account.owner-tenant-authority.v2/content"
REVOCATION_V2_IDENTITY_HASH_DOMAIN = "account.owner-tenant-authority.v2-revocation/identity"
REVOCATION_V2_CONTENT_HASH_DOMAIN = "account.owner-tenant-authority.v2-revocation/content"


def _token(value: object, name: str) -> str:
    """Validate and return one bounded canonical token."""

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
    """Validate and return one lowercase SHA-256 digest."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    """Validate one timezone-aware datetime without changing its value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc(value: datetime) -> str:
    """Serialize one aware datetime with canonical UTC microsecond precision."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one canonical payload under an independent versioned domain."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _set_or_validate_hash(
    instance: object,
    name: str,
    expected: str,
    message: str,
) -> None:
    """Fill one omitted frozen hash or reject a supplied mutation."""

    observed = getattr(instance, name)
    if type(observed) is not str:
        raise TypeError(f"{name} must be an exact string")
    if observed == "":
        object.__setattr__(instance, name, expected)
        return
    if _digest(observed, name) != expected:
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class OwnerTenantAuthorityV2:
    """One immutable long-lived owner decision over Evidence v4.

    Scope values are derived from the sealed ``assignment`` and ``policy``;
    they are not constructor inputs.  The root is valid only after the
    assignment and policy were current at both approval and recording time.
    Its validity may extend beyond the short-lived assignment and actor
    observations, but never beyond the sealed policy.  A future Application
    must revalidate durable latest, revocation, current policy, and fresh
    authentication before using this decision for a read.
    """

    authority_id: str
    authority_version: str
    assignment: AccountOwnerAssignmentEvidenceV4
    policy: SingleOwnerAuthorityPolicyV1
    approved_by: AccountOwnerAssignmentActor
    approved_at: datetime
    recorded_at: datetime
    valid_until: datetime
    status: str = STATUS
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = ARTIFACT_TYPE
    schema: str = SCHEMA
    permission: str = PERMISSION

    def __post_init__(self) -> None:
        """Validate the sealed Evidence/policy graph, actor, clocks, and hashes."""

        self._validate_fixed_semantics()
        for name in ("authority_id", "authority_version"):
            _token(getattr(self, name), name)
        if type(self.assignment) is not AccountOwnerAssignmentEvidenceV4:
            raise TypeError("assignment must be an exact AccountOwnerAssignmentEvidenceV4")
        if type(self.policy) is not SingleOwnerAuthorityPolicyV1:
            raise TypeError("policy must be an exact SingleOwnerAuthorityPolicyV1")
        self.assignment.__post_init__()
        self.policy.__post_init__()
        if self.policy != self.assignment.subject.policy:
            raise ValueError("authority policy must equal the assignment Subject policy")
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be an exact AccountOwnerAssignmentActor")
        self.approved_by.__post_init__()
        if (
            self.approved_by.role != APPROVER_ROLE
            or not self.approved_by.is_staff
            or self.approved_by.kind != "human"
        ):
            raise ValueError("authority approver must be a human staff owner approver")
        claimant = self.assignment.claimant
        if (
            self.approved_by.actor_id != claimant.actor_id
            or self.approved_by.user_id != claimant.user_id
            or self.approved_by.kind != claimant.kind
            or self.approved_by.is_staff is not claimant.is_staff
        ):
            raise ValueError("authority approver must match the sealed owner actor")
        approved_at = _aware(self.approved_at, "approved_at")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        valid_until = _aware(self.valid_until, "valid_until")
        if not approved_at <= recorded_at < valid_until:
            raise ValueError("authority clock sequence is invalid")
        if not self.assignment.is_current_at(approved_at) or not self.assignment.is_current_at(
            recorded_at
        ):
            raise ValueError("authority root requires a current assignment at both clocks")
        if not self.policy.is_current_at(approved_at) or not self.policy.is_current_at(recorded_at):
            raise ValueError("authority root requires a current policy at both clocks")
        if valid_until > self.policy.valid_until:
            raise ValueError("authority validity exceeds the sealed policy")
        expected_identity = _hash(
            AUTHORITY_V2_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        _set_or_validate_hash(
            self,
            "identity_hash",
            expected_identity,
            "authority v2 identity_hash is invalid",
        )
        expected_content = _hash(
            AUTHORITY_V2_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        _set_or_validate_hash(
            self,
            "content_hash",
            expected_content,
            "authority v2 content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject attempts to reinterpret the v2 decision as another artifact."""

        for name, expected in (
            ("owner", OWNER),
            ("artifact_type", ARTIFACT_TYPE),
            ("schema", SCHEMA),
            ("permission", PERMISSION),
            ("status", STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"owner tenant authority v2 {name} is fixed")

    @property
    def is_root(self) -> bool:
        """Return whether this immutable v2 record is the first and only root form."""

        return True

    @property
    def tenant_id(self) -> str:
        """Return the tenant scope sealed by the exact policy."""

        return self.policy.tenant_id

    @property
    def owner_id(self) -> str:
        """Return the owner scope sealed by the exact policy."""

        return self.policy.owner_id

    @property
    def account_namespace(self) -> str:
        """Return the Account namespace sealed by the exact policy and assignment."""

        return self.policy.account_namespace

    @property
    def account_id(self) -> str:
        """Return the Account identifier sealed by the exact policy and assignment."""

        return self.policy.account_id

    @property
    def actor_id(self) -> str:
        """Return the owner actor identity sealed by Evidence v4."""

        return self.assignment.claimant.actor_id

    @property
    def actor_user_id(self) -> int:
        """Return the owner user identity sealed by Evidence v4."""

        return self.assignment.claimant.user_id

    @property
    def assignment_evidence_id(self) -> str:
        """Return the exact upstream Evidence v4 identity."""

        return self.assignment.evidence_id

    @property
    def assignment_evidence_version(self) -> str:
        """Return the exact upstream Evidence v4 version."""

        return self.assignment.evidence_version

    @property
    def assignment_evidence_content_hash(self) -> str:
        """Return the exact upstream Evidence v4 content seal."""

        return self.assignment.content_hash

    @property
    def activation_available(self) -> bool:
        """Return false because this decision authorizes evidence reads only."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Return true because this decision can never authorize execution."""

        return MUST_NOT_EXECUTE

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable decision was recorded by ``as_of``."""

        return self.recorded_at <= _aware(as_of, "as_of")

    def is_current_at(self, as_of: datetime) -> bool:
        """Return only this row's own time validity.

        Durable latest selection, revocation, current-policy validation, and
        fresh authentication are deliberately left to the Application layer.
        """

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return self.recorded_at <= cutoff < self.valid_until

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible v2 decision payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": MUST_NOT_EXECUTE,
        }

    def _identity_payload(self) -> dict[str, object]:
        """Return stable v2 identity fields covered by ``identity_hash``."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "authority_id": self.authority_id,
            "authority_version": self.authority_version,
            "assignment_identity_hash": self.assignment.identity_hash,
            "policy_identity_hash": self.policy.identity_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every sealed graph, derived scope, actor, clock, and state fact."""

        return {
            **self._identity_payload(),
            "assignment": self.assignment.to_payload(),
            "policy": self.policy.to_payload(),
            "tenant_id": self.tenant_id,
            "owner_id": self.owner_id,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "actor_id": self.actor_id,
            "actor_user_id": self.actor_user_id,
            "assignment_evidence_id": self.assignment_evidence_id,
            "assignment_evidence_version": self.assignment_evidence_version,
            "assignment_evidence_content_hash": self.assignment_evidence_content_hash,
            "approved_by": self.approved_by.to_payload(),
            "approved_at": _utc(self.approved_at),
            "recorded_at": _utc(self.recorded_at),
            "valid_until": _utc(self.valid_until),
            "permission": self.permission,
            "status": self.status,
            "must_not_execute": MUST_NOT_EXECUTE,
        }


@dataclass(frozen=True, slots=True)
class OwnerTenantAuthorityV2Revocation:
    """One immutable revocation event for an OwnerTenantAuthorityV2 root.

    This event does not mutate or rewrite the decision.  A future Application
    must require the exact durable authority and policy hashes, observe this
    event at its recorded cutoff, and still perform current-policy and fresh
    authentication checks.  A revocation remains valid even when its decision
    had already expired; it never creates an active successor.
    """

    authority_content_hash: str
    policy_content_hash: str
    revoked_by: AccountOwnerAssignmentActor
    revoked_at: datetime
    recorded_at: datetime
    reason: str
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = REVOCATION_ARTIFACT_TYPE
    schema: str = REVOCATION_SCHEMA
    permission: str = PERMISSION
    status: str = REVOCATION_STATUS

    def __post_init__(self) -> None:
        """Validate revocation selectors, dedicated role, clocks, and hashes."""

        self._validate_fixed_semantics()
        _digest(self.authority_content_hash, "authority_content_hash")
        _digest(self.policy_content_hash, "policy_content_hash")
        if type(self.revoked_by) is not AccountOwnerAssignmentActor:
            raise TypeError("revoked_by must be an exact AccountOwnerAssignmentActor")
        self.revoked_by.__post_init__()
        if (
            self.revoked_by.role != REVOKER_ROLE
            or not self.revoked_by.is_staff
            or self.revoked_by.kind != "human"
        ):
            raise ValueError("revoked_by must be a human staff owner revoker")
        _token(self.reason, "reason")
        revoked_at = _aware(self.revoked_at, "revoked_at")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        if revoked_at > recorded_at:
            raise ValueError("revocation clock sequence is invalid")
        expected_identity = _hash(
            REVOCATION_V2_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        _set_or_validate_hash(
            self,
            "identity_hash",
            expected_identity,
            "authority v2 revocation identity_hash is invalid",
        )
        expected_content = _hash(
            REVOCATION_V2_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        _set_or_validate_hash(
            self,
            "content_hash",
            expected_content,
            "authority v2 revocation content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as an active authority or another artifact."""

        for name, expected in (
            ("owner", OWNER),
            ("artifact_type", REVOCATION_ARTIFACT_TYPE),
            ("schema", REVOCATION_SCHEMA),
            ("permission", PERMISSION),
            ("status", REVOCATION_STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"authority v2 revocation {name} is fixed")

    @property
    def activation_available(self) -> bool:
        """Return false because a revocation is evidence and never a grant."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Return true because revocation evidence cannot authorize execution."""

        return MUST_NOT_EXECUTE

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable revocation was recorded by ``as_of``."""

        return self.recorded_at <= _aware(as_of, "as_of")

    def is_effective_at(self, as_of: datetime) -> bool:
        """Return whether a known revocation event has taken effect by ``as_of``."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return self.recorded_at <= cutoff and self.revoked_at <= cutoff

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical JSON-compatible revocation payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": MUST_NOT_EXECUTE,
        }

    def _identity_payload(self) -> dict[str, object]:
        """Return stable revocation identity fields covered by its hash."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "authority_content_hash": self.authority_content_hash,
            "policy_content_hash": self.policy_content_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every revocation binding, actor, reason, clock, and state fact."""

        return {
            **self._identity_payload(),
            "revoked_by": self.revoked_by.to_payload(),
            "revoked_at": _utc(self.revoked_at),
            "recorded_at": _utc(self.recorded_at),
            "reason": self.reason,
            "permission": self.permission,
            "status": self.status,
            "must_not_execute": MUST_NOT_EXECUTE,
        }


def validate_owner_tenant_authority_v2_root(value: OwnerTenantAuthorityV2) -> None:
    """Validate one active v2 root with its complete current source coverage."""

    if type(value) is not OwnerTenantAuthorityV2:
        raise TypeError("value must be an exact OwnerTenantAuthorityV2")
    value.__post_init__()


def validate_owner_tenant_authority_v2_revocation(
    authority: OwnerTenantAuthorityV2,
    revocation: OwnerTenantAuthorityV2Revocation,
) -> None:
    """Bind one immutable revocation to an exact owner decision without rewriting it."""

    if type(authority) is not OwnerTenantAuthorityV2:
        raise TypeError("authority must be an exact OwnerTenantAuthorityV2")
    if type(revocation) is not OwnerTenantAuthorityV2Revocation:
        raise TypeError("revocation must be an exact OwnerTenantAuthorityV2Revocation")
    authority.__post_init__()
    revocation.__post_init__()
    if revocation.authority_content_hash != authority.content_hash:
        raise ValueError("revocation authority content hash does not match the exact decision")
    if revocation.policy_content_hash != authority.policy.content_hash:
        raise ValueError("revocation policy content hash does not match the exact policy")
    owner = authority.assignment.claimant
    revoked_by = revocation.revoked_by
    if (
        revoked_by.actor_id != owner.actor_id
        or revoked_by.user_id != owner.user_id
        or revoked_by.kind != owner.kind
        or revoked_by.is_staff is not owner.is_staff
    ):
        raise ValueError("revocation actor must match the sealed owner")
    if revocation.revoked_at < authority.recorded_at:
        raise ValueError("revocation cannot precede the durable authority record")


__all__ = [
    "APPROVER_ROLE",
    "ARTIFACT_TYPE",
    "AUTHORITY_V2_CONTENT_HASH_DOMAIN",
    "AUTHORITY_V2_IDENTITY_HASH_DOMAIN",
    "MUST_NOT_EXECUTE",
    "OWNER",
    "OwnerTenantAuthorityV2",
    "OwnerTenantAuthorityV2Revocation",
    "PERMISSION",
    "REVOKER_ROLE",
    "REVOCATION_ARTIFACT_TYPE",
    "REVOCATION_STATUS",
    "REVOCATION_SCHEMA",
    "REVOCATION_V2_CONTENT_HASH_DOMAIN",
    "REVOCATION_V2_IDENTITY_HASH_DOMAIN",
    "SCHEMA",
    "STATUS",
    "validate_owner_tenant_authority_v2_revocation",
    "validate_owner_tenant_authority_v2_root",
]
