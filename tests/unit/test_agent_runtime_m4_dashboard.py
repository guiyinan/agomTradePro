"""
Unit Tests for M4 WP-M4-01: Operator Dashboard API.

Tests verify the dashboard views return structured data.
"""


import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.agent_runtime.interface.views import OperatorDashboardViewSet


@pytest.mark.django_db
class TestOperatorDashboard:
    """Integration tests for operator dashboard views."""

    @pytest.fixture
    def factory(self):
        return APIRequestFactory()

    @pytest.fixture
    def staff_user(self):
        from django.contrib.auth.models import User
        return User.objects.create_user(
            username="dashboard_staff",
            password="test",
            is_staff=True,
        )

    @pytest.fixture
    def task_with_data(self, staff_user):
        from apps.agent_runtime.infrastructure.models import (
            AgentProposalModel,
            AgentTaskModel,
            AgentTimelineEventModel,
        )

        task = AgentTaskModel._default_manager.create(
            request_id="atr_dashboard_test",
            task_domain="research",
            task_type="test",
            status="draft",
            input_payload={},
            created_by=staff_user,
        )

        AgentTimelineEventModel._default_manager.create(
            request_id=task.request_id,
            task=task,
            event_type="task_created",
            event_source="api",
            event_payload={},
        )

        AgentProposalModel._default_manager.create(
            request_id="apr_dashboard_test",
            task=task,
            proposal_type="signal_create",
            status="generated",
            risk_level="medium",
            proposal_payload={},
        )

        return task

    def test_summary_returns_counts(self, factory, staff_user, task_with_data):
        view = OperatorDashboardViewSet.as_view({"get": "summary"})
        request = factory.get("/api/agent-runtime/dashboard/summary/")
        force_authenticate(request, user=staff_user)
        response = view(request)

        assert response.status_code == 200
        data = response.data
        assert "request_id" in data
        assert "task_counts_by_status" in data
        assert "proposal_counts_by_status" in data
        assert "needs_attention_count" in data
        assert "total_tasks" in data
        assert data["total_tasks"] >= 1

    def test_task_detail_returns_full_view(self, factory, staff_user, task_with_data):
        view = OperatorDashboardViewSet.as_view({"get": "task_detail"})
        request = factory.get(f"/api/agent-runtime/dashboard/task/{task_with_data.id}/")
        force_authenticate(request, user=staff_user)
        response = view(request, task_id=str(task_with_data.id))

        assert response.status_code == 200
        data = response.data
        assert "task" in data
        assert "timeline" in data
        assert "proposals" in data
        assert "guardrail_decisions" in data
        assert "execution_records" in data
        assert len(data["timeline"]) >= 1
        assert len(data["proposals"]) >= 1

    def test_task_detail_not_found(self, factory, staff_user):
        view = OperatorDashboardViewSet.as_view({"get": "task_detail"})
        request = factory.get("/api/agent-runtime/dashboard/task/99999/")
        force_authenticate(request, user=staff_user)
        response = view(request, task_id="99999")

        assert response.status_code == 404

    def test_proposals_returns_list(self, factory, staff_user, task_with_data):
        view = OperatorDashboardViewSet.as_view({"get": "proposals"})
        request = factory.get("/api/agent-runtime/dashboard/proposals/")
        force_authenticate(request, user=staff_user)
        response = view(request)

        assert response.status_code == 200
        assert "proposals" in response.data
        assert "total_count" in response.data
        assert response.data["total_count"] >= 1

    def test_proposals_filter_by_status(self, factory, staff_user, task_with_data):
        view = OperatorDashboardViewSet.as_view({"get": "proposals"})
        request = factory.get("/api/agent-runtime/dashboard/proposals/?status=generated")
        force_authenticate(request, user=staff_user)
        response = view(request)

        assert response.status_code == 200
        for p in response.data["proposals"]:
            assert p["status"] == "generated"

    def test_guardrails_returns_list(self, factory, staff_user):
        view = OperatorDashboardViewSet.as_view({"get": "guardrails"})
        request = factory.get("/api/agent-runtime/dashboard/guardrails/")
        force_authenticate(request, user=staff_user)
        response = view(request)

        assert response.status_code == 200
        assert "guardrail_decisions" in response.data

    def test_executions_returns_list(self, factory, staff_user):
        view = OperatorDashboardViewSet.as_view({"get": "executions"})
        request = factory.get("/api/agent-runtime/dashboard/executions/")
        force_authenticate(request, user=staff_user)
        response = view(request)

        assert response.status_code == 200
        assert "execution_records" in response.data

    def test_non_staff_user_denied(self, factory):
        """Non-staff, non-operator user cannot access dashboard."""
        from django.contrib.auth.models import User
        regular_user = User.objects.create_user(
            username="dashboard_regular",
            password="test",
            is_staff=False,
        )
        view = OperatorDashboardViewSet.as_view({"get": "summary"})
        request = factory.get("/api/agent-runtime/dashboard/summary/")
        force_authenticate(request, user=regular_user)
        response = view(request)

        assert response.status_code == 403

    def test_operator_group_allowed(self, factory):
        """User in 'operator' group can access dashboard."""
        from django.contrib.auth.models import Group, User
        operator_group, _ = Group.objects.get_or_create(name="operator")
        op_user = User.objects.create_user(
            username="dashboard_operator",
            password="test",
            is_staff=False,
        )
        op_user.groups.add(operator_group)

        view = OperatorDashboardViewSet.as_view({"get": "summary"})
        request = factory.get("/api/agent-runtime/dashboard/summary/")
        force_authenticate(request, user=op_user)
        response = view(request)

        assert response.status_code == 200

    def test_needs_attention_no_double_count(self, factory, staff_user):
        """Verify needs_attention_count does not double-count tasks."""
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        # Task with BOTH requires_human=True AND status=needs_human
        AgentTaskModel._default_manager.create(
            request_id="atr_double_count_test",
            task_domain="research",
            task_type="test",
            status="needs_human",
            input_payload={},
            requires_human=True,
            created_by=staff_user,
        )

        view = OperatorDashboardViewSet.as_view({"get": "summary"})
        request = factory.get("/api/agent-runtime/dashboard/summary/")
        force_authenticate(request, user=staff_user)
        response = view(request)

        # The single task should be counted exactly once
        assert response.data["needs_attention_count"] == 1
