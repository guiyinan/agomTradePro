"""Pure decisions for safely reconciling abandoned Celery executions."""

from datetime import datetime

from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskOrphanAttemptEvidence,
    TaskOrphanClusterSnapshot,
    TaskOrphanLeaseState,
    TaskStatus,
)

_MAX_ORPHAN_GRACE_SECONDS = 3_600
_NONTERMINAL_BACKEND_STATES = {"PENDING", "STARTED", "RETRY", "UNKNOWN"}


def confirms_task_orphan(
    record: TaskExecutionRecord,
    *,
    snapshot: TaskOrphanClusterSnapshot,
    attempt_evidence: TaskOrphanAttemptEvidence,
) -> bool:
    """Return true only when every required timeout and absence signal agrees."""

    if (
        record.status is not TaskStatus.STARTED
        or record.retries != 0
        or record.started_at is None
        or record.attempt_id is None
        or not record.attempt_id
        or record.worker is None
        or not record.worker
        or not snapshot.complete
        or snapshot.ready_message_count != 0
        or snapshot.managed_queue_count <= 0
        or snapshot.active_task_ids is None
        or snapshot.reserved_task_ids is None
        or snapshot.scheduled_task_ids is None
        or snapshot.responding_worker_names is None
        or record.worker in snapshot.responding_worker_names
    ):
        return False

    hard_limit = attempt_evidence.hard_time_limit_seconds
    visibility_timeout = snapshot.broker_visibility_timeout_seconds
    grace = snapshot.grace_seconds
    if (
        isinstance(hard_limit, bool)
        or not isinstance(hard_limit, int)
        or hard_limit <= 0
        or isinstance(visibility_timeout, bool)
        or not isinstance(visibility_timeout, int)
        or visibility_timeout <= 0
        or isinstance(grace, bool)
        or not isinstance(grace, int)
        or not 0 <= grace <= _MAX_ORPHAN_GRACE_SECONDS
    ):
        return False

    if (
        attempt_evidence.backend_state not in _NONTERMINAL_BACKEND_STATES
        or attempt_evidence.lease_state
        not in {TaskOrphanLeaseState.ABSENT, TaskOrphanLeaseState.NOT_REQUIRED}
    ):
        return False

    observed_task_ids = (
        *snapshot.active_task_ids,
        *snapshot.reserved_task_ids,
        *snapshot.scheduled_task_ids,
    )
    if record.task_id in observed_task_ids:
        return False

    started_at = _timestamp(record.started_at)
    observed_at = _timestamp(snapshot.observed_at)
    if started_at <= 0 or observed_at <= 0:
        return False
    deadline = started_at + hard_limit + visibility_timeout + grace
    return observed_at > deadline


def _timestamp(value: datetime) -> float:
    """Return an aware timestamp; malformed timezone evidence fails closed."""

    if value.tzinfo is None or value.utcoffset() is None:
        return 0.0
    return value.timestamp()
