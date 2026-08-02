"""Deterministic shadow-reconciliation and query-budget evidence."""

from __future__ import annotations

import pytest

from apps.data_center.application.reconciliation import (
    build_reconciliation_report,
    check_query_budget,
)
from apps.data_center.domain.reconciliation import (
    QueryBudget,
    ReconciliationClassification,
)


def test_reconciliation_report_classifies_same_expected_missing_and_conflict() -> None:
    """Every difference category remains explicit and machine-countable."""

    report = build_reconciliation_report(
        "macro.fact",
        {"same": 1, "expected": 2, "missing": 3, "conflict": 4},
        {"same": 1, "expected": 2.0, "conflict": 5, "canonical_only": 6},
        equivalent=lambda left, right: float(left) == float(right),
        expected_difference_keys={"expected"},
    )

    assert report.counts == {
        "same": 1,
        "expected_difference": 1,
        "data_missing": 2,
        "semantic_conflict": 1,
        "code_defect": 0,
    }
    assert not report.is_clean
    assert (
        next(row for row in report.rows if row.natural_key == "same").classification
        == ReconciliationClassification.SAME
    )


def test_reconciliation_report_can_mark_known_code_defects() -> None:
    """Known implementation defects are not mislabeled as provider conflicts."""

    report = build_reconciliation_report(
        "equity.price.bar",
        {"600000.SH|2026-08-01": 10},
        {"600000.SH|2026-08-01": 11},
        code_defect_keys={"600000.SH|2026-08-01"},
    )

    assert report.rows[0].classification == ReconciliationClassification.CODE_DEFECT


def test_query_budget_has_strict_count_and_latency_boundaries() -> None:
    """N+1/query-latency regressions fail at the declared boundary."""

    budget = QueryBudget("data_center.news.current", max_queries=2, max_p95_ms=50.0)
    passed = check_query_budget(budget, query_count=2, p95_ms=50.0)
    failed = check_query_budget(budget, query_count=3, p95_ms=50.1)

    assert passed.passed is True
    assert failed.passed is False
    assert failed.violations == ("query_count_exceeded", "p95_latency_exceeded")


def test_query_budget_rejects_missing_latency_when_latency_is_required() -> None:
    """A latency budget cannot be silently skipped when no percentile was measured."""

    budget = QueryBudget("data_center.financial.current", max_queries=3, max_p95_ms=25.0)
    result = check_query_budget(budget, query_count=1)

    assert result.passed is False
    assert result.violations == ("p95_latency_exceeded",)


def test_query_budget_rejects_invalid_observations() -> None:
    """Negative and non-finite observations fail before comparison."""

    with pytest.raises(ValueError, match="query_count"):
        check_query_budget(QueryBudget("test", max_queries=1), query_count=-1)
    with pytest.raises(ValueError, match="p95_ms"):
        check_query_budget(QueryBudget("test", max_queries=1), query_count=1, p95_ms=float("nan"))
