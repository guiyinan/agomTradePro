"""Application facade for deterministic shadow reconciliation and query budgets."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping

from apps.data_center.domain.reconciliation import (
    QueryBudget,
    QueryBudgetResult,
    ReconciliationReport,
    evaluate_query_budget,
    reconcile_records,
)


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


__all__ = ["build_reconciliation_report", "check_query_budget"]
