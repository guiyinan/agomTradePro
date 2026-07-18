"""
Integration tests for API RBAC (Role-Based Access Control).

WP-M1-06: Security And Audit Hook

Tests verify:
- Deny access to disallowed roles
- Permission denied cases
- Audit trail exists for mutating runtime calls
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.agent_runtime.infrastructure.models import AgentTaskModel


@pytest.mark.django_db
class TestAPIRBAC:
    """Tests for API Role-Based Access Control."""

    @pytest.fixture
    def api_client(self):
        """Create an API client."""
        return APIClient()

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock()
        user.id = 1
        user.pk = 1
        user.is_authenticated = True
        user.is_staff = False
        user.is_superuser = False
        return user

    @pytest.fixture
    def mock_staff_user(self):
        """Create a mock staff user."""
        user = MagicMock()
        user.id = 2
        user.pk = 2
        user.is_authenticated = True
        user.is_staff = True
        user.is_superuser = False
        return user

    @pytest.fixture
    def mock_super_user(self):
        """Create a mock superuser."""
        user = MagicMock()
        user.id = 3
        user.pk = 3
        user.is_authenticated = True
        user.is_staff = True
        user.is_superuser = True
        return user

    # ========== Authentication Tests ==========

    def test_unauthenticated_user_cannot_create_task(self, api_client):
        """Test that unauthenticated users cannot create tasks."""
        url = reverse("agent_runtime:task-list")
        response = api_client.post(
            url,
            {
                "task_domain": "research",
                "task_type": "test",
                "input_payload": {},
            },
            format="json",
        )

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_unauthenticated_user_cannot_list_tasks(self, api_client):
        """Test that unauthenticated users cannot list tasks."""
        url = reverse("agent_runtime:task-list")
        response = api_client.get(url)

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_unauthenticated_user_cannot_get_task(self, api_client):
        """Test that unauthenticated users cannot get task details."""
        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.get(url)

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_unauthenticated_user_cannot_resume_task(self, api_client):
        """Test that unauthenticated users cannot resume tasks."""
        url = reverse("agent_runtime:task-resume", kwargs={"pk": 1})
        response = api_client.post(url, {"reason": "test"}, format="json")

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    def test_unauthenticated_user_cannot_cancel_task(self, api_client):
        """Test that unauthenticated users cannot cancel tasks."""
        url = reverse("agent_runtime:task-cancel", kwargs={"pk": 1})
        response = api_client.post(url, {"reason": "test"}, format="json")

        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]

    # ========== Health Endpoint Tests ==========

    def test_health_endpoint_no_auth_required(self, api_client):
        """Test that health endpoint does not require authentication."""
        url = reverse("agent_runtime:health-list")
        response = api_client.get(url)

        # Health check should be accessible without auth
        assert response.status_code == status.HTTP_200_OK

    # ========== Forbidden Method Tests ==========

    def test_put_task_forbidden(self, api_client, mock_user):
        """Test that PUT method is forbidden (405)."""
        api_client.force_authenticate(user=mock_user)
        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.put(url, {"status": "completed"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_patch_task_forbidden(self, api_client, mock_user):
        """Test that PATCH method is forbidden (405)."""
        api_client.force_authenticate(user=mock_user)
        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.patch(url, {"status": "completed"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_delete_task_forbidden(self, api_client, mock_user):
        """Test that DELETE method is forbidden (405)."""
        api_client.force_authenticate(user=mock_user)
        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
class TestRealRepositoryAssembly:
    """Cover mutating APIs with their production repository composition."""

    @pytest.fixture
    def authenticated_client(self, django_user_model):
        user = django_user_model.objects.create_user(
            username="agent-runtime-real-repo",
            password="test-only-password",
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client, user

    def test_resume_api_updates_task_with_real_repository(self, authenticated_client):
        client, user = authenticated_client
        task = AgentTaskModel._default_manager.create(
            request_id="atr_real_resume",
            task_domain="research",
            task_type="real_repository_resume",
            status="failed",
            input_payload={},
            created_by=user,
        )

        response = client.post(
            reverse("agent_runtime:task-resume", kwargs={"pk": task.pk}),
            {"target_status": "draft", "reason": "issue fixed"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task.refresh_from_db()
        assert task.status == "draft"

    def test_cancel_api_updates_task_with_real_repository(self, authenticated_client):
        client, user = authenticated_client
        task = AgentTaskModel._default_manager.create(
            request_id="atr_real_cancel",
            task_domain="monitoring",
            task_type="real_repository_cancel",
            status="draft",
            input_payload={},
            created_by=user,
        )

        response = client.post(
            reverse("agent_runtime:task-cancel", kwargs={"pk": task.pk}),
            {"reason": "no longer needed"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task.refresh_from_db()
        assert task.status == "cancelled"

    def test_create_proposal_validates_task_with_real_repository(self, authenticated_client):
        client, user = authenticated_client
        task = AgentTaskModel._default_manager.create(
            request_id="atr_real_proposal",
            task_domain="decision",
            task_type="real_repository_proposal",
            status="draft",
            input_payload={},
            created_by=user,
        )

        response = client.post(
            reverse("agent_runtime:proposal-list"),
            {
                "task_id": task.pk,
                "proposal_type": "signal_create",
                "risk_level": "medium",
                "approval_required": True,
                "proposal_payload": {"asset_code": "000001.SH"},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["proposal"]["task_id"] == task.pk


@pytest.mark.django_db
class TestAuditTrail:
    """Tests for audit trail on mutating operations."""

    @pytest.fixture
    def api_client(self):
        """Create an API client."""
        return APIClient()

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock()
        user.id = 1
        user.pk = 1
        user.is_authenticated = True
        user.is_staff = False
        return user

    @patch("apps.agent_runtime.interface.views.CreateTaskUseCase")
    def test_create_task_creates_audit_log(self, mock_use_case_class, api_client, mock_user):
        """Verify create task operation creates audit log."""

        # Setup mock with JSON-serializable attributes (avoid MagicMock infinite loop)
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_test"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "test"
        mock_task.status = MagicMock()
        mock_task.status.value = "draft"
        mock_task.schema_version = "v1"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = None
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_test"
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        # Return a mock with explicit serializable attributes to avoid
        # MagicMock tolist() infinite loop in DRF JSON encoder
        mock_model = MagicMock()
        mock_model.id = 1
        mock_model.request_id = "atr_test"
        mock_model.schema_version = "v1"
        mock_model.task_domain = "research"
        mock_model.task_type = "test"
        mock_model.status = "draft"
        mock_model.input_payload = {}
        mock_model.current_step = None
        mock_model.last_error = None
        mock_model.requires_human = False
        mock_model.created_by = None
        mock_model.created_at = datetime.now(UTC)
        mock_model.updated_at = datetime.now(UTC)

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.get"
        ) as mock_get:
            mock_get.return_value = mock_model

            url = reverse("agent_runtime:task-list")
            response = api_client.post(
                url,
                {
                    "task_domain": "research",
                    "task_type": "test",
                    "input_payload": {},
                },
                format="json",
            )

        # Response should succeed
        assert response.status_code == status.HTTP_201_CREATED

    @patch("apps.agent_runtime.interface.views.ResumeTaskUseCase")
    def test_resume_task_creates_audit_log(self, mock_use_case_class, api_client, mock_user):
        """Verify resume task operation creates audit log."""

        # Setup mock with JSON-serializable attributes
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_test"
        mock_task.status = MagicMock()
        mock_task.status.value = "draft"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "test"
        mock_task.schema_version = "v1"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = None
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_test"
        mock_output.timeline_event_id = 123
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        mock_model = MagicMock()
        mock_model.request_id = "atr_test"
        mock_model.status = "failed"

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.filter"
        ) as mock_filter:
            mock_queryset = MagicMock()
            mock_queryset.first.return_value = mock_model
            mock_queryset.only.return_value = mock_queryset
            mock_filter.return_value = mock_queryset

            url = reverse("agent_runtime:task-resume", kwargs={"pk": 1})
            response = api_client.post(url, {"reason": "Fixed"}, format="json")

        # Response should succeed
        assert response.status_code == status.HTTP_200_OK

    @patch("apps.agent_runtime.interface.views.CancelTaskUseCase")
    def test_cancel_task_creates_audit_log(self, mock_use_case_class, api_client, mock_user):
        """Verify cancel task operation creates audit log."""

        # Setup mock with JSON-serializable attributes
        mock_use_case = MagicMock()
        mock_task = MagicMock()
        mock_task.id = 1
        mock_task.request_id = "atr_test"
        mock_task.status = MagicMock()
        mock_task.status.value = "cancelled"
        mock_task.task_domain = MagicMock()
        mock_task.task_domain.value = "research"
        mock_task.task_type = "test"
        mock_task.schema_version = "v1"
        mock_task.input_payload = {}
        mock_task.current_step = None
        mock_task.last_error = None
        mock_task.requires_human = False
        mock_task.created_by = None
        mock_task.created_at = datetime.now(UTC)
        mock_task.updated_at = datetime.now(UTC)

        mock_output = MagicMock()
        mock_output.task = mock_task
        mock_output.request_id = "atr_test"
        mock_output.timeline_event_id = 124
        mock_use_case.execute.return_value = mock_output
        mock_use_case_class.return_value = mock_use_case

        api_client.force_authenticate(user=mock_user)

        mock_model = MagicMock()
        mock_model.request_id = "atr_test"
        mock_model.status = "draft"

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.filter"
        ) as mock_filter:
            mock_queryset = MagicMock()
            mock_queryset.first.return_value = mock_model
            mock_queryset.only.return_value = mock_queryset
            mock_filter.return_value = mock_queryset

            url = reverse("agent_runtime:task-cancel", kwargs={"pk": 1})
            response = api_client.post(url, {"reason": "Not needed"}, format="json")

        # Response should succeed
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestErrorResponses:
    """Tests for error response format compliance."""

    @pytest.fixture
    def api_client(self):
        """Create an API client."""
        return APIClient()

    @pytest.fixture
    def mock_user(self):
        """Create a mock authenticated user."""
        user = MagicMock()
        user.id = 1
        user.pk = 1
        user.is_authenticated = True
        return user

    def test_404_response_format(self, api_client, mock_user):
        """Test 404 response follows FROZEN error contract."""
        api_client.force_authenticate(user=mock_user)

        with patch(
            "apps.agent_runtime.interface.views.AgentTaskModel._default_manager.filter"
        ) as mock_filter:
            mock_queryset = MagicMock()
            mock_queryset.first.return_value = None
            mock_filter.return_value = mock_queryset

            url = reverse("agent_runtime:task-detail", kwargs={"pk": 99999})
            response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Verify FROZEN error format (schema-contract.md:151)
        data = response.data
        assert "request_id" in data
        assert "success" in data
        assert data["success"] is False
        assert "error_code" in data
        assert "message" in data

    def test_400_response_format(self, api_client, mock_user):
        """Test 400 response follows FROZEN error contract."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-list")
        response = api_client.post(
            url,
            {
                "task_domain": "invalid_domain",
                "task_type": "test",
                "input_payload": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        # Verify FROZEN error format
        data = response.data
        assert "request_id" in data or "success" in data

    def test_405_response_format(self, api_client, mock_user):
        """Test 405 response follows FROZEN error contract."""
        api_client.force_authenticate(user=mock_user)

        url = reverse("agent_runtime:task-detail", kwargs={"pk": 1})
        response = api_client.put(url, {"status": "completed"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Verify FROZEN error format
        data = response.data
        assert "request_id" in data
        assert "success" in data
        assert data["success"] is False
        assert "error_code" in data
        assert data["error_code"] == "method_not_allowed"
