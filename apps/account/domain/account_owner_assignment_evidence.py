"""Account-owned inactive evidence for canonical account owner assignment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

ACCOUNT_OWNER_ASSIGNMENT_OWNER = "account"
ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE = "account_owner_assignment_evidence"
ACCOUNT_OWNER_ASSIGNMENT_SCHEMA = "account-owner-assignment-evidence.v1"
ACCOUNT_OWNER_ASSIGNMENT_PERMISSION = "evidence_only"
ACCOUNT_OWNER_ASSIGNMENT_STATUS = "inactive"
ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS = ("account_owner_assignment_provider_not_integrated",)
ACCOUNT_OWNER_ASSIGNMENT_STATES = ("authoritative", "legacy_default")
ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_KINDS = ("creation", "migration", "manual_reclaim")
ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE = "account"
ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE = "simulated-account-row"
ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_OWNER = "simulated_trading"
ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_ARTIFACT_TYPE = "unified_account_row_observation"

_PROVENANCE_ARTIFACT_TYPES = {
    "creation": "account_creation_receipt",
    "migration": "account_legacy_default_assignment_receipt",
    "manual_reclaim": "account_owner_reclaim_receipt",
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


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentActor:
    """Exact authenticated human participating in owner assignment approval."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = False

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("actor user_id must be an exact positive integer")
        _require_token(self.role, "role")
        if self.kind != "human":
            raise ValueError("account owner assignment actor must be human")
        if type(self.is_staff) is not bool:
            raise TypeError("actor is_staff must be an exact boolean")

    def to_payload(self) -> dict[str, object]:
        """Return the exact authenticated actor identity."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "role": self.role,
            "kind": self.kind,
            "is_staff": self.is_staff,
        }


@dataclass(frozen=True, slots=True)
class AccountOwnerAssignmentEvidence:
    """Two-person Account owner evidence that grants no activation authority."""

    evidence_id: str
    evidence_version: str
    account_namespace: str
    account_id: str
    underlying_unified_account_namespace: str
    underlying_unified_account_id: int
    assignment_state: str
    assigned_owner_user_id: int | None
    row_observation_owner: str
    row_observation_artifact_type: str
    row_observation_id: str
    row_observation_version: str
    row_observation_content_hash: str
    provenance_kind: str
    provenance_ref_owner: str
    provenance_ref_artifact_type: str
    provenance_ref_id: str
    provenance_ref_version: str
    provenance_ref_content_hash: str
    claimant: AccountOwnerAssignmentActor
    approved_by: AccountOwnerAssignmentActor
    issued_at: datetime
    approved_at: datetime
    recorded_at: datetime
    valid_until: datetime
    supersedes_content_hash: str | None = None
    identity_hash: str = ""
    content_hash: str = ""
    owner: str = ACCOUNT_OWNER_ASSIGNMENT_OWNER
    artifact_type: str = ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE
    schema: str = ACCOUNT_OWNER_ASSIGNMENT_SCHEMA
    permission: str = ACCOUNT_OWNER_ASSIGNMENT_PERMISSION
    status: str = ACCOUNT_OWNER_ASSIGNMENT_STATUS
    blocker_codes: tuple[str, ...] = ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS

    def __post_init__(self) -> None:
        self._validate_fixed_semantics()
        for field_name in (
            "evidence_id",
            "evidence_version",
            "account_namespace",
            "account_id",
            "underlying_unified_account_namespace",
            "row_observation_owner",
            "row_observation_artifact_type",
            "row_observation_id",
            "row_observation_version",
            "provenance_ref_owner",
            "provenance_ref_artifact_type",
            "provenance_ref_id",
            "provenance_ref_version",
        ):
            _require_token(getattr(self, field_name), field_name)
        if type(self.underlying_unified_account_id) is not int:
            raise TypeError("underlying_unified_account_id must be an exact integer")
        if self.underlying_unified_account_id <= 0:
            raise ValueError("underlying_unified_account_id must be positive")
        if self.account_namespace != ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE:
            raise ValueError("account_namespace is fixed")
        if (
            self.underlying_unified_account_namespace
            != ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE
        ):
            raise ValueError("underlying_unified_account_namespace is fixed")
        _require_hash(self.row_observation_content_hash, "row_observation_content_hash")
        _require_hash(self.provenance_ref_content_hash, "provenance_ref_content_hash")
        if self.row_observation_owner != ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_OWNER:
            raise ValueError("row_observation_owner is fixed")
        if (
            self.row_observation_artifact_type
            != ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_ARTIFACT_TYPE
        ):
            raise ValueError("row_observation_artifact_type is fixed")
        self._validate_assignment()
        self._validate_provenance()
        self._validate_actors()
        for field_name in ("issued_at", "approved_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if not self.issued_at <= self.approved_at <= self.recorded_at < self.valid_until:
            raise ValueError("account owner assignment clock sequence is invalid")
        if self.supersedes_content_hash is not None:
            _require_hash(self.supersedes_content_hash, "supersedes_content_hash")
        expected_identity_hash = _canonical_hash(self._identity_payload())
        if not self.identity_hash:
            object.__setattr__(self, "identity_hash", expected_identity_hash)
        else:
            _require_hash(self.identity_hash, "identity_hash")
            if self.identity_hash != expected_identity_hash:
                raise ValueError("account owner assignment identity_hash is invalid")
        expected_content_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_content_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_content_hash:
                raise ValueError("account owner assignment content_hash is invalid")

    def _validate_fixed_semantics(self) -> None:
        if self.owner != ACCOUNT_OWNER_ASSIGNMENT_OWNER:
            raise ValueError("account owner assignment owner is fixed")
        if self.artifact_type != ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE:
            raise ValueError("account owner assignment artifact_type is fixed")
        if self.schema != ACCOUNT_OWNER_ASSIGNMENT_SCHEMA:
            raise ValueError("account owner assignment schema is fixed")
        if self.permission != ACCOUNT_OWNER_ASSIGNMENT_PERMISSION:
            raise ValueError("account owner assignment permission is fixed")
        if self.status != ACCOUNT_OWNER_ASSIGNMENT_STATUS:
            raise ValueError("account owner assignment status is fixed inactive")
        if self.blocker_codes != ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS:
            raise ValueError("account owner assignment blocker_codes are fixed")

    def _validate_assignment(self) -> None:
        if type(self.assignment_state) is not str:
            raise TypeError("assignment_state must be an exact string")
        if self.assignment_state not in ACCOUNT_OWNER_ASSIGNMENT_STATES:
            raise ValueError("assignment_state is invalid")
        if self.assignment_state == "authoritative":
            if type(self.assigned_owner_user_id) is not int or self.assigned_owner_user_id <= 0:
                raise ValueError("authoritative assignment requires a positive owner")
            return
        if self.assigned_owner_user_id is not None:
            raise ValueError("legacy_default assignment cannot claim an owner")

    def _validate_provenance(self) -> None:
        if self.provenance_kind not in ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_KINDS:
            raise ValueError("provenance_kind is invalid")
        if self.provenance_ref_owner != ACCOUNT_OWNER_ASSIGNMENT_OWNER:
            raise ValueError("provenance reference owner is invalid")
        expected_type = _PROVENANCE_ARTIFACT_TYPES[self.provenance_kind]
        if self.provenance_ref_artifact_type != expected_type:
            raise ValueError("provenance reference artifact type is invalid")
        if self.assignment_state == "legacy_default" and self.provenance_kind != "migration":
            raise ValueError("legacy_default assignment requires migration provenance")
        if self.provenance_kind == "migration" and self.assignment_state != "legacy_default":
            raise ValueError("migration provenance requires legacy_default assignment")
        if self.provenance_kind == "manual_reclaim" and self.assignment_state != "authoritative":
            raise ValueError("manual_reclaim provenance cannot be legacy_default")

    def _validate_actors(self) -> None:
        if type(self.claimant) is not AccountOwnerAssignmentActor:
            raise TypeError("claimant must be an exact AccountOwnerAssignmentActor")
        if type(self.approved_by) is not AccountOwnerAssignmentActor:
            raise TypeError("approved_by must be an exact AccountOwnerAssignmentActor")
        AccountOwnerAssignmentActor.__post_init__(self.claimant)
        AccountOwnerAssignmentActor.__post_init__(self.approved_by)
        if self.approved_by.is_staff is not True:
            raise ValueError("account owner assignment approver must be human staff")
        if self.claimant.actor_id == self.approved_by.actor_id:
            raise ValueError("claimant and approver must be different actors")
        if self.claimant.user_id == self.approved_by.user_id:
            raise ValueError("claimant and approver must be different users")
        if (
            self.assignment_state == "authoritative"
            and self.claimant.user_id != self.assigned_owner_user_id
        ):
            raise ValueError("authoritative owner must match the claimant user")

    @property
    def activation_available(self) -> bool:
        """Remain false because owner evidence grants no execution authority."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because owner evidence cannot authorize execution."""

        return True

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether this evidence is recorded and unexpired at a cutoff."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until

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
            "account_namespace": self.account_namespace,
            "account_id": self.account_id,
            "underlying_unified_account_namespace": (self.underlying_unified_account_namespace),
            "underlying_unified_account_id": self.underlying_unified_account_id,
            "assignment_state": self.assignment_state,
            "assigned_owner_user_id": self.assigned_owner_user_id,
            "row_observation_owner": self.row_observation_owner,
            "row_observation_artifact_type": self.row_observation_artifact_type,
            "row_observation_id": self.row_observation_id,
            "row_observation_version": self.row_observation_version,
            "row_observation_content_hash": self.row_observation_content_hash,
            "provenance_kind": self.provenance_kind,
            "provenance_ref_owner": self.provenance_ref_owner,
            "provenance_ref_artifact_type": self.provenance_ref_artifact_type,
            "provenance_ref_id": self.provenance_ref_id,
            "provenance_ref_version": self.provenance_ref_version,
            "provenance_ref_content_hash": self.provenance_ref_content_hash,
            "claimant": self.claimant.to_payload(),
            "approved_by": self.approved_by.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "approved_at": _utc_text(self.approved_at),
            "recorded_at": _utc_text(self.recorded_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_content_hash": self.supersedes_content_hash,
            "permission": self.permission,
            "status": self.status,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the canonical inactive Account owner evidence payload."""

        return {
            **self._content_payload(),
            "identity_hash": self.identity_hash,
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_account_owner_assignment_successor(
    previous: AccountOwnerAssignmentEvidence,
    successor: AccountOwnerAssignmentEvidence,
) -> None:
    """Validate adjacent evidence in one canonical Account/underlying-row chain."""

    if type(previous) is not AccountOwnerAssignmentEvidence:
        raise TypeError("previous must be exact AccountOwnerAssignmentEvidence")
    if type(successor) is not AccountOwnerAssignmentEvidence:
        raise TypeError("successor must be exact AccountOwnerAssignmentEvidence")
    AccountOwnerAssignmentEvidence.__post_init__(previous)
    AccountOwnerAssignmentEvidence.__post_init__(successor)
    if successor.supersedes_content_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous assignment evidence")
    if successor.evidence_id != previous.evidence_id:
        raise ValueError("successor changed evidence_id")
    if successor.evidence_version == previous.evidence_version:
        raise ValueError("successor evidence_version must advance")
    for field_name in (
        "account_namespace",
        "account_id",
        "underlying_unified_account_namespace",
        "underlying_unified_account_id",
        "row_observation_owner",
        "row_observation_artifact_type",
        "row_observation_id",
    ):
        if getattr(successor, field_name) != getattr(previous, field_name):
            raise ValueError(f"successor changed {field_name}")
    if successor.row_observation_version == previous.row_observation_version:
        raise ValueError("successor row_observation_version must advance")
    if successor.recorded_at <= previous.recorded_at:
        raise ValueError("successor recorded_at must advance")


__all__ = [
    "ACCOUNT_OWNER_ASSIGNMENT_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_ACCOUNT_NAMESPACE",
    "ACCOUNT_OWNER_ASSIGNMENT_BLOCKERS",
    "ACCOUNT_OWNER_ASSIGNMENT_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_PERMISSION",
    "ACCOUNT_OWNER_ASSIGNMENT_PROVENANCE_KINDS",
    "ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_ARTIFACT_TYPE",
    "ACCOUNT_OWNER_ASSIGNMENT_ROW_OBSERVATION_OWNER",
    "ACCOUNT_OWNER_ASSIGNMENT_SCHEMA",
    "ACCOUNT_OWNER_ASSIGNMENT_STATES",
    "ACCOUNT_OWNER_ASSIGNMENT_STATUS",
    "ACCOUNT_OWNER_ASSIGNMENT_UNDERLYING_NAMESPACE",
    "AccountOwnerAssignmentActor",
    "AccountOwnerAssignmentEvidence",
    "validate_account_owner_assignment_successor",
]
