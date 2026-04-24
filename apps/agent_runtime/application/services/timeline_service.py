"""
Timeline Event Writer Service.

This service writes timeline events for task lifecycle tracking.
Every task has a timeline from creation.

FROZEN: This service implements WP-M1-03 from the implementation plan.
"""

import logging
from typing import Any, Dict, Optional, Union

from django.utils import timezone

from apps.agent_runtime.application.repository_provider import get_timeline_repository
from apps.agent_runtime.domain.entities import (
    AgentProposal,
    AgentTask,
    EventSource,
    TimelineEventType,
)

logger = logging.getLogger(__name__)


class TimelineEventWriterService:
    """
    Timeline Event Writer Service.

    Writes timeline events for task lifecycle tracking.
    Every task has a timeline from creation.

    Event payloads include:
    - actor: The entity causing the event (user_id, agent_id, etc.)
    - request_id: The stable request trace id
    - Additional context based on event type
    """

    def __init__(self, timeline_repository: Any | None = None) -> None:
        self.timeline_repository = timeline_repository or get_timeline_repository()

    def write_event(
        self,
        event_type: TimelineEventType | str,
        task_id: int,
        event_payload: dict[str, Any],
        event_source: EventSource | str,
        request_id: str,
        proposal_id: int | None = None,
        step_index: int | None = None,
    ) -> int | None:
        """
        Write a generic timeline event.

        Args:
            event_type: The type of event from TimelineEventType enum
            task_id: The ID of the associated task
            event_payload: Event details including actor and request_id
            event_source: Source of event (api/sdk/mcp/system/human)
            request_id: Stable request trace id
            proposal_id: Optional linked proposal ID
            step_index: Optional step sequence number

        Returns:
            The created event ID, or None if creation failed
        """
        try:
            # Normalize string enums to enum values
            if isinstance(event_type, str):
                event_type = TimelineEventType(event_type)
            if isinstance(event_source, str):
                event_source = EventSource(event_source)

            # Ensure payload has required fields
            payload = {
                "request_id": request_id,
                **event_payload,
            }

            event_id = self.timeline_repository.create_event(
                request_id=request_id,
                task_id=task_id,
                proposal_id=proposal_id,
                event_type=event_type.value,
                event_source=event_source.value,
                step_index=step_index,
                event_payload=payload,
            )

            logger.debug(
                f"Timeline event written: {event_type.value} for task {task_id}"
            )
            return event_id

        except Exception as e:
            logger.error(f"Failed to write timeline event: {e}")
            return None

    def write_task_created_event(
        self,
        task: AgentTask | int,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Write a task_created event.

        Args:
            task: AgentTask entity or task_id
            event_source: Source of the event
            actor: Optional actor information (e.g., {"user_id": 123})

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""  # Will be filled by caller if needed

        payload = {
            "task_domain": task.task_domain.value if isinstance(task, AgentTask) else None,
            "task_type": task.task_type if isinstance(task, AgentTask) else None,
        }

        if actor:
            payload["actor"] = actor

        return self.write_event(
            event_type=TimelineEventType.TASK_CREATED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
        )

    def write_state_changed_event(
        self,
        task: AgentTask | int,
        old_status: str | object,
        new_status: str | object,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> int | None:
        """
        Write a state_changed event.

        Args:
            task: AgentTask entity or task_id
            old_status: Previous status value
            new_status: New status value
            event_source: Source of the event
            actor: Optional actor information
            reason: Optional reason for state change

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        # Handle both string and enum status values
        old_status_val = old_status.value if hasattr(old_status, 'value') else old_status
        new_status_val = new_status.value if hasattr(new_status, 'value') else new_status

        payload = {
            "old_status": old_status_val,
            "new_status": new_status_val,
        }

        if actor:
            payload["actor"] = actor
        if reason:
            payload["reason"] = reason

        return self.write_event(
            event_type=TimelineEventType.STATE_CHANGED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
        )

    def write_step_started_event(
        self,
        task: AgentTask | int,
        step_key: str,
        step_index: int | None = None,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Write a step_started event.

        Args:
            task: AgentTask entity or task_id
            step_key: Step identifier
            step_index: Step sequence number
            event_source: Source of the event
            actor: Optional actor information

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        payload = {
            "step_key": step_key,
        }

        if actor:
            payload["actor"] = actor

        return self.write_event(
            event_type=TimelineEventType.STEP_STARTED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
            step_index=step_index,
        )

    def write_step_completed_event(
        self,
        task: AgentTask | int,
        step_key: str,
        step_index: int | None = None,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Write a step_completed event.

        Args:
            task: AgentTask entity or task_id
            step_key: Step identifier
            step_index: Step sequence number
            event_source: Source of the event
            actor: Optional actor information
            output: Optional step output data

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        payload = {
            "step_key": step_key,
        }

        if actor:
            payload["actor"] = actor
        if output:
            payload["output"] = output

        return self.write_event(
            event_type=TimelineEventType.STEP_COMPLETED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
            step_index=step_index,
        )

    def write_step_failed_event(
        self,
        task: AgentTask | int,
        step_key: str,
        error_message: str,
        step_index: int | None = None,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Write a step_failed event.

        Args:
            task: AgentTask entity or task_id
            step_key: Step identifier
            error_message: Error description
            step_index: Step sequence number
            event_source: Source of the event
            actor: Optional actor information

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        payload = {
            "step_key": step_key,
            "error_message": error_message,
        }

        if actor:
            payload["actor"] = actor

        return self.write_event(
            event_type=TimelineEventType.STEP_FAILED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
            step_index=step_index,
        )

    def write_task_resumed_event(
        self,
        task: AgentTask | int,
        reason: str,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Write a task_resumed event.

        Args:
            task: AgentTask entity or task_id
            reason: Reason for resuming the task
            event_source: Source of the event
            actor: Optional actor information

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        payload = {
            "reason": reason,
        }

        if actor:
            payload["actor"] = actor

        return self.write_event(
            event_type=TimelineEventType.TASK_RESUMED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
        )

    def write_task_cancelled_event(
        self,
        task: AgentTask | int,
        reason: str,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
    ) -> int | None:
        """
        Write a task_cancelled event.

        Args:
            task: AgentTask entity or task_id
            reason: Reason for cancellation
            event_source: Source of the event
            actor: Optional actor information

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        payload = {
            "reason": reason,
        }

        if actor:
            payload["actor"] = actor

        return self.write_event(
            event_type=TimelineEventType.TASK_CANCELLED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
        )

    def write_task_escalated_event(
        self,
        task: AgentTask | int,
        reason: str,
        event_source: EventSource | str = EventSource.SYSTEM,
        actor: dict[str, Any] | None = None,
        escalation_target: str | None = None,
    ) -> int | None:
        """
        Write a task_escalated event.

        Args:
            task: AgentTask entity or task_id
            reason: Reason for escalation
            event_source: Source of the event
            actor: Optional actor information
            escalation_target: Optional target of escalation

        Returns:
            The created event ID, or None if creation failed
        """
        if isinstance(task, AgentTask):
            task_id = task.id
            request_id = task.request_id
        else:
            task_id = task
            request_id = ""

        payload = {
            "reason": reason,
        }

        if actor:
            payload["actor"] = actor
        if escalation_target:
            payload["escalation_target"] = escalation_target

        return self.write_event(
            event_type=TimelineEventType.TASK_ESCALATED,
            task_id=task_id,
            event_payload=payload,
            event_source=event_source,
            request_id=request_id,
        )
