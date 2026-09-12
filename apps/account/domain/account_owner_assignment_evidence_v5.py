"""Re-observation-backed inactive owner-assignment approval evidence v5.

This pure Domain value seals one exact SubjectV5 and same-owner staff approval.
Construction records no human decision by itself and grants no owner, scope, or
execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_subject_v5 import AccountOwnerAssignmentSubjectV5
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
)

ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ARTIFACT_TYPE = "account_owner_assignment_evidence_v5"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_SCHEMA = "account-owner-assignment-evidence.v5"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_PERMISSION = "evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ASSIGNMENT_STATE = "authoritative"
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_BLOCKERS = (
    "account_owner_assignment_evidence_v5_not_integrated",
)
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_IDENTITY_HASH_DOMAIN = (
    "account-owner-assignment-evidence.v5/identity"
)
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_CONTENT_HASH_DOMAIN = (
    "account-owner-assignment-evidence.v5/content"
)


def _token(value: object, name: str) -> str:
    """Validate one bounded canonical token."""

    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or value.strip() != value or len(value) > 192 or any(c.isspace() for c in value):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _positive_integer(value: object, name: str) -> int:
    """Validate one exact positive integer while rejecting bool."""

    if type(value) is not int:
        raise TypeError(f"{name} must be an exact positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be an exact positive integer")
    return value


def _digest(value: object, name: str) -> str:
    """Validate one lowercase SHA-256 digest."""

    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    """Validate one timezone-aware datetime without creating a clock value."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc_text(value: datetime) -> str:
    """Serialize an aware datetime as canonical UTC microsecond text."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_hash(domain: str, payload: dict[str, object]) -> str:
    """Hash one canonical payload under a versioned Domain separator."""

    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_seals(
    *,
    prefix: str,
    values: tuple[tuple[str, object, str], ...],
) -> None:
    """Require every explicit v5 seal to equal its nested source value."""

    for name, actual, expected in values:
        _digest(actual, name)
        if actual != expected:
            raise ValueError(f"{prefix} {name} does not match exact upstream evidence")


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentEvidenceV5:
    """Seal same-owner staff claimant and approver facts for one Subject v5."""

    evidence_id: str
    evidence_version: str
    subject: AccountOwnerAssignmentSubjectV5
    policy_identity_hash: str
    policy_content_hash: str
    assigned_owner_user_id: int
    approved_by: AccountOwnerAssignmentActor
    approved_at: datetime
    recorded_at: datetime
    approval_valid_until: datetime
    valid_until: datetime
    account_claim_hash: str
    underlying_claim_hash: str
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ARTIFACT_TYPE
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_SCHEMA
    assignment_state: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ASSIGNMENT_STATE
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_BLOCKERS

    def __post_init__(self) -> None:
        """Validate same-owner policy participants, clocks, upstream seals, and hashes."""

        self._validate_fixed_semantics()
        for name in ("evidence_id", "evidence_version"):
            _token(getattr(self, name), name)
        if type(self.subject) is not AccountOwnerAssignmentSubjectV5:
            raise TypeError("subject must be an exact owner-assignment subject v5")
        self.subject.__post_init__()
        policy = self.subject.policy
        claimant = self.subject.claimant
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be an exact AccountOwnerAssignmentActor")
        self.approved_by.__post_init__()
        _positive_integer(self.assigned_owner_user_id, "assigned_owner_user_id")
        _validate_seals(
            prefix="evidence v5",
            values=(
                ("policy_identity_hash", self.policy_identity_hash, policy.identity_hash),
                ("policy_content_hash", self.policy_content_hash, policy.content_hash),
                ("account_claim_hash", self.account_claim_hash, self.subject.account_claim_hash),
                (
                    "underlying_claim_hash",
                    self.underlying_claim_hash,
                    self.subject.underlying_claim_hash,
                ),
            ),
        )
        if self.assigned_owner_user_id != claimant.user_id:
            raise ValueError("evidence v5 owner must equal the exact receipt claimant")
        _positive_integer(claimant.user_id, "claimant.user_id")
        _positive_integer(self.approved_by.user_id, "approved_by.user_id")
        for name in ("approved_at", "recorded_at", "approval_valid_until", "valid_until"):
            _aware(getattr(self, name), name)
        if not self.subject.requested_at <= self.approved_at <= self.recorded_at:
            raise ValueError("evidence v5 clock sequence is invalid")
        if self.recorded_at >= self.approval_valid_until:
            raise ValueError("evidence v5 approval validity is expired")
        try:
            validate_single_owner_participants(
                policy=policy,
                claimant=claimant,
                approver=self.approved_by,
                as_of=self.recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "evidence v5 participants are not the same current staff owner"
            ) from error
        if not self.subject.is_current_at(self.recorded_at):
            raise ValueError("evidence v5 requires a current subject when recorded")
        source_valid_until = min(
            self.subject.receipt.valid_until,
            policy.valid_until,
            self.subject.reobservation.valid_until,
        )
        if self.valid_until > source_valid_until:
            raise ValueError("evidence v5 validity exceeds receipt, policy, or Reobservation v1")
        if self.valid_until != min(self.subject.valid_until, self.approval_valid_until):
            raise ValueError("evidence v5 validity must equal the exact upstream minimum")
        expected_identity_hash = _canonical_hash(
            ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "evidence v5 identity_hash is invalid",
        )
        expected_content_hash = _canonical_hash(
            ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "evidence v5 content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as another artifact or executable state."""

        for name, expected in (
            ("owner", ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_OWNER),
            (
                "artifact_type",
                ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ARTIFACT_TYPE,
            ),
            (
                "schema",
                ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_SCHEMA,
            ),
            ("assignment_state", ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ASSIGNMENT_STATE),
            ("permission", ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_PERMISSION),
            ("status", ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"evidence v5 {name} is fixed")
        if type(self.blocker_codes) is not tuple:
            raise TypeError("blocker_codes must be an exact tuple")
        if self.blocker_codes != ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_BLOCKERS:
            raise ValueError("evidence v5 blocker_codes are fixed")

    def _validate_or_set_hash(self, name: str, expected: str, message: str) -> None:
        """Compute an omitted hash and reject every supplied mutation."""

        observed = getattr(self, name)
        if type(observed) is not str:
            raise TypeError(f"{name} must be an exact string")
        if observed == "":
            object.__setattr__(self, name, expected)
            return
        if _digest(observed, name) != expected:
            raise ValueError(message)

    @property
    def claimant(self) -> AccountOwnerAssignmentActor:
        """Expose the claimant sealed by the nested Receipt v5."""

        return self.subject.claimant

    @property
    def policy(self) -> SingleOwnerAuthorityPolicyV1:
        """Expose the policy sealed by the nested Receipt v5."""

        return self.subject.policy

    @property
    def requested_at(self) -> datetime:
        """Expose the original source request clock from Subject v5."""

        return self.subject.requested_at

    @property
    def activation_available(self) -> bool:
        """Remain false because approval evidence grants no assignment authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because approval evidence cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable evidence had been recorded by a cutoff."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return self.recorded_at <= cutoff

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this evidence and its complete subject remain current."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return self.recorded_at <= cutoff < self.valid_until and self.subject.is_current_at(cutoff)

    def _identity_payload(self) -> dict[str, object]:
        """Return stable v5 evidence identity fields."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "evidence_id": self.evidence_id,
            "evidence_version": self.evidence_version,
            "policy_identity_hash": self.policy_identity_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every subject, participant, clock, seal, and inactive-state fact."""

        return {
            **self._identity_payload(),
            "subject": self.subject.to_payload(),
            "policy_identity_hash": self.policy_identity_hash,
            "policy_content_hash": self.policy_content_hash,
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "approved_by": self.approved_by.to_payload(),
            "approved_at": _utc_text(self.approved_at),
            "recorded_at": _utc_text(self.recorded_at),
            "approval_valid_until": _utc_text(self.approval_valid_until),
            "valid_until": _utc_text(self.valid_until),
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical inactive evidence payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_evidence_v5_root(
    evidence: AccountOwnerAssignmentEvidenceV5,
) -> None:
    """Validate one immutable Evidence v5 root value."""

    if type(evidence) is not AccountOwnerAssignmentEvidenceV5:
        raise TypeError("evidence must be an exact owner-assignment evidence v5")
    evidence.__post_init__()


def validate_account_owner_assignment_evidence_v5_dual_mapping_root(
    evidence: AccountOwnerAssignmentEvidenceV5,
    *,
    account_claim_hash: str,
    underlying_claim_hash: str,
) -> None:
    """Require both candidate-independent mapping roots to match one exact evidence root."""

    validate_account_owner_assignment_evidence_v5_root(evidence)
    _digest(account_claim_hash, "account_claim_hash")
    _digest(underlying_claim_hash, "underlying_claim_hash")
    if (
        evidence.account_claim_hash != account_claim_hash
        or evidence.underlying_claim_hash != underlying_claim_hash
    ):
        raise ValueError("evidence v5 dual mapping root differs")


def resolve_account_owner_assignment_evidence_v5_final(
    chain: tuple[AccountOwnerAssignmentEvidenceV5, ...], *, as_of: datetime
) -> AccountOwnerAssignmentEvidenceV5 | None:
    """Return the sole historical root; v5 approval successors are unsupported."""

    cutoff = _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if len(chain) > 1:
        raise ValueError("evidence v5 successors are not supported")
    if not chain:
        return None
    evidence = chain[0]
    validate_account_owner_assignment_evidence_v5_root(evidence)
    return evidence if evidence.is_knowable_at(cutoff) else None


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_ASSIGNMENT_STATE",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_CONTENT_HASH_DOMAIN",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_IDENTITY_HASH_DOMAIN",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V5_STATUS",
    "AccountOwnerAssignmentEvidenceV5",
    "resolve_account_owner_assignment_evidence_v5_final",
    "validate_account_owner_assignment_evidence_v5_dual_mapping_root",
    "validate_account_owner_assignment_evidence_v5_root",
]
