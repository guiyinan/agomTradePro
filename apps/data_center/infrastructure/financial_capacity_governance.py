"""Read exact capacity approvals entered independently in the deployment database."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityRehearsalCeilingSource,
    FinancialCapacityWorkflowError,
    FinancialProductionCeilingSource,
    FinancialQualificationCeilingSource,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
)
from apps.data_center.application.financial_capacity_governance import (
    parse_financial_capacity_governance_record,
)
from apps.data_center.infrastructure.models import (
    FinancialCapacityGovernanceRecordModel,
    FinancialCapacityOwnerApprovalEventModel,
)


class DjangoFinancialCapacityGovernanceSource(
    FinancialProductionCeilingSource,
    FinancialQualificationCeilingSource,
    FinancialCapacityRehearsalCeilingSource,
):
    """Read exact, owner-event-bound ceilings; raw JSON owner labels are never authority."""

    def get(
        self,
        *,
        receipt_sha256: str,
        candidate_sha: str,
        manifest_sha256: str,
    ) -> GovernedFinancialProductionCeiling | None:
        """Return the sole matching production approval from the independent DB record store."""

        matches: list[GovernedFinancialProductionCeiling] = []
        rows = (
            FinancialCapacityGovernanceRecordModel._default_manager.filter(
                stage=FinancialCapacityGovernanceRecordModel.PRODUCTION,
                revocation__isnull=True,
            )
            .select_related("owner_approval_event")
            .iterator(chunk_size=100)
        )
        for row in rows:
            raw_record = row.record
            if not isinstance(raw_record, Mapping):
                continue
            try:
                ceiling = parse_financial_capacity_governance_record(
                    stage="production",
                    record=raw_record,
                )
            except (FinancialCapacityWorkflowError, TypeError, ValueError):
                continue
            if not isinstance(ceiling, GovernedFinancialProductionCeiling):
                continue
            if (
                ceiling.approval_id == row.approval_id
                and _has_matching_owner_event(row, ceiling, raw_record)
                and ceiling.receipt_sha256 == receipt_sha256
                and ceiling.binding.candidate_sha == candidate_sha
                and ceiling.manifest_sha256 == manifest_sha256
            ):
                matches.append(ceiling)
        return matches[0] if len(matches) == 1 else None

    def get_qualification(
        self,
        *,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
    ) -> GovernedFinancialQualificationCeiling | None:
        """Return the sole exact isolated-workload approval from the database."""

        matches: list[GovernedFinancialQualificationCeiling] = []
        rows = (
            FinancialCapacityGovernanceRecordModel._default_manager.filter(
                stage=FinancialCapacityGovernanceRecordModel.QUALIFICATION,
                revocation__isnull=True,
            )
            .select_related("owner_approval_event")
            .iterator(chunk_size=100)
        )
        for row in rows:
            raw_record = row.record
            if not isinstance(raw_record, Mapping):
                continue
            try:
                ceiling = parse_financial_capacity_governance_record(
                    stage="qualification",
                    record=raw_record,
                )
            except (FinancialCapacityWorkflowError, TypeError, ValueError):
                continue
            if not isinstance(ceiling, GovernedFinancialQualificationCeiling):
                continue
            if (
                ceiling.approval_id == row.approval_id
                and _has_matching_owner_event(row, ceiling, raw_record)
                and ceiling.binding == binding
                and ceiling.manifest_sha256 == manifest_sha256
            ):
                matches.append(ceiling)
        return matches[0] if len(matches) == 1 else None

    def get_capacity_rehearsal(
        self,
        *,
        binding: FinancialCapacityBinding,
        manifest_sha256: str,
    ) -> GovernedFinancialCapacityRehearsalCeiling | None:
        """Return the exact full-scope isolated rehearsal approval from the DB."""

        matches: list[GovernedFinancialCapacityRehearsalCeiling] = []
        rows = (
            FinancialCapacityGovernanceRecordModel._default_manager.filter(
                stage=FinancialCapacityGovernanceRecordModel.CAPACITY_REHEARSAL,
                revocation__isnull=True,
            )
            .select_related("owner_approval_event")
            .iterator(chunk_size=100)
        )
        for row in rows:
            raw_record = row.record
            if not isinstance(raw_record, Mapping):
                continue
            try:
                ceiling = parse_financial_capacity_governance_record(
                    stage="capacity_rehearsal",
                    record=raw_record,
                )
            except (FinancialCapacityWorkflowError, TypeError, ValueError):
                continue
            if not isinstance(ceiling, GovernedFinancialCapacityRehearsalCeiling):
                continue
            if (
                ceiling.approval_id == row.approval_id
                and _has_matching_owner_event(row, ceiling, raw_record)
                and ceiling.binding == binding
                and ceiling.manifest_sha256 == manifest_sha256
            ):
                matches.append(ceiling)
        return matches[0] if len(matches) == 1 else None


def _has_matching_owner_event(
    row: FinancialCapacityGovernanceRecordModel,
    ceiling: (
        GovernedFinancialCapacityRehearsalCeiling
        | GovernedFinancialQualificationCeiling
        | GovernedFinancialProductionCeiling
    ),
    raw_record: Mapping[str, object],
) -> bool:
    """Require a separate authenticated-owner event bound to the exact payload digest."""

    try:
        event = row.owner_approval_event
    except FinancialCapacityOwnerApprovalEventModel.DoesNotExist:
        return False
    canonical = json.dumps(
        raw_record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return (
        bool(event.event_id)
        and event.approved_by == ceiling.approved_by
        and event.approved_at == ceiling.approved_at
        and event.approval_receipt_sha256 == ceiling.approval_receipt_sha256
        and event.record_sha256 == hashlib.sha256(canonical).hexdigest()
    )


__all__ = ["DjangoFinancialCapacityGovernanceSource"]
