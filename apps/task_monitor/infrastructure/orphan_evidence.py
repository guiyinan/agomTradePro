"""Read-only Celery, broker, and domain-lease evidence for Task Monitor."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from django.conf import settings
from django.utils import timezone

from apps.task_monitor.domain.entities import (
    TaskExecutionRecord,
    TaskOrphanAttemptEvidence,
    TaskOrphanClusterSnapshot,
    TaskOrphanLeaseState,
)
from shared.domain.task_lease_evidence import (
    DomainTaskLeaseEvidence,
    DomainTaskLeaseProbeProtocol,
    DomainTaskLeaseState,
)

_MAX_GRACE_SECONDS = 3_600
_DEFAULT_GRACE_SECONDS = 300
_INSPECT_TIMEOUT_SECONDS = 2.0
_SAFE_EVIDENCE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")


class CeleryTaskOrphanEvidenceProvider:
    """Collect complete read-only snapshots and per-attempt status evidence."""

    def __init__(
        self,
        celery_app: Any,
        *,
        domain_lease_probes: Sequence[DomainTaskLeaseProbeProtocol] = (),
    ) -> None:
        self.celery_app = celery_app
        self.domain_lease_probes = tuple(domain_lease_probes)

    def capture_cluster_snapshot(self) -> TaskOrphanClusterSnapshot:
        """Capture ready queue counts and worker task lists without mutating them."""

        observed_at = timezone.now()
        visibility_timeout = self._visibility_timeout_seconds()
        grace_seconds = self._grace_seconds()
        ready_snapshot = self._ready_message_count()
        ready_message_count = ready_snapshot[0] if ready_snapshot is not None else None
        managed_queue_count = ready_snapshot[1] if ready_snapshot is not None else 0
        worker_snapshot = self._worker_snapshot()
        complete = (
            visibility_timeout is not None
            and grace_seconds is not None
            and ready_message_count is not None
            and managed_queue_count > 0
            and worker_snapshot is not None
        )
        if worker_snapshot is None:
            active_ids = None
            reserved_ids = None
            scheduled_ids = None
            responding_workers = None
        else:
            active_ids, reserved_ids, scheduled_ids, responding_workers = worker_snapshot
        return TaskOrphanClusterSnapshot(
            observed_at=observed_at,
            complete=complete,
            broker_visibility_timeout_seconds=visibility_timeout,
            grace_seconds=grace_seconds,
            ready_message_count=ready_message_count,
            active_task_ids=active_ids,
            reserved_task_ids=reserved_ids,
            scheduled_task_ids=scheduled_ids,
            responding_worker_names=responding_workers,
            managed_queue_count=managed_queue_count,
        )

    def get_attempt_evidence(
        self,
        record: TaskExecutionRecord,
        *,
        snapshot: TaskOrphanClusterSnapshot,
    ) -> TaskOrphanAttemptEvidence:
        """Read one task's effective hard limit, backend state, and domain lease."""

        del snapshot  # The cluster snapshot is captured once for the whole batch.
        lease_state, lease_evidence_code = self._domain_lease_evidence(record)
        return TaskOrphanAttemptEvidence(
            hard_time_limit_seconds=self._hard_time_limit_seconds(record.task_name),
            backend_state=self._backend_state(record.task_id),
            lease_state=lease_state,
            lease_evidence_code=lease_evidence_code,
        )

    def _visibility_timeout_seconds(self) -> int | None:
        """Read the broker transport's positive visibility timeout."""

        conf = getattr(self.celery_app, "conf", None)
        options = getattr(conf, "broker_transport_options", None)
        value = options.get("visibility_timeout") if isinstance(options, Mapping) else None
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _grace_seconds() -> int | None:
        """Read a bounded orphan grace interval from Django settings."""

        value: object = getattr(
            settings, "TASK_MONITOR_ORPHAN_GRACE_SECONDS", _DEFAULT_GRACE_SECONDS
        )
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= _MAX_GRACE_SECONDS
        ):
            return None
        return value

    def _ready_message_count(self) -> tuple[int, int] | None:
        """Read passive message counts for every configured Celery task queue."""

        conf = getattr(self.celery_app, "conf", None)
        queues = getattr(conf, "task_queues", None)
        if not isinstance(queues, Sequence) or isinstance(queues, (str, bytes)) or not queues:
            return None
        queue_names: set[str] = set()
        for queue in queues:
            name = getattr(queue, "name", None)
            if not isinstance(name, str) or not name:
                return None
            queue_names.add(name)
        if not queue_names:
            return None

        connection: Any = None
        channel: Any = None
        try:
            connection = self.celery_app.connection_for_read()
            channel = connection.channel()
            total_messages = 0
            for queue_name in sorted(queue_names):
                declaration = channel.queue_declare(queue=queue_name, passive=True)
                count: object = getattr(declaration, "message_count", None)
                if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    return None
                total_messages += count
            return total_messages, len(queue_names)
        except Exception:
            return None
        finally:
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
            if connection is not None:
                try:
                    connection.release()
                except Exception:
                    pass

    def _worker_snapshot(
        self,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
        """Read ping plus active, reserved, and scheduled task IDs consistently."""

        try:
            inspect = self.celery_app.control.inspect(timeout=_INSPECT_TIMEOUT_SECONDS)
            if inspect is None:
                return None
            ping = inspect.ping()
            active = inspect.active()
            reserved = inspect.reserved()
            scheduled = inspect.scheduled()
        except Exception:
            return None

        if not all(isinstance(value, Mapping) for value in (ping, active, reserved, scheduled)):
            return None
        worker_names = tuple(sorted(str(worker) for worker in ping))
        if any(not isinstance(worker, str) or not worker for worker in ping):
            return None
        if any(
            not isinstance(response, Mapping) or response.get("ok") != "pong"
            for response in ping.values()
        ):
            return None
        expected_workers = set(worker_names)
        if any(
            {str(worker) for worker in value} != expected_workers
            or any(not isinstance(worker, str) or not worker for worker in value)
            for value in (active, reserved, scheduled)
        ):
            return None

        active_ids = self._task_ids(active, scheduled=False)
        reserved_ids = self._task_ids(reserved, scheduled=False)
        scheduled_ids = self._task_ids(scheduled, scheduled=True)
        if active_ids is None or reserved_ids is None or scheduled_ids is None:
            return None
        return active_ids, reserved_ids, scheduled_ids, worker_names

    @staticmethod
    def _task_ids(
        worker_tasks: Mapping[object, object],
        *,
        scheduled: bool,
    ) -> tuple[str, ...] | None:
        """Extract every task ID, rejecting malformed worker evidence."""

        task_ids: list[str] = []
        for tasks in worker_tasks.values():
            if not isinstance(tasks, Sequence) or isinstance(tasks, (str, bytes)):
                return None
            for item in tasks:
                if not isinstance(item, Mapping):
                    return None
                candidate: object = item.get("id")
                if scheduled:
                    request = item.get("request")
                    if not isinstance(request, Mapping):
                        return None
                    candidate = request.get("id")
                if not isinstance(candidate, str) or not candidate:
                    return None
                task_ids.append(candidate)
        return tuple(task_ids)

    def _hard_time_limit_seconds(self, task_name: str) -> int | None:
        """Resolve the effective registered Celery hard time limit."""

        tasks = getattr(self.celery_app, "tasks", None)
        task = tasks.get(task_name) if isinstance(tasks, Mapping) else None
        value: object = getattr(task, "time_limit", None)
        if value is None:
            conf = getattr(self.celery_app, "conf", None)
            value = getattr(conf, "task_time_limit", None)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    def _backend_state(self, task_id: str) -> str | None:
        """Read only the Celery result state, never projecting its result payload."""

        try:
            backend = self.celery_app.backend
            metadata = backend.get_task_meta(task_id)
        except Exception:
            return None
        if not isinstance(metadata, Mapping):
            return None
        state: object = metadata.get("status")
        return state.upper() if isinstance(state, str) and state else None

    def _domain_lease_evidence(
        self,
        record: TaskExecutionRecord,
    ) -> tuple[TaskOrphanLeaseState, str]:
        """Resolve one injected lease probe, or require no declared domain lease."""

        matching_probes = []
        for probe in self.domain_lease_probes:
            try:
                if probe.supports_task_name(record.task_name):
                    matching_probes.append(probe)
            except Exception:
                return (
                    TaskOrphanLeaseState.UNKNOWN,
                    "domain_lease_probe_unavailable",
                )
        if not matching_probes:
            tasks = getattr(self.celery_app, "tasks", None)
            task = tasks.get(record.task_name) if isinstance(tasks, Mapping) else None
            lease_required: object = getattr(
                task,
                "task_monitor_requires_domain_lease_evidence",
                None,
            )
            return (
                (
                    TaskOrphanLeaseState.UNKNOWN
                    if lease_required is not None and lease_required is not False
                    else TaskOrphanLeaseState.NOT_REQUIRED
                ),
                "no_domain_lease_declared",
            )
        if len(matching_probes) != 1:
            return (
                TaskOrphanLeaseState.UNKNOWN,
                "domain_lease_probe_ambiguous",
            )
        try:
            evidence = matching_probes[0].get_lease_evidence(
                task_name=record.task_name,
                task_kwargs=record.kwargs,
            )
        except Exception:
            return (
                TaskOrphanLeaseState.UNKNOWN,
                "domain_lease_probe_unavailable",
            )
        if (
            not isinstance(evidence, DomainTaskLeaseEvidence)
            or not isinstance(evidence.state, DomainTaskLeaseState)
            or not isinstance(evidence.evidence_code, str)
            or not _SAFE_EVIDENCE_CODE.fullmatch(evidence.evidence_code)
        ):
            return (
                TaskOrphanLeaseState.UNKNOWN,
                "domain_lease_evidence_invalid",
            )
        states = {
            DomainTaskLeaseState.ABSENT: TaskOrphanLeaseState.ABSENT,
            DomainTaskLeaseState.ACTIVE: TaskOrphanLeaseState.ACTIVE,
            DomainTaskLeaseState.UNKNOWN: TaskOrphanLeaseState.UNKNOWN,
        }
        return states[evidence.state], evidence.evidence_code
