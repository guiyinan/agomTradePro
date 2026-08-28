"""Application facade for deterministic shadow reconciliation and query budgets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from apps.data_center.application.sync_transaction import (
    DataCenterSyncClock,
    DataCenterSyncUnitOfWork,
    DataConflictAuditWriter,
)
from apps.data_center.domain.reconciliation import (
    QueryBudget,
    QueryBudgetResult,
    ReconciliationClassification,
    ReconciliationEvidence,
    ReconciliationReport,
    evaluate_query_budget,
    reconcile_records,
)
from core.integration.data_center_audit import (
    DataConflictAuditObservation,
    DataConflictTransition,
)


class ReconciliationEvidenceRepositoryPort(Protocol):
    """Transaction-bound persistence port for reconciliation evidence."""

    @property
    def unit_of_work_key(self) -> str:
        """Return the exact transaction identity used by this repository."""

    def save(self, evidence: ReconciliationEvidence) -> ReconciliationEvidence:
        """Append or replay one immutable evidence record."""

    def get_latest(self, dataset_key: str) -> ReconciliationEvidence | None:
        """Return the newest evidence for one dataset."""

    def get_latest_for_update(self, dataset_key: str) -> ReconciliationEvidence | None:
        """Lock and return the newest evidence inside the active transaction."""


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


def reconciliation_evidence_content_hash(evidence: ReconciliationEvidence) -> str:
    """Hash the exact persisted reconciliation evidence representation.

    The digest is calculated from the domain value returned by the repository,
    so the audit reference covers the actual durable representation rather than
    an unpersisted request object.
    """

    if not isinstance(evidence, ReconciliationEvidence):
        raise TypeError("evidence must be a ReconciliationEvidence")
    rows: list[dict[str, object]] = [
        {
            "natural_key": row.natural_key,
            "classification": row.classification.value,
            "legacy_value": row.legacy_value,
            "canonical_value": row.canonical_value,
        }
        for row in evidence.report.rows
    ]
    payload: dict[str, object] = {
        "evidence_id": evidence.evidence_id,
        "dataset_key": evidence.report.dataset_key,
        "legacy_snapshot_hash": evidence.legacy_snapshot_hash,
        "canonical_snapshot_hash": evidence.canonical_snapshot_hash,
        "observed_at": evidence.observed_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "rows": rows,
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("reconciliation evidence must be JSON-compatible") from error
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
    """Persist evidence and its actual conflict transition in one unit of work."""

    def __init__(
        self,
        repository: ReconciliationEvidenceRepositoryPort,
        *,
        audit_writer: DataConflictAuditWriter,
        unit_of_work: DataCenterSyncUnitOfWork,
        clock: DataCenterSyncClock,
    ) -> None:
        if repository.unit_of_work_key != unit_of_work.unit_of_work_key:
            raise ValueError("reconciliation repository and unit of work differ")
        self._repository = repository
        self._audit_writer = audit_writer
        self._unit_of_work = unit_of_work
        self._clock = clock

    def execute(
        self,
        report: ReconciliationReport,
        *,
        legacy_snapshot_hash: str,
        canonical_snapshot_hash: str,
        evidence_id: str | None = None,
        observed_at: datetime | None = None,
    ) -> ReconciliationEvidence:
        """Persist evidence and emit only a detected/resolved state transition."""

        recorded_at = self._clock.now()
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("reconciliation clock must be timezone-aware")
        evidence_observed_at = observed_at or recorded_at
        if evidence_observed_at.tzinfo is None or evidence_observed_at.utcoffset() is None:
            raise ValueError("reconciliation observed_at must be timezone-aware")
        if evidence_observed_at > recorded_at:
            raise ValueError("reconciliation observed_at cannot be after recorded_at")
        evidence = ReconciliationEvidence(
            evidence_id=evidence_id or str(uuid4()),
            report=report,
            legacy_snapshot_hash=legacy_snapshot_hash,
            canonical_snapshot_hash=canonical_snapshot_hash,
            observed_at=evidence_observed_at,
        )
        with self._unit_of_work.atomic():
            previous = self._repository.get_latest_for_update(report.dataset_key)
            persisted = self._repository.save(evidence)
            if persisted != evidence:
                raise ValueError("reconciliation repository substituted the evidence")
            transition = _conflict_transition(previous, persisted)
            if transition is not None:
                current_count = _semantic_conflict_count(persisted)
                previous_count = (
                    _semantic_conflict_count(previous) if previous is not None else None
                )
                self._audit_writer.write(
                    DataConflictAuditObservation(
                        dataset_key=persisted.report.dataset_key,
                        transition=transition,
                        evidence_id=persisted.evidence_id,
                        evidence_version="1",
                        evidence_content_hash=reconciliation_evidence_content_hash(persisted),
                        conflict_count=current_count,
                        previous_conflict_count=previous_count,
                        previous_evidence_id=(
                            previous.evidence_id if previous is not None else None
                        ),
                        previous_evidence_version="1" if previous is not None else None,
                        previous_evidence_content_hash=(
                            reconciliation_evidence_content_hash(previous)
                            if previous is not None
                            else None
                        ),
                        occurred_at=persisted.observed_at,
                        recorded_at=recorded_at,
                    )
                )
        return persisted


def _semantic_conflict_count(evidence: ReconciliationEvidence) -> int:
    """Return the exact semantic-conflict count from one evidence record."""

    return evidence.report.counts[ReconciliationClassification.SEMANTIC_CONFLICT.value]


def _conflict_transition(
    previous: ReconciliationEvidence | None,
    current: ReconciliationEvidence,
) -> DataConflictTransition | None:
    """Derive the only registered conflict lifecycle transitions."""

    previous_count = _semantic_conflict_count(previous) if previous is not None else 0
    current_count = _semantic_conflict_count(current)
    if previous_count == 0 and current_count > 0:
        return "detected"
    if previous_count > 0 and current_count == 0:
        return "resolved"
    return None


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
    "reconciliation_evidence_content_hash",
    "ReconciliationEvidenceRepositoryPort",
]
