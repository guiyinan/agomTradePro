"""Application facade for deterministic shadow reconciliation and query budgets."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from datetime import UTC, datetime
from uuid import uuid4

from apps.data_center.domain.protocols import ReconciliationEvidenceRepositoryProtocol
from apps.data_center.domain.reconciliation import (
    QueryBudget,
    QueryBudgetResult,
    ReconciliationEvidence,
    ReconciliationReport,
    evaluate_query_budget,
    reconcile_records,
)


class RecordReconciliationEvidenceUseCase:
    """Turn an injected shadow report into durable Data Center evidence."""

    def __init__(self, repository: ReconciliationEvidenceRepositoryProtocol) -> None:
        self._repository = repository

    def execute(
        self,
        report: ReconciliationReport,
        *,
        legacy_snapshot_hash: str,
        canonical_snapshot_hash: str,
        evidence_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> ReconciliationEvidence:
        """Persist one report with immutable source hashes and observation time."""

        evidence = ReconciliationEvidence(
            evidence_id=evidence_id or str(uuid4()),
            report=report,
            legacy_snapshot_hash=legacy_snapshot_hash,
            canonical_snapshot_hash=canonical_snapshot_hash,
            observed_at=observed_at or datetime.now(UTC),
        )
        return self._repository.save(evidence)


def build_reconciliation_report(
    dataset_key: str,
    legacy_records: Mapping[str, object],
    canonical_records: Mapping[str, object],
    *,
    equivalent: Callable[[object, object], bool] | None = None,
    expected_difference_keys: Collection[str] = (),
    code_defect_keys: Collection[str] = (),
) -> ReconciliationReport:
    """Build an audit-ready report from injected legacy/canonical snapshots."""

    return reconcile_records(
        dataset_key,
        legacy_records,
        canonical_records,
        equivalent=equivalent,
        expected_difference_keys=expected_difference_keys,
        code_defect_keys=code_defect_keys,
    )


def check_query_budget(
    budget: QueryBudget,
    *,
    query_count: int,
    p95_ms: float | None = None,
) -> QueryBudgetResult:
    """Evaluate one measured query-port observation."""

    return evaluate_query_budget(budget, query_count=query_count, p95_ms=p95_ms)


__all__ = [
    "RecordReconciliationEvidenceUseCase",
    "build_reconciliation_report",
    "check_query_budget",
]
