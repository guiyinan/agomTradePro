"""Canonical integrity and inactive approval contracts for transition plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hmac import compare_digest

from .entities import ConstraintDecision, OrderDraft, TransitionPlan

_APPROVAL_OWNER = "portfolio"
_APPROVAL_SCHEMA = "portfolio-transition-plan-approval-receipt.v1"
_APPROVAL_BLOCKER = "portfolio_transition_execution_evidence_not_integrated"


def _constraint_payload(value: ConstraintDecision) -> dict[str, object]:
    return {
        "rule_code": value.rule_code,
        "asset_code": value.asset_code,
        "allowed": value.allowed,
        "original_quantity": value.original_quantity,
        "allowed_quantity": value.allowed_quantity,
        "reason": value.reason,
    }


def _order_payload(value: OrderDraft) -> dict[str, object]:
    return {
        "asset_code": value.asset_code,
        "side": value.side,
        "quantity": value.quantity,
        "reference_price": str(value.reference_price),
        "estimated_fee": str(value.estimated_fee),
        "status": value.status,
        "remaining_quantity": value.remaining_quantity,
        "constraints": [_constraint_payload(item) for item in value.constraints],
    }


def canonical_transition_plan_payload_v1(plan: TransitionPlan) -> dict[str, object]:
    """Return the byte-compatible payload used by existing canonical-v1 rows."""

    if type(plan) is not TransitionPlan:
        raise TypeError("plan must be an exact TransitionPlan")
    return {
        "account_id": plan.account_id,
        "decision_snapshot_id": plan.decision_snapshot_id,
        "portfolio_snapshot_id": plan.portfolio_snapshot_id,
        "target_portfolio_id": plan.target_portfolio_id,
        "as_of_time": plan.as_of_time.isoformat(),
        "expires_at": plan.expires_at.isoformat(),
        "orders": [_order_payload(order) for order in plan.orders],
        "constraints": [_constraint_payload(item) for item in plan.constraints],
        "cash_before": str(plan.cash_before),
        "cash_after": str(plan.cash_after),
        "planning_policy_version": plan.metadata.get("planning_policy_version", ""),
        "version": plan.version,
    }


def canonical_transition_plan_bytes_v1(plan: TransitionPlan) -> bytes:
    """Return the historical canonical-v1 JSON bytes without semantic migration."""

    return json.dumps(
        canonical_transition_plan_payload_v1(plan),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def transition_plan_content_hash_v1(plan: TransitionPlan) -> str:
    """Hash one exact canonical-v1 transition-plan payload."""

    return hashlib.sha256(canonical_transition_plan_bytes_v1(plan)).hexdigest()


def transition_plan_hash_matches_v1(plan: TransitionPlan, expected_hash: str) -> bool:
    """Compare one stored digest without normalizing or silently repairing it."""

    if type(expected_hash) is not str or len(expected_hash) != 64:
        return False
    if any(character not in "0123456789abcdef" for character in expected_hash):
        return False
    return compare_digest(transition_plan_content_hash_v1(plan), expected_hash)


def _require_token(value: str, field_name: str, *, maximum: int = 192) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty canonical token")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds its maximum length")


def _require_aware(value: datetime, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite_decimal(value: Decimal, field_name: str, *, positive: bool = False) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def validate_transition_plan_for_approval_receipt(plan: TransitionPlan) -> None:
    """Validate strict receipt eligibility without changing canonical-v1 bytes."""

    if type(plan) is not TransitionPlan:
        raise TypeError("plan must be an exact TransitionPlan")
    for field_name in (
        "plan_id",
        "idempotency_key",
        "account_id",
        "decision_snapshot_id",
        "portfolio_snapshot_id",
        "target_portfolio_id",
    ):
        _require_token(getattr(plan, field_name), field_name)
    _require_aware(plan.as_of_time, "as_of_time")
    _require_aware(plan.expires_at, "expires_at")
    if plan.as_of_time >= plan.expires_at:
        raise ValueError("transition plan validity window is invalid")
    if type(plan.version) is not int or plan.version <= 0:
        raise ValueError("version must be a positive integer")
    _require_finite_decimal(plan.cash_before, "cash_before")
    _require_finite_decimal(plan.cash_after, "cash_after")
    if type(plan.metadata) is not dict or set(plan.metadata) != {"planning_policy_version"}:
        raise ValueError("metadata must contain only planning_policy_version")
    _require_token(str(plan.metadata["planning_policy_version"]), "planning_policy_version")
    asset_codes: set[str] = set()
    flattened_constraints: list[ConstraintDecision] = []
    for order in plan.orders:
        if type(order) is not OrderDraft:
            raise TypeError("orders must contain exact OrderDraft values")
        _require_token(order.asset_code, "order.asset_code", maximum=32)
        if order.asset_code in asset_codes:
            raise ValueError("transition plan contains duplicate order assets")
        asset_codes.add(order.asset_code)
        if order.side not in {"buy", "sell"}:
            raise ValueError("order.side is invalid")
        if order.status not in {"draft", "partial", "blocked"}:
            raise ValueError("order.status is invalid")
        if type(order.quantity) is not int or order.quantity < 0:
            raise ValueError("order.quantity must be a non-negative integer")
        if type(order.remaining_quantity) is not int or order.remaining_quantity < 0:
            raise ValueError("order.remaining_quantity must be a non-negative integer")
        _require_finite_decimal(order.reference_price, "order.reference_price", positive=True)
        _require_finite_decimal(order.estimated_fee, "order.estimated_fee")
        flattened_constraints.extend(order.constraints)
    for constraint in plan.constraints:
        if type(constraint) is not ConstraintDecision:
            raise TypeError("constraints must contain exact ConstraintDecision values")
        _require_token(constraint.rule_code, "constraint.rule_code")
        _require_token(constraint.asset_code, "constraint.asset_code", maximum=32)
        if type(constraint.allowed) is not bool:
            raise ValueError("constraint.allowed must be a bool")
        if type(constraint.original_quantity) is not int or constraint.original_quantity < 0:
            raise ValueError("constraint.original_quantity must be a non-negative integer")
        if type(constraint.allowed_quantity) is not int:
            raise ValueError("constraint.allowed_quantity must be an integer")
        if not 0 <= constraint.allowed_quantity <= constraint.original_quantity:
            raise ValueError("constraint quantities are invalid")
    if tuple(flattened_constraints) != plan.constraints:
        raise ValueError("plan constraints must exactly flatten order constraints")


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt_hash(payload: dict[str, object]) -> str:
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
class TransitionPlanApprovalActor:
    """Server-authenticated human staff identity for a future approval receipt."""

    actor_id: str
    user_id: int
    role: str
    kind: str = "human"
    is_staff: bool = True

    def __post_init__(self) -> None:
        _require_token(self.actor_id, "actor_id")
        if type(self.user_id) is not int or self.user_id <= 0:
            raise ValueError("user_id must be a positive integer")
        _require_token(self.role, "role")
        if self.kind != "human" or self.is_staff is not True:
            raise ValueError("plan approval actor must be human staff")

    def to_payload(self) -> dict[str, object]:
        """Return the immutable actor identity."""

        return {
            "actor_id": self.actor_id,
            "user_id": self.user_id,
            "role": self.role,
            "kind": self.kind,
            "is_staff": self.is_staff,
        }


@dataclass(frozen=True, slots=True)
class TransitionPlanApprovalReceipt:
    """Inactive exact approval contract; it never authorizes execution."""

    receipt_id: str
    receipt_version: str
    subject_id: str
    subject_version: str
    subject_content_hash: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    account_id: str
    decision_snapshot_id: str
    requested_by: TransitionPlanApprovalActor
    approved_by: TransitionPlanApprovalActor
    issued_at: datetime
    valid_until: datetime
    plan_status_at_issue: str = "APPROVED"
    content_hash: str = ""
    owner: str = _APPROVAL_OWNER
    schema: str = _APPROVAL_SCHEMA
    approval_state: str = "approved"
    execution_permission: str = "inactive"
    blocker_codes: tuple[str, ...] = (_APPROVAL_BLOCKER,)

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        receipt_version: str,
        subject_id: str,
        subject_version: str,
        subject_content_hash: str,
        requested_by: TransitionPlanApprovalActor,
        plan: TransitionPlan,
        approved_by: TransitionPlanApprovalActor,
        issued_at: datetime,
    ) -> TransitionPlanApprovalReceipt:
        """Build an inactive receipt after strict plan validation."""

        validate_transition_plan_for_approval_receipt(plan)
        if plan.status != "APPROVED":
            raise ValueError("only an approved transition plan can receive a receipt")
        if issued_at < plan.as_of_time:
            raise ValueError("approval receipt cannot predate the transition plan")
        return cls(
            receipt_id=receipt_id,
            receipt_version=receipt_version,
            subject_id=subject_id,
            subject_version=subject_version,
            subject_content_hash=subject_content_hash,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            plan_content_hash=transition_plan_content_hash_v1(plan),
            account_id=plan.account_id,
            decision_snapshot_id=plan.decision_snapshot_id,
            requested_by=requested_by,
            approved_by=approved_by,
            issued_at=issued_at,
            valid_until=plan.expires_at,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "receipt_version",
            "subject_id",
            "subject_version",
            "plan_id",
            "account_id",
            "decision_snapshot_id",
        ):
            _require_token(getattr(self, field_name), field_name)
        if self.owner != _APPROVAL_OWNER or self.schema != _APPROVAL_SCHEMA:
            raise ValueError("receipt authority or schema is invalid")
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        if len(self.plan_content_hash) != 64 or any(
            item not in "0123456789abcdef" for item in self.plan_content_hash
        ):
            raise ValueError("plan_content_hash must be lowercase SHA-256")
        if len(self.subject_content_hash) != 64 or any(
            item not in "0123456789abcdef" for item in self.subject_content_hash
        ):
            raise ValueError("subject_content_hash must be lowercase SHA-256")
        if type(self.requested_by) is not TransitionPlanApprovalActor:
            raise TypeError("requested_by must be an exact TransitionPlanApprovalActor")
        TransitionPlanApprovalActor.__post_init__(self.requested_by)
        if type(self.approved_by) is not TransitionPlanApprovalActor:
            raise TypeError("approved_by must be an exact TransitionPlanApprovalActor")
        TransitionPlanApprovalActor.__post_init__(self.approved_by)
        if (
            self.requested_by.actor_id == self.approved_by.actor_id
            or self.requested_by.user_id == self.approved_by.user_id
        ):
            raise ValueError("plan approval requires two distinct human actors")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.valid_until, "valid_until")
        if self.issued_at >= self.valid_until:
            raise ValueError("approval receipt validity window is invalid")
        if self.approval_state != "approved":
            raise ValueError("approval_state is fixed")
        if self.plan_status_at_issue != "APPROVED":
            raise ValueError("plan_status_at_issue is fixed APPROVED")
        if self.execution_permission != "inactive":
            raise ValueError("execution_permission is fixed inactive")
        if self.blocker_codes != (_APPROVAL_BLOCKER,):
            raise ValueError("inactive blocker_codes are fixed")
        expected_hash = _receipt_hash(self._content_payload())
        if not self.content_hash:
            object.__setattr__(self, "content_hash", expected_hash)
        elif self.content_hash != expected_hash:
            raise ValueError("approval receipt content_hash is invalid")

    @property
    def must_not_execute(self) -> bool:
        """Remain true until owner Evidence and Risk receipts are integrated."""

        return True

    def _content_payload(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "schema": self.schema,
            "receipt_id": self.receipt_id,
            "receipt_version": self.receipt_version,
            "subject_id": self.subject_id,
            "subject_version": self.subject_version,
            "subject_content_hash": self.subject_content_hash,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_content_hash": self.plan_content_hash,
            "account_id": self.account_id,
            "decision_snapshot_id": self.decision_snapshot_id,
            "requested_by": self.requested_by.to_payload(),
            "approved_by": self.approved_by.to_payload(),
            "issued_at": _utc_text(self.issued_at),
            "valid_until": _utc_text(self.valid_until),
            "plan_status_at_issue": self.plan_status_at_issue,
            "approval_state": self.approval_state,
            "execution_permission": self.execution_permission,
            "blocker_codes": list(self.blocker_codes),
        }

    def to_payload(self) -> dict[str, object]:
        """Return the sealed receipt while preserving its inactive state."""

        return {
            **self._content_payload(),
            "content_hash": self.content_hash,
            "must_not_execute": True,
        }


__all__ = [
    "TransitionPlanApprovalActor",
    "TransitionPlanApprovalReceipt",
    "canonical_transition_plan_bytes_v1",
    "canonical_transition_plan_payload_v1",
    "transition_plan_content_hash_v1",
    "transition_plan_hash_matches_v1",
    "validate_transition_plan_for_approval_receipt",
]
