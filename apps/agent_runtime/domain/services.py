"""
Domain Services for Agent Runtime.

This module contains the state machine service for managing AgentTask
status transitions according to the FROZEN contract.

See: docs/plans/ai-native/vendor-baseline-contract.md Section 5
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class InvalidStateTransitionError(Exception):
    """
    Raised when an invalid state transition is attempted.

    Attributes:
        current_status: The current status of the task
        target_status: The status that was requested
        allowed_transitions: List of valid target statuses from current status
        message: Human-readable error message
    """

    def __init__(
        self,
        current_status: str,
        target_status: str,
        allowed_transitions: list[str],
        message: str | None = None
    ):
        self.current_status = current_status
        self.target_status = target_status
        self.allowed_transitions = allowed_transitions

        if message is None:
            message = (
                f"Invalid state transition from '{current_status}' to '{target_status}'. "
                f"Allowed transitions: {', '.join(allowed_transitions) or 'none'}"
            )

        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class StateTransition:
    """
    Represents a valid state transition.

    Attributes:
        from_status: Source status
        to_status: Target status
        trigger: What triggers this transition
        requires_human: Whether this transition requires explicit human intervention
    """
    from_status: str
    to_status: str
    trigger: str
    requires_human: bool = False


class TaskStateMachine:
    """
    State machine for AgentTask status transitions.

    This class enforces the FROZEN state transition rules from the contract.
    All state changes MUST go through this service.

    Terminal states: completed, cancelled
    Resumable states: failed, needs_human

    Usage:
        >>> from apps.agent_runtime.domain.entities import AgentTask, TaskStatus
        >>> machine = TaskStateMachine()
        >>>
        >>> # Check if transition is allowed
        >>> if machine.can_transition(TaskStatus.DRAFT, TaskStatus.CONTEXT_READY):
        ...     # Perform transition
        ...     updated_task = machine.transition(task, TaskStatus.CONTEXT_READY)
    """

    # Define allowed transitions as per contract Section 5.1
    # Format: (from_status, to_status): (trigger, requires_human)
    _TRANSITIONS: dict[tuple[str, str], StateTransition] = {
        # draft transitions
        ("draft", "context_ready"): StateTransition("draft", "context_ready", "Context aggregation complete", False),
        ("draft", "cancelled"): StateTransition("draft", "cancelled", "User cancellation", True),

        # context_ready transitions
        ("context_ready", "proposal_generated"): StateTransition("context_ready", "proposal_generated", "Proposal created", False),
        ("context_ready", "needs_human"): StateTransition("context_ready", "needs_human", "Context requires review", True),
        ("context_ready", "cancelled"): StateTransition("context_ready", "cancelled", "User cancellation", True),

        # proposal_generated transitions
        ("proposal_generated", "awaiting_approval"): StateTransition("proposal_generated", "awaiting_approval", "Proposal submitted for approval", False),
        ("proposal_generated", "needs_human"): StateTransition("proposal_generated", "needs_human", "Proposal requires review", True),
        ("proposal_generated", "cancelled"): StateTransition("proposal_generated", "cancelled", "User cancellation", True),

        # awaiting_approval transitions
        ("awaiting_approval", "approved"): StateTransition("awaiting_approval", "approved", "Approval granted", True),
        ("awaiting_approval", "rejected"): StateTransition("awaiting_approval", "rejected", "Approval denied", True),
        ("awaiting_approval", "needs_human"): StateTransition("awaiting_approval", "needs_human", "Escalation required", True),

        # approved transitions
        ("approved", "executing"): StateTransition("approved", "executing", "Execution started", False),
        ("approved", "cancelled"): StateTransition("approved", "cancelled", "User cancellation", True),

        # rejected transitions
        ("rejected", "proposal_generated"): StateTransition("rejected", "proposal_generated", "Retry with new proposal", True),
        ("rejected", "cancelled"): StateTransition("rejected", "cancelled", "User cancellation", True),

        # executing transitions
        ("executing", "completed"): StateTransition("executing", "completed", "Execution successful", False),
        ("executing", "failed"): StateTransition("executing", "failed", "Execution failed", False),
        ("executing", "needs_human"): StateTransition("executing", "needs_human", "Execution blocked", True),
        ("executing", "cancelled"): StateTransition("executing", "cancelled", "User cancellation", True),

        # failed transitions (resumable - requires explicit human action)
        ("failed", "draft"): StateTransition("failed", "draft", "Human Retry - requires explicit action", True),
        ("failed", "cancelled"): StateTransition("failed", "cancelled", "User cancellation", True),

        # needs_human transitions (resumable - requires explicit human action)
        ("needs_human", "draft"): StateTransition("needs_human", "draft", "Human Reset - requires explicit action", True),
        ("needs_human", "context_ready"): StateTransition("needs_human", "context_ready", "Human Continue - requires explicit action", True),
        ("needs_human", "proposal_generated"): StateTransition("needs_human", "proposal_generated", "Human Continue - requires explicit action", True),
        ("needs_human", "cancelled"): StateTransition("needs_human", "cancelled", "User cancellation", True),
    }

    # Terminal states - no transitions allowed FROM these states
    _TERMINAL_STATES = frozenset({
        "completed",
        "cancelled",
    })

    # Resumable states - can transition back to active states with human intervention
    _RESUMABLE_STATES = frozenset({
        "failed",
        "needs_human",
    })

    def can_transition(self, current_status: str, target_status: str) -> bool:
        """
        Check if a state transition is allowed.

        Args:
            current_status: Current task status
            target_status: Desired target status

        Returns:
            True if the transition is allowed, False otherwise
        """
        # Normalize to string values
        current = current_status.value if isinstance(current_status, Enum) else current_status
        target = target_status.value if isinstance(target_status, Enum) else target_status

        key = (current, target)
        return key in self._TRANSITIONS

    def get_allowed_transitions(self, current_status: str) -> list[str]:
        """
        Get all allowed target statuses from the current status.

        Args:
            current_status: Current task status

        Returns:
            List of allowed target status values
        """
        # Normalize to string value
        current = current_status.value if isinstance(current_status, Enum) else current_status

        # Check if we're in a terminal state
        if current in self._TERMINAL_STATES:
            return []

        allowed = []
        for (from_status, to_status) in self._TRANSITIONS.keys():
            if from_status == current:
                allowed.append(to_status)

        return allowed

    def get_transition_info(self, current_status: str, target_status: str) -> StateTransition | None:
        """
        Get detailed information about a transition.

        Args:
            current_status: Current task status
            target_status: Target task status

        Returns:
            StateTransition if the transition exists, None otherwise
        """
        # Normalize to string values
        current = current_status.value if isinstance(current_status, Enum) else current_status
        target = target_status.value if isinstance(target_status, Enum) else target_status

        return self._TRANSITIONS.get((current, target))

    def transition(
        self,
        task: Any,  # AgentTask - avoid circular import by using Any
        target_status: str,
        reason: str | None = None
    ) -> Any:
        """
        Perform a state transition on a task.

        This method validates the transition and returns a new task instance
        with the updated status. It does NOT persist the change - that is
        the responsibility of the application layer.

        Args:
            task: The current AgentTask instance
            target_status: The desired target status
            reason: Optional reason for the transition (for audit trail)

        Returns:
            A new AgentTask instance with the updated status

        Raises:
            InvalidStateTransitionError: If the transition is not allowed
        """
        # Get current status
        current_status = task.status
        current = current_status.value if isinstance(current_status, Enum) else current_status
        target = target_status.value if isinstance(target_status, Enum) else target_status

        # Check if transition is allowed
        if not self.can_transition(current, target):
            allowed = self.get_allowed_transitions(current)
            raise InvalidStateTransitionError(
                current_status=current,
                target_status=target_status,
                allowed_transitions=allowed
            )

        # Get transition info for audit
        transition_info = self._TRANSITIONS[(current, target)]

        # Create updated task (using dataclass replace)
        updated_task = replace(task, status=target_status)

        return updated_task

    def is_terminal(self, status: str) -> bool:
        """
        Check if a status is a terminal state.

        Terminal states are final - no transitions are allowed FROM them.

        Args:
            status: Status to check

        Returns:
            True if the status is terminal, False otherwise
        """
        # Normalize to string value
        status_str = status.value if isinstance(status, Enum) else status
        return status_str in self._TERMINAL_STATES

    def is_resumable(self, status: str) -> bool:
        """
        Check if a status is resumable.

        Resumable states can transition back to active states with
        explicit human intervention.

        Args:
            status: Status to check

        Returns:
            True if the status is resumable, False otherwise
        """
        # Normalize to string value
        status_str = status.value if isinstance(status, Enum) else status
        return status_str in self._RESUMABLE_STATES

    def requires_human_intervention(self, current_status: str, target_status: str) -> bool:
        """
        Check if a transition requires explicit human intervention.

        Some transitions (like failed -> draft or needs_human -> *)
        require explicit human action and should NOT be performed automatically.

        Args:
            current_status: Current task status
            target_status: Target task status

        Returns:
            True if the transition requires human intervention
        """
        transition = self.get_transition_info(current_status, target_status)
        return transition.requires_human if transition else False

    # =========================================================================
    # Convenience Methods for WP-M1-03
    # =========================================================================
    # These methods provide a higher-level API for common state transitions.
    # They wrap the core transition logic with semantic naming and validation.
    # =========================================================================

    def mark_context_ready(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as having context ready (draft -> context_ready).

        Args:
            task: AgentTask entity
            reason: Optional reason for the transition

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "context_ready", reason=reason)

    def mark_proposal_generated(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as having proposal generated (context_ready -> proposal_generated).

        Args:
            task: AgentTask entity
            reason: Optional reason for the transition

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "proposal_generated", reason=reason)

    def mark_awaiting_approval(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as awaiting approval (proposal_generated -> awaiting_approval).

        Args:
            task: AgentTask entity
            reason: Optional reason for the transition

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "awaiting_approval", reason=reason)

    def mark_approved(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as approved (awaiting_approval -> approved).

        NOTE: This transition requires human intervention.

        Args:
            task: AgentTask entity
            reason: Optional reason for the transition

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "approved", reason=reason)

    def mark_rejected(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as rejected (awaiting_approval -> rejected).

        NOTE: This transition requires human intervention.

        Args:
            task: AgentTask entity
            reason: Optional reason for rejection

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "rejected", reason=reason)

    def mark_executing(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as executing (approved -> executing).

        Args:
            task: AgentTask entity
            reason: Optional reason for the transition

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "executing", reason=reason)

    def mark_completed(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as completed (executing -> completed).

        This is a terminal state - no further transitions are allowed.

        Args:
            task: AgentTask entity
            reason: Optional reason for completion

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "completed", reason=reason)

    def mark_failed(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as failed (executing -> failed).

        This is a resumable state - can transition back to draft with human intervention.

        Args:
            task: AgentTask entity
            reason: Optional reason for failure

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "failed", reason=reason)

    def mark_needs_human(self, task: Any, reason: str | None = None) -> Any:
        """
        Mark task as needing human intervention.

        Allowed from: context_ready, proposal_generated, awaiting_approval, executing

        This is a resumable state - can transition back to active states with human intervention.

        Args:
            task: AgentTask entity
            reason: Optional reason for escalation

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "needs_human", reason=reason)

    def cancel_task(self, task: Any, reason: str | None = None) -> Any:
        """
        Cancel a task.

        Allowed from: draft, context_ready, proposal_generated, approved, rejected, failed, needs_human

        This is a terminal state - no further transitions are allowed.

        NOTE: This transition requires human intervention.

        Args:
            task: AgentTask entity
            reason: Optional reason for cancellation

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If task is already in terminal state
        """
        return self.transition(task, "cancelled", reason=reason)

    def resume_task(
        self,
        task: Any,
        target_status: str | None = None,
        reason: str | None = None
    ) -> Any:
        """
        Resume a task from a resumable state (failed, needs_human).

        Resumable states can transition back to active states with human intervention.
        Default target depends on current state:
        - failed -> draft
        - needs_human -> draft

        NOTE: This transition requires human intervention.

        Args:
            task: AgentTask entity
            target_status: Optional target status (defaults based on current state)
            reason: Optional reason for resuming

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If task is not in a resumable state
            ValueError: If no valid target status is determined
        """
        current = task.status.value if hasattr(task.status, 'value') else task.status

        if not self.is_resumable(current):
            raise ValueError(
                f"Task is not in a resumable state. Current status: {current}. "
                f"Resumable states: failed, needs_human"
            )

        if target_status is None:
            # Default transitions for resumable states
            target_status = "draft"
        else:
            # Normalize target_status
            target_status = target_status.value if hasattr(target_status, 'value') else target_status

        return self.transition(task, target_status, reason=reason)

    def retry_from_rejected(self, task: Any, reason: str | None = None) -> Any:
        """
        Retry from rejected state (rejected -> proposal_generated).

        NOTE: This transition requires human intervention.

        Args:
            task: AgentTask entity
            reason: Optional reason for retry

        Returns:
            Updated AgentTask entity

        Raises:
            InvalidStateTransitionError: If transition is not allowed
        """
        return self.transition(task, "proposal_generated", reason=reason)


# Singleton instance for use across the application
_task_state_machine: TaskStateMachine | None = None


def get_task_state_machine() -> TaskStateMachine:
    """
    Get the singleton TaskStateMachine instance.

    Returns:
        The shared TaskStateMachine instance
    """
    global _task_state_machine
    if _task_state_machine is None:
        _task_state_machine = TaskStateMachine()
    return _task_state_machine
