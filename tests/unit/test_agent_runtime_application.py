"""
Unit tests for Agent Runtime Application layer.

WP-M1-07: Tests (027-030)

NOTE: These tests focus on domain layer logic (state machine, entities)
and use integration-style tests for use cases that require Django ORM.
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone
from dataclasses import dataclass, replace

from apps.agent_runtime.domain.entities import (
    TaskDomain,
    TaskStatus,
    AgentTask,
)
from apps.agent_runtime.domain.services import (
    TaskStateMachine,
    InvalidStateTransitionError,
    get_task_state_machine,
)
from apps.agent_runtime.application.use_cases import (
    generate_request_id,
)


class TestGenerateRequestId:
    """Tests for request ID generation."""

    def test_generates_unique_ids(self):
        """Test that generated IDs are unique."""
        id1 = generate_request_id()
        id2 = generate_request_id()
        assert id1 != id2

    def test_format_is_correct(self):
        """Test that generated ID has correct format."""
        rid = generate_request_id()
        assert rid.startswith("atr_")
        # Format: atr_YYYYMMDD_XXXXXX
        parts = rid.split("_")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # XXXXXX

    def test_format_matches_contract(self):
        """Test that format matches schema-contract.md."""
        rid = generate_request_id()
        # Contract: atr_YYYYMMDD_XXXXXX
        import re
        pattern = r"^atr_\d{8}_[A-Z0-9]{6}$"
        assert re.match(pattern, rid), f"Request ID {rid} does not match contract format"


class TestTaskStateMachine:
    """Tests for TaskStateMachine."""

    @pytest.fixture
    def machine(self):
        return TaskStateMachine()

    def test_singleton_get_task_state_machine(self):
        """Test that get_task_state_machine returns singleton."""
        machine1 = get_task_state_machine()
        machine2 = get_task_state_machine()
        assert machine1 is machine2

    def test_resumable_states(self, machine):
        """Test that failed and needs_human are resumable."""
        assert machine.is_resumable("failed") is True
        assert machine.is_resumable("needs_human") is True
        assert machine.is_resumable("completed") is False
        assert machine.is_resumable("cancelled") is False
        assert machine.is_resumable("draft") is False
        assert machine.is_resumable("executing") is False

    def test_terminal_states(self, machine):
        """Test that completed and cancelled are terminal."""
        assert machine.is_terminal("completed") is True
        assert machine.is_terminal("cancelled") is True
        assert machine.is_terminal("draft") is False
        assert machine.is_terminal("failed") is False
        assert machine.is_terminal("needs_human") is False

    @pytest.mark.parametrize("current,target,expected", [
        # Valid transitions for resuming
        ("failed", "draft", True),
        ("needs_human", "draft", True),
        ("needs_human", "context_ready", True),
        ("needs_human", "proposal_generated", True),
        # Invalid transitions for resuming
        ("completed", "draft", False),
        ("cancelled", "draft", False),
        ("draft", "completed", False),
    ])
    def test_can_transition(self, machine, current, target, expected):
        """Test can_transition returns correct result for various transitions."""
        assert machine.can_transition(current, target) == expected

    def test_transition_uses_frozen_dataclass(self, machine):
        """Test that transition returns a new frozen dataclass."""
        task = AgentTask(
            id=1,
            request_id="atr_test",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated = machine.transition(task, TaskStatus.CONTEXT_READY)

        # Original task is unchanged (frozen)
        assert task.status == TaskStatus.DRAFT
        # Updated task has new status
        assert updated.status == TaskStatus.CONTEXT_READY
        # Cannot modify frozen dataclass
        with pytest.raises(AttributeError):
            task.status = TaskStatus.COMPLETED  # type: ignore

    def test_transition_raises_for_invalid(self, machine):
        """Test that transition raises for invalid transition."""
        task = AgentTask(
            id=1,
            request_id="atr_test",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with pytest.raises(InvalidStateTransitionError) as exc_info:
            machine.transition(task, TaskStatus.COMPLETED)

        assert exc_info.value.current_status == "draft"
        assert exc_info.value.target_status == "completed"
        assert "context_ready" in exc_info.value.allowed_transitions

    def test_requires_human_intervention(self, machine):
        """Test requires_human_intervention returns correct values."""
        # Transitions requiring human intervention
        assert machine.requires_human_intervention("failed", "draft") is True
        assert machine.requires_human_intervention("needs_human", "draft") is True
        assert machine.requires_human_intervention("awaiting_approval", "approved") is True
        assert machine.requires_human_intervention("awaiting_approval", "rejected") is True

        # Transitions NOT requiring human intervention
        assert machine.requires_human_intervention("draft", "context_ready") is False
        assert machine.requires_human_intervention("approved", "executing") is False
        assert machine.requires_human_intervention("executing", "completed") is False

    def test_get_allowed_transitions_for_resumable_states(self, machine):
        """Test get_allowed_transitions for resumable states."""
        # failed state
        failed_allowed = machine.get_allowed_transitions("failed")
        assert "draft" in failed_allowed
        assert "cancelled" in failed_allowed
        assert "completed" not in failed_allowed

        # needs_human state
        needs_human_allowed = machine.get_allowed_transitions("needs_human")
        assert "draft" in needs_human_allowed
        assert "context_ready" in needs_human_allowed
        assert "proposal_generated" in needs_human_allowed
        assert "cancelled" in needs_human_allowed


class TestAgentTaskEntity:
    """Tests for AgentTask entity."""

    def test_create_agent_task(self):
        """Test creating AgentTask entity."""
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
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert task.id == 1
        assert task.request_id == "atr_20260316_000001"
        assert task.task_domain == TaskDomain.RESEARCH
        assert task.task_type == "macro_portfolio_review"
        assert task.status == TaskStatus.DRAFT
        assert task.input_payload == {"query": "test"}

    def test_agent_task_is_frozen(self):
        """Test that AgentTask is frozen (immutable)."""
        task = AgentTask(
            id=1,
            request_id="atr_test",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        with pytest.raises(AttributeError):
            task.status = TaskStatus.COMPLETED  # type: ignore

    def test_agent_task_replace(self):
        """Test that AgentTask can be replaced with new values."""
        task = AgentTask(
            id=1,
            request_id="atr_test",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        updated = replace(task, status=TaskStatus.CONTEXT_READY)

        # Original unchanged
        assert task.status == TaskStatus.DRAFT
        # Updated has new value
        assert updated.status == TaskStatus.CONTEXT_READY


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
        assert error.message == "Cannot restart completed task"


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

    def test_invalid_domain_raises(self):
        """Test that invalid domain raises ValueError."""
        with pytest.raises(ValueError):
            TaskDomain("invalid_domain")


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

    def test_status_from_string(self):
        """Test creating status from string value."""
        assert TaskStatus("draft") == TaskStatus.DRAFT
        assert TaskStatus("needs_human") == TaskStatus.NEEDS_HUMAN
        assert TaskStatus("completed") == TaskStatus.COMPLETED
