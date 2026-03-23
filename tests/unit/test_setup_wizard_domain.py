"""
Unit tests for Setup Wizard Domain layer.

Tests domain entities and services without any external dependencies.
"""

import pytest
from datetime import datetime, timezone

from apps.setup_wizard.domain.entities import (
    AdminConfig,
    AIProviderConfigDTO,
    DataSourceConfigDTO,
    SetupProgress,
    SetupState,
    SetupStatus,
    WizardStep,
)
from apps.setup_wizard.domain.services import (
    PasswordStrengthChecker,
    SetupProgressCalculator,
    SetupValidator,
)


class TestWizardStep:
    """Tests for WizardStep enum"""

    def test_wizard_step_values(self):
        assert WizardStep.WELCOME.value == "welcome"
        assert WizardStep.ADMIN_PASSWORD.value == "admin_password"
        assert WizardStep.AI_PROVIDER.value == "ai_provider"
        assert WizardStep.DATA_SOURCE.value == "data_source"
        assert WizardStep.COMPLETE.value == "complete"


class TestSetupStatus:
    """Tests for SetupStatus enum"""

    def test_setup_status_values(self):
        assert SetupStatus.NOT_INITIALIZED.value == "not_initialized"
        assert SetupStatus.IN_PROGRESS.value == "in_progress"
        assert SetupStatus.COMPLETED.value == "completed"


class TestAdminConfig:
    """Tests for AdminConfig entity"""

    def test_create_admin_config(self):
        config = AdminConfig(
            username="admin",
            password="SecurePass123",
            email="admin@example.com",
        )
        assert config.username == "admin"
        assert config.password == "SecurePass123"
        assert config.email == "admin@example.com"

    def test_create_admin_config_without_email(self):
        config = AdminConfig(
            username="admin",
            password="SecurePass123",
        )
        assert config.username == "admin"
        assert config.email is None

    def test_validate_password_strength_too_short(self):
        config = AdminConfig(
            username="admin",
            password="short",
        )
        is_valid, message = config.validate_password_strength()
        assert is_valid is False
        assert "8" in message

    def test_validate_password_strength_no_letter(self):
        config = AdminConfig(
            username="admin",
            password="12345678",
        )
        is_valid, message = config.validate_password_strength()
        assert is_valid is False
        assert "letter" in message.lower() or "字母" in message

    def test_validate_password_strength_no_digit(self):
        config = AdminConfig(
            username="admin",
            password="password",
        )
        is_valid, message = config.validate_password_strength()
        assert is_valid is False
        assert "digit" in message.lower() or "数字" in message

    def test_validate_password_strength_valid(self):
        config = AdminConfig(
            username="admin",
            password="SecurePass123",
        )
        is_valid, message = config.validate_password_strength()
        assert is_valid is True
        assert message == ""


class TestAIProviderConfigDTO:
    """Tests for AIProviderConfigDTO entity"""

    def test_create_ai_provider_config(self):
        config = AIProviderConfigDTO(
            name="openai",
            provider_type="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4",
            is_active=True,
            priority=10,
        )
        assert config.name == "openai"
        assert config.provider_type == "openai"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.api_key == "sk-test"
        assert config.default_model == "gpt-4"
        assert config.is_active is True
        assert config.priority == 10

    def test_create_ai_provider_config_defaults(self):
        config = AIProviderConfigDTO(
            name="test",
            provider_type="custom",
            base_url="https://api.test.com/v1",
            api_key="test-key",
        )
        assert config.default_model == "gpt-3.5-turbo"
        assert config.is_active is True
        assert config.priority == 10


class TestDataSourceConfigDTO:
    """Tests for DataSourceConfigDTO entity"""

    def test_create_data_source_config(self):
        config = DataSourceConfigDTO(
            tushare_token="test-token",
            fred_api_key="fred-key",
            akshare_enabled=True,
        )
        assert config.tushare_token == "test-token"
        assert config.fred_api_key == "fred-key"
        assert config.akshare_enabled is True

    def test_create_data_source_config_defaults(self):
        config = DataSourceConfigDTO()
        assert config.tushare_token is None
        assert config.fred_api_key is None
        assert config.akshare_enabled is True


class TestSetupProgress:
    """Tests for SetupProgress entity"""

    def test_create_setup_progress(self):
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        progress = SetupProgress(
            current_step=WizardStep.ADMIN_PASSWORD,
            completed_steps=[WizardStep.WELCOME],
            started_at=now,
        )
        assert progress.current_step == WizardStep.ADMIN_PASSWORD
        assert WizardStep.WELCOME in progress.completed_steps
        assert progress.started_at == now

    def test_is_step_completed(self):
        progress = SetupProgress(
            current_step=WizardStep.AI_PROVIDER,
            completed_steps=[WizardStep.WELCOME, WizardStep.ADMIN_PASSWORD],
        )
        assert progress.is_step_completed(WizardStep.WELCOME) is True
        assert progress.is_step_completed(WizardStep.ADMIN_PASSWORD) is True
        assert progress.is_step_completed(WizardStep.AI_PROVIDER) is False

    def test_get_progress_percentage(self):
        progress = SetupProgress(
            current_step=WizardStep.AI_PROVIDER,
            completed_steps=[WizardStep.WELCOME, WizardStep.ADMIN_PASSWORD],
        )
        percentage = progress.get_progress_percentage()
        assert 0 <= percentage <= 100

    def test_get_progress_percentage_complete(self):
        progress = SetupProgress(
            current_step=WizardStep.COMPLETE,
            completed_steps=[
                WizardStep.WELCOME,
                WizardStep.ADMIN_PASSWORD,
                WizardStep.AI_PROVIDER,
                WizardStep.DATA_SOURCE,
                WizardStep.COMPLETE,
            ],
        )
        assert progress.get_progress_percentage() == 100


class TestSetupState:
    """Tests for SetupState entity"""

    def test_create_setup_state_not_initialized(self):
        state = SetupState(status=SetupStatus.NOT_INITIALIZED)
        assert state.status == SetupStatus.NOT_INITIALIZED
        assert state.is_first_time_setup() is True
        assert state.requires_auth() is False

    def test_create_setup_state_completed(self):
        state = SetupState(
            status=SetupStatus.COMPLETED,
            admin_configured=True,
        )
        assert state.is_first_time_setup() is False
        assert state.requires_auth() is True

    def test_requires_auth_when_admin_configured(self):
        state = SetupState(
            status=SetupStatus.NOT_INITIALIZED,
            admin_configured=True,
        )
        assert state.requires_auth() is True


class TestSetupValidator:
    """Tests for SetupValidator service"""

    def test_validate_admin_username_valid(self):
        is_valid, message = SetupValidator.validate_admin_username("admin")
        assert is_valid is True
        assert message == ""

    def test_validate_admin_username_too_short(self):
        is_valid, message = SetupValidator.validate_admin_username("ab")
        assert is_valid is False
        assert "3" in message

    def test_validate_admin_username_must_start_with_letter(self):
        is_valid, message = SetupValidator.validate_admin_username("123admin")
        assert is_valid is False
        assert "letter" in message.lower() or "字母" in message

    def test_validate_admin_username_invalid_chars(self):
        is_valid, message = SetupValidator.validate_admin_username("admin@")
        assert is_valid is False

    def test_validate_admin_email_valid(self):
        is_valid, message = SetupValidator.validate_admin_email("admin@example.com")
        assert is_valid is True
        assert message == ""

    def test_validate_admin_email_none(self):
        is_valid, message = SetupValidator.validate_admin_email(None)
        assert is_valid is True

    def test_validate_admin_email_empty(self):
        is_valid, message = SetupValidator.validate_admin_email("")
        assert is_valid is True

    def test_validate_admin_email_invalid(self):
        is_valid, message = SetupValidator.validate_admin_email("invalid-email")
        assert is_valid is False

    def test_validate_ai_provider_config_valid(self):
        config = AIProviderConfigDTO(
            name="test",
            provider_type="openai",
            base_url="https://api.test.com",
            api_key="test-key",
            default_model="gpt-4",
        )
        is_valid, message = SetupValidator.validate_ai_provider_config(config)
        assert is_valid is True

    def test_validate_ai_provider_config_missing_name(self):
        config = AIProviderConfigDTO(
            name="",
            provider_type="openai",
            base_url="https://api.test.com",
            api_key="test-key",
            default_model="gpt-4",
        )
        is_valid, message = SetupValidator.validate_ai_provider_config(config)
        assert is_valid is False

    def test_validate_ai_provider_config_missing_api_key(self):
        config = AIProviderConfigDTO(
            name="test",
            provider_type="openai",
            base_url="https://api.test.com",
            api_key="",
            default_model="gpt-4",
        )
        is_valid, message = SetupValidator.validate_ai_provider_config(config)
        assert is_valid is False


class TestPasswordStrengthChecker:
    """Tests for PasswordStrengthChecker service"""

    def test_check_strength_weak(self):
        score, level, suggestions = PasswordStrengthChecker.check_strength("abc")
        assert score < 40
        assert level in ["弱", "很弱"]
        assert len(suggestions) > 0

    def test_check_strength_medium(self):
        score, level, suggestions = PasswordStrengthChecker.check_strength("Password123")
        assert 40 <= score < 80
        assert level == "中"

    def test_check_strength_strong(self):
        score, level, suggestions = PasswordStrengthChecker.check_strength("SecurePass123!@#")
        assert score >= 80
        assert level == "强"

    def test_check_strength_empty(self):
        score, level, suggestions = PasswordStrengthChecker.check_strength("")
        assert score == 0
        assert level == "很弱"


class TestSetupProgressCalculator:
    """Tests for SetupProgressCalculator service"""

    def test_get_next_step_from_welcome(self):
        next_step = SetupProgressCalculator.get_next_step(WizardStep.WELCOME)
        assert next_step == WizardStep.ADMIN_PASSWORD

    def test_get_next_step_from_admin_password(self):
        next_step = SetupProgressCalculator.get_next_step(WizardStep.ADMIN_PASSWORD)
        assert next_step == WizardStep.AI_PROVIDER

    def test_get_next_step_from_complete(self):
        next_step = SetupProgressCalculator.get_next_step(WizardStep.COMPLETE)
        assert next_step is None

    def test_get_previous_step_from_ai_provider(self):
        prev_step = SetupProgressCalculator.get_previous_step(WizardStep.AI_PROVIDER)
        assert prev_step == WizardStep.ADMIN_PASSWORD

    def test_get_previous_step_from_welcome(self):
        prev_step = SetupProgressCalculator.get_previous_step(WizardStep.WELCOME)
        assert prev_step is None
