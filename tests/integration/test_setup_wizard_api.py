"""
API Integration tests for Setup Wizard Interface layer.

Tests HTTP endpoints and views.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from apps.setup_wizard.domain.entities import WizardStep

User = get_user_model()


def _response_text(response) -> str:
    return response.content.decode("utf-8")


def _assert_html_contract(response, *fragments: str) -> str:
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")

    content = _response_text(response)
    for fragment in fragments:
        assert fragment in content
    return content


def _assert_wizard_page_contract(response, *step_fragments: str) -> str:
    common_fragments = (
        "系统初始化向导 - AgomTradePro",
        'class="setup-progress"',
        "step-label\">欢迎<",
        "step-label\">管理员<",
        "step-label\">AI 配置<",
        "step-label\">数据源<",
        "step-label\">完成<",
        "/setup/api/password-strength/",
    )
    return _assert_html_contract(response, *common_fragments, *step_fragments)


def _assert_auth_page_contract(response) -> str:
    return _assert_html_contract(
        response,
        "系统初始化 - AgomTradePro",
        "验证管理员身份",
        "管理员密码",
        'action="/setup/auth/"',
        "返回首页",
    )


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
            _assert_wizard_page_contract(
                response,
                "欢迎使用 AgomTradePro",
                "Regime 判定引擎",
                "政策闸门过滤",
                'action="/setup/step/welcome/"',
                "开始配置",
            )

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

    def test_invalid_step_returns_400_json(self, client):
        response = client.post("/setup/step/not-a-step/")

        assert response.status_code == 400
        assert response.json() == {"error": "无效的步骤"}

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

    def test_existing_install_welcome_does_not_generate_keys(self, client):
        session = client.session
        session["setup_wizard_authenticated"] = True
        session["setup_wizard"] = {"current_step": "welcome"}
        session.save()

        with patch("apps.setup_wizard.interface.views.CheckSetupStatusUseCase") as mock_check:
            mock_result = MagicMock()
            mock_result.is_first_time = False
            mock_result.requires_auth = True
            mock_result.current_step = WizardStep.WELCOME
            mock_result.state = MagicMock()
            mock_check.return_value.execute.return_value = mock_result

            with patch(
                "apps.setup_wizard.interface.views.EnsureSecurityKeysUseCase"
            ) as mock_ensure:
                mock_ensure.return_value.execute.return_value = {
                    "secret_key_generated": False,
                    "encryption_key_generated": False,
                    "secret_key_configured": False,
                    "encryption_key_configured": False,
                }

                response = client.post("/setup/step/welcome/", follow=True)

        assert response.status_code in [200, 302]
        mock_ensure.return_value.execute.assert_called_once_with(
            generate_secret_key=False,
            generate_encryption_key=False,
        )

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

    def test_data_source_success_marks_setup_complete(self, client):
        session = client.session
        session["setup_wizard_authenticated"] = True
        session["setup_wizard"] = {"current_step": "data_source"}
        session.save()

        with patch(
            "apps.setup_wizard.application.use_cases.SetupDataSourceUseCase.execute"
        ) as mock_setup, patch(
            "apps.setup_wizard.interface.views.CompleteSetupUseCase.execute"
        ) as mock_complete:
            mock_setup.return_value = MagicMock(success=True, message="ok")

            response = client.post(
                "/setup/step/data_source/",
                data={
                    "tushare_token": "token-123",
                    "tushare_http_url": "https://proxy.example.com",
                    "fred_api_key": "fred-key",
                    "akshare_enabled": "on",
                },
            )

        assert response.status_code == 302
        mock_complete.assert_called_once()
        assert client.session["setup_wizard"]["current_step"] == "complete"


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
                _assert_auth_page_contract(response)

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
            content = _assert_auth_page_contract(response)
            assert "密码错误" in content

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
            _assert_wizard_page_contract(
                response,
                "欢迎使用 AgomTradePro",
                'action="/setup/step/welcome/"',
                "开始配置",
            )
            assert client.session["setup_wizard_authenticated"] is True
            assert client.session["setup_wizard"]["current_step"] == "welcome"

    def test_logout_clears_setup_session_state(self, client):
        session = client.session
        session["setup_wizard_authenticated"] = True
        session["setup_wizard"] = {"current_step": "ai_provider"}
        session.save()

        response = client.post("/setup/logout/")

        assert response.status_code == 302
        assert "setup_wizard_authenticated" not in client.session
        assert "setup_wizard" not in client.session


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
                if step_info[1]:
                    _assert_auth_page_contract(response)
                else:
                    _assert_wizard_page_contract(
                        response,
                        "欢迎使用 AgomTradePro",
                        'action="/setup/step/welcome/"',
                        "开始配置",
                    )
