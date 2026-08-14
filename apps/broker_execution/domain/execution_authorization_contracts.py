"""Pure contracts for a future owner-bound broker execution receipt.

These values deliberately do not issue or activate an execution authorization.  They
freeze the identities and validity intersection that authoritative Portfolio, Risk,
Research, and Broker providers must prove before the application layer may persist an
active receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

_RECEIPT_VERSION = "broker-live-order-execution-authorization.v1"
_RECEIPT_OWNER = "broker_execution"
_RECEIPT_CAPABILITY = "live_order_execution"


class BrokerExecutionPermission(str, Enum):
    """Permission vocabulary consumed by the future Broker authorization issuer."""

    DISPLAY_ONLY = "display_only"
    DECISION_ELIGIBLE = "decision_eligible"
    EXECUTION_ELIGIBLE = "execution_eligible"


def _require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty canonical token")
    if len(value) > maximum or any(character.isspace() for character in value):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: str, field_name: str) -> None:
    if type(value) is not str or len(value) != 64:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True, order=True)
class ExactAuthorizationArtifactRef:
    """Consumer-owned identity for one exact upstream authorization artifact."""

    owner: str
    artifact_type: str
    artifact_id: str
    artifact_version: str
    content_hash: str

    def __post_init__(self) -> None:
        for field_name in ("owner", "artifact_type", "artifact_id", "artifact_version"):
            _require_token(getattr(self, field_name), field_name)
        _require_hash(self.content_hash, "content_hash")

    def to_payload(self) -> dict[str, object]:
        """Return the canonical JSON-compatible identity."""

        return {
            "owner": self.owner,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class BrokerExecutionAuthorizationScope:
    """Exact cross-owner facts that one future execution receipt must bind."""

    account_id: int
    plan_ref: ExactAuthorizationArtifactRef
    plan_approval_ref: ExactAuthorizationArtifactRef
    order_ref: ExactAuthorizationArtifactRef
    evidence_output_ref: ExactAuthorizationArtifactRef
    evidence_envelope_ref: ExactAuthorizationArtifactRef
    operator_spec_ref: ExactAuthorizationArtifactRef
    track_record_ref: ExactAuthorizationArtifactRef
    risk_authorization_ref: ExactAuthorizationArtifactRef
    benchmark_snapshot_ref: ExactAuthorizationArtifactRef
    plan_valid_until: datetime
    order_valid_until: datetime
    evidence_valid_until: datetime
    risk_valid_until: datetime
    benchmark_valid_until: datetime
    scope_content_hash: str = ""

    def __post_init__(self) -> None:
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("account_id must be a positive integer")
        expected_ref_types = (
            ("plan_ref", "portfolio", "transition_plan"),
            (
                "plan_approval_ref",
                "portfolio",
                "transition_plan_approval_receipt",
            ),
            ("order_ref", "broker_execution", "live_order_approval_snapshot"),
            ("evidence_envelope_ref", "research", "evidence_envelope"),
            ("operator_spec_ref", "research", "evidence_operator_spec"),
            ("track_record_ref", "research", "track_record_snapshot"),
            (
                "risk_authorization_ref",
                "risk_center",
                "broker_order_risk_authorization",
            ),
            ("benchmark_snapshot_ref", "portfolio", "policy_benchmark_snapshot"),
        )
        for field_name, owner, artifact_type in expected_ref_types:
            value = getattr(self, field_name)
            if type(value) is not ExactAuthorizationArtifactRef:
                raise TypeError(f"{field_name} must be an exact artifact reference")
            ExactAuthorizationArtifactRef.__post_init__(value)
            if value.owner != owner or value.artifact_type != artifact_type:
                raise ValueError(f"{field_name} has an invalid owner or artifact type")
        if type(self.evidence_output_ref) is not ExactAuthorizationArtifactRef:
            raise TypeError("evidence_output_ref must be an exact artifact reference")
        ExactAuthorizationArtifactRef.__post_init__(self.evidence_output_ref)
        try:
            UUID(self.order_ref.artifact_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("order_ref artifact_id must be a canonical UUID") from exc
        if str(UUID(self.order_ref.artifact_id)) != self.order_ref.artifact_id:
            raise ValueError("order_ref artifact_id must be a canonical UUID")
        for field_name in (
            "plan_valid_until",
            "order_valid_until",
            "evidence_valid_until",
            "risk_valid_until",
            "benchmark_valid_until",
        ):
            _require_aware(getattr(self, field_name), field_name)
        expected_hash = _canonical_hash(self._content_payload())
        if not self.scope_content_hash:
            object.__setattr__(self, "scope_content_hash", expected_hash)
        else:
            _require_hash(self.scope_content_hash, "scope_content_hash")
            if self.scope_content_hash != expected_hash:
                raise ValueError("scope_content_hash does not match the authorization scope")

    @property
    def valid_until(self) -> datetime:
        """Return the strict intersection of all upstream validity windows."""

        return min(
            self.plan_valid_until,
            self.order_valid_until,
            self.evidence_valid_until,
            self.risk_valid_until,
            self.benchmark_valid_until,
        )

    def _content_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "plan_ref": self.plan_ref.to_payload(),
            "plan_approval_ref": self.plan_approval_ref.to_payload(),
            "order_ref": self.order_ref.to_payload(),
            "evidence_output_ref": self.evidence_output_ref.to_payload(),
            "evidence_envelope_ref": self.evidence_envelope_ref.to_payload(),
            "operator_spec_ref": self.operator_spec_ref.to_payload(),
            "track_record_ref": self.track_record_ref.to_payload(),
            "risk_authorization_ref": self.risk_authorization_ref.to_payload(),
            "benchmark_snapshot_ref": self.benchmark_snapshot_ref.to_payload(),
            "plan_valid_until": _utc_text(self.plan_valid_until),
            "order_valid_until": _utc_text(self.order_valid_until),
            "evidence_valid_until": _utc_text(self.evidence_valid_until),
            "risk_valid_until": _utc_text(self.risk_valid_until),
            "benchmark_valid_until": _utc_text(self.benchmark_valid_until),
        }

    def to_payload(self) -> dict[str, object]:
        """Return this content-addressed scope without implying activation."""

        return {**self._content_payload(), "scope_content_hash": self.scope_content_hash}


@dataclass(frozen=True, slots=True)
class BrokerExecutionAuthorizationReceiptContract:
    """Structurally sealed receipt contract; no production issuer exists yet."""

    receipt_id: str
    scope: BrokerExecutionAuthorizationScope
    evidence_permission: BrokerExecutionPermission
    risk_permission: BrokerExecutionPermission
    approved_by_user_id: int
    approved_by_role: str
    issued_at: datetime
    valid_until: datetime
    supersedes_receipt_hash: str | None = None
    content_hash: str = ""
    owner: str = _RECEIPT_OWNER
    capability: str = _RECEIPT_CAPABILITY
    receipt_version: str = _RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_token(self.receipt_id, "receipt_id")
        if self.owner != _RECEIPT_OWNER:
            raise ValueError("receipt owner is fixed")
        if self.capability != _RECEIPT_CAPABILITY:
            raise ValueError("receipt capability is fixed")
        if self.receipt_version != _RECEIPT_VERSION:
            raise ValueError("receipt_version is fixed")
        if type(self.scope) is not BrokerExecutionAuthorizationScope:
            raise TypeError("scope must be an exact BrokerExecutionAuthorizationScope")
        BrokerExecutionAuthorizationScope.__post_init__(self.scope)
        if type(self.evidence_permission) is not BrokerExecutionPermission:
            raise TypeError("evidence_permission must be an exact BrokerExecutionPermission")
        if type(self.risk_permission) is not BrokerExecutionPermission:
            raise TypeError("risk_permission must be an exact BrokerExecutionPermission")
        if self.evidence_permission is not BrokerExecutionPermission.EXECUTION_ELIGIBLE:
            raise ValueError("evidence permission is not execution eligible")
        if self.risk_permission is not BrokerExecutionPermission.EXECUTION_ELIGIBLE:
            raise ValueError("risk permission is not execution eligible")
        if type(self.approved_by_user_id) is not int or self.approved_by_user_id <= 0:
            raise ValueError("approved_by_user_id must be a positive integer")
        _require_token(self.approved_by_role, "approved_by_role")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.issued_at >= self.valid_until:
            raise ValueError("receipt validity window is invalid")
        if self.valid_until != self.scope.valid_until:
            raise ValueError("receipt valid_until must equal the strict upstream minimum")
        if self.supersedes_receipt_hash is not None:
            _require_hash(self.supersedes_receipt_hash, "supersedes_receipt_hash")
        expected_hash = _canonical_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        else:
            _require_hash(self.content_hash, "content_hash")
            if self.content_hash != expected_hash:
                raise ValueError("receipt content_hash does not match the contract")

    @property
    def activation_available(self) -> bool:
        """Remain false until exact owner providers and append-only storage exist."""

        return False

    @property
    def must_not_execute(self) -> bool:
        """Remain true because a locally valid schema is not an active receipt."""

        return True

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "capability": self.capability,
            "receipt_version": self.receipt_version,
            "receipt_id": self.receipt_id,
            "scope": self.scope.to_payload(),
            "evidence_permission": self.evidence_permission.value,
            "risk_permission": self.risk_permission.value,
            "approved_by_user_id": self.approved_by_user_id,
            "approved_by_role": self.approved_by_role,
            "issued_at": _utc_text(self.issued_at),
            "valid_until": _utc_text(self.valid_until),
            "supersedes_receipt_hash": self.supersedes_receipt_hash,
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed, explicitly inactive receipt-contract projection."""

        return {
            **self._content_payload(),
            "content_hash": self.content_hash,
            "activation_available": False,
            "must_not_execute": True,
        }


def validate_receipt_successor(
    previous: BrokerExecutionAuthorizationReceiptContract,
    successor: BrokerExecutionAuthorizationReceiptContract,
) -> None:
    """Validate one adjacent supersession link; persistence must prevent forks."""

    if type(previous) is not BrokerExecutionAuthorizationReceiptContract:
        raise TypeError("previous must be an exact receipt contract")
    if type(successor) is not BrokerExecutionAuthorizationReceiptContract:
        raise TypeError("successor must be an exact receipt contract")
    if successor.supersedes_receipt_hash != previous.content_hash:
        raise ValueError("successor does not bind the exact previous receipt")
    if successor.scope.account_id != previous.scope.account_id:
        raise ValueError("receipt successor changed account identity")
    if successor.scope.order_ref.artifact_id != previous.scope.order_ref.artifact_id:
        raise ValueError("receipt successor changed order identity")
    if successor.issued_at <= previous.issued_at:
        raise ValueError("receipt successor clock must advance")


__all__ = [
    "BrokerExecutionAuthorizationReceiptContract",
    "BrokerExecutionAuthorizationScope",
    "BrokerExecutionPermission",
    "ExactAuthorizationArtifactRef",
    "validate_receipt_successor",
]
