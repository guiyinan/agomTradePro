"""
Unit Tests for M4 WP-M4-02: Handoff Use Case.

Tests verify handoff payload structure and timeline event creation.
"""

import pytest
from unittest.mock import patch, MagicMock

from apps.agent_runtime.application.handoff_use_cases import (
    HandoffTaskUseCase,
    HandoffInput,
    HandoffOutput,
)


@pytest.mark.django_db
class TestHandoffUseCase:
    """Integration tests for handoff behavior with real DB."""

    @pytest.fixture
    def task_model(self):
        from apps.agent_runtime.infrastructure.models import AgentTaskModel
        return AgentTaskModel._default_manager.create(
            request_id="atr_test_handoff",
            task_domain="research",
            task_type="macro_review",
            status="needs_human",
            input_payload={"focus": "regime"},
        )

    def test_handoff_creates_record(self, task_model):
        from apps.agent_runtime.infrastructure.models import AgentHandoffModel

        use_case = HandoffTaskUseCase()
        output = use_case.execute(HandoffInput(
            task_id=task_model.id,
            to_agent="human_operator",
            handoff_reason="Needs domain expertise",
            open_risks=["macro data may be stale"],
            actor={"user_id": 1, "agent_id": "research_agent"},
        ))

        assert output.handoff_id is not None
        assert output.request_id == task_model.request_id

        # Verify record in DB
        handoff = AgentHandoffModel._default_manager.get(pk=output.handoff_id)
        assert handoff.to_agent == "human_operator"
        assert handoff.from_agent == "research_agent"
        assert handoff.handoff_status == "completed"

    def test_handoff_payload_has_required_fields(self, task_model):
        use_case = HandoffTaskUseCase()
        output = use_case.execute(HandoffInput(
            task_id=task_model.id,
            to_agent="human_operator",
            handoff_reason="Test reason",
        ))

        payload = output.handoff_payload
        assert "current_status" in payload
        assert "task_domain" in payload
        assert "task_type" in payload
        assert "completed_steps" in payload
        assert "pending_steps" in payload
        assert "latest_context_reference" in payload
        assert "open_proposals" in payload
        assert "open_risks" in payload
        assert "recommended_next_actor" in payload

    def test_handoff_captures_current_status(self, task_model):
        use_case = HandoffTaskUseCase()
        output = use_case.execute(HandoffInput(
            task_id=task_model.id,
            to_agent="ops_team",
            handoff_reason="Escalation",
        ))

        assert output.handoff_payload["current_status"] == "needs_human"
        assert output.handoff_payload["recommended_next_actor"] == "ops_team"

    def test_handoff_creates_timeline_event(self, task_model):
        from apps.agent_runtime.infrastructure.models import AgentTimelineEventModel

        use_case = HandoffTaskUseCase()
        use_case.execute(HandoffInput(
            task_id=task_model.id,
            to_agent="human_operator",
            handoff_reason="Escalation",
        ))

        events = AgentTimelineEventModel._default_manager.filter(
            task_id=task_model.id,
            event_type="task_escalated",
        )
        assert events.count() == 1
        assert "Escalation" in events.first().event_payload.get("reason", "")

    def test_handoff_includes_open_risks(self, task_model):
        use_case = HandoffTaskUseCase()
        output = use_case.execute(HandoffInput(
            task_id=task_model.id,
            to_agent="human",
            handoff_reason="Risk",
            open_risks=["regime shift", "data lag"],
        ))

        assert output.handoff_payload["open_risks"] == ["regime shift", "data lag"]

    def test_handoff_with_steps(self, task_model):
        from apps.agent_runtime.infrastructure.models import AgentTaskStepModel

        # Create some steps
        AgentTaskStepModel._default_manager.create(
            request_id=task_model.request_id,
            task=task_model,
            step_key="fetch_macro",
            step_name="Fetch Macro Data",
            step_index=0,
            status="completed",
        )
        AgentTaskStepModel._default_manager.create(
            request_id=task_model.request_id,
            task=task_model,
            step_key="analyze_regime",
            step_name="Analyze Regime",
            step_index=1,
            status="pending",
        )

        use_case = HandoffTaskUseCase()
        output = use_case.execute(HandoffInput(
            task_id=task_model.id,
            to_agent="human",
            handoff_reason="Review",
        ))

        assert len(output.handoff_payload["completed_steps"]) == 1
        assert output.handoff_payload["completed_steps"][0]["step_key"] == "fetch_macro"
        assert len(output.handoff_payload["pending_steps"]) == 1
        assert output.handoff_payload["pending_steps"][0]["step_key"] == "analyze_regime"
