"""Inactive claimant provenance bound exclusively to Account physical evidence v2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import AccountOwnerAssignmentActor
from apps.account.domain.physical_account_row_observation_v2 import (
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_ARTIFACT_TYPE,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SCHEMA,
    PhysicalAccountRowObservationV2,
)

ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_ARTIFACT_TYPE = (
    "account_owner_assignment_provenance_receipt_v2"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_SCHEMA = (
    "account-owner-assignment-provenance-receipt.v2"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_PERMISSION = "evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_BLOCKERS = (
    "account_owner_assignment_provenance_receipt_v2_not_integrated",
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
    return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentProvenanceReceiptV2:
    """Seal a human claimant statement; this receipt never establishes identity."""

    receipt_id: str
    receipt_version: str
    provenance_kind: str
    assignment_state: str
    assigned_owner_user_id: int | None
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_observation_owner: str
    row_observation_artifact_type: str
    row_observation_schema: str
    row_observation_id: str
    row_observation_version: str
    row_observation_identity_hash: str
    row_observation_content_hash: str
    row_observation_supersedes_content_hash: str | None
    row_observation_recorded_at: datetime
    row_observation_valid_until: datetime
    source_content_hash: str
    raw_observation_content_hash: str
    row_is_active: bool
    row_is_present: bool
    row_is_tombstone: bool
    row_user_id: int | None
    claimant: AccountOwnerAssignmentActor
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_ARTIFACT_TYPE
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_SCHEMA
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_BLOCKERS

    def __post_init__(self) -> None:
        fixed = (
            (self.owner, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_OWNER),
            (self.artifact_type, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_ARTIFACT_TYPE),
            (self.schema, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_SCHEMA),
            (self.permission, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_PERMISSION),
            (self.status, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_STATUS),
            (self.blocker_codes, ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_BLOCKERS),
            (self.row_observation_owner, PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_OWNER),
            (self.row_observation_artifact_type, PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_ARTIFACT_TYPE),
            (self.row_observation_schema, PHYSICAL_ACCOUNT_ROW_OBSERVATION_V2_SCHEMA),
        )
        if any(actual != expected for actual, expected in fixed):
            raise ValueError("v2 provenance fixed semantics are invalid")
        for name in (
            "receipt_id",
            "receipt_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "row_observation_id",
            "row_observation_version",
        ):
            _token(getattr(self, name), name)
        if (
            type(self.underlying_unified_account_id) is not int
            or self.underlying_unified_account_id <= 0
        ):
            raise ValueError("underlying_unified_account_id must be an exact positive integer")
        for name in (
            "row_observation_identity_hash",
            "row_observation_content_hash",
            "source_content_hash",
            "raw_observation_content_hash",
        ):
            _digest(getattr(self, name), name)
        for name in ("row_is_active", "row_is_present", "row_is_tombstone"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.row_is_present == self.row_is_tombstone:
            raise ValueError("row presence facts are inconsistent")
        if not self.row_is_active or not self.row_is_present or self.row_is_tombstone:
            raise ValueError("a new owner claim requires an exact live row")
        if self.row_user_id is not None and (
            type(self.row_user_id) is not int or self.row_user_id <= 0
        ):
            raise ValueError("row_user_id must be null or an exact positive integer")
        if self.row_observation_supersedes_content_hash is not None:
            _digest(
                self.row_observation_supersedes_content_hash,
                "row_observation_supersedes_content_hash",
            )
        if type(self.claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("claimant must be an exact AccountOwnerAssignmentActor")
        AccountOwnerAssignmentActor.__post_init__(self.claimant)
        if self.provenance_kind not in ("creation", "migration", "manual_reclaim"):
            raise ValueError("provenance_kind is invalid")
        if self.provenance_kind == "migration":
            if (
                self.assignment_state != "legacy_default_claim"
                or self.assigned_owner_user_id is not None
            ):
                raise ValueError("migration cannot assert an assigned owner")
            if not self.claimant.is_staff or self.claimant.role != "legacy_assignment_reviewer":
                raise ValueError("migration requires a human staff reviewer")
        else:
            if (
                self.assignment_state != "claimed_owner"
                or self.assigned_owner_user_id != self.claimant.user_id
            ):
                raise ValueError("claimant must assign only self")
            if self.claimant.role != "account_owner_claimant":
                raise ValueError("owner claim requires claimant role")
            if self.provenance_kind == "creation" and self.row_user_id != self.claimant.user_id:
                raise ValueError("creation claimant must equal the live row user")
        for name in (
            "row_observation_recorded_at",
            "row_observation_valid_until",
            "issued_at",
            "recorded_at",
            "valid_until",
        ):
            _aware(getattr(self, name), name)
        if (
            not self.row_observation_recorded_at
            <= self.issued_at
            <= self.recorded_at
            < self.valid_until
            <= self.row_observation_valid_until
        ):
            raise ValueError("receipt clock sequence is invalid")
        if self.supersedes_content_hash is not None:
            _digest(self.supersedes_content_hash, "supersedes_content_hash")
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
        """Remain false because a claimant receipt is not an approval."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because this contract grants no execution authority."""

        return True

    def is_current_at(self, as_of: datetime) -> bool:
        """Return whether this exact live-row claim is recorded and unexpired."""

        _aware(as_of, "as_of")
        return (
            self.recorded_at <= as_of < self.valid_until
            and self.row_is_active
            and self.row_is_present
            and not self.row_is_tombstone
        )

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
            "provenance_kind": self.provenance_kind,
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": self.underlying_unified_account_namespace,
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "row_observation_owner": self.row_observation_owner,
            "row_observation_artifact_type": self.row_observation_artifact_type,
            "row_observation_schema": self.row_observation_schema,
            "row_observation_id": self.row_observation_id,
            "row_observation_version": self.row_observation_version,
            "row_observation_identity_hash": self.row_observation_identity_hash,
            "row_observation_content_hash": self.row_observation_content_hash,
            "row_observation_supersedes_content_hash": self.row_observation_supersedes_content_hash,
            "row_observation_recorded_at": _utc(self.row_observation_recorded_at),
            "row_observation_valid_until": _utc(self.row_observation_valid_until),
            "source_content_hash": self.source_content_hash,
            "raw_observation_content_hash": self.raw_observation_content_hash,
            "row_is_active": self.row_is_active,
            "row_is_present": self.row_is_present,
            "row_is_tombstone": self.row_is_tombstone,
            "row_user_id": self.row_user_id,
            "claimant": self.claimant.to_payload(),
            "issued_at": _utc(self.issued_at),
            "recorded_at": _utc(self.recorded_at),
            "valid_until": _utc(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed claimant receipt without identity authority."""

        AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_provenance_receipt_v2_row(
    receipt: AccountOwnerAssignmentProvenanceReceiptV2, row: PhysicalAccountRowObservationV2
) -> None:
    """Recompute both caller-provided seals and require an exact v2 row binding."""
    if (
        type(receipt) is not AccountOwnerAssignmentProvenanceReceiptV2
        or type(row) is not PhysicalAccountRowObservationV2
    ):
        raise TypeError("receipt and row must be exact v2 values")
    AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(receipt)
    PhysicalAccountRowObservationV2.__post_init__(row)
    left = (
        receipt.account_namespace,
        receipt.account_id,
        receipt.underlying_unified_account_namespace,
        receipt.underlying_unified_account_id,
        receipt.row_observation_owner,
        receipt.row_observation_artifact_type,
        receipt.row_observation_schema,
        receipt.row_observation_id,
        receipt.row_observation_version,
        receipt.row_observation_identity_hash,
        receipt.row_observation_content_hash,
        receipt.row_observation_supersedes_content_hash,
        receipt.row_observation_recorded_at,
        receipt.row_observation_valid_until,
        receipt.source_content_hash,
        receipt.raw_observation_content_hash,
        receipt.row_is_active,
        receipt.row_is_present,
        receipt.row_is_tombstone,
        receipt.row_user_id,
    )
    right = (
        row.account_namespace,
        row.account_id,
        row.underlying_unified_account_namespace,
        row.underlying_unified_account_id,
        row.owner,
        row.artifact_type,
        row.schema,
        row.observation_id,
        row.observation_version,
        row.identity_hash,
        row.content_hash,
        row.supersedes_content_hash,
        row.recorded_at,
        row.valid_until,
        row.source_content_hash,
        row.raw_observation_content_hash,
        row.is_active,
        row.is_present,
        row.is_tombstone,
        row.row_user_id,
    )
    if left != right:
        raise ValueError("receipt does not bind the exact physical v2 row")
    if not row.is_knowable_at(receipt.recorded_at):
        raise ValueError("physical v2 row was not knowable when recorded")


def validate_account_owner_assignment_provenance_receipt_v2_root(
    root: AccountOwnerAssignmentProvenanceReceiptV2,
) -> None:
    """Require the first claimant receipt to have no receipt predecessor."""

    if type(root) is not AccountOwnerAssignmentProvenanceReceiptV2:
        raise TypeError("root must be an exact v2 receipt")
    AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(root)
    if root.supersedes_content_hash is not None:
        raise ValueError("root predecessor must be absent")


def validate_account_owner_assignment_provenance_receipt_v2_successor(
    previous: AccountOwnerAssignmentProvenanceReceiptV2,
    successor: AccountOwnerAssignmentProvenanceReceiptV2,
) -> None:
    """Validate adjacent claimant receipts and their exact v2 row link."""

    if (
        type(previous) is not AccountOwnerAssignmentProvenanceReceiptV2
        or type(successor) is not AccountOwnerAssignmentProvenanceReceiptV2
    ):
        raise TypeError("receipt versions must be exact v2 values")
    AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(previous)
    AccountOwnerAssignmentProvenanceReceiptV2.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind exact predecessor")
    for name in (
        "receipt_id",
        "provenance_kind",
        "assignment_state",
        "assigned_owner_user_id",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_observation_id",
        "claimant",
    ):
        if getattr(successor, name) != getattr(previous, name):
            raise ValueError(f"successor changed {name}")
    if successor.receipt_version == previous.receipt_version:
        raise ValueError("successor receipt_version must advance")
    if successor.row_observation_version == previous.row_observation_version:
        exact_row_fields = (
            "row_observation_identity_hash",
            "row_observation_content_hash",
            "row_observation_supersedes_content_hash",
            "row_observation_recorded_at",
            "row_observation_valid_until",
            "source_content_hash",
            "raw_observation_content_hash",
            "row_user_id",
            "row_is_active",
            "row_is_present",
            "row_is_tombstone",
        )
        if any(getattr(successor, name) != getattr(previous, name) for name in exact_row_fields):
            raise ValueError("same row version changed exact row evidence")
    elif successor.row_observation_supersedes_content_hash != previous.row_observation_content_hash:
        raise ValueError("successor row does not bind exact previous row")
    if successor.issued_at <= previous.issued_at or successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor clocks and versions must advance")


def resolve_account_owner_assignment_provenance_receipt_v2_head(
    chain: tuple[AccountOwnerAssignmentProvenanceReceiptV2, ...], *, as_of: datetime
) -> AccountOwnerAssignmentProvenanceReceiptV2 | None:
    """Return only the final PIT head; terminal/expired heads never fall back."""
    _aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    if chain:
        validate_account_owner_assignment_provenance_receipt_v2_root(chain[0])
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_account_owner_assignment_provenance_receipt_v2_successor(previous, successor)
    visible = tuple(item for item in chain if item.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_current_at(as_of) else None


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_V2_STATUS",
    "AccountOwnerAssignmentProvenanceReceiptV2",
    "resolve_account_owner_assignment_provenance_receipt_v2_head",
    "validate_account_owner_assignment_provenance_receipt_v2_root",
    "validate_account_owner_assignment_provenance_receipt_v2_row",
    "validate_account_owner_assignment_provenance_receipt_v2_successor",
]
