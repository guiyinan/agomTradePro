"""Application use case for fail-closed Task Monitor orphan reconciliation."""

import json
import logging
from dataclasses import dataclass

from apps.task_monitor.domain.entities import TaskStatus
from apps.task_monitor.domain.interfaces import (
    TaskOrphanEvidenceProviderProtocol,
    TaskRecordRepositoryProtocol,
)
from apps.task_monitor.domain.orphan_policy import confirms_task_orphan

logger = logging.getLogger(__name__)
_ORPHAN_TIMEOUT_CODE = "TASK_ORPHAN_TIMEOUT"


@dataclass(frozen=True)
class TaskOrphanReconciliationResult:
    """Counts for one bounded orphan-reconciliation maintenance pass."""

    checked_count: int
    timed_out_count: int
    deferred_count: int
    evidence_complete: bool


class ReconcileOrphanedTaskRecordsUseCase:
    """Coordinate evidence reads and conditional Task Monitor timeout writes."""

    def __init__(
        self,
        *,
        repository: TaskRecordRepositoryProtocol,
        evidence_provider: TaskOrphanEvidenceProviderProtocol,
        limit: int = 200,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("orphan reconciliation limit must be between 1 and 500")
        self.repository = repository
        self.evidence_provider = evidence_provider
        self.limit = limit

    def execute(self) -> TaskOrphanReconciliationResult:
        """Mark only attempts whose complete evidence proves they are orphaned."""

        candidates = self.repository.list_orphan_reconciliation_candidates(limit=self.limit)
        if not candidates:
            return TaskOrphanReconciliationResult(
                checked_count=0,
                timed_out_count=0,
                deferred_count=0,
                evidence_complete=True,
            )

        try:
            snapshot = self.evidence_provider.capture_cluster_snapshot()
        except Exception as exc:
            logger.info("Task orphan snapshot unavailable: error_type=%s", type(exc).__name__)
            return TaskOrphanReconciliationResult(
                checked_count=len(candidates),
                timed_out_count=0,
                deferred_count=len(candidates),
                evidence_complete=False,
            )

        if not snapshot.complete:
            return TaskOrphanReconciliationResult(
                checked_count=len(candidates),
                timed_out_count=0,
                deferred_count=len(candidates),
                evidence_complete=False,
            )

        timed_out_count = 0
        for record in candidates:
            if record.attempt_id is None:
                continue
            try:
                attempt_evidence = self.evidence_provider.get_attempt_evidence(
                    record,
                    snapshot=snapshot,
                )
                if not confirms_task_orphan(
                    record,
                    snapshot=snapshot,
                    attempt_evidence=attempt_evidence,
                ):
                    continue
                result = json.dumps(
                    {
                        "outcome": "failed",
                        "success": False,
                        "requested": None,
                        "succeeded": None,
                        "failed": None,
                        "stored": None,
                        "counts_unavailable": True,
                        "error_code": _ORPHAN_TIMEOUT_CODE,
                        "blocked_reason": _ORPHAN_TIMEOUT_CODE,
                        "orphan_evidence": attempt_evidence.to_safe_dict(
                            record=record,
                            snapshot=snapshot,
                        ),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                started_at = record.started_at
                runtime_seconds = (
                    max(0.0, (snapshot.observed_at - started_at).total_seconds())
                    if started_at is not None
                    else None
                )
                updated = self.repository.timeout_orphan_if_current_attempt(
                    task_id=record.task_id,
                    expected_status=TaskStatus.STARTED,
                    expected_attempt_id=record.attempt_id,
                    finished_at=snapshot.observed_at,
                    runtime_seconds=runtime_seconds,
                    result=result,
                    exception=_ORPHAN_TIMEOUT_CODE,
                )
                if updated:
                    timed_out_count += 1
            except Exception as exc:
                logger.info(
                    "Task orphan candidate deferred: error_type=%s",
                    type(exc).__name__,
                )

        return TaskOrphanReconciliationResult(
            checked_count=len(candidates),
            timed_out_count=timed_out_count,
            deferred_count=len(candidates) - timed_out_count,
            evidence_complete=True,
        )
