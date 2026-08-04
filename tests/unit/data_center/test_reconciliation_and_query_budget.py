"""Deterministic shadow-reconciliation and query-budget evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.data_center.application.reconciliation import (
    build_reconciliation_report,
    check_query_budget,
    export_reconciliation_snapshot,
    hash_reconciliation_snapshot,
)
from apps.data_center.domain.reconciliation import (
    QueryBudget,
    ReconciliationClassification,
)

_D1_FIXTURE_DIR = Path(__file__).parents[2] / "fixtures" / "data_center_reconciliation"


def _load_d1_fixture(name: str) -> dict[str, object]:
    """Load one bounded D1 shadow fixture as a JSON object."""

    payload = json.loads((_D1_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_d1_fixture_export_emits_hashes_and_all_classification_evidence() -> None:
    """A bounded D1 fixture produces reproducible, machine-readable evidence."""

    legacy = _load_d1_fixture("equity_price_bar_legacy.json")
    canonical = _load_d1_fixture("equity_price_bar_canonical.json")
    exported = export_reconciliation_snapshot(
        "equity.price.bar",
        legacy,
        canonical,
        expected_difference_keys={"000002.SZ|2026-08-01"},
        code_defect_keys={"600000.SH|2026-08-01"},
    )

    assert len(exported.legacy_snapshot_hash) == 64
    assert len(exported.canonical_snapshot_hash) == 64
    assert exported.report.counts == {
        "same": 1,
        "expected_difference": 1,
        "data_missing": 2,
        "semantic_conflict": 0,
        "code_defect": 1,
    }
    assert exported.report.is_clean is False
    assert exported.to_dict()["classification_evidence"] == [
        {"natural_key": "000001.SZ|2026-08-01", "classification": "same"},
        {
            "natural_key": "000002.SZ|2026-08-01",
            "classification": "expected_difference",
        },
        {"natural_key": "300001.SZ|2026-08-01", "classification": "data_missing"},
        {"natural_key": "600000.SH|2026-08-01", "classification": "code_defect"},
        {"natural_key": "601318.SH|2026-08-01", "classification": "data_missing"},
    ]

    # Sorting is part of the evidence contract; input insertion order cannot
    # change either source hash.
    assert exported.legacy_snapshot_hash == hash_reconciliation_snapshot(
        dict(reversed(list(legacy.items())))
    )


def test_reconciliation_snapshot_hash_rejects_non_json_values() -> None:
    """Unsupported values fail closed instead of being stringified into evidence."""

    with pytest.raises(ValueError, match="JSON-compatible"):
        hash_reconciliation_snapshot({"row": float("nan")})


def test_reconciliation_snapshot_export_rejects_empty_natural_key() -> None:
    """An invalid natural key cannot produce a misleading shadow report."""

    with pytest.raises(ValueError, match="keys cannot be empty"):
        export_reconciliation_snapshot("equity.price.bar", {" ": 1}, {})


def test_reconciliation_snapshot_hash_rejects_normalized_key_collision() -> None:
    """Different raw keys cannot collapse to one natural key in evidence."""

    with pytest.raises(ValueError, match="key collision"):
        hash_reconciliation_snapshot({1: 1, "1": 1})


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
