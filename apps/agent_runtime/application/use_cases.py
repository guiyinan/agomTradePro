"""
Application Use Cases for Agent Runtime.

These use cases orchestate business logic for agentTask operations.
All use cases follow the FROZEN contract and emit timeline events.

WP-M1-05: Use Cases (020-024)
See: docs/plans/ai-native/vendor-baseline-contract.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.utils import timezone

from apps.agent_runtime.application.repository_provider import AgentTaskRepository
from apps.agent_runtime.application.services import TimelineEventWriterService
from apps.agent_runtime.domain.entities import (
    AgentTask,
    EventSource,
    TaskDomain,
    TaskStatus,
)
from apps.agent_runtime.domain.services import (
    InvalidStateTransitionError,
    TaskStateMachine,
    get_task_state_machine,
)

if TYPE_CHECKING:
    from apps.agent_runtime.application.services.audit_service import AgentRuntimeAuditService

logger = logging.getLogger(__name__)


def generate_request_id() -> str:
    """
    Generate a unique request ID.

    Format: atr_YYYYMMDD_XXXXXX
    - atr: Agent Task Request prefix
    - YYYYMMDD: Date component
    - XXXXXX: Random component for uniqueness
    """
    date_part = timezone.now().strftime("%Y%m%d")
    random_part = uuid4().hex[:6].upper()
    return f"atr_{date_part}_{random_part}"


def _resolve_optional_audit_service() -> AgentRuntimeAuditService | None:
    """Load the optional audit service without hiding non-import failures."""

    try:
        from apps.agent_runtime.application.services.audit_service import get_audit_service
    except ImportError as exc:
        logger.debug("Agent runtime audit service import skipped: %s", exc)
        return None
    return get_audit_service()


@dataclass
class CreateTaskInput:
    """Input DTO for creating a task."""

    task_domain: str
    task_type: str
    input_payload: dict[str, Any]
    created_by: int | None = None


@dataclass
class CreateTaskOutput:
    """Output DTO for task creation."""

    task: AgentTask
    request_id: str
    timeline_event_id: int | None = None


@dataclass
class GetTaskOutput:
    """Output DTO for getting a task."""

    task: AgentTask
    request_id: str


@dataclass
class ListTasksInput:
    """Input DTO for listing tasks."""

    status: str | None = None
    task_domain: str | None = None
    task_type: str | None = None
    requires_human: bool | None = None
    search: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class ListTasksOutput:
    """Output DTO for listing tasks."""

    tasks: list[AgentTask]
    total_count: int
    request_id: str


@dataclass
class ResumeTaskInput:
    """Input DTO for resuming a task."""

    task_id: int
    target_status: str | None = None
    reason: str | None = None
    actor: dict[str, Any] | None = None


@dataclass
class ResumeTaskOutput:
    """Output DTO for task resume."""

    task: AgentTask
    request_id: str
    timeline_event_id: int | None = None


@dataclass
class CancelTaskInput:
    """Input DTO for cancelling a task."""

    task_id: int
    reason: str
    actor: dict[str, Any] | None = None


@dataclass
class CancelTaskOutput:
    """Output DTO for task cancellation."""

    task: AgentTask
    request_id: str
    timeline_event_id: int | None = None


class CreateTaskUseCase:
    """
    Use case for creating a new AgentTask.

    Creates a task in 'draft' status and emits a timeline event.
    """

    def __init__(
        self,
        state_machine: TaskStateMachine | None = None,
        timeline_service: TimelineEventWriterService | None = None,
        audit_service: AgentRuntimeAuditService | None = None,
        task_repo: AgentTaskRepository | None = None,
    ):
        self.state_machine = state_machine or get_task_state_machine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        self.task_repo = task_repo or AgentTaskRepository()
        if self.audit_service is None:
            self.audit_service = _resolve_optional_audit_service()

    def execute(self, input_dto: CreateTaskInput) -> CreateTaskOutput:
        """
        Execute the create task use case.

        Args:
            input_dto: Input data for task creation

        Returns:
            CreateTaskOutput with the created task

        Raises:
            ValueError: If input validation fails
        """
        # Validate domain
        try:
            TaskDomain(input_dto.task_domain)
        except ValueError:
            raise ValueError(
                f"Invalid task_domain. Must be one of: {[d.value for d in TaskDomain]}"
            ) from None

        # Generate request ID
        request_id = generate_request_id()

        task = self.task_repo.create_task(
            request_id=request_id,
            task_domain=input_dto.task_domain,
            task_type=input_dto.task_type,
            input_payload=input_dto.input_payload,
            created_by=input_dto.created_by,
            status=TaskStatus.DRAFT.value,
        )

        # Emit timeline event
        timeline_event_id = self.timeline_service.write_task_created_event(
            task=task,
            event_source=EventSource.API,
            actor={"user_id": input_dto.created_by} if input_dto.created_by else None,
        )

        # Log audit event
        if self.audit_service:
            try:
                self.audit_service.log_task_created(
                    task_id=task.id,
                    request_id=request_id,
                    task_domain=input_dto.task_domain,
                    task_type=input_dto.task_type,
                    user_id=input_dto.created_by,
                    input_payload=input_dto.input_payload,
                    source="API",
                )
            except Exception as e:
                logger.warning(f"Failed to log audit event: {e}")

        logger.info(f"Created task {task.id} with request_id={request_id}")

        return CreateTaskOutput(
            task=task,
            request_id=request_id,
            timeline_event_id=timeline_event_id,
        )


class GetTaskUseCase:
    """
    Use case for retrieving a single AgentTask.
    """

    def __init__(self, task_repo: AgentTaskRepository | None = None):
        self.task_repo = task_repo or AgentTaskRepository()

    def execute(self, task_id: int) -> GetTaskOutput:
        """
        Execute the get task use case.

        Args:
            task_id: ID of the task to retrieve

        Returns:
            GetTaskOutput with the task

        Raises:
            AgentTaskModel.DoesNotExist: If task not found
        """
        task = self.task_repo.get_task(task_id)

        return GetTaskOutput(
            task=task,
            request_id=task.request_id,
        )


class ListTasksUseCase:
    """
    Use case for listing AgentTasks with filters.
    """

    def __init__(self, task_repo: AgentTaskRepository | None = None):
        self.task_repo = task_repo or AgentTaskRepository()

    def execute(
        self,
        input_dto: ListTasksInput | None = None,
        **filters: Any,
    ) -> ListTasksOutput:
        """
        Execute the list tasks use case.

        Args:
            input_dto: Filter and pagination parameters

        Returns:
            ListTasksOutput with tasks and total count
        """
        if input_dto is None:
            input_dto = ListTasksInput(**filters)
        elif filters:
            raise TypeError("Pass either input_dto or keyword filters, not both")

        request_id = generate_request_id()
        listing = self.task_repo.list_tasks(
            status=input_dto.status,
            task_domain=input_dto.task_domain,
            task_type=input_dto.task_type,
            requires_human=input_dto.requires_human,
            search=input_dto.search,
            limit=input_dto.limit,
            offset=input_dto.offset,
        )

        return ListTasksOutput(
            tasks=listing["tasks"],
            total_count=listing["total_count"],
            request_id=request_id,
        )


class ResumeTaskUseCase:
    """
    Use case for resuming a task from a resumable state.

    Resumable states: failed, needs_human
    Allowed transitions from resumable states require human intervention.
    """

    def __init__(
        self,
        state_machine: TaskStateMachine | None = None,
        timeline_service: TimelineEventWriterService | None = None,
        audit_service: AgentRuntimeAuditService | None = None,
        task_repo: AgentTaskRepository | None = None,
    ):
        self.state_machine = state_machine or get_task_state_machine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        self.task_repo = task_repo or AgentTaskRepository()
        if self.audit_service is None:
            self.audit_service = _resolve_optional_audit_service()

    def execute(self, input_dto: ResumeTaskInput) -> ResumeTaskOutput:
        """
        Execute the resume task use case.

        Args:
            input_dto: Input data for task resume

        Returns:
            ResumeTaskOutput with the updated task

        Raises:
            AgentTaskModel.DoesNotExist: If task not found
            InvalidStateTransitionError: If transition is not allowed
            ValueError: If task is not in a resumable state
        """
        task = self.task_repo.get_task(input_dto.task_id)

        # Check if task is in a resumable state
        if not self.state_machine.is_resumable(task.status.value):
            raise ValueError(
                f"Task is not in a resumable state. Current status: {task.status.value}"
            )

        # Determine target status
        old_status = task.status
        if input_dto.target_status:
            target_status = TaskStatus(input_dto.target_status)
        else:
            # Default transitions for resumable states
            if task.status == TaskStatus.FAILED:
                target_status = TaskStatus.DRAFT
            elif task.status == TaskStatus.NEEDS_HUMAN:
                target_status = TaskStatus.DRAFT
            else:
                raise ValueError(f"No default resume transition for status: {task.status.value}")

        # Validate transition
        if not self.state_machine.can_transition(task.status.value, target_status.value):
            allowed = self.state_machine.get_allowed_transitions(task.status.value)
            raise InvalidStateTransitionError(
                current_status=task.status.value,
                target_status=target_status.value,
                allowed_transitions=allowed,
            )

        # Check if human intervention is required
        if self.state_machine.requires_human_intervention(task.status.value, target_status.value):
            logger.info(
                f"Human intervention required for transition {task.status.value} -> {target_status.value}"
            )

        # Perform transition
        updated_task = self.state_machine.transition(task, target_status, input_dto.reason)

        # Update model
        updated_task = self.task_repo.update_task_state(
            updated_task.id,
            status=updated_task.status.value,
            requires_human=False,
        )

        # Emit timeline events
        timeline_event_id = self.timeline_service.write_state_changed_event(
            task=updated_task,
            old_status=old_status.value,
            new_status=target_status.value,
            event_source=EventSource.HUMAN,
            actor=input_dto.actor,
            reason=input_dto.reason,
        )

        # Also emit resume event
        self.timeline_service.write_task_resumed_event(
            task=updated_task,
            reason=input_dto.reason or f"Resumed from {old_status.value}",
            event_source=EventSource.HUMAN,
            actor=input_dto.actor,
        )

        # Log audit event
        if self.audit_service:
            try:
                self.audit_service.log_task_resumed(
                    task_id=updated_task.id,
                    request_id=task.request_id,
                    from_status=old_status.value,
                    to_status=target_status.value,
                    reason=input_dto.reason,
                    user_id=input_dto.actor.get("user_id") if input_dto.actor else None,
                    source="API",
                )
            except Exception as e:
                logger.warning(f"Failed to log audit event: {e}")

        logger.info(f"Resumed task {task.id} from {old_status.value} to {target_status.value}")

        return ResumeTaskOutput(
            task=updated_task,
            request_id=task.request_id,
            timeline_event_id=timeline_event_id,
        )


class CancelTaskUseCase:
    """
    Use case for cancelling an AgentTask.

    Cancellation is allowed from any non-terminal state.
    Terminal states: completed, cancelled
    """

    def __init__(
        self,
        state_machine: TaskStateMachine | None = None,
        timeline_service: TimelineEventWriterService | None = None,
        audit_service: AgentRuntimeAuditService | None = None,
        task_repo: AgentTaskRepository | None = None,
    ):
        self.state_machine = state_machine or get_task_state_machine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        self.task_repo = task_repo or AgentTaskRepository()
        if self.audit_service is None:
            self.audit_service = _resolve_optional_audit_service()

    def execute(self, input_dto: CancelTaskInput) -> CancelTaskOutput:
        """
        Execute the cancel task use case.

        Args:
            input_dto: Input data for task cancellation

        Returns:
            CancelTaskOutput with the cancelled task

        Raises:
            AgentTaskModel.DoesNotExist: If task not found
            InvalidStateTransitionError: If task is in terminal state
        """
        task = self.task_repo.get_task(input_dto.task_id)

        # Check if task is already in terminal state
        if self.state_machine.is_terminal(task.status.value):
            raise InvalidStateTransitionError(
                current_status=task.status.value,
                target_status=TaskStatus.CANCELLED.value,
                allowed_transitions=[],
                message=f"Task is already in terminal state: {task.status.value}",
            )

        old_status = task.status
        target_status = TaskStatus.CANCELLED

        # Validate transition
        if not self.state_machine.can_transition(task.status.value, target_status.value):
            allowed = self.state_machine.get_allowed_transitions(task.status.value)
            raise InvalidStateTransitionError(
                current_status=task.status.value,
                target_status=target_status.value,
                allowed_transitions=allowed,
            )

        # Perform transition
        updated_task = self.state_machine.transition(task, target_status, input_dto.reason)

        # Update model
        updated_task = self.task_repo.update_task_state(
            updated_task.id,
            status=updated_task.status.value,
        )

        # Emit timeline events
        timeline_event_id = self.timeline_service.write_task_cancelled_event(
            task=updated_task,
            reason=input_dto.reason,
            event_source=EventSource.HUMAN,
            actor=input_dto.actor,
        )

        # Also emit state change event
        self.timeline_service.write_state_changed_event(
            task=updated_task,
            old_status=old_status.value,
            new_status=target_status.value,
            event_source=EventSource.HUMAN,
            actor=input_dto.actor,
            reason=input_dto.reason,
        )

        # Log audit event
        if self.audit_service:
            try:
                self.audit_service.log_task_cancelled(
                    task_id=updated_task.id,
                    request_id=task.request_id,
                    from_status=old_status.value,
                    reason=input_dto.reason,
                    user_id=input_dto.actor.get("user_id") if input_dto.actor else None,
                    source="API",
                )
            except Exception as e:
                logger.warning(f"Failed to log audit event: {e}")

        logger.info(f"Cancelled task {task.id} from {old_status.value}")

        return CancelTaskOutput(
            task=updated_task,
            request_id=task.request_id,
            timeline_event_id=timeline_event_id,
        )
