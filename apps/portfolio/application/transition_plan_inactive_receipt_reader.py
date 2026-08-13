"""Portfolio-owned ID-only reader for inactive plan approval receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.portfolio.domain.transition_plan_integrity import (
    TransitionPlanApprovalReceipt,
)

PORTFOLIO_INACTIVE_RECEIPT_OWNER = "portfolio"
PORTFOLIO_INACTIVE_RECEIPT_CAPABILITY = "transition_plan_inactive_approval"
PORTFOLIO_INACTIVE_RECEIPT_SCHEMA = "portfolio-transition-plan-approval-receipt.v1"
PORTFOLIO_INACTIVE_RECEIPT_BLOCKER = "portfolio_transition_execution_evidence_not_integrated"


class TransitionPlanInactiveReceiptReaderUnavailable(ValueError):
    """The exact inactive receipt is unavailable at the requested cutoff."""


class TransitionPlanInactiveReceiptReaderCorruption(ValueError):
    """The owner repository returned a substituted or invalid receipt."""


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")


def _require_hash(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ExactInactiveTransitionPlanApprovalReceipt:
    """Sealed owner projection of one exact inactive approval receipt."""

    receipt_id: str
    receipt_version: str
    content_hash: str
    subject_id: str
    subject_version: str
    subject_content_hash: str
    plan_id: str
    plan_version: int
    plan_content_hash: str
    account_id: str
    decision_snapshot_id: str
    issued_at: datetime
    recorded_at: datetime
    valid_until: datetime
    owner: str = PORTFOLIO_INACTIVE_RECEIPT_OWNER
    capability: str = PORTFOLIO_INACTIVE_RECEIPT_CAPABILITY
    schema: str = PORTFOLIO_INACTIVE_RECEIPT_SCHEMA
    approval_state: str = "approved"
    execution_permission: str = "inactive"
    blocker_codes: tuple[str, ...] = (PORTFOLIO_INACTIVE_RECEIPT_BLOCKER,)
    must_not_execute: bool = True

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
        if type(self.plan_version) is not int or self.plan_version <= 0:
            raise ValueError("plan_version must be a positive integer")
        for field_name in (
            "content_hash",
            "subject_content_hash",
            "plan_content_hash",
        ):
            _require_hash(getattr(self, field_name), field_name)
        for field_name in ("issued_at", "recorded_at", "valid_until"):
            _require_aware(getattr(self, field_name), field_name)
        if self.recorded_at != self.issued_at:
            raise ValueError("recorded_at must equal the sealed receipt issued_at")
        if self.recorded_at >= self.valid_until:
            raise ValueError("inactive receipt validity window is invalid")
        if self.owner != PORTFOLIO_INACTIVE_RECEIPT_OWNER:
            raise ValueError("inactive receipt owner is fixed")
        if self.capability != PORTFOLIO_INACTIVE_RECEIPT_CAPABILITY:
            raise ValueError("inactive receipt capability is fixed")
        if self.schema != PORTFOLIO_INACTIVE_RECEIPT_SCHEMA:
            raise ValueError("inactive receipt schema is fixed")
        if self.approval_state != "approved":
            raise ValueError("inactive receipt approval_state is fixed")
        if self.execution_permission != "inactive":
            raise ValueError("inactive receipt execution_permission is fixed")
        if self.blocker_codes != (PORTFOLIO_INACTIVE_RECEIPT_BLOCKER,):
            raise ValueError("inactive receipt blocker_codes are fixed")
        if self.must_not_execute is not True:
            raise ValueError("inactive receipt must never authorize execution")

    def is_knowable_at(self, as_of: datetime) -> bool:
        """Return whether the exact inactive receipt is knowable and unexpired."""

        _require_aware(as_of, "as_of")
        return self.recorded_at <= as_of < self.valid_until


@dataclass(frozen=True, slots=True)
class GetExactInactiveTransitionPlanApprovalReceiptQuery:
    """ID-only selector for one immutable receipt winner at a PIT cutoff."""

    receipt_id: str
    receipt_version: str
    as_of: datetime

    def __post_init__(self) -> None:
        _require_token(self.receipt_id, "receipt_id")
        _require_token(self.receipt_version, "receipt_version")
        _require_aware(self.as_of, "as_of")


class ExactInactiveTransitionPlanApprovalReceiptRepository(Protocol):
    """Owner identity-winner read port for the append-only receipt ledger."""

    def get_receipt_winner(
        self, *, receipt_id: str, receipt_version: str, as_of: datetime
    ) -> TransitionPlanApprovalReceipt | None:
        """Return one immutable identity winner knowable at the cutoff."""


class GetExactInactiveTransitionPlanApprovalReceipt:
    """Read and revalidate one owner receipt without caller-supplied hashes."""

    def __init__(self, repository: ExactInactiveTransitionPlanApprovalReceiptRepository) -> None:
        self._repository = repository

    def execute(
        self, query: GetExactInactiveTransitionPlanApprovalReceiptQuery
    ) -> ExactInactiveTransitionPlanApprovalReceipt:
        """Return one sealed, exact and still-inactive receipt projection."""

        receipt = self._repository.get_receipt_winner(
            receipt_id=query.receipt_id,
            receipt_version=query.receipt_version,
            as_of=query.as_of,
        )
        if receipt is None:
            raise TransitionPlanInactiveReceiptReaderUnavailable(
                "exact inactive transition plan receipt is unavailable"
            )
        if type(receipt) is not TransitionPlanApprovalReceipt:
            raise TransitionPlanInactiveReceiptReaderCorruption(
                "transition plan approval receipt type substitution"
            )
        if (
            receipt.receipt_id != query.receipt_id
            or receipt.receipt_version != query.receipt_version
        ):
            raise TransitionPlanInactiveReceiptReaderCorruption(
                "transition plan approval receipt identity substitution"
            )
        try:
            _require_hash(receipt.content_hash, "content_hash")
            TransitionPlanApprovalReceipt.__post_init__(receipt)
        except (TypeError, ValueError) as error:
            raise TransitionPlanInactiveReceiptReaderCorruption(
                "transition plan approval receipt is invalid"
            ) from error
        if not receipt.issued_at <= query.as_of < receipt.valid_until:
            raise TransitionPlanInactiveReceiptReaderUnavailable(
                "exact inactive transition plan receipt is unavailable at the cutoff"
            )
        return ExactInactiveTransitionPlanApprovalReceipt(
            receipt_id=receipt.receipt_id,
            receipt_version=receipt.receipt_version,
            content_hash=receipt.content_hash,
            subject_id=receipt.subject_id,
            subject_version=receipt.subject_version,
            subject_content_hash=receipt.subject_content_hash,
            plan_id=receipt.plan_id,
            plan_version=receipt.plan_version,
            plan_content_hash=receipt.plan_content_hash,
            account_id=receipt.account_id,
            decision_snapshot_id=receipt.decision_snapshot_id,
            issued_at=receipt.issued_at,
            recorded_at=receipt.issued_at,
            valid_until=receipt.valid_until,
        )


__all__ = [
    "ExactInactiveTransitionPlanApprovalReceipt",
    "ExactInactiveTransitionPlanApprovalReceiptRepository",
    "GetExactInactiveTransitionPlanApprovalReceipt",
    "GetExactInactiveTransitionPlanApprovalReceiptQuery",
    "PORTFOLIO_INACTIVE_RECEIPT_BLOCKER",
    "PORTFOLIO_INACTIVE_RECEIPT_CAPABILITY",
    "PORTFOLIO_INACTIVE_RECEIPT_OWNER",
    "PORTFOLIO_INACTIVE_RECEIPT_SCHEMA",
    "TransitionPlanInactiveReceiptReaderCorruption",
    "TransitionPlanInactiveReceiptReaderUnavailable",
]
