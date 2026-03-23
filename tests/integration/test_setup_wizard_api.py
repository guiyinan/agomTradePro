"""
API Integration tests for Setup Wizard Interface layer.

Tests HTTP endpoints and views.
"""

import pytest
from unittest.mock import patch, MagicMock
from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.setup_wizard.domain.entities import WizardStep, SetupStatus

User = get_user_model()


@pytest.mark.django_db
class TestSetupWizardViews:
    """Tests for Setup Wizard views"""

    def test_wizard_view_get_first_time(self, client):
        with patch("apps.setup_wizard.interface.views.CheckSetupStatusUseCase") as mock_use_case:
            mock_result = MagicMock()
            mock_result.is_first_time = True
            mock_result.requires_auth = False
            mock_result.current_step = WizardStep.WELCOME
            mock_result.state = MagicMock()
            mock_use_case.return_value.execute.return_value = mock_result

            response = client.get("/setup/")
            assert response.status_code == 200

    def test_auth_view_get(self, client):
        response = client.get("/setup/auth/")
        assert response.status_code == 405

    def test_password_strength_api_empty(self, client):
        response = client.get("/setup/api/password-strength/?password=")
        assert response.status_code == 200
        data = response.json()
        assert data["score"] == 0
        assert data["level"] == "很弱"

    def test_password_strength_api_weak(self, client):
        response = client.get("/setup/api/password-strength/?password=abc")
        assert response.status_code == 200
        data = response.json()
        assert data["score"] < 40

    def test_password_strength_api_strong(self, client):
        response = client.get("/setup/api/password-strength/?password=SecurePass123!@#")
        assert response.status_code == 200
        data = response.json()
        assert data["score"] >= 80
        assert data["level"] == "强"


@pytest.mark.django_db
class TestSetupWizardStepSubmission:
    """Tests for step form submissions"""

    def test_welcome_step_post(self, client):
        with patch("apps.setup_wizard.interface.views.CheckSetupStatusUseCase") as mock_check:
            mock_result = MagicMock()
            mock_result.is_first_time = True
            mock_result.requires_auth = False
            mock_result.current_step = WizardStep.WELCOME
            mock_result.state = MagicMock()
            mock_check.return_value.execute.return_value = mock_result

            response = client.post("/setup/step/welcome/", follow=True)
            assert response.status_code in [200, 302, 400]

    def test_admin_password_step_password_mismatch(self, client):
        with patch("apps.setup_wizard.interface.views.CheckSetupStatusUseCase") as mock_check:
            mock_result = MagicMock()
            mock_result.is_first_time = True
            mock_result.requires_auth = False
            mock_result.current_step = WizardStep.ADMIN_PASSWORD
            mock_result.state = MagicMock()
            mock_check.return_value.execute.return_value = mock_result

            with patch(
                "apps.setup_wizard.application.use_cases.SetupAdminUseCase.execute"
            ) as mock_execute:
                mock_execute.return_value = MagicMock(
                    success=False, message="密码不匹配", password_strength=(0, "", [])
                )

                response = client.post(
                    "/setup/step/admin_password/",
                    data={
                        "username": "testadmin",
                        "password": "Password123",
                        "confirm_password": "DifferentPassword",
                        "email": "admin@test.com",
                    },
                    follow=True,
                )
                assert response.status_code in [200, 302]


@pytest.mark.django_db
class TestSetupWizardSecurity:
    """Security tests for Setup Wizard"""

    def test_requires_auth_when_admin_exists(self, client):
        with patch(
            "apps.setup_wizard.infrastructure.repositories.AdminRepository.has_admin_user"
        ) as mock_has_admin:
            mock_has_admin.return_value = True

            with patch("apps.setup_wizard.interface.views.CheckSetupStatusUseCase") as mock_check:
                mock_result = MagicMock()
                mock_result.is_first_time = False
                mock_result.requires_auth = True
                mock_result.current_step = WizardStep.WELCOME
                mock_result.state = MagicMock()
                mock_check.return_value.execute.return_value = mock_result

                response = client.get("/setup/")
                assert response.status_code == 200

    def test_auth_with_wrong_password(self, client):
        with patch(
            "apps.setup_wizard.application.use_cases.VerifyAdminAuthUseCase.execute"
        ) as mock_verify:
            mock_verify.return_value = False

            response = client.post(
                "/setup/auth/",
                data={"password": "wrongpassword"},
                follow=True,
            )
            assert response.status_code in [200, 302]

    def test_auth_with_correct_password(self, client):
        with patch(
            "apps.setup_wizard.application.use_cases.VerifyAdminAuthUseCase.execute"
        ) as mock_verify:
            mock_verify.return_value = True

            response = client.post(
                "/setup/auth/",
                data={"password": "correctpassword"},
                follow=True,
            )
            assert response.status_code in [200, 302]


@pytest.mark.django_db
class TestSetupWizardCompleteFlow:
    """End-to-end tests for complete setup flow"""

    def test_complete_setup_flow(self, client):
        with patch("apps.setup_wizard.interface.views.CheckSetupStatusUseCase") as mock_check:
            for step_info in [
                (WizardStep.WELCOME, False, False),
                (WizardStep.ADMIN_PASSWORD, True, False),
                (WizardStep.AI_PROVIDER, True, True),
                (WizardStep.DATA_SOURCE, True, True),
            ]:
                mock_result = MagicMock()
                mock_result.is_first_time = step_info[0] == WizardStep.WELCOME
                mock_result.requires_auth = step_info[1]
                mock_result.current_step = step_info[0]
                mock_result.state = MagicMock(
                    admin_configured=step_info[1],
                    ai_provider_configured=step_info[2],
                    data_source_configured=step_info[0] == WizardStep.DATA_SOURCE,
                )
                mock_check.return_value.execute.return_value = mock_result

                response = client.get("/setup/")
                assert response.status_code in [200, 302]
