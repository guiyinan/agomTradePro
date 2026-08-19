"""Django persistence adapter for the dormant Terminal Agent run ledger.

This module implements only the TAR-02 repository contract.  It persists
owner-scoped dispatch metadata, never stores the request message, and never
publishes to an external dispatcher, broker, Agent worker, or provider.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.agent_runtime.application.terminal_agent_run_ports import (
    TerminalQueuedSubmissionPort,
    TerminalQueuedSubmissionRequest,
)
from apps.agent_runtime.domain.terminal_agent_run_contract import (
    TerminalAgentRunContract,
    TerminalOwnershipError,
    TerminalRunContractError,
    TerminalRunStatus,
    TerminalRunSubmission,
    TerminalRuntimeMode,
    validate_terminal_run_id,
)
from apps.agent_runtime.infrastructure.models import (
    AgentTaskModel,
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
            model.save(update_fields=["dispatch_status", "claimed_by", "claimed_at", "updated_at"])
            return model.to_domain_contract()

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
