"""Pure shadow-reconciliation and query-budget contracts."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class ReconciliationClassification(str, Enum):
    """Stable categories for legacy/canonical shadow-read differences."""

    SAME = "same"
    EXPECTED_DIFFERENCE = "expected_difference"
    DATA_MISSING = "data_missing"
    SEMANTIC_CONFLICT = "semantic_conflict"
    CODE_DEFECT = "code_defect"


@dataclass(frozen=True)
class ReconciliationDifference:
    """One deterministic natural-key comparison result."""

    natural_key: str
    classification: ReconciliationClassification
    legacy_value: object | None = None
    canonical_value: object | None = None


@dataclass(frozen=True)
class ReconciliationReport:
    """Immutable summary suitable for audit logs and CI evidence."""

    dataset_key: str
    rows: tuple[ReconciliationDifference, ...]

    @property
    def counts(self) -> dict[str, int]:
        """Return stable category counts."""

        counts = {classification.value: 0 for classification in ReconciliationClassification}
        for row in self.rows:
            counts[row.classification.value] += 1
        return counts

    @property
    def is_clean(self) -> bool:
        """Return whether no unresolved difference remains."""

        return all(
            row.classification
            in {
                ReconciliationClassification.SAME,
                ReconciliationClassification.EXPECTED_DIFFERENCE,
            }
            for row in self.rows
        )


@dataclass(frozen=True)
class ReconciliationEvidence:
    """Persistable evidence for one legacy/canonical shadow comparison."""

    evidence_id: str
    report: ReconciliationReport
    legacy_snapshot_hash: str
    canonical_snapshot_hash: str
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("ReconciliationEvidence.evidence_id cannot be empty")
        if not self.legacy_snapshot_hash.strip():
            raise ValueError("ReconciliationEvidence.legacy_snapshot_hash cannot be empty")
        if not self.canonical_snapshot_hash.strip():
            raise ValueError("ReconciliationEvidence.canonical_snapshot_hash cannot be empty")
        if self.report.dataset_key.strip() == "":
            raise ValueError("ReconciliationEvidence.report dataset_key cannot be empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("ReconciliationEvidence.observed_at must be timezone-aware")


def reconcile_records(
    dataset_key: str,
    legacy_records: Mapping[str, object],
    canonical_records: Mapping[str, object],
    *,
    equivalent: Callable[[object, object], bool] | None = None,
    expected_difference_keys: Collection[str] = (),
    code_defect_keys: Collection[str] = (),
) -> ReconciliationReport:
    """Compare two read snapshots without importing either storage implementation.

    ``legacy_records`` and ``canonical_records`` are injected snapshots.  The
    application layer can therefore run this against a one-time maintenance
    export, while normal business reads remain canonical-only.
    """

    normalized_dataset_key = str(dataset_key or "").strip()
    if not normalized_dataset_key:
        raise ValueError("dataset_key must be non-empty")
    comparator = equivalent or (lambda left, right: left == right)
    expected = set(expected_difference_keys)
    defects = set(code_defect_keys)
    natural_keys = sorted(set(legacy_records) | set(canonical_records))
    rows: list[ReconciliationDifference] = []
    for natural_key in natural_keys:
        legacy_present = natural_key in legacy_records
        canonical_present = natural_key in canonical_records
        if not legacy_present or not canonical_present:
            classification = ReconciliationClassification.DATA_MISSING
        elif natural_key in defects:
            classification = ReconciliationClassification.CODE_DEFECT
        elif natural_key in expected:
            classification = ReconciliationClassification.EXPECTED_DIFFERENCE
        elif comparator(legacy_records[natural_key], canonical_records[natural_key]):
            classification = ReconciliationClassification.SAME
        else:
            classification = ReconciliationClassification.SEMANTIC_CONFLICT
        rows.append(
            ReconciliationDifference(
                natural_key=natural_key,
                classification=classification,
                legacy_value=legacy_records.get(natural_key),
                canonical_value=canonical_records.get(natural_key),
            )
        )
    return ReconciliationReport(dataset_key=normalized_dataset_key, rows=tuple(rows))


@dataclass(frozen=True)
class QueryBudget:
    """Bound one canonical query port's query count and latency percentile."""

    budget_key: str
    max_queries: int
    max_p95_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.budget_key.strip():
            raise ValueError("budget_key must be non-empty")
        if isinstance(self.max_queries, bool) or self.max_queries < 0:
            raise ValueError("max_queries must be non-negative")
        if self.max_p95_ms is not None and (not isfinite(self.max_p95_ms) or self.max_p95_ms < 0):
            raise ValueError("max_p95_ms must be finite and non-negative")


@dataclass(frozen=True)
class QueryBudgetResult:
    """Evaluation result with stable machine-readable failures."""

    budget_key: str
    query_count: int
    p95_ms: float | None
    passed: bool
    violations: tuple[str, ...]


def evaluate_query_budget(
    budget: QueryBudget,
    *,
    query_count: int,
    p95_ms: float | None = None,
) -> QueryBudgetResult:
    """Evaluate observed query count and optional P95 latency against a contract."""

    if isinstance(query_count, bool) or query_count < 0:
        raise ValueError("query_count must be non-negative")
    if p95_ms is not None and (not isfinite(p95_ms) or p95_ms < 0):
        raise ValueError("p95_ms must be finite and non-negative")
    violations: list[str] = []
    if query_count > budget.max_queries:
        violations.append("query_count_exceeded")
    if budget.max_p95_ms is not None and (p95_ms is None or p95_ms > budget.max_p95_ms):
        violations.append("p95_latency_exceeded")
    return QueryBudgetResult(
        budget_key=budget.budget_key,
        query_count=query_count,
        p95_ms=p95_ms,
        passed=not violations,
        violations=tuple(violations),
    )


__all__ = [
    "QueryBudget",
    "QueryBudgetResult",
    "ReconciliationClassification",
    "ReconciliationDifference",
    "ReconciliationEvidence",
    "ReconciliationReport",
    "evaluate_query_budget",
    "reconcile_records",
]
