"""
M4 WP-M4-04: Regression Suite.

Validates that all prior milestones remain intact.
Organized into CI groups via pytest markers.

CI groups:
- agent_runtime_unit: Domain logic, state machine, guardrails, failure classifier
- agent_runtime_api: Route registration, error contract
- agent_runtime_sdk: SDK module endpoint contracts
- agent_runtime_mcp: MCP tool/resource/prompt registration
- agent_runtime_e2e: End-to-end workflows
"""

import asyncio
import pytest
from unittest.mock import MagicMock


# ── agent_runtime_unit: Domain invariants ─────────────────────

@pytest.mark.agent_runtime_unit
class TestDomainInvariants:
    """Verify domain entities and enums are intact across milestones."""

    def test_task_status_values(self):
        from apps.agent_runtime.domain.entities import TaskStatus
        expected = {
            "draft", "context_ready", "proposal_generated",
            "awaiting_approval", "approved", "rejected",
            "executing", "completed", "failed", "needs_human", "cancelled",
        }
        assert {s.value for s in TaskStatus} == expected

    def test_proposal_status_values(self):
        from apps.agent_runtime.domain.entities import ProposalStatus
        expected = {
            "draft", "generated", "submitted", "approved",
            "rejected", "executed", "execution_failed", "expired",
        }
        assert {s.value for s in ProposalStatus} == expected

    def test_guardrail_decision_values(self):
        from apps.agent_runtime.domain.entities import GuardrailDecision
        expected = {"allowed", "blocked", "needs_human", "degraded_mode"}
        assert {d.value for d in GuardrailDecision} == expected

    def test_failure_type_values(self):
        from apps.agent_runtime.domain.failure_classifier import FailureType
        expected = {
            "validation_error", "dependency_unavailable", "data_stale",
            "authorization_blocked", "execution_failure", "unknown_system_error",
        }
        assert {f.value for f in FailureType} == expected

    def test_task_domain_values(self):
        from apps.agent_runtime.domain.entities import TaskDomain
        expected = {"research", "monitoring", "decision", "execution", "ops"}
        assert {d.value for d in TaskDomain} == expected

    def test_state_machine_happy_path(self):
        from apps.agent_runtime.domain.services import get_task_state_machine
        sm = get_task_state_machine()
        assert sm.can_transition("draft", "context_ready")
        assert sm.can_transition("approved", "executing")
        assert sm.can_transition("executing", "completed")
        assert not sm.can_transition("completed", "draft")

    def test_guardrail_engine_exists(self):
        from apps.agent_runtime.domain.guardrails import get_guardrail_engine
        engine = get_guardrail_engine()
        assert engine is not None

    def test_high_risk_types_non_empty(self):
        from apps.agent_runtime.domain.guardrails import HIGH_RISK_PROPOSAL_TYPES
        assert len(HIGH_RISK_PROPOSAL_TYPES) >= 5


# ── agent_runtime_api: Route registration ─────────────────────

@pytest.mark.agent_runtime_api
class TestRouteRegistration:
    """Verify API routes are registered and no drift occurred."""

    @pytest.fixture(autouse=True)
    def _resolve(self):
        from django.urls import resolve, reverse, NoReverseMatch
        self.resolve = resolve
        self.reverse = reverse
        self.NoReverseMatch = NoReverseMatch

    def test_task_list_route(self):
        url = self.reverse("agent_runtime:task-list")
        assert "/tasks/" in url

    def test_task_detail_route(self):
        url = self.reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        assert "/tasks/1/" in url

    def test_task_resume_route(self):
        url = self.reverse("agent_runtime:task-resume", kwargs={"pk": 1})
        assert "/tasks/1/resume/" in url

    def test_task_cancel_route(self):
        url = self.reverse("agent_runtime:task-cancel", kwargs={"pk": 1})
        assert "/tasks/1/cancel/" in url

    def test_task_handoff_route(self):
        url = self.reverse("agent_runtime:task-handoff", kwargs={"pk": 1})
        assert "/tasks/1/handoff/" in url

    def test_task_timeline_route(self):
        url = self.reverse("agent_runtime:task-timeline", kwargs={"pk": 1})
        assert "/tasks/1/timeline/" in url

    def test_proposal_list_route(self):
        url = self.reverse("agent_runtime:proposal-list")
        assert "/proposals/" in url

    def test_proposal_approve_route(self):
        url = self.reverse("agent_runtime:proposal-approve", kwargs={"pk": 1})
        assert "/proposals/1/approve/" in url

    def test_proposal_reject_route(self):
        url = self.reverse("agent_runtime:proposal-reject", kwargs={"pk": 1})
        assert "/proposals/1/reject/" in url

    def test_proposal_execute_route(self):
        url = self.reverse("agent_runtime:proposal-execute", kwargs={"pk": 1})
        assert "/proposals/1/execute/" in url

    def test_context_research_route(self):
        url = self.reverse("agent_runtime:context-research")
        assert "context" in url and "research" in url

    def test_health_route(self):
        url = self.reverse("agent_runtime:health-list")
        assert "/health/" in url

    def test_dashboard_summary_route(self):
        url = self.reverse("agent_runtime:dashboard-summary")
        assert "dashboard" in url and "summary" in url


# ── agent_runtime_sdk: SDK module contracts ───────────────────

@pytest.mark.agent_runtime_sdk
class TestSDKContracts:
    """Verify SDK modules have all required methods."""

    def test_agent_runtime_module_methods(self):
        from sdk.agomsaaf.modules.agent_runtime import AgentRuntimeModule
        client = MagicMock()
        mod = AgentRuntimeModule(client)
        assert hasattr(mod, "create_task")
        assert hasattr(mod, "get_task")
        assert hasattr(mod, "list_tasks")
        assert hasattr(mod, "resume_task")
        assert hasattr(mod, "cancel_task")
        assert hasattr(mod, "get_task_timeline")
        assert hasattr(mod, "get_task_artifacts")
        assert hasattr(mod, "get_needs_attention")

    def test_agent_context_module_methods(self):
        from sdk.agomsaaf.modules.agent_context import AgentContextModule
        client = MagicMock()
        mod = AgentContextModule(client)
        assert hasattr(mod, "get_context_snapshot")
        assert hasattr(mod, "get_research_context")
        assert hasattr(mod, "get_monitoring_context")
        assert hasattr(mod, "get_decision_context")
        assert hasattr(mod, "get_execution_context")
        assert hasattr(mod, "get_ops_context")

    def test_agent_proposal_module_methods(self):
        from sdk.agomsaaf.modules.agent_proposal import AgentProposalModule
        client = MagicMock()
        mod = AgentProposalModule(client)
        assert hasattr(mod, "create_proposal")
        assert hasattr(mod, "get_proposal")
        assert hasattr(mod, "submit_proposal_for_approval")
        assert hasattr(mod, "approve_proposal")
        assert hasattr(mod, "reject_proposal")
        assert hasattr(mod, "execute_proposal")


# ── agent_runtime_mcp: MCP registration ──────────────────────

@pytest.mark.agent_runtime_mcp
class TestMCPRegistration:
    """Verify all MCP tools/resources/prompts remain registered."""

    @pytest.fixture(autouse=True)
    def _tool_names(self):
        from agomsaaf_mcp.server import server
        loop = asyncio.new_event_loop()
        try:
            tools = loop.run_until_complete(server.list_tools())
        finally:
            loop.close()
        self.tool_names = {t.name for t in tools}

    # M2 task tools
    def test_m2_start_research_task(self):
        assert "start_research_task" in self.tool_names

    def test_m2_resume_agent_task(self):
        assert "resume_agent_task" in self.tool_names

    def test_m2_cancel_agent_task(self):
        assert "cancel_agent_task" in self.tool_names

    # M3 proposal tools
    def test_m3_create_agent_proposal(self):
        assert "create_agent_proposal" in self.tool_names

    def test_m3_approve_agent_proposal(self):
        assert "approve_agent_proposal" in self.tool_names

    def test_m3_reject_agent_proposal(self):
        assert "reject_agent_proposal" in self.tool_names

    def test_m3_execute_agent_proposal(self):
        assert "execute_agent_proposal" in self.tool_names
