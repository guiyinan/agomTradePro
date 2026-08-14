"""Final inactive owner-assignment evidence over Account physical evidence v2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.account_owner_assignment_provenance_receipt_v2 import (
    AccountOwnerAssignmentProvenanceReceiptV2,
    validate_account_owner_assignment_provenance_receipt_v2_row,
)
from apps.account.domain.physical_account_row_observation_v2 import (
    PhysicalAccountRowObservationV2,
)

OWNER = "account"
SUBJECT_ARTIFACT_TYPE = "account_owner_assignment_subject_v2"
SUBJECT_SCHEMA = "account-owner-assignment-subject.v2"
EVIDENCE_ARTIFACT_TYPE = "account_owner_assignment_evidence_v2"
EVIDENCE_SCHEMA = "account-owner-assignment-evidence.v2"
PERMISSION = "evidence_only"
STATUS = "inactive"
BLOCKERS = ("account_owner_assignment_evidence_v2_not_integrated",)


def _aware(value: object, name: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


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


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _hash(payload: dict[str, object]) -> str:
    value = json.dumps(
        payload, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _claim_hash(domain: str, payload: dict[str, object]) -> str:
    return _hash({"domain": domain, **payload})


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentSubjectV2:
    """Immutable candidate subject whose two complete inputs are revalidated."""

    subject_id: str
    subject_version: str
    physical: PhysicalAccountRowObservationV2
    receipt: AccountOwnerAssignmentProvenanceReceiptV2
    requested_at: datetime
    valid_until: datetime
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = SUBJECT_ARTIFACT_TYPE
    schema: str = SUBJECT_SCHEMA
    permission: str = PERMISSION
    status: str = STATUS

    def __post_init__(self) -> None:
        if (self.owner, self.artifact_type, self.schema, self.permission, self.status) != (
            OWNER,
            SUBJECT_ARTIFACT_TYPE,
            SUBJECT_SCHEMA,
            PERMISSION,
            STATUS,
        ):
            raise ValueError("subject fixed semantics are invalid")
        _token(self.subject_id, "subject_id")
        _token(self.subject_version, "subject_version")
        if type(self.physical) is not PhysicalAccountRowObservationV2:
            raise TypeError("physical must be exact PhysicalAccountRowObservationV2")
        if type(self.receipt) is not AccountOwnerAssignmentProvenanceReceiptV2:
            raise TypeError("receipt must be exact v2 receipt; v1 substitution is forbidden")
        PhysicalAccountRowObservationV2.__post_init__(self.physical)
        AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(self.receipt)
        validate_account_owner_assignment_provenance_receipt_v2_row(self.receipt, self.physical)
        _aware(self.requested_at, "requested_at")
        _aware(self.valid_until, "valid_until")
        if not self.receipt.recorded_at <= self.requested_at < self.valid_until:
            raise ValueError("subject clock sequence is invalid")
        if self.valid_until != min(self.physical.valid_until, self.receipt.valid_until):
            raise ValueError("subject validity must be the exact upstream minimum")
        identity = _hash(self._identity_payload())
        if self.identity_hash and self.identity_hash != identity:
            raise ValueError("subject identity_hash is invalid")
        object.__setattr__(self, "identity_hash", identity)
        content = _hash(self._content_payload())
        if self.content_hash and self.content_hash != content:
            raise ValueError("subject content_hash is invalid")
        object.__setattr__(self, "content_hash", content)

    @property
    def claimant(self) -> AccountOwnerAssignmentActor:
        """Expose only the claimant already sealed by the receipt."""
        return self.receipt.claimant

    def is_current_at(self, as_of: datetime) -> bool:
        """Require both upstream values and this subject to remain current."""
        _aware(as_of, "as_of")
        return (
            self.requested_at <= as_of < self.valid_until
            and self.physical.is_current_at(as_of)
            and self.receipt.is_current_at(as_of)
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
            "account_namespace": self.physical.account_namespace,
            "account_id": self.physical.account_id,
            "underlying_unified_account_namespace": self.physical.underlying_unified_account_namespace,
            "underlying_unified_account_id": self.physical.underlying_unified_account_id,
            "physical_identity_hash": self.physical.identity_hash,
            "physical_content_hash": self.physical.content_hash,
            "physical_source_content_hash": self.physical.source_content_hash,
            "physical_raw_content_hash": self.physical.raw_observation_content_hash,
            "physical_recorded_at": _utc(self.physical.recorded_at),
            "physical_valid_until": _utc(self.physical.valid_until),
            "physical_is_present": self.physical.is_present,
            "physical_is_tombstone": self.physical.is_tombstone,
            "receipt_identity_hash": self.receipt.identity_hash,
            "receipt_content_hash": self.receipt.content_hash,
            "receipt_recorded_at": _utc(self.receipt.recorded_at),
            "receipt_valid_until": _utc(self.receipt.valid_until),
            "claimant": self.claimant.to_payload(),
            "requested_at": _utc(self.requested_at),
            "valid_until": _utc(self.valid_until),
            "permission": self.permission,
            "status": self.status,
        }

    def to_payload(self) -> dict[str, object]:
        """Return exact subject seals without approval or authority."""
        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentEvidenceV2:
    """Two-person final assignment evidence that still grants no execution authority."""

    evidence_id: str
    evidence_version: str
    subject: AccountOwnerAssignmentSubjectV2
    assignment_state: str
    assigned_owner_user_id: int | None
    approved_by: AccountOwnerAssignmentActor
    approved_at: datetime
    recorded_at: datetime
    approval_valid_until: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    account_claim_hash: str = ""
    underlying_claim_hash: str = ""
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = OWNER
    artifact_type: str = EVIDENCE_ARTIFACT_TYPE
    schema: str = EVIDENCE_SCHEMA
    permission: str = PERMISSION
    status: str = STATUS
    blocker_codes: tuple[str, ...] = BLOCKERS

    def __post_init__(self) -> None:
        if (
            self.owner,
            self.artifact_type,
            self.schema,
            self.permission,
            self.status,
            self.blocker_codes,
        ) != (OWNER, EVIDENCE_ARTIFACT_TYPE, EVIDENCE_SCHEMA, PERMISSION, STATUS, BLOCKERS):
            raise ValueError("evidence fixed semantics are invalid")
        _token(self.evidence_id, "evidence_id")
        _token(self.evidence_version, "evidence_version")
        if type(self.subject) is not AccountOwnerAssignmentSubjectV2:
            raise TypeError("subject must be exact AccountOwnerAssignmentSubjectV2")
        self.subject.__post_init__()
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be exact AccountOwnerAssignmentActor")
        AccountOwnerAssignmentActor.__post_init__(self.approved_by)
        if (
            not self.approved_by.is_staff
            or self.approved_by.role != "account_owner_assignment_approver"
        ):
            raise ValueError("approver must be human staff with assignment approver role")
        claimant = self.subject.claimant
        if (
            claimant.actor_id == self.approved_by.actor_id
            or claimant.user_id == self.approved_by.user_id
        ):
            raise ValueError("claimant and approver must be distinct actors and users")
        if self.subject.receipt.assignment_state == "claimed_owner":
            if (
                self.assignment_state != "authoritative"
                or self.assigned_owner_user_id != claimant.user_id
            ):
                raise ValueError(
                    "claimed owner requires independent approval of the exact claimant"
                )
        elif self.subject.receipt.assignment_state == "legacy_default_claim":
            if self.assignment_state != "legacy_default" or self.assigned_owner_user_id is not None:
                raise ValueError("legacy claim must remain ownerless legacy_default")
        else:
            raise ValueError("unsupported receipt assignment state")
        for name in ("approved_at", "recorded_at", "approval_valid_until", "valid_until"):
            _aware(getattr(self, name), name)
        if not (
            self.subject.requested_at
            <= self.approved_at
            <= self.recorded_at
            < self.approval_valid_until
        ):
            raise ValueError("evidence clock sequence is invalid")
        if self.valid_until != min(self.subject.valid_until, self.approval_valid_until):
            raise ValueError("evidence validity must equal the approval/upstream minimum")
        if self.supersedes_content_hash is not None:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")
        account_claim = _claim_hash(
            "account-owner-assignment-v2/account-root",
            {
                "account_namespace": self.subject.physical.account_namespace,
                "account_id": self.subject.physical.account_id,
            },
        )
        underlying_claim = _claim_hash(
            "account-owner-assignment-v2/underlying-root",
            {
                "underlying_unified_account_namespace": self.subject.physical.underlying_unified_account_namespace,
                "underlying_unified_account_id": self.subject.physical.underlying_unified_account_id,
            },
        )
        for given, expected, name in (
            (self.account_claim_hash, account_claim, "account_claim_hash"),
            (self.underlying_claim_hash, underlying_claim, "underlying_claim_hash"),
        ):
            if given and given != expected:
                raise ValueError(f"{name} is invalid")
            object.__setattr__(self, name, expected)
        identity = _hash(self._identity_payload())
        if self.identity_hash and self.identity_hash != identity:
            raise ValueError("identity_hash is invalid")
        object.__setattr__(self, "identity_hash", identity)
        content = _hash(self._content_payload())
        if self.content_hash and self.content_hash != content:
            raise ValueError("content_hash is invalid")
        object.__setattr__(self, "content_hash", content)

    @property
    def activation_available(self) -> bool:
        """Remain false: authoritative identity evidence is not execution permission."""
        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true for this inactive evidence contract."""
        return True

    def is_current_at(self, as_of: datetime) -> bool:
        """Return only an unexpired final value whose complete subject remains current."""
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
        row = self.subject.physical
        receipt = self.subject.receipt
        return {
            **self._identity_payload(),
            "account_namespace": row.account_namespace,
            "account_id": row.account_id,
            "underlying_unified_account_namespace": row.underlying_unified_account_namespace,
            "underlying_unified_account_id": row.underlying_unified_account_id,
            "physical_identity_hash": row.identity_hash,
            "physical_content_hash": row.content_hash,
            "physical_source_content_hash": row.source_content_hash,
            "physical_raw_content_hash": row.raw_observation_content_hash,
            "physical_recorded_at": _utc(row.recorded_at),
            "physical_valid_until": _utc(row.valid_until),
            "physical_is_present": row.is_present,
            "physical_is_tombstone": row.is_tombstone,
            "receipt_identity_hash": receipt.identity_hash,
            "receipt_content_hash": receipt.content_hash,
            "receipt_recorded_at": _utc(receipt.recorded_at),
            "receipt_valid_until": _utc(receipt.valid_until),
            "subject_identity_hash": self.subject.identity_hash,
            "subject_content_hash": self.subject.content_hash,
            "claimant": self.subject.claimant.to_payload(),
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "approved_by": self.approved_by.to_payload(),
            "approved_at": _utc(self.approved_at),
            "recorded_at": _utc(self.recorded_at),
            "approval_valid_until": _utc(self.approval_valid_until),
            "valid_until": _utc(self.valid_until),
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete immutable evidence payload."""
        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_evidence_v2_root(
    root: AccountOwnerAssignmentEvidenceV2,
) -> None:
    """Validate a dual-key root without binding candidate content into root claims."""
    if type(root) is not AccountOwnerAssignmentEvidenceV2:
        raise TypeError("root must be exact AccountOwnerAssignmentEvidenceV2")
    root.__post_init__()
    if root.supersedes_content_hash is not None:
        raise ValueError("root predecessor must be absent")


def validate_account_owner_assignment_evidence_v2_successor(
    previous: AccountOwnerAssignmentEvidenceV2, successor: AccountOwnerAssignmentEvidenceV2
) -> None:
    """Require exact predecessor and immutable mapping on both claim roots."""
    if (
        type(previous) is not AccountOwnerAssignmentEvidenceV2
        or type(successor) is not AccountOwnerAssignmentEvidenceV2
    ):
        raise TypeError("chain values must be exact v2 evidence")
    previous.__post_init__()
    successor.__post_init__()
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind exact predecessor")
    for name in ("evidence_id", "account_claim_hash", "underlying_claim_hash"):
        if getattr(successor, name) != getattr(previous, name):
            raise ValueError(f"successor changed {name}")
    for name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
    ):
        if getattr(successor.subject.physical, name) != getattr(previous.subject.physical, name):
            raise ValueError(f"successor changed {name}")
    if successor.subject.physical.observation_id != previous.subject.physical.observation_id:
        raise ValueError("successor changed physical observation_id")
    if successor.subject.physical != previous.subject.physical:
        if (
            successor.subject.physical.supersedes_content_hash
            != previous.subject.physical.content_hash
            or successor.subject.physical.observation_version
            == previous.subject.physical.observation_version
        ):
            raise ValueError("successor physical evidence is not adjacent")
    if successor.subject.receipt.receipt_id != previous.subject.receipt.receipt_id:
        raise ValueError("successor changed claimant receipt_id")
    if successor.subject.receipt != previous.subject.receipt:
        if (
            successor.subject.receipt.supersedes_content_hash
            != previous.subject.receipt.content_hash
            or successor.subject.receipt.receipt_version == previous.subject.receipt.receipt_version
        ):
            raise ValueError("successor claimant receipt is not adjacent")
    if successor.evidence_version == previous.evidence_version:
        raise ValueError("successor evidence_version must advance")
    if successor.subject.subject_version == previous.subject.subject_version:
        raise ValueError("successor subject_version must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


def resolve_account_owner_assignment_evidence_v2_head(
    chain: tuple[AccountOwnerAssignmentEvidenceV2, ...], *, as_of: datetime
) -> AccountOwnerAssignmentEvidenceV2 | None:
    """Return only the final visible live head; never fall back from invalid heads."""
    _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if chain:
        validate_account_owner_assignment_evidence_v2_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_account_owner_assignment_evidence_v2_successor(previous, successor)
    visible = tuple(value for value in chain if value.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(as_of) else None


__all__ = [
    "AccountOwnerAssignmentEvidenceV2",
    "AccountOwnerAssignmentSubjectV2",
    "resolve_account_owner_assignment_evidence_v2_head",
    "validate_account_owner_assignment_evidence_v2_root",
    "validate_account_owner_assignment_evidence_v2_successor",
]
