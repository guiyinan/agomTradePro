"""Inactive creation-claim receipt bound only to canonical Binding v2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)

ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_ARTIFACT_TYPE = (
    "account_owner_assignment_provenance_receipt_v3"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_SCHEMA = (
    "account-owner-assignment-provenance-receipt.v3"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_PERMISSION = "claim_evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_BLOCKERS = (
    "account_owner_assignment_provenance_receipt_v3_not_integrated",
)


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


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentProvenanceReceiptV3:
    """Seal one human creation claim without granting owner authority."""

    receipt_id: str
    receipt_version: str
    binding: CanonicalAccountCreationBindingV2
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    allocation_identity_hash: str
    allocation_content_hash: str
    creation_root_identity_hash: str
    creation_root_content_hash: str
    binding_identity_hash: str
    binding_content_hash: str
    account_claim_hash: str
    underlying_claim_hash: str
    physical_observation_content_hash: str
    physical_source_content_hash: str
    physical_raw_observation_content_hash: str
    assigned_owner_user_id: int
    claimant: AccountOwnerAssignmentActor
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_ARTIFACT_TYPE
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_SCHEMA
    provenance_kind: str = "creation"
    assignment_state: str = "claimed_owner"
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_BLOCKERS

    def __post_init__(self) -> None:
        fixed = (
            (self.owner, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_OWNER),
            (self.artifact_type, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_ARTIFACT_TYPE),
            (self.schema, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_SCHEMA),
            (self.provenance_kind, "creation"),
            (self.assignment_state, "claimed_owner"),
            (self.permission, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_PERMISSION),
            (self.status, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_STATUS),
            (self.blocker_codes, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_BLOCKERS),
        )
        if any(actual != expected for actual, expected in fixed):
            raise ValueError("v3 creation-claim semantics are fixed")
        for name in (
            "receipt_id",
            "receipt_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
        ):
            _token(getattr(self, name), name)
        if (
            type(self.underlying_unified_account_id) is not int
            or self.underlying_unified_account_id <= 0
        ):
            raise ValueError("underlying_unified_account_id must be an exact positive integer")
        if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
            raise ValueError("assigned_owner_user_id must be an exact positive integer")
        for name in (
            "allocation_identity_hash",
            "allocation_content_hash",
            "creation_root_identity_hash",
            "creation_root_content_hash",
            "binding_identity_hash",
            "binding_content_hash",
            "account_claim_hash",
            "underlying_claim_hash",
            "physical_observation_content_hash",
            "physical_source_content_hash",
            "physical_raw_observation_content_hash",
        ):
            _digest(getattr(self, name), name)
        if type(self.binding) is not CanonicalAccountCreationBindingV2:
            raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
        self.binding.__post_init__()
        if type(self.claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("claimant must be an exact AccountOwnerAssignmentActor")
        self.claimant.__post_init__()
        if self.claimant.role != "account_owner_claimant" or self.claimant.is_staff:
            raise ValueError("creation claim requires a non-staff human claimant")
        allocation = self.binding.allocation
        physical = self.binding.creation_root.physical_observation
        if not (
            self.assigned_owner_user_id
            == self.claimant.user_id
            == allocation.requested_row_user_id
            == physical.row_user_id
        ):
            raise ValueError("creation claimant must equal allocation and physical row user")
        for name in ("issued_at", "recorded_at", "valid_until"):
            _aware(getattr(self, name), name)
        if not self.binding.recorded_at <= self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("receipt clock sequence is invalid")
        if self.valid_until > min(allocation.valid_until, self.binding.creation_root.valid_until):
            raise ValueError("receipt cannot outlive allocation or creation root")
        if not self.binding.creation_root.is_knowable_at(self.recorded_at):
            raise ValueError("creation root must be current when receipt is recorded")
        if self.supersedes_content_hash is not None:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")
        validate_account_owner_assignment_provenance_receipt_v3_binding(self, self.binding)
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
        """Remain false because a claimant receipt is not approval."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this receipt grants no execution authority."""

        return True

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact claim is recorded and unexpired."""

        _aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

    def _identity_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "receipt_version": self.receipt_version,
        }

    def _content_payload(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "binding": self.binding.to_payload(),
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": self.underlying_unified_account_namespace,
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "allocation_identity_hash": self.allocation_identity_hash,
            "allocation_content_hash": self.allocation_content_hash,
            "creation_root_identity_hash": self.creation_root_identity_hash,
            "creation_root_content_hash": self.creation_root_content_hash,
            "binding_identity_hash": self.binding_identity_hash,
            "binding_content_hash": self.binding_content_hash,
            "account_claim_hash": self.account_claim_hash,
            "underlying_claim_hash": self.underlying_claim_hash,
            "physical_observation_content_hash": self.physical_observation_content_hash,
            "physical_source_content_hash": self.physical_source_content_hash,
            "physical_raw_observation_content_hash": self.physical_raw_observation_content_hash,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "claimant": self.claimant.to_payload(),
            "issued_at": _utc(self.issued_at),
            "recorded_at": _utc(self.recorded_at),
            "valid_until": _utc(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "provenance_kind": self.provenance_kind,
            "assignment_state": self.assignment_state,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the complete sealed creation-claim receipt."""

        self.__post_init__()
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_provenance_receipt_v3_binding(
    receipt: AccountOwnerAssignmentProvenanceReceiptV3,
    binding: CanonicalAccountCreationBindingV2,
) -> None:
    """Require every receipt claim and seal to match one exact Binding v2."""

    if type(receipt) is not AccountOwnerAssignmentProvenanceReceiptV3:
        raise TypeError("receipt must be an exact v3 receipt")
    if type(binding) is not CanonicalAccountCreationBindingV2:
        raise TypeError("binding must be an exact CanonicalAccountCreationBindingV2")
    binding.__post_init__()
    allocation = binding.allocation
    root = binding.creation_root
    physical = root.physical_observation
    actual = (
        receipt.binding,
        receipt.account_namespace,
        receipt.account_id,
        receipt.underlying_unified_account_namespace,
        receipt.underlying_unified_account_id,
        receipt.allocation_identity_hash,
        receipt.allocation_content_hash,
        receipt.creation_root_identity_hash,
        receipt.creation_root_content_hash,
        receipt.binding_identity_hash,
        receipt.binding_content_hash,
        receipt.account_claim_hash,
        receipt.underlying_claim_hash,
        receipt.physical_observation_content_hash,
        receipt.physical_source_content_hash,
        receipt.physical_raw_observation_content_hash,
    )
    expected = (
        binding,
        binding.account_namespace_claim,
        binding.account_id_claim,
        binding.underlying_unified_account_namespace_claim,
        binding.underlying_unified_account_id_claim,
        allocation.identity_hash,
        allocation.content_hash,
        root.identity_hash,
        root.content_hash,
        binding.identity_hash,
        binding.content_hash,
        binding.account_claim_hash,
        binding.underlying_claim_hash,
        physical.content_hash,
        physical.source_content_hash,
        physical.raw_observation_content_hash,
    )
    if actual != expected:
        raise ValueError("receipt does not bind the exact canonical Binding v2")


def validate_account_owner_assignment_provenance_receipt_v3_root(
    root: AccountOwnerAssignmentProvenanceReceiptV3,
) -> None:
    """Require the first v3 receipt to have no predecessor."""

    if type(root) is not AccountOwnerAssignmentProvenanceReceiptV3:
        raise TypeError("root must be an exact v3 receipt")
    root.__post_init__()
    if root.supersedes_content_hash is not None:
        raise ValueError("root predecessor must be absent")


def validate_account_owner_assignment_provenance_receipt_v3_successor(
    previous: AccountOwnerAssignmentProvenanceReceiptV3,
    successor: AccountOwnerAssignmentProvenanceReceiptV3,
) -> None:
    """Validate adjacent versions of one exact creation claim."""

    if (
        type(previous) is not AccountOwnerAssignmentProvenanceReceiptV3
        or type(successor) is not AccountOwnerAssignmentProvenanceReceiptV3
    ):
        raise TypeError("receipt versions must be exact v3 values")
    previous.__post_init__()
    successor.__post_init__()
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind exact predecessor")
    for name in (
        "receipt_id",
        "binding",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "assigned_owner_user_id",
        "claimant",
    ):
        if getattr(successor, name) != getattr(previous, name):
            raise ValueError(f"successor changed {name}")
    if successor.receipt_version == previous.receipt_version:
        raise ValueError("successor receipt_version must advance")
    if successor.issued_at <= previous.issued_at or successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor clocks must advance")


def resolve_account_owner_assignment_provenance_receipt_v3_head(
    chain: tuple[AccountOwnerAssignmentProvenanceReceiptV3, ...], *, as_of: datetime
) -> AccountOwnerAssignmentProvenanceReceiptV3 | None:
    """Return only the final PIT head; an expired head never falls back."""

    _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if chain:
        validate_account_owner_assignment_provenance_receipt_v3_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_account_owner_assignment_provenance_receipt_v3_successor(previous, successor)
    visible = tuple(receipt for receipt in chain if receipt.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(as_of) else None


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V3_STATUS",
    "AccountOwnerAssignmentProvenanceReceiptV3",
    "resolve_account_owner_assignment_provenance_receipt_v3_head",
    "validate_account_owner_assignment_provenance_receipt_v3_binding",
    "validate_account_owner_assignment_provenance_receipt_v3_root",
    "validate_account_owner_assignment_provenance_receipt_v3_successor",
]
