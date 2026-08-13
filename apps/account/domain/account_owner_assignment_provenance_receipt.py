"""Account-owned inactive provenance receipts for owner-assignment claims."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.domain.account_owner_assignment_evidence import (
    ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE,
    ACCOUNT_OWNER_ASSIGNMENT_OWNER,
    ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE,
    AccountOwnerAssignmentActor,
)
from apps.account.domain.physical_account_row_observation import (
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER,
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA,
    PhysicalAccountRowObservation,
)

ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_OWNER = ACCOUNT_OWNER_ASSIGNMENT_OWNER
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_SCHEMA = (
    "account-owner-assignment-provenance-receipt.v1"
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_PERMISSION = "evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_BLOCKERS = (
    "account_owner_assignment_provenance_receipt_provider_not_integrated",
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_KINDS = (
    "creation",
    "migration",
    "manual_reclaim",
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATES = (
    "authoritative",
    "legacy_default",
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ARTIFACT_TYPES = (
    "account_creation_receipt",
    "account_legacy_default_assignment_receipt",
    "account_owner_reclaim_receipt",
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ACCOUNT_NAMESPACE = (
    ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_UNDERLYING_NAMESPACE = (
    ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE
)
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ROW_OWNER = PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ROW_ARTIFACT_TYPE = (
    PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE
)

_ARTIFACT_TYPE_BY_KIND: dict[str, str] = {
    "creation": "account_creation_receipt",
    "migration": "account_legacy_default_assignment_receipt",
    "manual_reclaim": "account_owner_reclaim_receipt",
}
_CLAIMANT_ROLE_BY_KIND: dict[str, str] = {
    "creation": "account_owner_claimant",
    "migration": "legacy_assignment_reviewer",
    "manual_reclaim": "account_owner_claimant",
}


def _require_token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
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
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _physical_row_identity_hash(observation_id: str, observation_version: str) -> str:
    return _canonical_hash(
        {
            "owner": PHYSICAL_ACCOUNT_ROW_OBSERVATION_OWNER,
            "artifact_type": PHYSICAL_ACCOUNT_ROW_OBSERVATION_ARTIFACT_TYPE,
            "schema": PHYSICAL_ACCOUNT_ROW_OBSERVATION_SCHEMA,
            "observation_id": observation_id,
            "observation_version": observation_version,
        }
    )


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentProvenanceReceipt:
    """Seal one claimant-side provenance definition without approval authority.

    Creation and manual-reclaim claimants assert their own ownership. A migration
    claimant is a current staff reviewer attesting only that the row has a legacy
    default assignment; the reviewer is never promoted to assigned owner. The
    independent second-person approval remains exclusively in the downstream
    ``AccountOwnerAssignmentEvidence`` contract.
    """

    receipt_id: str
    receipt_version: str
    provenance_kind: str
    artifact_type: str
    assignment_state: str
    assigned_owner_user_id: int | None
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    row_observation_owner: str
    row_observation_artifact_type: str
    row_observation_id: str
    row_observation_version: str
    row_observation_identity_hash: str
    row_observation_content_hash: str
    row_observation_valid_until: datetime
    claimant: AccountOwnerAssignmentActor
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_OWNER
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_SCHEMA
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_BLOCKERS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "receipt_id",
            "receipt_version",
            "provenance_kind",
            "artifact_type",
            "assignment_state",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "row_observation_owner",
            "row_observation_artifact_type",
            "row_observation_id",
            "row_observation_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        self._validate_row_reference()
        if type(self.claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("claimant must be an exact AccountOwnerAssignmentActor")
        AccountOwnerAssignmentActor.__post_init__(self.claimant)
        self._validate_provenance()
        for field_name in (
            "row_observation_valid_until",
            "issued_at",
            "recorded_at",
            "valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        if not self.issued_at <= self.recorded_at < self.valid_until:
            raise ValueError("provenance receipt clock sequence is invalid")
        if self.valid_until > self.row_observation_valid_until:
            raise ValueError("receipt cannot outlive row observation validity")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("provenance receipt identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("provenance receipt content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        fixed = (
            (
                self.owner,
                ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_OWNER,
                "owner",
            ),
            (
                self.schema,
                ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_SCHEMA,
                "schema",
            ),
            (
                self.permission,
                ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_PERMISSION,
                "permission",
            ),
            (
                self.status,
                ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATUS,
                "status",
            ),
        )
        for actual, expected, field_name in fixed:
            if actual != expected:
                raise ValueError(f"provenance receipt {field_name} is fixed")
        if self.blocker_codes != ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_BLOCKERS:
            raise ValueError("provenance receipt blocker_codes are fixed")

    def _validate_row_reference(self) -> None:
        if self.account_namespace != ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ACCOUNT_NAMESPACE:
            raise ValueError("account_namespace is fixed")
        if (
            self.underlying_unified_account_namespace
            != ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_UNDERLYING_NAMESPACE
        ):
            raise ValueError("underlying_unified_account_namespace is fixed")
        if self.row_observation_owner != ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ROW_OWNER:
            raise ValueError("row_observation_owner is fixed")
        if (
            self.row_observation_artifact_type
            != ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ROW_ARTIFACT_TYPE
        ):
            raise ValueError("row_observation_artifact_type is fixed")
        _require_hash(
            self.row_observation_identity_hash,
            "row_observation_identity_hash",
        )
        _require_hash(
            self.row_observation_content_hash,
            "row_observation_content_hash",
        )
        expected_row_identity_hash = _physical_row_identity_hash(
            self.row_observation_id,
            self.row_observation_version,
        )
        if self.row_observation_identity_hash != expected_row_identity_hash:
            raise ValueError("row_observation_identity_hash is invalid")

    def _validate_provenance(self) -> None:
        if self.provenance_kind not in ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_KINDS:
            raise ValueError("provenance_kind is invalid")
        expected_artifact_type = _ARTIFACT_TYPE_BY_KIND[self.provenance_kind]
        if self.artifact_type != expected_artifact_type:
            raise ValueError("provenance receipt artifact_type is invalid for its kind")
        expected_claimant_role = _CLAIMANT_ROLE_BY_KIND[self.provenance_kind]
        if self.claimant.role != expected_claimant_role:
            raise ValueError("provenance receipt claimant role is invalid for its kind")
        if self.provenance_kind == "migration":
            if self.assignment_state != "legacy_default":
                raise ValueError("migration receipt requires legacy_default assignment")
            if self.assigned_owner_user_id is not None:
                raise ValueError("legacy_default receipt cannot claim an owner")
            if self.claimant.is_staff is not True:
                raise ValueError("migration claimant must be a human staff reviewer")
            return
        if self.assignment_state != "authoritative":
            raise ValueError("creation and manual_reclaim require authoritative assignment")
        if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
            raise ValueError("authoritative receipt requires an exact positive owner")
        if self.assigned_owner_user_id != self.claimant.user_id:
            raise ValueError("authoritative receipt owner must match the claimant user")

    @property
    def activation_available(self) -> bool:
        """Remain false because a provenance receipt grants no authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because approval and execution live in later contracts."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this exact receipt is recorded and unexpired."""

        _require_aware(as_of, "as_of")
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
            "provenance_kind": self.provenance_kind,
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "row_observation_owner": self.row_observation_owner,
            "row_observation_artifact_type": self.row_observation_artifact_type,
            "row_observation_id": self.row_observation_id,
            "row_observation_version": self.row_observation_version,
            "row_observation_identity_hash": self.row_observation_identity_hash,
            "row_observation_content_hash": self.row_observation_content_hash,
            "row_observation_valid_until": _utc_text(self.row_observation_valid_until),
            "claimant": self.claimant.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed claimant-side receipt without approval fields."""

        AccountOwnerAssignmentProvenanceReceipt.__post_init__(self)
        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_provenance_receipt_row(
    receipt: AccountOwnerAssignmentProvenanceReceipt,
    row: PhysicalAccountRowObservation,
) -> None:
    """Require a receipt to bind every exact physical-row seal and validity."""

    if type(receipt) is not AccountOwnerAssignmentProvenanceReceipt:
        raise TypeError("receipt must be an exact AccountOwnerAssignmentProvenanceReceipt")
    if type(row) is not PhysicalAccountRowObservation:
        raise TypeError("row must be an exact PhysicalAccountRowObservation")
    AccountOwnerAssignmentProvenanceReceipt.__post_init__(receipt)
    PhysicalAccountRowObservation.__post_init__(row)
    receipt_values = (
        receipt.account_namespace,
        receipt.account_id,
        receipt.underlying_unified_account_namespace,
        receipt.underlying_unified_account_id,
        receipt.row_observation_owner,
        receipt.row_observation_artifact_type,
        receipt.row_observation_id,
        receipt.row_observation_version,
        receipt.row_observation_identity_hash,
        receipt.row_observation_content_hash,
        receipt.row_observation_valid_until,
    )
    row_values = (
        row.account_namespace,
        row.account_id,
        row.underlying_unified_account_namespace,
        row.underlying_unified_account_id,
        row.owner,
        row.artifact_type,
        row.observation_id,
        row.observation_version,
        row.identity_hash,
        row.content_hash,
        row.valid_until,
    )
    if receipt_values != row_values:
        raise ValueError("receipt does not bind the exact physical row observation")
    if not row.is_knowable_at(receipt.recorded_at):
        raise ValueError("physical row was not knowable when receipt was recorded")


def validate_account_owner_assignment_provenance_receipt_successor(
    previous: AccountOwnerAssignmentProvenanceReceipt,
    successor: AccountOwnerAssignmentProvenanceReceipt,
) -> None:
    """Validate adjacent versions of one exact claimant-side receipt."""

    if type(previous) is not AccountOwnerAssignmentProvenanceReceipt:
        raise TypeError("previous must be an exact AccountOwnerAssignmentProvenanceReceipt")
    if type(successor) is not AccountOwnerAssignmentProvenanceReceipt:
        raise TypeError("successor must be an exact AccountOwnerAssignmentProvenanceReceipt")
    AccountOwnerAssignmentProvenanceReceipt.__post_init__(previous)
    AccountOwnerAssignmentProvenanceReceipt.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous receipt")
    if successor.receipt_id != previous.receipt_id:
        raise ValueError("successor changed receipt_id")
    if successor.receipt_version == previous.receipt_version:
        raise ValueError("successor receipt_version must advance")
    for field_name in (
        "provenance_kind",
        "artifact_type",
        "assignment_state",
        "assigned_owner_user_id",
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_observation_owner",
        "row_observation_artifact_type",
        "row_observation_id",
        "claimant",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.row_observation_version == previous.row_observation_version:
        previous_row_seals = (
            previous.row_observation_identity_hash,
            previous.row_observation_content_hash,
            previous.row_observation_valid_until,
        )
        successor_row_seals = (
            successor.row_observation_identity_hash,
            successor.row_observation_content_hash,
            successor.row_observation_valid_until,
        )
        if successor_row_seals != previous_row_seals:
            raise ValueError("same row_observation_version changed exact row seals")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


def resolve_account_owner_assignment_provenance_receipt_head(
    chain: tuple[AccountOwnerAssignmentProvenanceReceipt, ...],
    *,
    as_of: datetime,
) -> AccountOwnerAssignmentProvenanceReceipt | None:
    """Resolve the PIT head without falling back from a final expired receipt."""

    _require_aware(as_of, "as_of")
    if type(chain) is not tuple:
        raise TypeError("chain must be an exact tuple")
    for receipt in chain:
        if type(receipt) is not AccountOwnerAssignmentProvenanceReceipt:
            raise TypeError(
                "chain values must be exact AccountOwnerAssignmentProvenanceReceipt values"
            )
        AccountOwnerAssignmentProvenanceReceipt.__post_init__(receipt)
    if chain and chain[0].supersedes_content_hash is not None:
        raise ValueError("receipt chain must start at a root")
    for previous, successor in zip(chain, chain[1:], strict=False):
        validate_account_owner_assignment_provenance_receipt_successor(
            previous,
            successor,
        )
    visible = tuple(receipt for receipt in chain if receipt.recorded_at <= as_of)
    if not visible:
        return None
    head = visible[-1]
    return head if head.is_knowable_at(as_of) else None


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ACCOUNT_NAMESPACE",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ARTIFACT_TYPES",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_KINDS",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ROW_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_ROW_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATES",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_STATUS",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_RECEIPT_UNDERLYING_NAMESPACE",
    "AccountOwnerAssignmentProvenanceReceipt",
    "resolve_account_owner_assignment_provenance_receipt_head",
    "validate_account_owner_assignment_provenance_receipt_row",
    "validate_account_owner_assignment_provenance_receipt_successor",
]
