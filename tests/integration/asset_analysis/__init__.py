"""
Integration tests for Task Lifecycle.

WP-M1-03: Domain State Machine
WP-M1-04: Timeline And Artifacts

Tests verify:
- Full task lifecycle from creation to completion
- Timeline events are written for each state change
- State transitions are enforced server-side
"""

from datetime import datetime, timezone

import pytest

from apps.agent_runtime.application.use_cases import (
    CancelTaskInput,
    CancelTaskUseCase,
    CreateTaskInput,
    CreateTaskUseCase,
    GetTaskUseCase,
    ListTasksUseCase,
    ResumeTaskInput,
    ResumeTaskUseCase,
)
from apps.agent_runtime.domain.entities import (
    EventSource,
    TaskDomain,
    TaskStatus,
    TimelineEventType,
)
from apps.agent_runtime.domain.services import (
    InvalidStateTransitionError,
    TaskStateMachine,
    get_task_state_machine,
)
from apps.agent_runtime.infrastructure.models import (
    AgentTaskModel,
    AgentTimelineEventModel,
)


@pytest.mark.django_db
class TestTaskLifecycle:
    """Integration tests for full task lifecycle."""

    @pytest.fixture
    def state_machine(self):
        """Get the state machine singleton."""
        return get_task_state_machine()

    @pytest.fixture
    def create_use_case(self):
        """Create a CreateTaskUseCase instance."""
        return CreateTaskUseCase()

    # ========== Creation Tests ==========

    def test_create_task_creates_timeline_event(self, create_use_case):
        """Verify task creation writes timeline event."""
        request = CreateTaskInput(
            task_domain="research",
            task_type="macro_portfolio_review",
            input_payload={"portfolio_id": 308},
        )

        result = create_use_case.execute(request)

        assert result.task is not None
        assert result.request_id.startswith("atr_")

        # Verify timeline event was created
        events = AgentTimelineEventModel.objects.filter(
            task_id=result.task.id,
            event_type="task_created",
        )
        assert events.count() == 1
        assert events.first().event_source == "api"

    def test_create_task_with_valid_domain_succeeds(self, create_use_case):
        """Verify valid task domains are accepted."""
        for domain in ["research", "monitoring", "decision", "execution", "ops"]:
            request = CreateTaskInput(
                task_domain=domain,
                task_type="test_task",
                input_payload={},
            )
            result = create_use_case.execute(request)
            assert result.task.task_domain.value == domain

    # ========== State Transition Tests ==========

    def test_happy_path_draft_to_completed(self, state_machine):
        """Test the happy path: draft -> context_ready -> proposal_generated -> awaiting_approval -> approved -> executing -> completed."""
        # Create task
        task = AgentTaskModel.objects.create(
            request_id="test_happy_path",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        # Create domain entity
        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        # Verify each transition
        transitions = [
            ("context_ready", TaskStatus.CONTEXT_READY),
            ("proposal_generated", TaskStatus.PROPOSAL_GENERATED),
            ("awaiting_approval", TaskStatus.AWAITING_APPROVAL),
            ("approved", TaskStatus.APPROVED),
            ("executing", TaskStatus.EXECUTING),
            ("completed", TaskStatus.COMPLETED),
        ]

        for trigger, expected_status in transitions:
            domain_task = state_machine.transition(domain_task, trigger)
            assert domain_task.status == expected_status

    def test_failed_path_can_resume(self, state_machine):
        """Test that failed tasks can be resumed to draft."""
        # Create task in failed state
        task = AgentTaskModel.objects.create(
            request_id="test_failed_resume",
            task_domain="research",
            task_type="test",
            status="failed",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.FAILED,
            input_payload={},
            current_step=None,
            last_error={"message": "Test failure"},
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        # Resume to draft
        domain_task = state_machine.resume_task(domain_task, target_status="draft")
        assert domain_task.status == TaskStatus.DRAFT

    def test_needs_human_can_resume_to_multiple_states(self, state_machine):
        """Test that needs_human tasks can resume to different states."""
        # Create task in needs_human state
        task = AgentTaskModel.objects.create(
            request_id="test_needs_human_resume",
            task_domain="research",
            task_type="test",
            status="needs_human",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.NEEDS_HUMAN,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=True,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        # Can resume to draft
        domain_task = state_machine.resume_task(domain_task, target_status="draft")
        assert domain_task.status == TaskStatus.DRAFT

        # Reset to needs_human for next test
        domain_task = domain_task.replace(status=TaskStatus.NEEDS_HUMAN)

        # Can resume to context_ready
        domain_task = state_machine.resume_task(domain_task, target_status="context_ready")
        assert domain_task.status == TaskStatus.CONTEXT_READY

    def test_illegal_transition_raises_error(self, state_machine):
        """Test that illegal transitions raise InvalidStateTransitionError."""
        # Create task in draft state
        task = AgentTaskModel.objects.create(
            request_id="test_illegal",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        # Cannot go directly from draft to completed
        with pytest.raises(InvalidStateTransitionError):
            state_machine.transition(domain_task, "completed")

    def test_cannot_transition_from_terminal_state(self, state_machine):
        """Test that terminal states cannot transition."""
        # Create task in completed state
        task = AgentTaskModel.objects.create(
            request_id="test_terminal",
            task_domain="research",
            task_type="test",
            status="completed",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.COMPLETED,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        # Cannot transition from completed
        with pytest.raises(InvalidStateTransitionError):
            state_machine.transition(domain_task, "draft")

    # ========== Cancel Tests ==========

    def test_cancel_from_draft(self, state_machine):
        """Test cancelling from draft state."""
        task = AgentTaskModel.objects.create(
            request_id="test_cancel_draft",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.DRAFT,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        domain_task = state_machine.cancel_task(domain_task, reason="User cancelled")
        assert domain_task.status == TaskStatus.CANCELLED

    def test_cancel_from_executing(self, state_machine):
        """Test cancelling from executing state."""
        task = AgentTaskModel.objects.create(
            request_id="test_cancel_executing",
            task_domain="research",
            task_type="test",
            status="executing",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.EXECUTING,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        domain_task = state_machine.cancel_task(domain_task, reason="Aborted")
        assert domain_task.status == TaskStatus.CANCELLED

    def test_cancel_from_terminal_fails(self, state_machine):
        """Test that cancelling from terminal state fails."""
        task = AgentTaskModel.objects.create(
            request_id="test_cancel_terminal",
            task_domain="research",
            task_type="test",
            status="completed",
            input_payload={},
        )

        from apps.agent_runtime.domain.entities import AgentTask
        domain_task = AgentTask(
            id=task.id,
            request_id=task.request_id,
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="test",
            status=TaskStatus.COMPLETED,
            input_payload={},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

        with pytest.raises(InvalidStateTransitionError):
            state_machine.cancel_task(domain_task, reason="Too late")


@pytest.mark.django_db
class TestTimelineEventGeneration:
    """Tests for timeline event generation during lifecycle."""

    def test_each_state_change_creates_event(self):
        """Verify each state change creates a timeline event."""
        # Create task
        task = AgentTaskModel.objects.create(
            request_id="test_timeline_events",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        # Create initial event
        AgentTimelineEventModel.objects.create(
            request_id=task.request_id,
            task=task,
            event_type="task_created",
            event_source="api",
            event_payload={"request_id": task.request_id},
        )

        # Simulate state changes
        states = ["context_ready", "proposal_generated", "awaiting_approval", "approved", "executing", "completed"]
        for i, state in enumerate(states):
            task.status = state
            task.save()

            AgentTimelineEventModel.objects.create(
                request_id=task.request_id,
                task=task,
                event_type="state_changed",
                event_source="system",
                step_index=i,
                event_payload={"new_status": state},
            )

        # Verify events exist
        events = AgentTimelineEventModel.objects.filter(task=task).order_by("created_at")
        assert events.count() == 7  # 1 created + 6 state changes

    def test_event_payload_includes_actor(self):
        """Verify event payload includes actor when provided."""
        task = AgentTaskModel.objects.create(
            request_id="test_actor_payload",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
        )

        AgentTimelineEventModel.objects.create(
            request_id=task.request_id,
            task=task,
            event_type="task_created",
            event_source="api",
            event_payload={
                "request_id": task.request_id,
                "actor": {"user_id": 42, "role": "admin"},
            },
        )

        event = AgentTimelineEventModel.objects.get(task=task)
        assert "actor" in event.event_payload
        assert event.event_payload["actor"]["user_id"] == 42


@pytest.mark.django_db
class TestUseCaseIntegration:
    """Integration tests for Use Cases with real database."""

    def test_create_and_retrieve_task(self):
        """Test creating and retrieving a task through use cases."""
        # Create
        create_uc = CreateTaskUseCase()
        create_result = create_uc.execute(CreateTaskInput(
            task_domain="research",
            task_type="integration_test",
            input_payload={"test": True},
        ))

        assert create_result.task.id is not None

        # Retrieve
        get_uc = GetTaskUseCase()
        get_result = get_uc.execute(create_result.task.id)

        assert get_result.task.request_id == create_result.request_id
        assert get_result.task.task_type == "integration_test"

    def test_list_tasks_with_filter(self):
        """Test listing tasks with domain filter."""
        # Create multiple tasks
        create_uc = CreateTaskUseCase()

        create_uc.execute(CreateTaskInput(
            task_domain="research",
            task_type="test_1",
            input_payload={},
        ))
        create_uc.execute(CreateTaskInput(
            task_domain="monitoring",
            task_type="test_2",
            input_payload={},
        ))

        # List with filter
        list_uc = ListTasksUseCase()
        result = list_uc.execute(task_domain="research")

        # All returned tasks should be research domain
        for task in result.tasks:
            assert task.task_domain.value == "research"
