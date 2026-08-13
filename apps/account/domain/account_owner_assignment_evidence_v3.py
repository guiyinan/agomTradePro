"""Creation-only staff approval over one exact Account provenance receipt v3."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v3 import (
    AccountOwnerAssignmentProvenanceReceiptV3,
)
from apps.account.domain.allocated_physical_account_row_observation_v3 import (
    AllocatedPhysicalAccountRowObservationV3,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)

OWNER = "account"
SUBJECT_ARTIFACT_TYPE = "account_owner_assignment_subject_v3"
SUBJECT_SCHEMA = "account-owner-assignment-subject.v3"
EVIDENCE_ARTIFACT_TYPE = "account_owner_assignment_evidence_v3"
EVIDENCE_SCHEMA = "account-owner-assignment-evidence.v3"
PERMISSION = "evidence_only"
STATUS = "inactive"
SUBJECT_BLOCKERS = ("account_owner_assignment_subject_v3_not_integrated",)
EVIDENCE_BLOCKERS = ("account_owner_assignment_evidence_v3_not_integrated",)


def _token(value: object, name: str) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be an exact string")
    if not value or value.strip() != value or len(value) > 192 or any(c.isspace() for c in value):
        raise ValueError(f"{name} must be a bounded canonical token")
    return value


def _digest(value: object, name: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mapping_hash(domain: str, payload: dict[str, object]) -> str:
    return _hash({"domain": domain, **payload})


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentSubjectV3:
    """Seal one exact creation claim and its still-current physical creation root."""

    subject_id: str
    subject_version: str
    receipt: AccountOwnerAssignmentProvenanceReceiptV3
    binding: CanonicalAccountCreationBindingV2
    physical_root: AllocatedPhysicalAccountRowObservationV3
    receipt_identity_hash: str
    receipt_content_hash: str
    binding_identity_hash: str
    binding_content_hash: str
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
        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.permission,
            self.status,
            self.blocker_codes,
        ) != (OWNER, SUBJECT_ARTIFACT_TYPE, SUBJECT_SCHEMA, PERMISSION, STATUS, SUBJECT_BLOCKERS):
            raise ValueError("subject v3 fixed semantics are invalid")
        _token(self.subject_id, "subject_id")
        _token(self.subject_version, "subject_version")
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV3:
            raise TypeError("receipt must be an exact provenance receipt v3")
        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact canonical Binding v2")
        if type(self.physical_root) is not AllocatedPhysicalAccountRowObservationV3:
            raise TypeError("physical_root must be an exact allocated Physical v3")
        self.receipt.__post_init__()
        self.binding.__post_init__()
        self.physical_root.__post_init__()
        if self.receipt.binding != self.binding or self.binding.creation_root != self.physical_root:
            raise ValueError("subject v3 does not bind the exact receipt/binding/physical root")
        physical = self.physical_root.physical_observation
        for name, actual, expected in (
            ("receipt_identity_hash", self.receipt_identity_hash, self.receipt.identity_hash),
            ("receipt_content_hash", self.receipt_content_hash, self.receipt.content_hash),
            ("binding_identity_hash", self.binding_identity_hash, self.binding.identity_hash),
            ("binding_content_hash", self.binding_content_hash, self.binding.content_hash),
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
        ):
            _digest(actual, name)
            if actual != expected:
                raise ValueError(f"subject v3 {name} does not match exact upstream evidence")
        if self.receipt.provenance_kind != "creation":
            raise ValueError("subject v3 supports creation receipts only")
        _aware(self.requested_at, "requested_at")
        _aware(self.valid_until, "valid_until")
        if not self.receipt.recorded_at <= self.requested_at < self.valid_until:
            raise ValueError("subject v3 clock sequence is invalid")
        if self.valid_until != min(self.receipt.valid_until, self.physical_root.valid_until):
            raise ValueError("subject v3 validity must equal the exact upstream minimum")
        if not self.receipt.is_current_at(
            self.requested_at
        ) or not self.physical_root.is_knowable_at(self.requested_at):
            raise ValueError("subject v3 requires current receipt and Physical v3")
        expected_identity = _hash(self._identity_payload())
        if self.identity_hash and self.identity_hash != expected_identity:
            raise ValueError("subject v3 identity_hash is invalid")
        object.__setattr__(self, "identity_hash", expected_identity)
        expected_content = _hash(self._content_payload())
        if self.content_hash and self.content_hash != expected_content:
            raise ValueError("subject v3 content_hash is invalid")
        object.__setattr__(self, "content_hash", expected_content)

    @property
    def claimant(self) -> AccountOwnerAssignmentActor:
        """Expose only the claimant sealed by the receipt."""

        return self.receipt.claimant

    @property
    def activation_available(self) -> bool:
        """Remain false because a pending subject grants no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a pending subject cannot authorize execution."""

        return True

    def is_current_at(self, as_of: datetime) -> bool:
        """Require the subject and both short-lived upstream values to remain current."""

        _aware(as_of, "as_of")
        return (
            self.requested_at <= as_of < self.valid_until
            and self.receipt.is_current_at(as_of)
            and self.physical_root.is_knowable_at(as_of)
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "receipt": self.receipt.to_payload(),
            "binding": self.binding.to_payload(),
            "physical_root": self.physical_root.to_payload(),
            "receipt_identity_hash": self.receipt_identity_hash,
            "receipt_content_hash": self.receipt_content_hash,
            "binding_identity_hash": self.binding_identity_hash,
            "binding_content_hash": self.binding_content_hash,
            "creation_root_identity_hash": self.creation_root_identity_hash,
            "creation_root_content_hash": self.creation_root_content_hash,
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "physical_observation_content_hash": self.physical_observation_content_hash,
            "physical_source_content_hash": self.physical_source_content_hash,
            "physical_raw_observation_content_hash": self.physical_raw_observation_content_hash,
            "requested_at": _utc(self.requested_at),
            "valid_until": _utc(self.valid_until),
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical pending-subject payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentEvidenceV3:
    """Seal one independent staff approval of an exact creation claimant."""

    evidence_id: str
    evidence_version: str
    subject: AccountOwnerAssignmentSubjectV3
    assigned_owner_user_id: int
    approved_by: AccountOwnerAssignmentActor
    approved_at: datetime
    recorded_at: datetime
    approval_valid_until: datetime
    valid_until: datetime
    account_claim_hash: str = ""
    underlying_claim_hash: str = ""
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = EVIDENCE_ARTIFACT_TYPE
    schema: str = EVIDENCE_SCHEMA
    assignment_state: str = "authoritative"
    permission: str = PERMISSION
    status: str = STATUS
    blocker_codes: tuple[str, ...] = EVIDENCE_BLOCKERS

    def __post_init__(self) -> None:
        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.assignment_state,
            self.permission,
            self.status,
            self.blocker_codes,
        ) != (
            OWNER,
            EVIDENCE_ARTIFACT_TYPE,
            EVIDENCE_SCHEMA,
            "authoritative",
            PERMISSION,
            STATUS,
            EVIDENCE_BLOCKERS,
        ):
            raise ValueError("evidence v3 fixed semantics are invalid")
        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        if type(self.subject) is not AccountOwnerAssignmentSubjectV3:
            raise TypeError("subject must be an exact owner-assignment subject v3")
        self.subject.__post_init__()
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be an exact human actor")
        self.approved_by.__post_init__()
        claimant = self.subject.claimant
        if (
            not self.approved_by.is_staff
            or self.approved_by.role != "account_owner_assignment_approver"
        ):
            raise ValueError("approver must be human staff with assignment approver role")
        if (
            self.approved_by.actor_id == claimant.actor_id
            or self.approved_by.user_id == claimant.user_id
        ):
            raise ValueError("claimant and approver must be distinct actors and users")
        if self.assigned_owner_user_id != claimant.user_id:
            raise ValueError("authoritative owner must equal the exact creation claimant")
        for name in ("approved_at", "recorded_at", "approval_valid_until", "valid_until"):
            _aware(getattr(self, name), name)
        if not (
            self.subject.requested_at
            <= self.approved_at
            <= self.recorded_at
            < self.approval_valid_until
        ):
            raise ValueError("evidence v3 clock sequence is invalid")
        if self.valid_until != min(self.subject.valid_until, self.approval_valid_until):
            raise ValueError("evidence v3 validity must equal the exact upstream minimum")
        if not self.subject.is_current_at(self.recorded_at):
            raise ValueError("evidence v3 requires a current subject when recorded")
        account_claim = _mapping_hash(
            "account-owner-assignment-v3/account-root",
            {
                "account_namespace": self.subject.binding.account_namespace_claim,
                "account_id": self.subject.binding.account_id_claim,
            },
        )
        underlying_claim = _mapping_hash(
            "account-owner-assignment-v3/underlying-root",
            {
                "underlying_unified_account_namespace": (
                    self.subject.binding.underlying_unified_account_namespace_claim
                ),
                "underlying_unified_account_id": (
                    self.subject.binding.underlying_unified_account_id_claim
                ),
            },
        )
        for name, current, expected in (
            ("account_claim_hash", self.account_claim_hash, account_claim),
            ("underlying_claim_hash", self.underlying_claim_hash, underlying_claim),
        ):
            if not current:
                object.__setattr__(self, name, expected)
            else:
                _digest(current, name)
                if current != expected:
                    raise ValueError(f"{name} is invalid")
        expected_identity = _hash(self._identity_payload())
        if self.identity_hash and self.identity_hash != expected_identity:
            raise ValueError("evidence v3 identity_hash is invalid")
        object.__setattr__(self, "identity_hash", expected_identity)
        expected_content = _hash(self._content_payload())
        if self.content_hash and self.content_hash != expected_content:
            raise ValueError("evidence v3 content_hash is invalid")
        object.__setattr__(self, "content_hash", expected_content)

    @property
    def activation_available(self) -> bool:
        """Remain false because assignment evidence is not activation authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because assignment evidence is not execution authority."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this immutable approval had been recorded by one PIT."""

        _aware(as_of, "as_of")
        return self.recorded_at <= as_of

    def is_current_at(self, as_of: datetime) -> bool:
        """Require this approval and its complete subject to remain current."""

        _aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until and self.subject.is_current_at(as_of)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "evidence_id": self.evidence_id,
            "evidence_version": self.evidence_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "subject": self.subject.to_payload(),
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "approved_by": self.approved_by.to_payload(),
            "approved_at": _utc(self.approved_at),
            "recorded_at": _utc(self.recorded_at),
            "approval_valid_until": _utc(self.approval_valid_until),
            "valid_until": _utc(self.valid_until),
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete canonical approval-evidence payload."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_evidence_v3_root(
    evidence: AccountOwnerAssignmentEvidenceV3,
) -> None:
    """Validate the only supported root form; v3 successors are intentionally absent."""

    if type(evidence) is not AccountOwnerAssignmentEvidenceV3:
        raise TypeError("evidence must be an exact owner-assignment evidence v3")
    evidence.__post_init__()


def validate_account_owner_assignment_evidence_v3_dual_mapping_root(
    evidence: AccountOwnerAssignmentEvidenceV3,
    *,
    account_claim_hash: str,
    underlying_claim_hash: str,
) -> None:
    """Require both candidate-independent mapping roots to match one exact evidence root."""

    validate_account_owner_assignment_evidence_v3_root(evidence)
    _digest(account_claim_hash, "account_claim_hash")
    _digest(underlying_claim_hash, "underlying_claim_hash")
    if (
        evidence.account_claim_hash != account_claim_hash
        or evidence.underlying_claim_hash != underlying_claim_hash
    ):
        raise ValueError("evidence v3 dual mapping root differs")


def resolve_account_owner_assignment_evidence_v3_final(
    chain: tuple[AccountOwnerAssignmentEvidenceV3, ...], *, as_of: datetime
) -> AccountOwnerAssignmentEvidenceV3 | None:
    """Return the sole historical root once recorded; successors and fallback are unsupported."""

    _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if len(chain) > 1:
        raise ValueError("evidence v3 successors are not supported")
    if not chain:
        return None
    evidence = chain[0]
    validate_account_owner_assignment_evidence_v3_root(evidence)
    return evidence if evidence.is_knowable_at(as_of) else None


__all__ = [
    "AccountOwnerAssignmentEvidenceV3",
    "AccountOwnerAssignmentSubjectV3",
    "EVIDENCE_ARTIFACT_TYPE",
    "EVIDENCE_BLOCKERS",
    "EVIDENCE_SCHEMA",
    "OWNER",
    "PERMISSION",
    "STATUS",
    "SUBJECT_ARTIFACT_TYPE",
    "SUBJECT_BLOCKERS",
    "SUBJECT_SCHEMA",
    "resolve_account_owner_assignment_evidence_v3_final",
    "validate_account_owner_assignment_evidence_v3_dual_mapping_root",
    "validate_account_owner_assignment_evidence_v3_root",
]
