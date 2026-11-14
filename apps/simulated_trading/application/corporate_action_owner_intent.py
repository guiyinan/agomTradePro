"""Immutable server-prepared commands for one explicit owner confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from apps.account.domain.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantSelector,
)
from apps.simulated_trading.application.corporate_action_share_tax_proof import (
    ShareCapitalTaxQualificationProof,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)

OwnerCorporateActionOperation = Literal[
    "cash_entitlement",
    "cash_payment",
    "share_entitlement",
    "share_delivery",
    "share_sellable_release",
    "rights_not_exercised",
    "tax_assess",
    "tax_recognize",
    "tax_collect",
]
OWNER_CORPORATE_ACTION_OPERATIONS = frozenset(
    {
        "cash_entitlement",
        "cash_payment",
        "share_entitlement",
        "share_delivery",
        "share_sellable_release",
        "rights_not_exercised",
        "tax_assess",
        "tax_recognize",
        "tax_collect",
    }
)


@dataclass(frozen=True, slots=True)
class OwnerCorporateActionPreparedIntent:
    """Exact server-generated facts; neither a token nor independent financial authority."""

    action: OwnerCorporateActionOperation
    account_id: int
    owner_user_id: int
    selector: SimulatedCorporateActionWriteGrantSelector
    source_reference: CorporateActionStageRequest
    requests: tuple[CorporateActionStageRequest, ...]
    assessment: CorporateActionTaxAssessment | None
    operation_id: str
    prepared_at: datetime
    valid_until: datetime
    share_tax_proof: ShareCapitalTaxQualificationProof | None = None

    def __post_init__(self) -> None:
        """Reject cross-owner, mixed-source, unbounded or incorrectly shaped commands."""
        if (
            type(self.action) is not str
            or self.action not in OWNER_CORPORATE_ACTION_OPERATIONS
            or type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.owner_user_id) is not int
            or self.owner_user_id <= 0
            or type(self.selector) is not SimulatedCorporateActionWriteGrantSelector
            or type(self.source_reference) is not CorporateActionStageRequest
            or type(self.requests) is not tuple
            or len(self.requests) > 12
            or type(self.operation_id) is not str
            or not self.operation_id
            or len(self.operation_id) > 192
        ):
            raise ValueError("owner corporate-action intent is invalid")
        self.selector.__post_init__()
        self.source_reference.__post_init__()
        for instant in (self.prepared_at, self.valid_until):
            if (
                type(instant) is not datetime
                or instant.tzinfo is None
                or instant.utcoffset() is None
            ):
                raise ValueError("intent clocks must be aware")
        if not self.source_reference.posted_at <= self.prepared_at < self.valid_until:
            raise ValueError("intent has no ordered finite confirmation window")
        if self.selector.binding.owner_user_id != self.owner_user_id:
            raise ValueError("intent selector belongs to another owner")
        for request in (self.source_reference, *self.requests):
            if type(request) is not CorporateActionStageRequest:
                raise ValueError("intent stage is untyped")
            request.__post_init__()
            if (
                request.account_id != self.account_id
                or request.owner_user_id != self.owner_user_id
                or request.source_record_id != self.source_reference.source_record_id
                or request.source_revision_id != self.source_reference.source_revision_id
                or request.asset_code != self.source_reference.asset_code
                or request.security_id != self.source_reference.security_id
            ):
                raise ValueError("intent stages cross owner or source scope")
        if self.action.startswith("tax_"):
            if self.requests or type(self.assessment) is not CorporateActionTaxAssessment:
                raise ValueError("tax intent requires an exact assessment and no posting stages")
            assessment = self.assessment.verify_integrity()
            action = assessment.action
            if (
                assessment.account_id != self.account_id
                or assessment.owner_user_id != self.owner_user_id
                or action.asset_code != self.source_reference.asset_code
                or action.security_id != self.source_reference.security_id
                or action.source_record_id != self.source_reference.source_record_id
                or action.source_revision_id != self.source_reference.source_revision_id
                or action.source_payload_sha256 != self.source_reference.source_payload_sha256
            ):
                raise ValueError("tax intent assessment crosses its source reference")
        elif self.assessment is not None or not self.requests:
            raise ValueError("posting intent requires exact stages without a tax assessment")
        if self.share_tax_proof is not None:
            self.share_tax_proof.verify_for(self.source_reference, as_of=self.prepared_at)
            if self.share_tax_proof.query.canonical_account_id != self.selector.binding.account_id:
                raise ValueError("share model differs from the exact granted account")
