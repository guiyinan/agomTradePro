"""
Integration tests for Setup Wizard Application layer.

Tests use cases with infrastructure dependencies.
"""

import pytest
from unittest.mock import patch, MagicMock

from apps.setup_wizard.application.use_cases import (
    CheckSetupStatusUseCase,
    CompleteSetupUseCase,
    GetNextStepUseCase,
    SetupAdminUseCase,
    SetupAIProviderUseCase,
    SetupDataSourceUseCase,
    VerifyAdminAuthUseCase,
)
from apps.setup_wizard.domain.entities import (
    AdminConfig,
    AIProviderConfigDTO,
    DataSourceConfigDTO,
    WizardStep,
    SetupStatus,
    SetupState,
    SetupProgress,
)


@pytest.mark.django_db
class TestCheckSetupStatusUseCase:
    """Tests for CheckSetupStatusUseCase"""

    def test_execute_first_time_setup(self):
        with patch(
            "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.get_state"
        ) as mock_get_state:
            with patch(
                "apps.setup_wizard.infrastructure.repositories.AdminRepository.has_admin_user"
            ) as mock_has_admin:
                mock_get_state.return_value = SetupState(
                    status=SetupStatus.NOT_INITIALIZED,
                    progress=SetupProgress(current_step=WizardStep.WELCOME),
                    admin_configured=False,
                )
                mock_has_admin.return_value = False

                use_case = CheckSetupStatusUseCase()
                result = use_case.execute()

                assert result.is_first_time is True
                assert result.requires_auth is False

    def test_execute_already_initialized(self):
        with patch(
            "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.get_state"
        ) as mock_get_state:
            with patch(
                "apps.setup_wizard.infrastructure.repositories.AdminRepository.has_admin_user"
            ) as mock_has_admin:
                mock_get_state.return_value = SetupState(
                    status=SetupStatus.COMPLETED,
                    progress=SetupProgress(current_step=WizardStep.COMPLETE),
                    admin_configured=True,
                    ai_provider_configured=True,
                    data_source_configured=True,
                )
                mock_has_admin.return_value = True

                use_case = CheckSetupStatusUseCase()
                result = use_case.execute()

                assert result.is_first_time is False
                assert result.requires_auth is True


@pytest.mark.django_db
class TestSetupAdminUseCase:
    """Tests for SetupAdminUseCase"""

    def test_execute_valid_config(self):
        config = AdminConfig(
            username="testadmin",
            password="SecurePass123",
            email="admin@test.com",
        )

        with patch(
            "apps.setup_wizard.infrastructure.repositories.AdminRepository.create_admin_user"
        ) as mock_create:
            with patch(
                "apps.setup_wizard.infrastructure.repositories.AdminRepository.set_admin_credentials"
            ):
                with patch(
                    "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.update_step"
                ):
                    mock_create.return_value = MagicMock(username="testadmin")

                    use_case = SetupAdminUseCase()
                    result = use_case.execute(config)

                    assert result.success is True

    def test_execute_invalid_username(self):
        config = AdminConfig(
            username="ab",
            password="SecurePass123",
        )

        use_case = SetupAdminUseCase()
        result = use_case.execute(config)

        assert result.success is False
        assert "3" in result.message

    def test_execute_weak_password(self):
        config = AdminConfig(
            username="testadmin",
            password="weak",
        )

        use_case = SetupAdminUseCase()
        result = use_case.execute(config)

        assert result.success is False
        assert "8" in result.message


@pytest.mark.django_db
class TestSetupAIProviderUseCase:
    """Tests for SetupAIProviderUseCase"""

    def test_execute_skip(self):
        use_case = SetupAIProviderUseCase()

        with patch(
            "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.update_step"
        ):
            result = use_case.execute(None)

            assert result.success is True

    def test_execute_valid_config(self):
        config = AIProviderConfigDTO(
            name="test-provider",
            provider_type="openai",
            base_url="https://api.test.com/v1",
            api_key="test-key",
            default_model="gpt-4",
        )

        with patch(
            "apps.setup_wizard.infrastructure.repositories.AIProviderRepository.save_config"
        ):
            with patch(
                "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.update_step"
            ):
                use_case = SetupAIProviderUseCase()
                result = use_case.execute(config)

                assert result.success is True


@pytest.mark.django_db
class TestSetupDataSourceUseCase:
    """Tests for SetupDataSourceUseCase"""

    def test_execute_skip(self):
        use_case = SetupDataSourceUseCase()

        with patch(
            "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.update_step"
        ):
            result = use_case.execute(None)

            assert result.success is True

    def test_execute_with_tushare_token(self):
        config = DataSourceConfigDTO(
            tushare_token="test-token",
            akshare_enabled=True,
        )

        with patch(
            "apps.setup_wizard.infrastructure.repositories.DataSourceRepository.save_config"
        ):
            with patch(
                "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.update_step"
            ):
                use_case = SetupDataSourceUseCase()
                result = use_case.execute(config)

                assert result.success is True


@pytest.mark.django_db
class TestVerifyAdminAuthUseCase:
    """Tests for VerifyAdminAuthUseCase"""

    def test_execute_correct_password(self):
        with patch(
            "apps.setup_wizard.infrastructure.repositories.AdminRepository.verify_admin_password"
        ) as mock_verify:
            mock_verify.return_value = True

            use_case = VerifyAdminAuthUseCase()
            result = use_case.execute("correct_password")

            assert result is True

    def test_execute_wrong_password(self):
        with patch(
            "apps.setup_wizard.infrastructure.repositories.AdminRepository.verify_admin_password"
        ) as mock_verify:
            mock_verify.return_value = False

            use_case = VerifyAdminAuthUseCase()
            result = use_case.execute("wrong_password")

            assert result is False


@pytest.mark.django_db
class TestCompleteSetupUseCase:
    """Tests for CompleteSetupUseCase"""

    def test_execute(self):
        with patch(
            "apps.setup_wizard.infrastructure.repositories.SetupStateRepository.mark_completed"
        ) as mock_mark:
            use_case = CompleteSetupUseCase()
            use_case.execute()

            mock_mark.assert_called_once()


class TestGetNextStepUseCase:
    """Tests for GetNextStepUseCase"""

    def test_execute(self):
        use_case = GetNextStepUseCase()

        next_step = use_case.execute(WizardStep.WELCOME)
        assert next_step == WizardStep.ADMIN_PASSWORD

        next_step = use_case.execute(WizardStep.COMPLETE)
        assert next_step is None
