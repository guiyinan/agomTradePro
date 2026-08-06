"""Exact fixed-income bundle projection for Research-owned R5 promotion."""

from __future__ import annotations

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
)
from apps.research.domain.r5_relative_value_promotion_record import (
    R5RelativeValueOwnerRecordSeal,
)


def project_r5_relative_value_owner_record(
    bundle: R5PersistedRelativeValueBundle,
) -> R5RelativeValueOwnerRecordSeal:
    """Project a strictly restored owner bundle into its complete Domain seal."""

    # Re-instantiation makes the receipt/result cross-link validation explicit at
    # the Application boundary instead of trusting a provider's nominal type.
    canonical = R5PersistedRelativeValueBundle(
        receipt=bundle.receipt,
        result=bundle.result,
    )
    return R5RelativeValueOwnerRecordSeal.create(
        result_id=canonical.result.result_id,
        result_version=canonical.result.result_version,
        result_record_hash=canonical.result.record_hash,
        receipt_id=canonical.receipt.receipt_id,
        receipt_version=canonical.receipt.receipt_version,
        receipt_hash=canonical.receipt.receipt_hash,
        command_hash=canonical.result.command_hash,
        evidence_clock_graph_hash=canonical.result.evidence_clock_graph_hash,
        recorded_at=canonical.result.recorded_at,
        assessment=canonical.result.assessment,
    )


__all__ = ["project_r5_relative_value_owner_record"]
