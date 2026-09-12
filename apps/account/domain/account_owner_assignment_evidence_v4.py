"""Policy-bound inactive owner-assignment evidence for one Account creation.

The v4 subject and evidence values preserve the complete Receipt v4 graph while
allowing the same real staff owner to appear in both single-owner roles.  These
pure Domain values validate facts supplied by an outer authenticated
composition; constructing them is not a human approval, an authentication
operation, or an execution-authority grant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    AccountOwnerAssignmentActor,
)
from apps.account.domain.account_owner_assignment_provenance_receipt_v4 import (
    AccountOwnerAssignmentProvenanceReceiptV4,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.single_owner_authority_policy_v1 import (
    SingleOwnerAuthorityPolicyV1,
    validate_single_owner_participants,
)

OWNER = "account"
SUBJECT_ARTIFACT_TYPE = "account_owner_assignment_subject_v4"
SUBJECT_SCHEMA = "account-owner-assignment-subject.v4"
EVIDENCE_ARTIFACT_TYPE = "account_owner_assignment_evidence_v4"
EVIDENCE_SCHEMA = "account-owner-assignment-evidence.v4"
PERMISSION = "evidence_only"
STATUS = "inactive"
ASSIGNMENT_STATE = "authoritative"
SUBJECT_BLOCKERS = ("account_owner_assignment_subject_v4_not_integrated",)
EVIDENCE_BLOCKERS = ("account_owner_assignment_evidence_v4_not_integrated",)
SUBJECT_IDENTITY_HASH_DOMAIN = "account-owner-assignment-subject.v4/identity"
SUBJECT_CONTENT_HASH_DOMAIN = "account-owner-assignment-subject.v4/content"
EVIDENCE_IDENTITY_HASH_DOMAIN = "account-owner-assignment-evidence.v4/identity"
EVIDENCE_CONTENT_HASH_DOMAIN = "account-owner-assignment-evidence.v4/content"

# Long names mirror the versioned Receipt constants and make codec imports
# unambiguous without changing the compact names used by the v3 Domain file.
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_OWNER = OWNER
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_ARTIFACT_TYPE = SUBJECT_ARTIFACT_TYPE
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_SCHEMA = SUBJECT_SCHEMA
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_PERMISSION = PERMISSION
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_STATUS = STATUS
ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_BLOCKERS = SUBJECT_BLOCKERS
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_OWNER = OWNER
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_ARTIFACT_TYPE = EVIDENCE_ARTIFACT_TYPE
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_SCHEMA = EVIDENCE_SCHEMA
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_PERMISSION = PERMISSION
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_STATUS = STATUS
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_ASSIGNMENT_STATE = ASSIGNMENT_STATE
ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_BLOCKERS = EVIDENCE_BLOCKERS


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
    """Require every explicit v4 seal to equal its nested source value."""

    for name, actual, expected in values:
        _digest(actual, name)
        if actual != expected:
            raise ValueError(f"{prefix} {name} does not match exact upstream evidence")


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentSubjectV4:
    """Bind one Receipt v4 to its exact Binding v2 and Physical v3 root."""

    subject_id: str
    subject_version: str
    receipt: AccountOwnerAssignmentProvenanceReceiptV4
    binding: CanonicalAccountCreationBindingV2
    physical_root: AllocatedPhysicalAccountRowObservationV3
    receipt_identity_hash: str
    receipt_content_hash: str
    policy_identity_hash: str
    policy_content_hash: str
    binding_identity_hash: str
    binding_content_hash: str
    allocation_identity_hash: str
    allocation_content_hash: str
    creation_root_identity_hash: str
    creation_root_content_hash: str
    account_claim_hash: str
    underlying_claim_hash: str
    physical_observation_content_hash: str
    physical_source_content_hash: str
    physical_raw_observation_content_hash: str
    requested_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = SUBJECT_ARTIFACT_TYPE
    schema: str = SUBJECT_SCHEMA
    permission: str = PERMISSION
    status: str = STATUS
    blocker_codes: tuple[str, ...] = SUBJECT_BLOCKERS

    def __post_init__(self) -> None:
        """Validate the complete receipt, policy, binding, root, clock, and hash graph."""

        self._validate_fixed_semantics()
        for name in ("subject_id", "subject_version"):
            _token(getattr(self, name), name)
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV4:
            raise TypeError("receipt must be an exact provenance receipt v4")
        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact canonical Binding v2")
        if type(self.physical_root) is not AllocatedPhysicalAccountRowObservationV3:
            raise TypeError("physical_root must be an exact allocated Physical v3")
        self.receipt.__post_init__()
        self.binding.__post_init__()
        self.physical_root.__post_init__()
        if self.receipt.binding != self.binding:
            raise ValueError("subject v4 does not bind the exact receipt and Binding v2")
        if self.binding.creation_root != self.physical_root:
            raise ValueError("subject v4 does not bind the exact Binding and Physical v3 root")
        policy = self.receipt.policy
        physical = self.physical_root.physical_observation
        _validate_seals(
            prefix="subject v4",
            values=(
                ("receipt_identity_hash", self.receipt_identity_hash, self.receipt.identity_hash),
                ("receipt_content_hash", self.receipt_content_hash, self.receipt.content_hash),
                ("policy_identity_hash", self.policy_identity_hash, policy.identity_hash),
                ("policy_content_hash", self.policy_content_hash, policy.content_hash),
                ("binding_identity_hash", self.binding_identity_hash, self.binding.identity_hash),
                ("binding_content_hash", self.binding_content_hash, self.binding.content_hash),
                (
                    "allocation_identity_hash",
                    self.allocation_identity_hash,
                    self.binding.allocation.identity_hash,
                ),
                (
                    "allocation_content_hash",
                    self.allocation_content_hash,
                    self.binding.allocation.content_hash,
                ),
                (
                    "creation_root_identity_hash",
                    self.creation_root_identity_hash,
                    self.physical_root.identity_hash,
                ),
                (
                    "creation_root_content_hash",
                    self.creation_root_content_hash,
                    self.physical_root.content_hash,
                ),
                ("account_claim_hash", self.account_claim_hash, self.binding.account_claim_hash),
                (
                    "underlying_claim_hash",
                    self.underlying_claim_hash,
                    self.binding.underlying_claim_hash,
                ),
                (
                    "physical_observation_content_hash",
                    self.physical_observation_content_hash,
                    physical.content_hash,
                ),
                (
                    "physical_source_content_hash",
                    self.physical_source_content_hash,
                    physical.source_content_hash,
                ),
                (
                    "physical_raw_observation_content_hash",
                    self.physical_raw_observation_content_hash,
                    physical.raw_observation_content_hash,
                ),
            ),
        )
        _aware(self.requested_at, "requested_at")
        _aware(self.valid_until, "valid_until")
        if not self.receipt.recorded_at <= self.requested_at < self.valid_until:
            raise ValueError("subject v4 clock sequence is invalid")
        if not self.receipt.is_current_at(self.requested_at):
            raise ValueError("subject v4 requires a current receipt and policy")
        if not self.physical_root.is_knowable_at(self.requested_at):
            raise ValueError("subject v4 requires a current Physical v3 root")
        source_valid_until = min(
            self.receipt.valid_until,
            policy.valid_until,
            self.physical_root.valid_until,
        )
        if self.valid_until != source_valid_until:
            raise ValueError("subject v4 validity must equal the exact upstream minimum")
        expected_identity_hash = _canonical_hash(
            SUBJECT_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "subject v4 identity_hash is invalid",
        )
        expected_content_hash = _canonical_hash(
            SUBJECT_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "subject v4 content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as another artifact or executable state."""

        for name, expected in (
            ("owner", OWNER),
            ("artifact_type", SUBJECT_ARTIFACT_TYPE),
            ("schema", SUBJECT_SCHEMA),
            ("permission", PERMISSION),
            ("status", STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"subject v4 {name} is fixed")
        if type(self.blocker_codes) is not tuple:
            raise TypeError("blocker_codes must be an exact tuple")
        if self.blocker_codes != SUBJECT_BLOCKERS:
            raise ValueError("subject v4 blocker_codes are fixed")

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
        """Expose the exact claimant sealed by Receipt v4."""

        return self.receipt.claimant

    @property
    def policy(self) -> SingleOwnerAuthorityPolicyV1:
        """Expose the exact policy sealed by Receipt v4."""

        return self.receipt.policy

    @property
    def activation_available(self) -> bool:
        """Remain false because a subject grants no assignment authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a subject cannot authorize execution."""

        return True

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this subject and its complete short-lived graph are current."""

        cutoff = _aware(as_of, "as_of")
        self.__post_init__()
        return (
            self.requested_at <= cutoff < self.valid_until
            and self.receipt.is_current_at(cutoff)
            and self.physical_root.is_knowable_at(cutoff)
        )

    def _identity_payload(self) -> dict[str, object]:
        """Return stable v4 subject identity fields."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "policy_identity_hash": self.policy_identity_hash,
            "receipt_identity_hash": self.receipt_identity_hash,
        }

    def _content_payload(self) -> dict[str, object]:
        """Return every nested source, seal, clock, and inactive-state fact."""

        return {
            **self._identity_payload(),
            "receipt": self.receipt.to_payload(),
            "binding": self.binding.to_payload(),
            "physical_root": self.physical_root.to_payload(),
            "receipt_identity_hash": self.receipt_identity_hash,
            "receipt_content_hash": self.receipt_content_hash,
            "policy_identity_hash": self.policy_identity_hash,
            "policy_content_hash": self.policy_content_hash,
            "binding_identity_hash": self.binding_identity_hash,
            "binding_content_hash": self.binding_content_hash,
            "allocation_identity_hash": self.allocation_identity_hash,
            "allocation_content_hash": self.allocation_content_hash,
            "creation_root_identity_hash": self.creation_root_identity_hash,
            "creation_root_content_hash": self.creation_root_content_hash,
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "physical_observation_content_hash": self.physical_observation_content_hash,
            "physical_source_content_hash": self.physical_source_content_hash,
            "physical_raw_observation_content_hash": self.physical_raw_observation_content_hash,
            "requested_at": _utc_text(self.requested_at),
            "valid_until": _utc_text(self.valid_until),
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical inactive subject payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentEvidenceV4:
    """Seal same-owner staff claimant and approver facts for one Subject v4."""

    evidence_id: str
    evidence_version: str
    subject: AccountOwnerAssignmentSubjectV4
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
    owner: str = OWNER
    artifact_type: str = EVIDENCE_ARTIFACT_TYPE
    schema: str = EVIDENCE_SCHEMA
    assignment_state: str = ASSIGNMENT_STATE
    permission: str = PERMISSION
    status: str = STATUS
    blocker_codes: tuple[str, ...] = EVIDENCE_BLOCKERS

    def __post_init__(self) -> None:
        """Validate same-owner policy participants, clocks, upstream seals, and hashes."""

        self._validate_fixed_semantics()
        for name in ("evidence_id", "evidence_version"):
            _token(getattr(self, name), name)
        if type(self.subject) is not AccountOwnerAssignmentSubjectV4:
            raise TypeError("subject must be an exact owner-assignment subject v4")
        self.subject.__post_init__()
        policy = self.subject.policy
        claimant = self.subject.claimant
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be an exact AccountOwnerAssignmentActor")
        self.approved_by.__post_init__()
        _positive_integer(self.assigned_owner_user_id, "assigned_owner_user_id")
        _validate_seals(
            prefix="evidence v4",
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
            raise ValueError("evidence v4 owner must equal the exact receipt claimant")
        _positive_integer(claimant.user_id, "claimant.user_id")
        _positive_integer(self.approved_by.user_id, "approved_by.user_id")
        for name in ("approved_at", "recorded_at", "approval_valid_until", "valid_until"):
            _aware(getattr(self, name), name)
        if not self.subject.requested_at <= self.approved_at <= self.recorded_at:
            raise ValueError("evidence v4 clock sequence is invalid")
        if self.recorded_at >= self.approval_valid_until:
            raise ValueError("evidence v4 approval validity is expired")
        try:
            validate_single_owner_participants(
                policy=policy,
                claimant=claimant,
                approver=self.approved_by,
                as_of=self.recorded_at,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "evidence v4 participants are not the same current staff owner"
            ) from error
        if not self.subject.is_current_at(self.recorded_at):
            raise ValueError("evidence v4 requires a current subject when recorded")
        source_valid_until = min(
            self.subject.receipt.valid_until,
            policy.valid_until,
            self.subject.physical_root.valid_until,
        )
        if self.valid_until > source_valid_until:
            raise ValueError("evidence v4 validity exceeds receipt, policy, or Physical v3")
        if self.valid_until != min(self.subject.valid_until, self.approval_valid_until):
            raise ValueError("evidence v4 validity must equal the exact upstream minimum")
        expected_identity_hash = _canonical_hash(
            EVIDENCE_IDENTITY_HASH_DOMAIN,
            self._identity_payload(),
        )
        self._validate_or_set_hash(
            "identity_hash",
            expected_identity_hash,
            "evidence v4 identity_hash is invalid",
        )
        expected_content_hash = _canonical_hash(
            EVIDENCE_CONTENT_HASH_DOMAIN,
            self._content_payload(),
        )
        self._validate_or_set_hash(
            "content_hash",
            expected_content_hash,
            "evidence v4 content_hash is invalid",
        )

    def _validate_fixed_semantics(self) -> None:
        """Reject reinterpretation as another artifact or executable state."""

        for name, expected in (
            ("owner", OWNER),
            ("artifact_type", EVIDENCE_ARTIFACT_TYPE),
            ("schema", EVIDENCE_SCHEMA),
            ("assignment_state", ASSIGNMENT_STATE),
            ("permission", PERMISSION),
            ("status", STATUS),
        ):
            actual = getattr(self, name)
            if type(actual) is not str:
                raise TypeError(f"{name} must be an exact string")
            if actual != expected:
                raise ValueError(f"evidence v4 {name} is fixed")
        if type(self.blocker_codes) is not tuple:
            raise TypeError("blocker_codes must be an exact tuple")
        if self.blocker_codes != EVIDENCE_BLOCKERS:
            raise ValueError("evidence v4 blocker_codes are fixed")

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
        """Expose the claimant sealed by the nested Receipt v4."""

        return self.subject.claimant

    @property
    def policy(self) -> SingleOwnerAuthorityPolicyV1:
        """Expose the policy sealed by the nested Receipt v4."""

        return self.subject.policy

    @property
    def requested_at(self) -> datetime:
        """Expose the original source request clock from Subject v4."""

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
        """Return stable v4 evidence identity fields."""

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


def validate_account_owner_assignment_subject_v4_root(
    subject: AccountOwnerAssignmentSubjectV4,
) -> None:
    """Validate one immutable Subject v4 root value."""

    if type(subject) is not AccountOwnerAssignmentSubjectV4:
        raise TypeError("subject must be an exact owner-assignment subject v4")
    subject.__post_init__()


def validate_account_owner_assignment_evidence_v4_root(
    evidence: AccountOwnerAssignmentEvidenceV4,
) -> None:
    """Validate one immutable Evidence v4 root value."""

    if type(evidence) is not AccountOwnerAssignmentEvidenceV4:
        raise TypeError("evidence must be an exact owner-assignment evidence v4")
    evidence.__post_init__()


def validate_account_owner_assignment_evidence_v4_dual_mapping_root(
    evidence: AccountOwnerAssignmentEvidenceV4,
    *,
    account_claim_hash: str,
    underlying_claim_hash: str,
) -> None:
    """Require both candidate-independent mapping roots to match one exact evidence root."""

    validate_account_owner_assignment_evidence_v4_root(evidence)
    _digest(account_claim_hash, "account_claim_hash")
    _digest(underlying_claim_hash, "underlying_claim_hash")
    if (
        evidence.account_claim_hash != account_claim_hash
        or evidence.underlying_claim_hash != underlying_claim_hash
    ):
        raise ValueError("evidence v4 dual mapping root differs")


def resolve_account_owner_assignment_evidence_v4_final(
    chain: tuple[AccountOwnerAssignmentEvidenceV4, ...], *, as_of: datetime
) -> AccountOwnerAssignmentEvidenceV4 | None:
    """Return the sole historical root; v4 approval successors are unsupported."""

    cutoff = _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if len(chain) > 1:
        raise ValueError("evidence v4 successors are not supported")
    if not chain:
        return None
    evidence = chain[0]
    validate_account_owner_assignment_evidence_v4_root(evidence)
    return evidence if evidence.is_knowable_at(cutoff) else None


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_ASSIGNMENT_STATE",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_EVIDENCE_V4_STATUS",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_SUBJECT_V4_STATUS",
    "ASSIGNMENT_STATE",
    "EVIDENCE_ARTIFACT_TYPE",
    "EVIDENCE_BLOCKERS",
    "EVIDENCE_CONTENT_HASH_DOMAIN",
    "EVIDENCE_IDENTITY_HASH_DOMAIN",
    "EVIDENCE_SCHEMA",
    "OWNER",
    "PERMISSION",
    "STATUS",
    "SUBJECT_ARTIFACT_TYPE",
    "SUBJECT_BLOCKERS",
    "SUBJECT_CONTENT_HASH_DOMAIN",
    "SUBJECT_IDENTITY_HASH_DOMAIN",
    "SUBJECT_SCHEMA",
    "AccountOwnerAssignmentEvidenceV4",
    "AccountOwnerAssignmentSubjectV4",
    "resolve_account_owner_assignment_evidence_v4_final",
    "validate_account_owner_assignment_evidence_v4_dual_mapping_root",
    "validate_account_owner_assignment_evidence_v4_root",
    "validate_account_owner_assignment_subject_v4_root",
]
