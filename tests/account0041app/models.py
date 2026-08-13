"""Expose only the 0041 ledger model to isolated Django tooling."""

from apps.account.infrastructure.account_owner_assignment_provenance_receipt_models import (
    AccountOwnerAssignmentProvenanceReceiptModel,
)

__all__ = ["AccountOwnerAssignmentProvenanceReceiptModel"]
