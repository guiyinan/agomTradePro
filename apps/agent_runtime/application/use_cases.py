"""
Application Use Cases for Agent Runtime.

These use cases orchestrate business logic for AgentTask operations.
All use cases follow the FROZEN contract and emit timeline events.

WP-M1-05: Use Cases (020-024)
See: docs/plans/ai-native/vendor-baseline-contract.md
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from uuid import uuid4

from django.utils import timezone

from apps.agent_runtime.domain.entities import (
    AgentTask,
    TaskDomain,
    TaskStatus,
    EventSource,
)
from apps.agent_runtime.domain.services import (
    TaskStateMachine,
    InvalidStateTransitionError,
    get_task_state_machine,
)
from apps.agent_runtime.application.services import TimelineEventWriterService


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


@dataclass
class CreateTaskInput:
    """Input DTO for creating a task."""

    task_domain: str
    task_type: str
    input_payload: Dict[str, Any]
    created_by: Optional[int] = None


@dataclass
class CreateTaskOutput:
    """Output DTO for task creation."""

    task: AgentTask
    request_id: str
    timeline_event_id: Optional[int] = None


@dataclass
class GetTaskOutput:
    """Output DTO for getting a task."""

    task: AgentTask
    request_id: str


@dataclass
class ListTasksInput:
    """Input DTO for listing tasks."""

    status: Optional[str] = None
    task_domain: Optional[str] = None
    task_type: Optional[str] = None
    requires_human: Optional[bool] = None
    search: Optional[str] = None
    limit: int = 50
    offset: int = 0


@dataclass
class ListTasksOutput:
    """Output DTO for listing tasks."""

    tasks: List[AgentTask]
    total_count: int
    request_id: str


@dataclass
class ResumeTaskInput:
    """Input DTO for resuming a task."""

    task_id: int
    target_status: Optional[str] = None
    reason: Optional[str] = None
    actor: Optional[Dict[str, Any]] = None


@dataclass
class ResumeTaskOutput:
    """Output DTO for task resume."""

    task: AgentTask
    request_id: str
    timeline_event_id: Optional[int] = None


@dataclass
class CancelTaskInput:
    """Input DTO for cancelling a task."""

    task_id: int
    reason: str
    actor: Optional[Dict[str, Any]] = None


@dataclass
class CancelTaskOutput:
    """Output DTO for task cancellation."""

    task: AgentTask
    request_id: str
    timeline_event_id: Optional[int] = None


class CreateTaskUseCase:
    """
    Use case for creating a new AgentTask.

    Creates a task in 'draft' status and emits a timeline event.
    """

    def __init__(
        self,
        state_machine: Optional[TaskStateMachine] = None,
        timeline_service: Optional[TimelineEventWriterService] = None,
        audit_service: Optional["AgentRuntimeAuditService"] = None,
    ):
        self.state_machine = state_machine or get_task_state_machine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        if self.audit_service is None:
            try:
                from apps.agent_runtime.application.services.audit_service import get_audit_service
                self.audit_service = get_audit_service()
            except Exception:
                self.audit_service = None

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
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        # Validate domain
        try:
            domain = TaskDomain(input_dto.task_domain)
        except ValueError:
            raise ValueError(
                f"Invalid task_domain. Must be one of: {[d.value for d in TaskDomain]}"
            )

        # Generate request ID
        request_id = generate_request_id()

        # Create task model
        task_model = AgentTaskModel._default_manager.create(
            request_id=request_id,
            schema_version="v1",
            task_domain=input_dto.task_domain,
            task_type=input_dto.task_type,
            status=TaskStatus.DRAFT.value,
            input_payload=input_dto.input_payload,
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by_id=input_dto.created_by,
        )

        # Convert to domain entity
        task = AgentTask(
            id=task_model.id,
            request_id=task_model.request_id,
            schema_version=task_model.schema_version,
            task_domain=TaskDomain(task_model.task_domain),
            task_type=task_model.task_type,
            status=TaskStatus(task_model.status),
            input_payload=task_model.input_payload,
            current_step=task_model.current_step,
            last_error=task_model.last_error,
            requires_human=task_model.requires_human,
            created_by=task_model.created_by_id,
            created_at=task_model.created_at,
            updated_at=task_model.updated_at,
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

    def __init__(self):
        pass

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
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        task_model = AgentTaskModel._default_manager.get(pk=task_id)

        # Convert to domain entity
        task = AgentTask(
            id=task_model.id,
            request_id=task_model.request_id,
            schema_version=task_model.schema_version,
            task_domain=TaskDomain(task_model.task_domain),
            task_type=task_model.task_type,
            status=TaskStatus(task_model.status),
            input_payload=task_model.input_payload,
            current_step=task_model.current_step,
            last_error=task_model.last_error,
            requires_human=task_model.requires_human,
            created_by=task_model.created_by_id,
            created_at=task_model.created_at,
            updated_at=task_model.updated_at,
        )

        return GetTaskOutput(
            task=task,
            request_id=task_model.request_id,
        )


class ListTasksUseCase:
    """
    Use case for listing AgentTasks with filters.
    """

    def __init__(self):
        pass

    def execute(self, input_dto: ListTasksInput) -> ListTasksOutput:
        """
        Execute the list tasks use case.

        Args:
            input_dto: Filter and pagination parameters

        Returns:
            ListTasksOutput with tasks and total count
        """
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        request_id = generate_request_id()
        queryset = AgentTaskModel._default_manager.all()

        # Apply filters
        if input_dto.status:
            queryset = queryset.filter(status=input_dto.status)
        if input_dto.task_domain:
            queryset = queryset.filter(task_domain=input_dto.task_domain)
        if input_dto.task_type:
            queryset = queryset.filter(task_type__icontains=input_dto.task_type)
        if input_dto.requires_human is not None:
            queryset = queryset.filter(requires_human=input_dto.requires_human)
        if input_dto.search:
            queryset = queryset.filter(
                task_type__icontains=input_dto.search
            ) | queryset.filter(request_id__icontains=input_dto.search)

        # Get total count before pagination
        total_count = queryset.count()

        # Apply pagination
        queryset = queryset.order_by("-created_at")[input_dto.offset : input_dto.offset + input_dto.limit]

        # Convert to domain entities
        tasks = []
        for task_model in queryset:
            task = AgentTask(
                id=task_model.id,
                request_id=task_model.request_id,
                schema_version=task_model.schema_version,
                task_domain=TaskDomain(task_model.task_domain),
                task_type=task_model.task_type,
                status=TaskStatus(task_model.status),
                input_payload=task_model.input_payload,
                current_step=task_model.current_step,
                last_error=task_model.last_error,
                requires_human=task_model.requires_human,
                created_by=task_model.created_by_id,
                created_at=task_model.created_at,
                updated_at=task_model.updated_at,
            )
            tasks.append(task)

        return ListTasksOutput(
            tasks=tasks,
            total_count=total_count,
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
        state_machine: Optional[TaskStateMachine] = None,
        timeline_service: Optional[TimelineEventWriterService] = None,
        audit_service: Optional["AgentRuntimeAuditService"] = None,
    ):
        self.state_machine = state_machine or get_task_state_machine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        if self.audit_service is None:
            try:
                from apps.agent_runtime.application.services.audit_service import get_audit_service
                self.audit_service = get_audit_service()
            except Exception:
                self.audit_service = None

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
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        # Get the task
        task_model = AgentTaskModel._default_manager.get(pk=input_dto.task_id)

        # Convert to domain entity
        task = AgentTask(
            id=task_model.id,
            request_id=task_model.request_id,
            schema_version=task_model.schema_version,
            task_domain=TaskDomain(task_model.task_domain),
            task_type=task_model.task_type,
            status=TaskStatus(task_model.status),
            input_payload=task_model.input_payload,
            current_step=task_model.current_step,
            last_error=task_model.last_error,
            requires_human=task_model.requires_human,
            created_by=task_model.created_by_id,
            created_at=task_model.created_at,
            updated_at=task_model.updated_at,
        )

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
        task_model.status = updated_task.status.value
        task_model.requires_human = False  # Clear flag on resume
        task_model.save(update_fields=["status", "requires_human", "updated_at"])

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
                    request_id=task_model.request_id,
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
            request_id=task_model.request_id,
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
        state_machine: Optional[TaskStateMachine] = None,
        timeline_service: Optional[TimelineEventWriterService] = None,
        audit_service: Optional["AgentRuntimeAuditService"] = None,
    ):
        self.state_machine = state_machine or get_task_state_machine()
        self.timeline_service = timeline_service or TimelineEventWriterService()
        self.audit_service = audit_service
        if self.audit_service is None:
            try:
                from apps.agent_runtime.application.services.audit_service import get_audit_service
                self.audit_service = get_audit_service()
            except Exception:
                self.audit_service = None

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
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        # Get the task
        task_model = AgentTaskModel._default_manager.get(pk=input_dto.task_id)

        # Convert to domain entity
        task = AgentTask(
            id=task_model.id,
            request_id=task_model.request_id,
            schema_version=task_model.schema_version,
            task_domain=TaskDomain(task_model.task_domain),
            task_type=task_model.task_type,
            status=TaskStatus(task_model.status),
            input_payload=task_model.input_payload,
            current_step=task_model.current_step,
            last_error=task_model.last_error,
            requires_human=task_model.requires_human,
            created_by=task_model.created_by_id,
            created_at=task_model.created_at,
            updated_at=task_model.updated_at,
        )

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
        task_model.status = updated_task.status.value
        task_model.save(update_fields=["status", "updated_at"])

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
                    request_id=task_model.request_id,
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
            request_id=task_model.request_id,
            timeline_event_id=timeline_event_id,
        )
