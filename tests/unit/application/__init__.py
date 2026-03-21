"""
Unit tests for Timeline Event Writer Service.

WP-M1-04: Timeline And Artifacts

Tests verify:
- All 8 event types are written correctly
- Event payloads include actor and request_id
- Both AgentTask entity and task_id integer are supported
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from apps.agent_runtime.application.services.timeline_service import (
    TimelineEventWriterService,
)
from apps.agent_runtime.domain.entities import (
    AgentTask,
    TaskDomain,
    TaskStatus,
    TimelineEventType,
    EventSource,
)


@pytest.mark.django_db
class TestTimelineEventWriterService:
    """Tests for TimelineEventWriterService."""

    @pytest.fixture
    def service(self):
        """Create a TimelineEventWriterService instance."""
        return TimelineEventWriterService()

    @pytest.fixture
    def sample_task(self):
        """Create a sample AgentTask entity."""
        return AgentTask(
            id=1,
            request_id="atr_20260316_000001",
            schema_version="v1",
            task_domain=TaskDomain.RESEARCH,
            task_type="macro_portfolio_review",
            status=TaskStatus.DRAFT,
            input_payload={"portfolio_id": 308},
            current_step=None,
            last_error=None,
            requires_human=False,
            created_by=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    # ========== write_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_event_with_enum_types(self, mock_model, service):
        """Test write_event with enum event_type and event_source."""
        mock_event = MagicMock()
        mock_event.id = 123
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_event(
            event_type=TimelineEventType.TASK_CREATED,
            task_id=1,
            event_payload={"test": "data"},
            event_source=EventSource.API,
            request_id="atr_test",
        )

        assert result == 123
        mock_model._default_manager.create.assert_called_once()
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "task_created"
        assert call_kwargs["event_source"] == "api"
        assert call_kwargs["request_id"] == "atr_test"
        assert "request_id" in call_kwargs["event_payload"]

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_event_with_string_types(self, mock_model, service):
        """Test write_event with string event_type and event_source."""
        mock_event = MagicMock()
        mock_event.id = 124
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_event(
            event_type="state_changed",
            task_id=2,
            event_payload={"old": "draft", "new": "completed"},
            event_source="system",
            request_id="atr_test_2",
        )

        assert result == 124
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "state_changed"
        assert call_kwargs["event_source"] == "system"

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_event_with_proposal_and_step(self, mock_model, service):
        """Test write_event with optional proposal_id and step_index."""
        mock_event = MagicMock()
        mock_event.id = 125
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_event(
            event_type=TimelineEventType.STEP_COMPLETED,
            task_id=1,
            event_payload={"step_key": "step_1"},
            event_source=EventSource.SYSTEM,
            request_id="atr_test",
            proposal_id=100,
            step_index=5,
        )

        assert result == 125
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["proposal_id"] == 100
        assert call_kwargs["step_index"] == 5

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_event_handles_exception(self, mock_model, service):
        """Test write_event returns None on exception."""
        mock_model._default_manager.create.side_effect = Exception("DB Error")

        result = service.write_event(
            event_type=TimelineEventType.TASK_CREATED,
            task_id=1,
            event_payload={},
            event_source=EventSource.SYSTEM,
            request_id="atr_test",
        )

        assert result is None

    # ========== write_task_created_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_task_created_event_with_entity(self, mock_model, service, sample_task):
        """Test write_task_created_event with AgentTask entity."""
        mock_event = MagicMock()
        mock_event.id = 200
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_task_created_event(
            task=sample_task,
            event_source=EventSource.API,
            actor={"user_id": 1},
        )

        assert result == 200
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["task_id"] == 1
        assert call_kwargs["request_id"] == "atr_20260316_000001"
        assert call_kwargs["event_type"] == "task_created"
        assert "task_domain" in call_kwargs["event_payload"]
        assert "actor" in call_kwargs["event_payload"]

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_task_created_event_with_task_id(self, mock_model, service):
        """Test write_task_created_event with integer task_id."""
        mock_event = MagicMock()
        mock_event.id = 201
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_task_created_event(
            task=999,
            event_source=EventSource.SYSTEM,
            actor=None,
        )

        assert result == 201
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["task_id"] == 999

    # ========== write_state_changed_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_state_changed_event_with_enums(self, mock_model, service, sample_task):
        """Test write_state_changed_event with TaskStatus enums."""
        mock_event = MagicMock()
        mock_event.id = 300
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_state_changed_event(
            task=sample_task,
            old_status=TaskStatus.DRAFT,
            new_status=TaskStatus.CONTEXT_READY,
            event_source=EventSource.SYSTEM,
            actor={"agent_id": "planner"},
            reason="Context gathered",
        )

        assert result == 300
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "state_changed"
        assert call_kwargs["event_payload"]["old_status"] == "draft"
        assert call_kwargs["event_payload"]["new_status"] == "context_ready"
        assert call_kwargs["event_payload"]["reason"] == "Context gathered"

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_state_changed_event_with_strings(self, mock_model, service):
        """Test write_state_changed_event with string status values."""
        mock_event = MagicMock()
        mock_event.id = 301
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_state_changed_event(
            task=1,
            old_status="draft",
            new_status="completed",
            event_source="api",
        )

        assert result == 301
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_payload"]["old_status"] == "draft"
        assert call_kwargs["event_payload"]["new_status"] == "completed"

    # ========== write_step_started_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_step_started_event(self, mock_model, service, sample_task):
        """Test write_step_started_event."""
        mock_event = MagicMock()
        mock_event.id = 400
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_step_started_event(
            task=sample_task,
            step_key="gather_context",
            step_index=1,
            event_source=EventSource.SYSTEM,
            actor={"agent_id": "researcher"},
        )

        assert result == 400
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "step_started"
        assert call_kwargs["step_index"] == 1
        assert call_kwargs["event_payload"]["step_key"] == "gather_context"

    # ========== write_step_completed_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_step_completed_event(self, mock_model, service, sample_task):
        """Test write_step_completed_event with output data."""
        mock_event = MagicMock()
        mock_event.id = 500
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_step_completed_event(
            task=sample_task,
            step_key="analyze_data",
            step_index=2,
            event_source=EventSource.SYSTEM,
            output={"result": "success", "count": 42},
        )

        assert result == 500
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "step_completed"
        assert call_kwargs["event_payload"]["output"]["result"] == "success"

    # ========== write_step_failed_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_step_failed_event(self, mock_model, service, sample_task):
        """Test write_step_failed_event with error message."""
        mock_event = MagicMock()
        mock_event.id = 600
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_step_failed_event(
            task=sample_task,
            step_key="fetch_data",
            error_message="Connection timeout",
            step_index=3,
            event_source=EventSource.SYSTEM,
        )

        assert result == 600
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "step_failed"
        assert call_kwargs["event_payload"]["error_message"] == "Connection timeout"

    # ========== write_task_resumed_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_task_resumed_event(self, mock_model, service, sample_task):
        """Test write_task_resumed_event."""
        mock_event = MagicMock()
        mock_event.id = 700
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_task_resumed_event(
            task=sample_task,
            reason="Error fixed, retrying",
            event_source=EventSource.HUMAN,
            actor={"user_id": 42},
        )

        assert result == 700
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "task_resumed"
        assert call_kwargs["event_payload"]["reason"] == "Error fixed, retrying"
        assert call_kwargs["event_source"] == "human"

    # ========== write_task_cancelled_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_task_cancelled_event(self, mock_model, service, sample_task):
        """Test write_task_cancelled_event."""
        mock_event = MagicMock()
        mock_event.id = 800
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_task_cancelled_event(
            task=sample_task,
            reason="User requested cancellation",
            event_source=EventSource.API,
            actor={"user_id": 1},
        )

        assert result == 800
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "task_cancelled"
        assert call_kwargs["event_payload"]["reason"] == "User requested cancellation"

    # ========== write_task_escalated_event Tests ==========

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_task_escalated_event(self, mock_model, service, sample_task):
        """Test write_task_escalated_event with escalation target."""
        mock_event = MagicMock()
        mock_event.id = 900
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_task_escalated_event(
            task=sample_task,
            reason="Requires human approval for high-risk trade",
            event_source=EventSource.SYSTEM,
            escalation_target="risk_manager",
        )

        assert result == 900
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert call_kwargs["event_type"] == "task_escalated"
        assert call_kwargs["event_payload"]["reason"] == "Requires human approval for high-risk trade"
        assert call_kwargs["event_payload"]["escalation_target"] == "risk_manager"

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_write_task_escalated_event_without_target(self, mock_model, service, sample_task):
        """Test write_task_escalated_event without escalation target."""
        mock_event = MagicMock()
        mock_event.id = 901
        mock_model._default_manager.create.return_value = mock_event

        result = service.write_task_escalated_event(
            task=sample_task,
            reason="Generic escalation",
            event_source=EventSource.SYSTEM,
        )

        assert result == 901
        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert "escalation_target" not in call_kwargs["event_payload"]


@pytest.mark.django_db
class TestTimelineEventPayloadRequirements:
    """Tests for payload requirements per WP-M1-04."""

    @pytest.fixture
    def service(self):
        """Create a TimelineEventWriterService instance."""
        return TimelineEventWriterService()

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_payload_includes_request_id(self, mock_model, service):
        """Verify all event payloads include request_id."""
        mock_event = MagicMock()
        mock_event.id = 1
        mock_model._default_manager.create.return_value = mock_event

        service.write_event(
            event_type=TimelineEventType.TASK_CREATED,
            task_id=1,
            event_payload={"data": "test"},
            event_source=EventSource.SYSTEM,
            request_id="atr_test_request_id",
        )

        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert "request_id" in call_kwargs["event_payload"]
        assert call_kwargs["event_payload"]["request_id"] == "atr_test_request_id"

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_payload_includes_actor_when_provided(self, mock_model, service):
        """Verify actor is included in payload when provided."""
        mock_event = MagicMock()
        mock_event.id = 2
        mock_model._default_manager.create.return_value = mock_event

        service.write_task_created_event(
            task=1,
            actor={"user_id": 123, "role": "admin"},
        )

        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert "actor" in call_kwargs["event_payload"]
        assert call_kwargs["event_payload"]["actor"]["user_id"] == 123

    @patch("apps.agent_runtime.infrastructure.models.AgentTimelineEventModel")
    def test_payload_excludes_actor_when_not_provided(self, mock_model, service):
        """Verify actor is excluded from payload when not provided."""
        mock_event = MagicMock()
        mock_event.id = 3
        mock_model._default_manager.create.return_value = mock_event

        service.write_task_created_event(
            task=1,
            actor=None,
        )

        call_kwargs = mock_model._default_manager.create.call_args[1]
        assert "actor" not in call_kwargs["event_payload"]


@pytest.mark.django_db
class TestAllEventTypesCovered:
    """Verify all 8 event types from WP-M1-04 are tested."""

    def test_all_event_types_exist(self):
        """Verify all required event types exist in enum."""
        required_types = [
            "task_created",
            "state_changed",
            "step_started",
            "step_completed",
            "step_failed",
            "task_resumed",
            "task_cancelled",
            "task_escalated",
        ]

        for event_type in required_types:
            # Should not raise ValueError
            TimelineEventType(event_type)

    def test_all_event_sources_exist(self):
        """Verify all event sources exist in enum."""
        required_sources = ["api", "sdk", "mcp", "system", "human"]

        for source in required_sources:
            # Should not raise ValueError
            EventSource(source)
