"""
API tests for Agent Runtime Interface layer.

WP-M1-07: Tests (027-030)

FROZEN: Tests verify that only allowed endpoints are exposed.
"""

from datetime import UTC, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient


class TestAgentTaskAPI:
    """Tests for Agent Task API endpoints."""

    @pytest.fixture
    def api_client(self):
        """Create an API client."""
        return APIClient()

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock()
        user.id = 1
        user.is_authenticated = True
        user.is_staff = False
        return user

    @pytest.fixture
    def mock_task_model(self):
        """Create a mock AgentTaskModel."""
        mock = MagicMock()
        mock.id = 1
        mock.request_id = "atr_20260316_000001"
        mock.schema_version = "v1"
        mock.task_domain = "research"
        mock.task_type = "macro_portfolio_review"
        mock.status = "draft"
        mock.input_payload = {"query": "test"}
        mock.current_step = None
        mock.last_error = None
        mock.requires_human = False
        mock.created_by_id = 1
        mock.created_by = MagicMock()
        mock.created_by.username = "test_user"
        mock.created_at = datetime.now(UTC)
        mock.updated_at = datetime.now(UTC)
        # Add relationships
        mock.steps = MagicMock()
        mock.steps.count.return_value = 0
        mock.proposals = MagicMock()
        mock.proposals.count.return_value = 0
        mock.artifacts = MagicMock()
        mock.artifacts.count.return_value = 0
        mock.timeline_events = MagicMock()
        mock.timeline_events.count.return_value = 0
        return mock

    # ========== Health Check Tests ==========

    def test_health_endpoint(self, api_client):
        """Test health check endpoint returns healthy status."""
        url = reverse("agent_runtime:health-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "healthy"
        assert response.data["version"] == "v1"
        assert "timestamp" in response.data

    # ========== Create Task Tests ==========

    @patch("apps.agent_runtime.interface.views.CreateTaskUseCase")
    def test_create_task_success(
        self, mock_use_case_class, api_client, mock_user, mock_task_model
    ):
        """Test successful task creation."""
        # Setup mock
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_20260316_000001"
        mock_task.schema_version = "v1"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "macro_portfolio_review"
        mock_task.status = MagicMock()
        mock_task.status.value = "draft"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = 1
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_20260316_000001"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        # Force authenticate
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        data = {
            "task_domain": "research",
            "task_type": "macro_portfolio_review",
            "input_payload": {"query": "test"},
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert "request_id" in response.data
        assert "task" in response.data

    def test_create_task_invalid_domain(self, api_client, mock_user):
        """Test task creation with invalid domain returns error in FROZEN format."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        data = {
            "task_domain": "invalid_domain",
            "task_type": "test",
            "input_payload": {},
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Verify FROZEN error response format
        assert "request_id" in response.data
        assert "success" in response.data
        assert response.data["success"] is False
        assert "error_code" in response.data
        assert "message" in response.data

    # ========== List Tasks Tests ==========

    @patch("apps.agent_runtime.interface.views.ListTasksUseCase")
    def test_list_tasks_success(
        self, mock_use_case_class, api_client, mock_user, mock_task_model
    ):
        """Test successful task listing."""
        # Setup mock
        mock_use_case = MagicMock()
        mock_output = MagicMock()
        mock_output.tasks = []
        mock_output.total_count = 0
        mock_output.request_id = "atr_20260316_000002"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "request_id" in response.data
        assert "tasks" in response.data
        assert "total_count" in response.data

    # ========== Get Task Tests ==========

    @patch("apps.agent_runtime.interface.views.GetTaskUseCase")
    def test_get_task_success(
        self, mock_use_case_class, api_client, mock_user, mock_task_model
    ):
        """Test successful task retrieval."""
        # Setup mock use case
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_20260316_000001"
        mock_task.schema_version = "v1"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "macro_portfolio_review"
        mock_task.status = MagicMock()
        mock_task.status.value = "draft"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = 1
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_20260316_000001"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["request_id"] == "atr_20260316_000001"

    def test_get_task_not_found(self, api_client, mock_user):
        """Test task retrieval when task doesn't exist returns FROZEN error format."""
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        api_client.force_authenticate(user=mock_user)

        with patch(
            "apps.agent_runtime.interface.views.GetTaskUseCase"
        ) as mock_use_case_class:
            mock_use_case = MagicMock()
            mock_use_case.execute.side_effect = AgentTaskModel.DoesNotExist
            mock_use_case_class.return_value = mock_use_case

            url = reverse("agent_runtime:task-detail", kwargs={"pk": 999})
            response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        # Verify FROZEN error response format
        assert "request_id" in response.data
        assert "success" in response.data
        assert response.data["success"] is False
        assert "error_code" in response.data
        assert response.data["error_code"] == "not_found"
        assert "message" in response.data

    # ========== FORBIDDEN PATHS TESTS (Requirement #6) ==========

    def test_put_task_is_forbidden(self, api_client, mock_user):
        """Test that PUT /tasks/{id}/ is forbidden (405 Method Not Allowed)."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.put(url, {"status": "completed"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        # Verify FROZEN error response format
        assert "request_id" in response.data
        assert "success" in response.data
        assert response.data["success"] is False
        assert "error_code" in response.data
        assert response.data["error_code"] == "method_not_allowed"
        assert "Use /resume or /cancel" in response.data["message"]

    def test_patch_task_is_forbidden(self, api_client, mock_user):
        """Test that PATCH /tasks/{id}/ is forbidden (405 Method Not Allowed)."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.patch(url, {"status": "completed"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        # Verify FROZEN error response format
        assert "request_id" in response.data
        assert "success" in response.data
        assert response.data["success"] is False
        assert "error_code" in response.data
        assert response.data["error_code"] == "method_not_allowed"

    def test_delete_task_is_forbidden(self, api_client, mock_user):
        """Test that DELETE /tasks/{id}/ is forbidden (405 Method Not Allowed)."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        # Verify FROZEN error response format
        assert "request_id" in response.data
        assert "success" in response.data
        assert response.data["success"] is False
        assert "error_code" in response.data
        assert response.data["error_code"] == "method_not_allowed"
        assert "Task deletion is not allowed" in response.data["message"]

    # ========== Cancel Task Tests ==========

    def test_cancel_task_missing_reason(self, api_client, mock_user, mock_task_model):
        """Test task cancellation without reason returns FROZEN error format."""
        api_client.force_authenticate(user=mock_user)

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.filter"
        ) as mock_filter:
            mock_queryset = MagicMock()
            mock_queryset.first.return_value = mock_task_model
            mock_filter.return_value = mock_queryset

            url = reverse("agent_runtime:task-cancel", kwargs={"pk": 1})
            response = api_client.post(url, {})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Verify FROZEN error response format
        assert "request_id" in response.data
        assert "success" in response.data
        assert response.data["success"] is False
        assert "error_code" in response.data
        assert response.data["error_code"] == "validation_error"
        assert "reason" in response.data["message"].lower()

    # ========== Resume Task Tests ==========

    @patch("apps.agent_runtime.interface.views.ResumeTaskUseCase")
    def test_resume_task_success(
        self, mock_use_case_class, api_client, mock_user, mock_task_model
    ):
        """Test successful task resume."""
        # Setup mock use case
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_test"
        mock_task.schema_version = "v1"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "macro_portfolio_review"
        mock_task.status = MagicMock()
        mock_task.status.value = "draft"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = 1
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_test"
        mock_output.timeline_event_id = 124
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.filter"
        ) as mock_filter:
            mock_queryset = MagicMock()
            mock_queryset.only.return_value = mock_filter.return_value
            mock_queryset.first.return_value = mock_task_model
            mock_filter.return_value = mock_queryset

            url = reverse("agent_runtime:task-resume", kwargs={"pk": 1})
            response = api_client.post(url, {"reason": "Fixed the issue"})

        assert response.status_code == status.HTTP_200_OK

    # ========== Timeline Tests ==========

    def test_get_task_timeline(self, api_client, mock_user, mock_task_model):
        """Test getting task timeline."""
        from apps.agent_runtime.interface.views import AgentTaskViewSet

        api_client.force_authenticate(user=mock_user)

        with patch.object(
            AgentTaskViewSet, "get_object", return_value=mock_task_model
        ):
            with patch(
                "apps.agent_runtime.interface.views.AgentTimelineEventModel._default_manager.filter"
            ) as mock_event_filter:
                mock_event_queryset = MagicMock()
                mock_event_queryset.order_by.return_value = mock_event_queryset
                mock_event_filter.return_value = mock_event_queryset

                url = reverse("agent_runtime:task-timeline", kwargs={"pk": 1})
                response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "request_id" in response.data
        assert "events" in response.data

    # ========== Needs Attention Tests ==========

    def test_needs_attention_endpoint(self, api_client, mock_user):
        """Test needs attention endpoint."""
        from apps.agent_runtime.interface.views import AgentTaskViewSet

        api_client.force_authenticate(user=mock_user)

        # The view chains: get_queryset().filter() | get_queryset().filter()
        # then .distinct().order_by()[:limit]
        mock_filtered = MagicMock()
        mock_filtered.__or__ = MagicMock(return_value=mock_filtered)
        mock_filtered.distinct.return_value = mock_filtered
        mock_filtered.order_by.return_value = mock_filtered
        mock_filtered.count.return_value = 0
        mock_filtered.__getitem__ = lambda self, key: mock_filtered
        mock_filtered.__iter__ = lambda self: iter([])

        mock_queryset = MagicMock()
        mock_queryset.filter.return_value = mock_filtered

        with patch.object(
            AgentTaskViewSet, "get_queryset", return_value=mock_queryset
        ):
            url = reverse("agent_runtime:task-needs-attention")
            response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert "request_id" in response.data
        assert "tasks" in response.data

    # ========== Cancel Task Success Test ==========

    @patch("apps.agent_runtime.interface.views.CancelTaskUseCase")
    def test_cancel_task_success(
        self, mock_use_case_class, api_client, mock_user, mock_task_model
    ):
        """Test successful task cancellation."""
        # Setup mock use case
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_test"
        mock_task.schema_version = "v1"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "test"
        mock_task.status = MagicMock()
        mock_task.status.value = "cancelled"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = 1
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_test"
        mock_output.timeline_event_id = 125
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.filter"
        ) as mock_filter:
            mock_queryset = MagicMock()
            mock_queryset.only.return_value = mock_filter.return_value
            mock_queryset.first.return_value = mock_task_model
            mock_filter.return_value = mock_queryset

            url = reverse("agent_runtime:task-cancel", kwargs={"pk": 1})
            response = api_client.post(url, {"reason": "No longer needed"})

        assert response.status_code == status.HTTP_200_OK

    # ========== List Tasks With Filters Tests ==========

    @patch("apps.agent_runtime.interface.views.ListTasksUseCase")
    def test_list_tasks_with_status_filter(
        self, mock_use_case_class, api_client, mock_user
    ):
        """Test task listing with status filter."""
        mock_use_case = MagicMock()
        mock_output = MagicMock()
        mock_output.tasks = []
        mock_output.total_count = 0
        mock_output.request_id = "atr_filter_test"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        response = api_client.get(url, {"status": "draft"})

        assert response.status_code == status.HTTP_200_OK
        assert "tasks" in response.data

    @patch("apps.agent_runtime.interface.views.ListTasksUseCase")
    def test_list_tasks_with_domain_filter(
        self, mock_use_case_class, api_client, mock_user
    ):
        """Test task listing with domain filter."""
        mock_use_case = MagicMock()
        mock_output = MagicMock()
        mock_output.tasks = []
        mock_output.total_count = 0
        mock_output.request_id = "atr_domain_filter"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        response = api_client.get(url, {"task_domain": "research"})

        assert response.status_code == status.HTTP_200_OK
        assert "tasks" in response.data

    @patch("apps.agent_runtime.interface.views.ListTasksUseCase")
    def test_list_tasks_pagination(
        self, mock_use_case_class, api_client, mock_user
    ):
        """Test task listing pagination."""
        mock_use_case = MagicMock()
        mock_output = MagicMock()
        mock_output.tasks = []
        mock_output.total_count = 100
        mock_output.request_id = "atr_paginated"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        response = api_client.get(url, {"limit": 10, "offset": 20})

        assert response.status_code == status.HTTP_200_OK
        assert response.data["total_count"] == 100

    # ========== Resume Task Validation Tests ==========

    def test_resume_task_from_non_resumable_state(
        self, api_client, mock_user, mock_task_model
    ):
        """Test that resuming from non-resumable state returns error."""
        from apps.agent_runtime.domain.services import InvalidStateTransitionError

        api_client.force_authenticate(user=mock_user)

        with patch(
            "apps.agent_runtime.interface.views.ResumeTaskUseCase"
        ) as mock_use_case_class:
            mock_use_case = MagicMock()
            mock_use_case.execute.side_effect = InvalidStateTransitionError(
                current_status="draft",
                target_status="draft",
                allowed_transitions=["context_ready"],
            )
            mock_use_case_class.return_value = mock_use_case

            url = reverse("agent_runtime:task-resume", kwargs={"pk": 1})
            response = api_client.post(url, {"reason": "Try to resume"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False
        assert "error_code" in response.data

    # ========== Create Task Validation Tests ==========

    def test_create_task_missing_required_fields(self, api_client, mock_user):
        """Test task creation with missing required fields."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        # Missing task_type which is required
        data = {
            "task_domain": "research",
            "input_payload": {},
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False

    def test_create_task_empty_task_type(self, api_client, mock_user):
        """Test task creation with empty task_type."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        data = {
            "task_domain": "research",
            "task_type": "",  # Empty string
            "input_payload": {},
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # ========== Authentication Tests ==========

    def test_unauthenticated_access_denied(self, api_client):
        """Test that unauthenticated access is denied."""
        url = reverse("agent_runtime:task-list")
        response = api_client.get(url)

        # Should return 401 or 403
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_unauthenticated_create_denied(self, api_client):
        """Test that unauthenticated task creation is denied."""
        url = reverse("agent_runtime:task-list")
        data = {
            "task_domain": "research",
            "task_type": "test",
            "input_payload": {},
        }
        response = api_client.post(url, data, format="json")

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    # ========== Error Response Format Tests ==========

    def test_error_response_format_matches_contract(self, api_client, mock_user):
        """Test that all error responses match FROZEN error contract."""
        from apps.agent_runtime.infrastructure.models import AgentTaskModel

        api_client.force_authenticate(user=mock_user)

        # Try to get non-existent task
        with patch(
            "apps.agent_runtime.interface.views.GetTaskUseCase"
        ) as mock_use_case_class:
            mock_use_case = MagicMock()
            mock_use_case.execute.side_effect = AgentTaskModel.DoesNotExist
            mock_use_case_class.return_value = mock_use_case

            url = reverse("agent_runtime:task-detail", kwargs={"pk": 999})
            response = api_client.get(url)

        # Verify FROZEN error contract format (schema-contract.md:151)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.data

        # Required fields
        assert "request_id" in data
        assert "success" in data
        assert data["success"] is False
        assert "error_code" in data
        assert "message" in data

        # Optional fields
        if "details" in data:
            assert isinstance(data["details"], dict)
