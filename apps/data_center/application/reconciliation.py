"""Application facade for deterministic shadow reconciliation and query budgets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
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


def hash_reconciliation_snapshot(snapshot: Mapping[str, object]) -> str:
    """Hash one JSON-compatible snapshot using a stable, fail-closed encoding.

    Shadow evidence is only useful when the bytes being compared can be
    reproduced.  We therefore sort object keys, use compact separators and
    reject NaN/Infinity or values that are not JSON-compatible instead of
    silently stringifying them.
    """

    normalized = _normalize_snapshot(snapshot)
    try:
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("reconciliation snapshot must be JSON-compatible") from exc
    return hashlib.sha256(encoded).hexdigest()


def _normalize_snapshot(snapshot: Mapping[str, object]) -> dict[str, object]:
    """Normalize snapshot keys without silently dropping collisions."""

    normalized: dict[str, object] = {}
    for raw_key, value in snapshot.items():
        key = str(raw_key).strip()
        if not key:
            raise ValueError("reconciliation snapshot keys cannot be empty")
        if key in normalized:
            raise ValueError(f"reconciliation snapshot key collision: {key}")
        normalized[key] = value
    return normalized


@dataclass(frozen=True)
class ReconciliationSnapshotExport:
    """Immutable hash and classification evidence for one injected snapshot pair.

    This is deliberately an Application-level value object.  It accepts
    snapshots supplied by a maintenance fixture or an owning repository, but
    never imports either legacy or canonical storage.  Production current
    reads therefore cannot accidentally become shadow reads.
    """

    report: ReconciliationReport
    legacy_snapshot: dict[str, object]
    canonical_snapshot: dict[str, object]
    legacy_snapshot_hash: str
    canonical_snapshot_hash: str

    @property
    def classification_evidence(self) -> tuple[dict[str, str], ...]:
        """Return deterministic per-natural-key classification evidence."""

        return tuple(
            {
                "natural_key": row.natural_key,
                "classification": row.classification.value,
            }
            for row in self.report.rows
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe export payload for maintenance evidence."""

        return {
            "dataset_key": self.report.dataset_key,
            "legacy_snapshot_hash": self.legacy_snapshot_hash,
            "canonical_snapshot_hash": self.canonical_snapshot_hash,
            "counts": self.report.counts,
            "classification_evidence": [dict(row) for row in self.classification_evidence],
        }


def export_reconciliation_snapshot(
    dataset_key: str,
    legacy_records: Mapping[str, object],
    canonical_records: Mapping[str, object],
    *,
    equivalent: Callable[[object, object], bool] | None = None,
    expected_difference_keys: Collection[str] = (),
    code_defect_keys: Collection[str] = (),
) -> ReconciliationSnapshotExport:
    """Build deterministic shadow evidence from two injected snapshots.

    The function is intentionally bounded to caller-provided records.  It
    does not discover, query or write any legacy table and it raises on an
    invalid snapshot rather than emitting an incomplete evidence record.
    """

    legacy = _normalize_snapshot(legacy_records)
    canonical = _normalize_snapshot(canonical_records)
    report = reconcile_records(
        dataset_key,
        legacy,
        canonical,
        equivalent=equivalent,
        expected_difference_keys=expected_difference_keys,
        code_defect_keys=code_defect_keys,
    )
    return ReconciliationSnapshotExport(
        report=report,
        legacy_snapshot=legacy,
        canonical_snapshot=canonical,
        legacy_snapshot_hash=hash_reconciliation_snapshot(legacy),
        canonical_snapshot_hash=hash_reconciliation_snapshot(canonical),
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
    "ReconciliationSnapshotExport",
    "build_reconciliation_report",
    "check_query_budget",
    "export_reconciliation_snapshot",
    "hash_reconciliation_snapshot",
]
