"""
Unit tests for Agent Runtime Domain layer.

WP-M1-07: Tests (027-030)
"""

from dataclasses import replace

import pytest

from apps.agent_runtime.domain.entities import (
    AgentTask,
    TaskDomain,
    TaskStatus,
    TimelineEventType,
)
from apps.agent_runtime.domain.services import (
    InvalidStateTransitionError,
    TaskStateMachine,
    get_task_state_machine,
)


class TestTaskStateMachine:
    """Tests for TaskStateMachine."""

    @pytest.fixture
    def machine(self):
        """Get the state machine instance."""
        return TaskStateMachine()

    @pytest.mark.parametrize("current,target,expected", [
        # Valid transitions
        ("draft", "context_ready", True),
        ("draft", "cancelled", True),
        ("context_ready", "proposal_generated", True),
        ("context_ready", "needs_human", True),
        ("proposal_generated", "awaiting_approval", True),
        ("awaiting_approval", "approved", True),
        ("awaiting_approval", "rejected", True),
        ("approved", "executing", True),
        ("executing", "completed", True),
        ("executing", "failed", True),
        ("failed", "draft", True),
        ("needs_human", "draft", True),
        # Invalid transitions
        ("draft", "completed", False),
        ("draft", "approved", False),
        ("completed", "draft", False),
        ("cancelled", "draft", False),
        ("completed", "cancelled", False),
    ])
    def test_can_transition(self, machine, current, target, expected):
        """Test can_transition returns correct result."""
        assert machine.can_transition(current, target) == expected

    def test_get_allowed_transitions_draft(self, machine):
        """Test allowed transitions from draft state."""
        allowed = machine.get_allowed_transitions("draft")
        assert "context_ready" in allowed
        assert "cancelled" in allowed
        assert len(allowed) == 2

    def test_get_allowed_transitions_terminal(self, machine):
        """Test that terminal states have no allowed transitions."""
        assert machine.get_allowed_transitions("completed") == []
        assert machine.get_allowed_transitions("cancelled") == []

    def test_get_allowed_transitions_needs_human(self, machine):
        """Test allowed transitions from needs_human state."""
        allowed = machine.get_allowed_transitions("needs_human")
        assert "draft" in allowed
        assert "context_ready" in allowed
        assert "proposal_generated" in allowed
        assert "cancelled" in allowed

    def test_is_terminal(self, machine):
        """Test is_terminal correctly identifies terminal states."""
        assert machine.is_terminal("completed") is True
        assert machine.is_terminal("cancelled") is True
        assert machine.is_terminal("draft") is False
        assert machine.is_terminal("failed") is False
        assert machine.is_terminal("needs_human") is False

    def test_is_resumable(self, machine):
        """Test is_resumable correctly identifies resumable states."""
        assert machine.is_resumable("failed") is True
        assert machine.is_resumable("needs_human") is True
        assert machine.is_resumable("draft") is False
        assert machine.is_resumable("completed") is False
        assert machine.is_resumable("cancelled") is False

    def test_requires_human_intervention(self, machine):
        """Test requires_human_intervention returns correct result."""
        # Transitions requiring human intervention
        assert machine.requires_human_intervention("failed", "draft") is True
        assert machine.requires_human_intervention("needs_human", "draft") is True
        assert machine.requires_human_intervention("awaiting_approval", "approved") is True
        assert machine.requires_human_intervention("awaiting_approval", "rejected") is True

        # Transitions NOT requiring human intervention
        assert machine.requires_human_intervention("draft", "context_ready") is False
        assert machine.requires_human_intervention("approved", "executing") is False
        assert machine.requires_human_intervention("executing", "completed") is False

    def test_transition_success(self, machine):
        """Test successful state transition."""
        task = AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="macro_portfolio_review",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

        updated = machine.transition(task, TaskStatus.CONTEXT_READY)

        assert updated.status == TaskStatus.CONTEXT_READY
        # Original task should be unchanged (frozen dataclass)
        assert task.status == TaskStatus.DRAFT

    def test_transition_invalid_raises_error(self, machine):
        """Test invalid transition raises InvalidStateTransitionError."""
        task = AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="macro_portfolio_review",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            machine.transition(task, TaskStatus.COMPLETED)

        error = exc_info.value
        assert error.current_status == "draft"
        assert error.target_status == "completed"
        assert "context_ready" in error.allowed_transitions

    def test_get_task_state_machine_singleton(self):
        """Test that get_task_state_machine returns singleton."""
        machine1 = get_task_state_machine()
        machine2 = get_task_state_machine()
        assert machine1 is machine2


class TestTaskStateMachineConvenienceMethods:
    """Tests for TaskStateMachine convenience methods (WP-M1-03)."""

    @pytest.fixture
    def machine(self):
        """Get the state machine instance."""
        return TaskStateMachine()

    @pytest.fixture
    def draft_task(self):
        """Create a task in draft state."""
        return AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

    @pytest.fixture
    def failed_task(self):
        """Create a task in failed state."""
        return AgentTask(
            id=2,
            request_id="atr_20260316_000002",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.FAILED,
            input_payload={},
            current_step=None,
            last_error={"message": "Test error"},
            requires_human=True,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

    @pytest.fixture
    def needs_human_task(self):
        """Create a task in needs_human state."""
        return AgentTask(
            id=3,
            request_id="atr_20260316_000003",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.NEEDS_HUMAN,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=True,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

    @pytest.fixture
    def completed_task(self):
        """Create a task in completed state."""
        return AgentTask(
            id=4,
            request_id="atr_20260316_000004",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.COMPLETED,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

    def test_mark_context_ready(self, machine, draft_task):
        """Test mark_context_ready transition."""
        updated = machine.mark_context_ready(draft_task)
        assert updated.status == TaskStatus.CONTEXT_READY

    def test_mark_proposal_generated(self, machine):
        """Test mark_proposal_generated transition."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.CONTEXT_READY, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_proposal_generated(task)
        assert updated.status == TaskStatus.PROPOSAL_GENERATED

    def test_mark_awaiting_approval(self, machine):
        """Test mark_awaiting_approval transition."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.PROPOSAL_GENERATED, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_awaiting_approval(task)
        assert updated.status == TaskStatus.AWAITING_APPROVAL

    def test_mark_approved(self, machine):
        """Test mark_approved transition (requires human)."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.AWAITING_APPROVAL, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_approved(task)
        assert updated.status == TaskStatus.APPROVED

    def test_mark_rejected(self, machine):
        """Test mark_rejected transition (requires human)."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.AWAITING_APPROVAL, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_rejected(task)
        assert updated.status == TaskStatus.REJECTED

    def test_mark_executing(self, machine):
        """Test mark_executing transition."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.APPROVED, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_executing(task)
        assert updated.status == TaskStatus.EXECUTING

    def test_mark_completed(self, machine):
        """Test mark_completed transition (terminal state)."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.EXECUTING, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_completed(task)
        assert updated.status == TaskStatus.COMPLETED
        assert machine.is_terminal(updated.status)

    def test_mark_failed(self, machine):
        """Test mark_failed transition (resumable state)."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.EXECUTING, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_failed(task, reason="Execution failed")
        assert updated.status == TaskStatus.FAILED
        assert machine.is_resumable(updated.status)

    def test_mark_needs_human(self, machine):
        """Test mark_needs_human transition (resumable state)."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.CONTEXT_READY, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.mark_needs_human(task, reason="Context requires review")
        assert updated.status == TaskStatus.NEEDS_HUMAN
        assert machine.is_resumable(updated.status)

    def test_cancel_task_from_draft(self, machine, draft_task):
        """Test cancel_task from draft state."""
        updated = machine.cancel_task(draft_task, reason="No longer needed")
        assert updated.status == TaskStatus.CANCELLED
        assert machine.is_terminal(updated.status)

    def test_cancel_task_from_executing(self, machine):
        """Test cancel_task from executing state."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.EXECUTING, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.cancel_task(task, reason="User cancelled")
        assert updated.status == TaskStatus.CANCELLED

    def test_cancel_task_from_terminal_fails(self, machine, completed_task):
        """Test cancel_task from terminal state raises error."""
        with pytest.raises(InvalidStateTransitionError):
            machine.cancel_task(completed_task, reason="Already done")

    def test_resume_task_from_failed(self, machine, failed_task):
        """Test resume_task from failed state."""
        updated = machine.resume_task(failed_task, reason="Fixed the issue")
        assert updated.status == TaskStatus.DRAFT

    def test_resume_task_from_needs_human(self, machine, needs_human_task):
        """Test resume_task from needs_human state."""
        updated = machine.resume_task(needs_human_task, reason="Human reviewed")
        assert updated.status == TaskStatus.DRAFT

    def test_resume_task_with_explicit_target(self, machine, needs_human_task):
        """Test resume_task with explicit target status."""
        updated = machine.resume_task(needs_human_task, target_status="context_ready")
        assert updated.status == TaskStatus.CONTEXT_READY

    def test_resume_task_from_non_resumable_fails(self, machine, draft_task):
        """Test resume_task from non-resumable state raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            machine.resume_task(draft_task)
        assert "not in a resumable state" in str(exc_info.value)

    def test_retry_from_rejected(self, machine):
        """Test retry_from_rejected transition."""
        task = AgentTask(
            id=1, request_id="test", schema_version="v1",
            task_domain=TaskDomain.RESEARCH, task_type="test",
            status=TaskStatus.REJECTED, input_payload={},
            current_step=None, last_error=None, requires_human=False,
            created_by=1, created_at=None, updated_at=None,
        )
        updated = machine.retry_from_rejected(task, reason="Addressed feedback")
        assert updated.status == TaskStatus.PROPOSAL_GENERATED


class TestInvalidStateTransitionError:
    """Tests for InvalidStateTransitionError."""

    def test_error_message_format(self):
        """Test error message is formatted correctly."""
        error = InvalidStateTransitionError(
            current_status="draft",
            target_status="completed",
            allowed_transitions=["context_ready", "cancelled"],
        )

        assert "draft" in str(error)
        assert "completed" in str(error)
        assert "context_ready" in str(error)
        assert error.current_status == "draft"
        assert error.target_status == "completed"
        assert error.allowed_transitions == ["context_ready", "cancelled"]

    def test_custom_message(self):
        """Test custom message override."""
        error = InvalidStateTransitionError(
            current_status="completed",
            target_status="draft",
            allowed_transitions=[],
            message="Cannot restart completed task",
        )

        assert "Cannot restart completed task" in str(error)


class TestTaskDomainEnum:
    """Tests for TaskDomain enum."""

    def test_all_domains_defined(self):
        """Test all expected domains are defined."""
        domains = [d.value for d in TaskDomain]
        assert "research" in domains
        assert "monitoring" in domains
        assert "decision" in domains
        assert "execution" in domains
        assert "ops" in domains

    def test_domain_from_string(self):
        """Test creating domain from string value."""
        assert TaskDomain("research") == TaskDomain.RESEARCH
        assert TaskDomain("decision") == TaskDomain.DECISION


class TestTaskStatusEnum:
    """Tests for TaskStatus enum."""

    def test_all_statuses_defined(self):
        """Test all expected statuses are defined."""
        statuses = [s.value for s in TaskStatus]
        expected = [
            "draft", "context_ready", "proposal_generated",
            "awaiting_approval", "approved", "rejected",
            "executing", "completed", "failed",
            "needs_human", "cancelled"
        ]
        for status in expected:
            assert status in statuses


class TestTimelineEventTypeEnum:
    """Tests for TimelineEventType enum."""

    def test_all_event_types_defined(self):
        """Test all expected event types are defined."""
        event_types = [e.value for e in TimelineEventType]
        assert "task_created" in event_types
        assert "state_changed" in event_types
        assert "step_started" in event_types
        assert "step_completed" in event_types
        assert "step_failed" in event_types
        assert "task_resumed" in event_types
        assert "task_cancelled" in event_types
        assert "task_escalated" in event_types


class TestAgentTaskEntity:
    """Tests for AgentTask entity."""

    def test_agent_task_creation(self):
        """Test creating an AgentTask entity."""
        task = AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="macro_portfolio_review",
            status=TaskStatus.DRAFT,
            input_payload={"query": "test"},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

        assert task.id == 1
        assert task.request_id == "atr_20260316_000001"
        assert task.task_domain == TaskDomain.RESEARCH
        assert task.status == TaskStatus.DRAFT
        assert task.input_payload == {"query": "test"}

    def test_agent_task_frozen(self):
        """Test AgentTask is immutable (frozen dataclass)."""
        task = AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="macro_portfolio_review",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

        with pytest.raises(AttributeError):
            task.status = TaskStatus.COMPLETED  # type: ignore

    def test_agent_task_replace(self):
        """Test AgentTask can be replaced with new values."""
        task = AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="macro_portfolio_review",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=None,
            updated_at=None,
        )

        updated = replace(task, status=TaskStatus.CONTEXT_READY)
        assert task.status == TaskStatus.DRAFT
        assert updated.status == TaskStatus.CONTEXT_READY
