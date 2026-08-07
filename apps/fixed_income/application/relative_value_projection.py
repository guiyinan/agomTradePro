"""Exact FixedIncome bundle projection for downstream R5 research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.fixed_income.application.relative_value_persistence import (
    R5PersistedRelativeValueBundle,
    R5RelativeValuePersistenceRepository,
)
from apps.fixed_income.domain.evidence import require_aware, require_sha256, require_token
from apps.fixed_income.domain.relative_value_record_seal import (
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


@dataclass(frozen=True)
class GetExactR5RelativeValueOwnerRecordCommand:
    """Exact result locator used by downstream Application consumers."""

    result_id: str
    result_version: str
    expected_record_hash: str
    as_of: datetime

    def __post_init__(self) -> None:
        require_token(self.result_id, "result_id", maximum=300)
        require_token(self.result_version, "result_version", maximum=300)
        require_sha256(self.expected_record_hash, "expected_record_hash")
        require_aware(self.as_of, "as_of")


class GetExactR5RelativeValueOwnerRecord:
    """Strictly restore and project one FixedIncome-owned result record."""

    def __init__(self, repository: R5RelativeValuePersistenceRepository) -> None:
        self._repository = repository

    @property
    def unit_of_work_key(self) -> str:
        """Return the underlying exact-query transaction boundary key."""

        return self._repository.unit_of_work_key

    def execute(
        self,
        command: GetExactR5RelativeValueOwnerRecordCommand,
    ) -> R5RelativeValueOwnerRecordSeal | None:
        """Return a full owner seal only after strict persisted replay."""

        bundle = self._repository.get_exact(
            result_id=command.result_id,
            result_version=command.result_version,
            expected_record_hash=command.expected_record_hash,
            as_of=command.as_of,
        )
        if bundle is None:
            return None
        return project_r5_relative_value_owner_record(bundle)


__all__ = [
    "GetExactR5RelativeValueOwnerRecord",
    "GetExactR5RelativeValueOwnerRecordCommand",
    "project_r5_relative_value_owner_record",
]
