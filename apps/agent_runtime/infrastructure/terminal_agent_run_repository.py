"""Django persistence adapter for the dormant Terminal Agent run ledger.

This module implements only the TAR-02 repository contract.  It persists
owner-scoped dispatch metadata, never stores the request message, and never
publishes to an external dispatcher, broker, Agent worker, or provider.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import ClassVar, cast

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.agent_runtime.application.terminal_agent_run_api_contract import JsonValue
from apps.agent_runtime.application.terminal_agent_run_ports import (
    TerminalQueuedSubmissionPort,
    TerminalQueuedSubmissionRequest,
    TerminalRunQueueSummary,
)
from apps.agent_runtime.application.terminal_agent_run_runtime import (
    TerminalAgentWorkerInput,
    TerminalRunEventRecord,
    TerminalRunSnapshot,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    InvalidTerminalRunTransition,
    TerminalAgentRunContract,
    TerminalOwnershipError,
    TerminalRunContractError,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
    assert_no_sensitive_runtime_data,
    transition_terminal_run,
    validate_terminal_run_id,
)
from apps.agent_runtime.infrastructure.models import (
    AgentTaskModel,
    TerminalAgentRunEventModel,
    TerminalAgentRunExecutionModel,
    TerminalAgentRunModel,
)


class TerminalRunRepositoryError(TerminalRunContractError):
    """Stable, redacted repository failure for the future route adapter."""

    default_reason_code: ClassVar[str] = "RUN_ADMISSION_CONFLICT"

    def __init__(self, reason_code: str | None = None) -> None:
        """Create an error without exposing database exception text."""

        self.reason_code = reason_code or self.default_reason_code
        super().__init__(self.reason_code)


class TerminalRunIdempotencyConflict(TerminalRunRepositoryError):
    """Reject reuse of one actor/client key with a different request identity."""

    default_reason_code: ClassVar[str] = "IDEMPOTENCY_KEY_CONFLICT"

    def __init__(self) -> None:
        """Create the stable idempotency conflict."""

        super().__init__(self.default_reason_code)


class TerminalAgentRunRepository(TerminalQueuedSubmissionPort):
    """Persist owner-scoped run metadata with database first-winner semantics."""

    _ACTIVE_STATUSES = (
        TerminalRunStatus.CLAIMED.value,
        TerminalRunStatus.RUNNING.value,
        TerminalRunStatus.WAITING_APPROVAL.value,
    )
    _QUEUED_STATUSES = (TerminalRunStatus.QUEUED.value,)
    _CANCELLABLE_STATUSES = (
        TerminalRunStatus.QUEUED.value,
        TerminalRunStatus.CLAIMED.value,
        TerminalRunStatus.RUNNING.value,
        TerminalRunStatus.WAITING_APPROVAL.value,
    )

    def submit(
        self,
        request: TerminalQueuedSubmissionRequest,
    ) -> TerminalAgentRunContract:
        """Admit one web-queued run without persisting its raw message."""

        submission = request.submission
        if submission.runtime_mode is not TerminalRuntimeMode.WEB_QUEUED:
            raise TerminalRunContractError("queued repository accepts only web_queued mode")
        actor_user_id = _require_positive_int(
            submission.selector.actor_user_id,
            field_name="actor_user_id",
        )

        with transaction.atomic():
            self._lock_admission_anchors(actor_user_id=actor_user_id)
            existing = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(
                    actor_user_id=actor_user_id,
                    client_request_id=submission.selector.client_request_id,
                )
                .first()
            )
            if existing is not None:
                return self._replay_existing(existing, submission)

            task_exists_for_owner = (
                AgentTaskModel._default_manager.select_for_update()
                .filter(id=submission.selector.task_id, created_by_id=actor_user_id)
                .only("id")
                .exists()
            )
            if not task_exists_for_owner:
                raise TerminalOwnershipError("RUN_NOT_OWNER")

            if TerminalAgentRunModel._default_manager.filter(
                run_id=submission.selector.run_id
            ).exists():
                raise TerminalRunRepositoryError("RUN_ID_CONFLICT")

            self._assert_admission_capacity(actor_user_id=actor_user_id)

            try:
                with transaction.atomic():
                    model = TerminalAgentRunModel._default_manager.create(
                        run_id=submission.selector.run_id,
                        task_id=submission.selector.task_id,
                        actor_user_id=actor_user_id,
                        client_request_id=submission.selector.client_request_id,
                        request_digest=submission.request_digest,
                        runtime_mode=submission.runtime_mode.value,
                        dispatch_status=TerminalRunStatus.QUEUED.value,
                        accepted_at=submission.accepted_at,
                        deadline_at=submission.deadline_at,
                    )
            except IntegrityError as exc:
                winner = (
                    TerminalAgentRunModel._default_manager.select_for_update()
                    .filter(
                        actor_user_id=actor_user_id,
                        client_request_id=submission.selector.client_request_id,
                    )
                    .first()
                )
                if winner is None:
                    raise TerminalRunRepositoryError() from exc
                return self._replay_existing(winner, submission)

        return model.to_domain_contract()

    def _lock_admission_anchors(self, *, actor_user_id: int) -> None:
        """Serialize all queue admissions before checking capacity counters.

        Queue limits are process-wide and owner-scoped.  A snapshot from
        ``queue_summary`` cannot reserve a slot, so every writer takes the
        same deterministic database lock before re-reading idempotency and
        counting rows.  The authenticated owner row also makes a missing or
        deleted actor fail closed instead of creating an unowned run.
        """

        user_model = get_user_model()
        global_anchor = user_model._default_manager.select_for_update().order_by("pk").first()
        if global_anchor is None:
            raise TerminalRunRepositoryError("RUN_ADMISSION_ANCHOR_UNAVAILABLE")
        actor = user_model._default_manager.select_for_update().filter(pk=actor_user_id).first()
        if actor is None:
            raise TerminalRunRepositoryError("RUN_OWNER_NOT_FOUND")

    def _assert_admission_capacity(self, *, actor_user_id: int) -> None:
        """Reject a new unique run while any configured queue cap is full."""

        rows = TerminalAgentRunModel._default_manager
        user_rows = rows.filter(actor_user_id=actor_user_id)
        limits = (
            (
                "per_user_active_limit",
                user_rows.filter(dispatch_status__in=self._ACTIVE_STATUSES).count(),
                int(getattr(settings, "TERMINAL_PER_USER_ACTIVE_LIMIT", 1)),
            ),
            (
                "per_user_queued_limit",
                user_rows.filter(dispatch_status__in=self._QUEUED_STATUSES).count(),
                int(getattr(settings, "TERMINAL_PER_USER_QUEUED_LIMIT", 4)),
            ),
            (
                "global_active_limit",
                rows.filter(dispatch_status__in=self._ACTIVE_STATUSES).count(),
                int(getattr(settings, "TERMINAL_GLOBAL_ACTIVE_LIMIT", 4)),
            ),
            (
                "global_queued_limit",
                rows.filter(dispatch_status__in=self._QUEUED_STATUSES).count(),
                int(getattr(settings, "TERMINAL_GLOBAL_QUEUED_LIMIT", 40)),
            ),
        )
        for reason_code, current, limit in limits:
            if current >= limit:
                raise TerminalRunRepositoryError(reason_code)

    def get_for_owner(
        self,
        *,
        run_id: str,
        actor_user_id: int,
    ) -> TerminalAgentRunContract | None:
        """Return one run only when its authenticated owner matches."""

        validate_terminal_run_id(run_id)
        actor = _require_positive_int(actor_user_id, field_name="actor_user_id")
        model = TerminalAgentRunModel._default_manager.filter(
            run_id=run_id,
            actor_user_id=actor,
        ).first()
        return model.to_domain_contract() if model is not None else None

    def claim(
        self,
        *,
        run_id: str,
        worker_id: str,
        claimed_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Atomically claim one queued run; a later claimant receives ``None``."""

        validate_terminal_run_id(run_id)
        worker = _require_worker_id(worker_id)
        timestamp = claimed_at or timezone.now()
        _require_aware(timestamp, field_name="claimed_at")

        with transaction.atomic():
            model = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(run_id=run_id)
                .first()
            )
            if model is None or model.dispatch_status != TerminalRunStatus.QUEUED.value:
                return None
            model.dispatch_status = TerminalRunStatus.CLAIMED.value
            model.claimed_by = worker
            model.claimed_at = timestamp
            model.heartbeat_at = timestamp
            model.save(
                update_fields=[
                    "dispatch_status",
                    "claimed_by",
                    "claimed_at",
                    "heartbeat_at",
                    "updated_at",
                ]
            )
            return model.to_domain_contract()

    def transition(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        target: TerminalRunStatus,
        worker_id: str | None = None,
        changed_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Apply one owner-scoped state transition under a row lock.

        This operation only changes the durable dispatch ledger.  It does not
        publish a task, invoke an external worker, or execute Agent work.
        """

        validate_terminal_run_id(run_id)
        actor = _require_positive_int(actor_user_id, field_name="actor_user_id")
        if not isinstance(target, TerminalRunStatus):
            raise TerminalRunRepositoryError("INVALID_RUN_STATUS")
        timestamp = changed_at or timezone.now()
        _require_aware(timestamp, field_name="changed_at")
        worker = _require_worker_id(worker_id) if worker_id is not None else None

        with transaction.atomic():
            model = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(run_id=run_id, actor_user_id=actor)
                .first()
            )
            if model is None:
                return None

            try:
                current = TerminalRunStatus(model.dispatch_status)
            except ValueError as exc:
                raise TerminalRunRepositoryError("INVALID_STORED_RUN_STATUS") from exc
            if current is target:
                return model.to_domain_contract()
            try:
                transition_terminal_run(current, target)
            except InvalidTerminalRunTransition as exc:
                raise TerminalRunRepositoryError("INVALID_RUN_TRANSITION") from exc

            update_fields = ["dispatch_status", "updated_at"]
            if target is TerminalRunStatus.CLAIMED:
                if worker is None:
                    raise TerminalRunRepositoryError("WORKER_ID_REQUIRED")
                model.claimed_by = worker
                model.claimed_at = timestamp
                model.heartbeat_at = timestamp
                update_fields.extend(["claimed_by", "claimed_at", "heartbeat_at"])
            elif target is TerminalRunStatus.QUEUED:
                model.claimed_by = None
                model.claimed_at = None
                model.heartbeat_at = None
                update_fields.extend(["claimed_by", "claimed_at", "heartbeat_at"])
            elif target is TerminalRunStatus.CANCEL_REQUESTED:
                if model.cancel_requested_at is None:
                    model.cancel_requested_at = timestamp
                    update_fields.append("cancel_requested_at")

            model.dispatch_status = target.value
            model.save(update_fields=update_fields)
            return model.to_domain_contract()

    def cancel(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        requested_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Request cancellation with owner-scoped, idempotent semantics."""

        validate_terminal_run_id(run_id)
        actor = _require_positive_int(actor_user_id, field_name="actor_user_id")
        timestamp = requested_at or timezone.now()
        _require_aware(timestamp, field_name="requested_at")

        with transaction.atomic():
            model = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(run_id=run_id, actor_user_id=actor)
                .first()
            )
            if model is None:
                return None
            if model.dispatch_status in {
                TerminalRunStatus.CANCEL_REQUESTED.value,
                TerminalRunStatus.CANCELLED.value,
            }:
                return model.to_domain_contract()
            if model.dispatch_status not in self._CANCELLABLE_STATUSES:
                raise TerminalRunRepositoryError("RUN_NOT_CANCELLABLE")

            model.dispatch_status = TerminalRunStatus.CANCEL_REQUESTED.value
            model.cancel_requested_at = model.cancel_requested_at or timestamp
            model.save(update_fields=["dispatch_status", "cancel_requested_at", "updated_at"])
            return model.to_domain_contract()

    def heartbeat(
        self,
        *,
        run_id: str,
        worker_id: str,
        heartbeat_at: datetime | None = None,
    ) -> TerminalAgentRunContract | None:
        """Refresh a matching worker lease without changing run state."""

        validate_terminal_run_id(run_id)
        worker = _require_worker_id(worker_id)
        timestamp = heartbeat_at or timezone.now()
        _require_aware(timestamp, field_name="heartbeat_at")

        with transaction.atomic():
            model = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(
                    run_id=run_id,
                    claimed_by=worker,
                    dispatch_status__in=self._ACTIVE_STATUSES,
                )
                .first()
            )
            if model is None:
                return None
            if model.heartbeat_at is not None and timestamp < model.heartbeat_at:
                raise TerminalRunRepositoryError("HEARTBEAT_REWIND")
            model.heartbeat_at = timestamp
            model.save(update_fields=["heartbeat_at", "updated_at"])
            return model.to_domain_contract()

    def queue_summary(self, *, actor_user_id: int) -> TerminalRunQueueSummary:
        """Return advisory owner/global queue counters from durable rows.

        The counts are intentionally a snapshot.  They cannot reserve an
        admission slot and therefore must be rechecked in a future serialized
        admission transaction.
        """

        actor = _require_positive_int(actor_user_id, field_name="actor_user_id")
        rows = TerminalAgentRunModel._default_manager
        user_rows = rows.filter(actor_user_id=actor)
        return TerminalRunQueueSummary(
            actor_user_id=actor,
            user_active=user_rows.filter(dispatch_status__in=self._ACTIVE_STATUSES).count(),
            user_queued=user_rows.filter(dispatch_status__in=self._QUEUED_STATUSES).count(),
            global_active=rows.filter(dispatch_status__in=self._ACTIVE_STATUSES).count(),
            global_queued=rows.filter(dispatch_status__in=self._QUEUED_STATUSES).count(),
        )

    def get_snapshot(
        self,
        *,
        run_id: str,
        actor_user_id: int,
    ) -> TerminalRunSnapshot | None:
        """Return one owner-scoped lifecycle snapshot."""

        validate_terminal_run_id(run_id)
        actor = _require_positive_int(actor_user_id, field_name="actor_user_id")
        model = TerminalAgentRunModel._default_manager.filter(
            run_id=run_id,
            actor_user_id=actor,
        ).first()
        if model is None:
            return None
        checkpoint = TerminalAgentRunExecutionModel._default_manager.filter(run=model).first()
        return TerminalRunSnapshot(
            run_id=model.run_id,
            task_id=model.task_id,
            status=TerminalRunStatus(model.dispatch_status),
            accepted_at=model.accepted_at,
            updated_at=model.updated_at,
            deadline_at=model.deadline_at,
            claimed_by=model.claimed_by,
            started_at=checkpoint.started_at if checkpoint is not None else None,
            heartbeat_at=model.heartbeat_at,
            finished_at=checkpoint.finished_at if checkpoint is not None else None,
            cancel_requested_at=model.cancel_requested_at,
            error_code=checkpoint.error_code if checkpoint is not None else None,
            result_ref=checkpoint.result_ref if checkpoint is not None else None,
        )

    def list_events(
        self,
        *,
        run_id: str,
        actor_user_id: int,
        after_sequence: int,
        limit: int,
    ) -> Sequence[TerminalRunEventRecord] | None:
        """Return bounded owner-scoped events after a replay cursor."""

        validate_terminal_run_id(run_id)
        actor = _require_positive_int(actor_user_id, field_name="actor_user_id")
        if (
            isinstance(after_sequence, bool)
            or not isinstance(after_sequence, int)
            or after_sequence < 0
        ):
            raise TerminalRunContractError("after_sequence_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 200:
            raise TerminalRunContractError("event_limit_invalid")
        run = TerminalAgentRunModel._default_manager.filter(
            run_id=run_id,
            actor_user_id=actor,
        ).first()
        if run is None:
            return None
        rows = TerminalAgentRunEventModel._default_manager.filter(
            run=run,
            sequence__gt=after_sequence,
        ).order_by("sequence")[:limit]
        return tuple(
            TerminalRunEventRecord(
                event_id=row.event_id,
                run_id=run_id,
                event_type=row.event_type,
                occurred_at=row.occurred_at,
                sequence=row.sequence,
                data=_json_mapping(row.data),
            )
            for row in rows
        )

    def append_event(
        self,
        *,
        run_id: str,
        worker_id: str,
        event_type: str,
        data: Mapping[str, object],
        occurred_at: datetime,
    ) -> TerminalRunEventRecord | None:
        """Append one event under the claimed worker lease."""

        validate_terminal_run_id(run_id)
        worker = _require_worker_id(worker_id)
        if not isinstance(event_type, str) or not event_type or event_type.strip() != event_type:
            raise TerminalRunContractError("event_type_invalid")
        _require_aware(occurred_at, field_name="occurred_at")
        assert_no_sensitive_runtime_data(data)
        payload = _json_mapping(data)
        with transaction.atomic():
            run = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(run_id=run_id, claimed_by=worker)
                .first()
            )
            if run is None:
                return None
            if run.dispatch_status not in set(self._ACTIVE_STATUSES) | {
                TerminalRunStatus.CANCEL_REQUESTED.value
            }:
                return None
            sequence = (
                TerminalAgentRunEventModel._default_manager.filter(run=run)
                .order_by("-sequence")
                .values_list("sequence", flat=True)
                .first()
                or 0
            ) + 1
            event_id = f"{run_id}-event-{sequence}"
            row = TerminalAgentRunEventModel._default_manager.create(
                run=run,
                event_id=event_id,
                sequence=sequence,
                event_type=event_type,
                occurred_at=occurred_at,
                data=payload,
            )
            return TerminalRunEventRecord(
                event_id=row.event_id,
                run_id=run_id,
                event_type=row.event_type,
                occurred_at=row.occurred_at,
                sequence=row.sequence,
                data=payload,
            )

    def mark_started(
        self,
        *,
        run_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> TerminalAgentRunContract | None:
        """Move a claimed run to running and persist its first checkpoint."""

        worker = _require_worker_id(worker_id)
        result = self.transition(
            run_id=run_id,
            actor_user_id=self._actor_for_worker(run_id, worker),
            target=TerminalRunStatus.RUNNING,
            worker_id=worker,
            changed_at=started_at,
        )
        if result is None:
            return None
        with transaction.atomic():
            run = TerminalAgentRunModel._default_manager.select_for_update().get(run_id=run_id)
            TerminalAgentRunExecutionModel._default_manager.update_or_create(
                run=run,
                defaults={"started_at": started_at, "heartbeat_at": started_at},
            )
        return result

    def mark_finished(
        self,
        *,
        run_id: str,
        worker_id: str,
        status: TerminalRunStatus,
        finished_at: datetime,
        error_code: str | None = None,
        result_ref: str | None = None,
        result_payload: Mapping[str, object] | None = None,
    ) -> TerminalAgentRunContract | None:
        """Persist a terminal outcome only for the current worker lease."""

        validate_terminal_run_id(run_id)
        worker = _require_worker_id(worker_id)
        if status not in {
            TerminalRunStatus.CANCELLED,
            TerminalRunStatus.COMPLETED,
            TerminalRunStatus.FAILED,
            TerminalRunStatus.TIMED_OUT,
        }:
            raise TerminalRunContractError("terminal_status_required")
        _require_aware(finished_at, field_name="finished_at")
        if result_payload is not None:
            assert_no_sensitive_runtime_data(result_payload)
            payload = _json_mapping(result_payload)
        else:
            payload = None
        with transaction.atomic():
            run = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(run_id=run_id, claimed_by=worker)
                .first()
            )
            if run is None:
                return None
            try:
                current = TerminalRunStatus(run.dispatch_status)
                transition_terminal_run(current, status)
            except (ValueError, InvalidTerminalRunTransition) as exc:
                raise TerminalRunRepositoryError("INVALID_RUN_TRANSITION") from exc
            run.dispatch_status = status.value
            run.heartbeat_at = finished_at
            run.save(update_fields=["dispatch_status", "heartbeat_at", "updated_at"])
            TerminalAgentRunExecutionModel._default_manager.update_or_create(
                run=run,
                defaults={
                    "finished_at": finished_at,
                    "heartbeat_at": finished_at,
                    "error_code": error_code,
                    "result_ref": result_ref,
                    "result_payload": payload,
                },
            )
            return run.to_domain_contract()

    def get_worker_input(
        self,
        *,
        run_id: str,
        task_id: int,
    ) -> TerminalAgentWorkerInput | None:
        """Read a task payload only after binding it to its durable run owner."""

        validate_terminal_run_id(run_id)
        actor_task = _require_positive_int(task_id, field_name="task_id")
        run = (
            TerminalAgentRunModel._default_manager.select_related("task", "actor_user")
            .filter(run_id=run_id, task_id=actor_task)
            .first()
        )
        if run is None:
            return None
        raw_payload = run.task.input_payload
        if not isinstance(raw_payload, dict):
            raise TerminalRunRepositoryError("TERMINAL_TASK_PAYLOAD_INVALID")
        raw_input = raw_payload.get("terminal_agent")
        if not isinstance(raw_input, dict):
            raise TerminalRunRepositoryError("TERMINAL_TASK_INPUT_MISSING")
        message = raw_input.get("message")
        session_id = raw_input.get("session_id")
        user_role = raw_input.get("user_role", "read_only")
        user_is_admin = raw_input.get("user_is_admin", False)
        mcp_enabled = raw_input.get("mcp_enabled", True)
        if (
            not isinstance(message, str)
            or not message.strip()
            or not isinstance(session_id, str)
            or not session_id.strip()
            or not isinstance(user_role, str)
            or not user_role.strip()
            or type(user_is_admin) is not bool
            or type(mcp_enabled) is not bool
        ):
            raise TerminalRunRepositoryError("TERMINAL_TASK_INPUT_INVALID")
        if "user_id" in raw_input and raw_input["user_id"] != run.actor_user_id:
            raise TerminalRunRepositoryError("TERMINAL_TASK_OWNER_MISMATCH")
        username = str(getattr(run.actor_user, "username", "") or "")
        provider_ref = raw_input.get("provider_ref")
        model = raw_input.get("model")
        if model is not None and not isinstance(model, str):
            raise TerminalRunRepositoryError("TERMINAL_TASK_MODEL_INVALID")
        context = raw_input.get("context", {})
        if not isinstance(context, dict):
            raise TerminalRunRepositoryError("TERMINAL_TASK_CONTEXT_INVALID")
        return TerminalAgentWorkerInput(
            run_id=run_id,
            task_id=actor_task,
            actor_user_id=run.actor_user_id,
            message=message,
            session_id=session_id,
            username=username,
            user_role=user_role,
            user_is_admin=user_is_admin,
            mcp_enabled=mcp_enabled,
            provider_ref=provider_ref,
            model=model,
            context=cast(Mapping[str, object], context),
        )

    def reap_stale(self, *, stale_before: datetime, reaped_at: datetime) -> int:
        """Mark claimed/running rows with stale heartbeats as orphaned.

        The reaper never requeues an unknown side-effect boundary. A stale
        worker is preserved as explicit orphan evidence instead of being
        silently executed a second time.
        """

        _require_aware(stale_before, field_name="stale_before")
        _require_aware(reaped_at, field_name="reaped_at")
        if stale_before > reaped_at:
            raise TerminalRunContractError("stale_before must not be after reaped_at")
        reaped = 0
        with transaction.atomic():
            rows = (
                TerminalAgentRunModel._default_manager.select_for_update()
                .filter(
                    dispatch_status__in=(
                        TerminalRunStatus.CLAIMED.value,
                        TerminalRunStatus.RUNNING.value,
                    ),
                    heartbeat_at__lt=stale_before,
                )
                .order_by("id")
            )
            for row in rows:
                row.dispatch_status = TerminalRunStatus.ORPHANED.value
                row.save(update_fields=["dispatch_status", "updated_at"])
                TerminalAgentRunExecutionModel._default_manager.update_or_create(
                    run=row,
                    defaults={
                        "heartbeat_at": row.heartbeat_at,
                        "finished_at": None,
                        "error_code": "terminal_worker_heartbeat_stale",
                    },
                )
                reaped += 1
        return reaped

    @staticmethod
    def _actor_for_worker(run_id: str, worker_id: str) -> int:
        """Resolve the owner for a worker transition without exposing prompts."""

        model = (
            TerminalAgentRunModel._default_manager.filter(
                run_id=run_id,
                claimed_by=worker_id,
            )
            .only("actor_user_id")
            .first()
        )
        if model is None:
            raise TerminalRunRepositoryError("RUN_NOT_CLAIMED")
        return int(model.actor_user_id)

    @staticmethod
    def _replay_existing(
        model: TerminalAgentRunModel,
        submission: TerminalRunSubmission,
    ) -> TerminalAgentRunContract:
        """Return an idempotent row only when its immutable identity matches."""

        selector = submission.selector
        if (
            model.request_digest != submission.request_digest
            or model.run_id != selector.run_id
            or model.task_id != selector.task_id
            or model.runtime_mode != submission.runtime_mode.value
        ):
            raise TerminalRunIdempotencyConflict()
        return model.to_domain_contract()


def _require_positive_int(value: object, *, field_name: str) -> int:
    """Require a positive integer at the infrastructure boundary."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TerminalRunContractError(f"{field_name}_invalid")
    return value


def _require_worker_id(value: object) -> str:
    """Require a bounded canonical worker identifier."""

    if not isinstance(value, str) or not value or value.strip() != value or len(value) > 128:
        raise TerminalRunContractError("worker_id_invalid")
    return value


def _require_aware(value: datetime, *, field_name: str) -> datetime:
    """Require a timezone-aware timestamp before ORM persistence."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise TerminalRunContractError(f"{field_name}_must_be_timezone_aware")
    return value


def _json_mapping(value: object) -> dict[str, JsonValue]:
    """Detach a JSON object and reject non-object event/result payloads."""

    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TerminalRunContractError("json_object_required")
    return cast(dict[str, JsonValue], dict(value))
