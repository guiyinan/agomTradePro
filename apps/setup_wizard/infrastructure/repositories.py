"""
Repository implementations for Setup Wizard.

实现数据持久化逻辑。
"""

from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser

from apps.setup_wizard.domain.entities import (
    AdminConfig,
    AIProviderConfigDTO,
    DataSourceConfigDTO,
    SetupProgress,
    SetupState,
    SetupStatus,
    WizardStep,
)
from apps.setup_wizard.infrastructure.models import SetupStateModel

UserModel = get_user_model()


class SetupStateRepositoryProtocol(Protocol):
    """安装状态仓储协议"""

    def get_state(self) -> SetupState:
        """获取当前安装状态"""
        ...

    def save_state(self, state: SetupState) -> None:
        """保存安装状态"""
        ...

    def mark_completed(self) -> None:
        """标记安装完成"""
        ...


class SetupStateRepository:
    """安装状态仓储实现"""

    def get_state(self) -> SetupState:
        """获取当前安装状态"""
        model = SetupStateModel.get_instance()

        progress = None
        if model.current_step:
            try:
                current_step = WizardStep(model.current_step)
            except ValueError:
                current_step = WizardStep.WELCOME

            completed_steps: list[WizardStep] = []
            for step_str in _normalized_step_values(model.completed_steps):
                try:
                    completed_steps.append(WizardStep(step_str))
                except ValueError:
                    pass

            progress = SetupProgress(
                current_step=current_step,
                completed_steps=completed_steps,
                started_at=model.created_at,
                completed_at=model.completed_at,
            )

        status = SetupStatus.COMPLETED if model.is_completed else SetupStatus.NOT_INITIALIZED

        return SetupState(
            status=status,
            progress=progress,
            admin_configured=bool(model.admin_username),
            ai_provider_configured=model.ai_provider_configured,
            data_source_configured=model.data_source_configured,
        )

    def save_state(self, state: SetupState) -> None:
        """保存安装状态"""
        model = SetupStateModel.get_instance()

        model.is_completed = state.status == SetupStatus.COMPLETED
        model.ai_provider_configured = state.ai_provider_configured
        model.data_source_configured = state.data_source_configured

        if state.progress:
            model.current_step = state.progress.current_step.value
            model.completed_steps = list(
                dict.fromkeys(s.value for s in state.progress.completed_steps)
            )

            if state.status == SetupStatus.COMPLETED:
                model.current_step = WizardStep.COMPLETE.value
                if WizardStep.COMPLETE.value not in model.completed_steps:
                    model.completed_steps.append(WizardStep.COMPLETE.value)
                model.completed_at = datetime.now(UTC)
            else:
                model.completed_at = None

        if state.status == SetupStatus.COMPLETED and not state.progress:
            model.current_step = WizardStep.COMPLETE.value
            model.completed_steps = [WizardStep.COMPLETE.value]
            model.completed_at = datetime.now(UTC)
        elif state.status != SetupStatus.COMPLETED and not state.progress:
            model.completed_at = None

        model.save(
            update_fields=[
                "is_completed",
                "ai_provider_configured",
                "data_source_configured",
                "current_step",
                "completed_steps",
                "completed_at",
                "updated_at",
            ]
        )

    def update_step(self, step: WizardStep, completed: bool = False) -> None:
        """更新当前步骤"""
        model = SetupStateModel.get_instance()
        model.current_step = step.value

        completed_steps = _normalized_step_values(model.completed_steps)
        if completed and step.value not in completed_steps:
            completed_steps.append(step.value)
        model.completed_steps = completed_steps

        model.save(update_fields=["current_step", "completed_steps", "updated_at"])

    def mark_completed(self) -> None:
        """标记安装完成"""
        model = SetupStateModel.get_instance()
        model.is_completed = True
        model.completed_at = datetime.now(UTC)
        model.current_step = WizardStep.COMPLETE.value
        completed_steps = _normalized_step_values(model.completed_steps)
        if WizardStep.COMPLETE.value not in completed_steps:
            completed_steps.append(WizardStep.COMPLETE.value)
        model.completed_steps = completed_steps
        model.save(
            update_fields=[
                "is_completed",
                "completed_at",
                "current_step",
                "completed_steps",
                "updated_at",
            ]
        )


class AdminRepository:
    """管理员用户仓储"""

    def has_admin_user(self) -> bool:
        """检查是否存在管理员用户"""
        return UserModel._default_manager.filter(is_superuser=True).exists()

    def create_admin_user(self, config: AdminConfig) -> AbstractBaseUser:
        """
        创建管理员用户

        Args:
            config: 管理员配置

        Returns:
            创建的用户对象
        """
        is_valid, message = config.validate_password_strength()
        if not is_valid:
            raise ValueError(message)
        username = config.username.strip()
        if not username or len(username) > 150:
            raise ValueError("Administrator username must contain 1 to 150 characters.")
        user = UserModel._default_manager.create_superuser(
            username=username,
            email=config.email or "",
            password=config.password,
        )
        return user

    def verify_admin_password(self, password: str) -> bool:
        """
        验证管理员密码

        用于已初始化系统重新进入向导时的认证。

        Args:
            password: 待验证的密码

        Returns:
            是否验证通过
        """
        admin_users = UserModel._default_manager.filter(is_superuser=True)
        for user in admin_users:
            if user.check_password(password):
                return True
        return False

    def set_admin_credentials(self, config: AdminConfig) -> None:
        """
        保存管理员凭据到状态模型

        Args:
            config: 管理员配置
        """
        model = SetupStateModel.get_instance()
        model.admin_username = config.username.strip()
        model.admin_email = config.email or ""
        model.save(update_fields=["admin_username", "admin_email", "updated_at"])


class AIProviderRepository:
    """AI Provider 配置仓储"""

    def save_config(self, config: AIProviderConfigDTO) -> None:
        """
        保存 AI Provider 配置

        API key 只允许写入加密字段；加密服务不可用时拒绝持久化。

        Args:
            config: AI Provider 配置
        """
        from apps.ai_provider.infrastructure.models import AIProviderConfig
        from shared.infrastructure.crypto import get_encryption_service

        defaults: dict[str, object] = {
            "provider_type": config.provider_type,
            "base_url": config.base_url,
            "default_model": config.default_model,
            "is_active": config.is_active,
            "priority": config.priority,
        }

        api_key = (
            _validated_secret(config.api_key, field_name="AI provider API key")
            if config.api_key
            else ""
        )
        crypto = get_encryption_service()
        if api_key:
            if crypto is None:
                raise ValueError("AI provider credential encryption is unavailable.")
            defaults["api_key_encrypted"] = crypto.encrypt(api_key)
            defaults["api_key"] = ""  # Clear deprecated plaintext field

        AIProviderConfig.objects.update_or_create(
            name=config.name,
            defaults=defaults,
        )

    def has_active_provider(self) -> bool:
        """检查是否存在活跃的 AI Provider"""
        from apps.ai_provider.infrastructure.models import AIProviderConfig

        return AIProviderConfig.objects.filter(is_active=True).exists()


class DataSourceRepository:
    """数据源配置仓储"""

    def save_config(self, config: DataSourceConfigDTO) -> None:
        """
        保存数据源配置

        Args:
            config: 数据源配置
        """
        from apps.data_center.application.public import save_data_source_configuration

        if config.tushare_token:
            tushare_token = _validated_secret(config.tushare_token, field_name="Tushare token")
            tushare_url = _validated_http_url(config.tushare_http_url)
            save_data_source_configuration(
                source_type="tushare",
                name="Tushare Pro",
                api_key=tushare_token,
                http_url=tushare_url,
            )

        if config.fred_api_key:
            fred_api_key = _validated_secret(config.fred_api_key, field_name="FRED API key")
            save_data_source_configuration(
                source_type="fred",
                name="FRED",
                api_key=fred_api_key,
            )

    def has_active_config(self) -> bool:
        """检查是否存在活跃的数据源配置"""
        from apps.data_center.application.public import list_active_data_sources

        return bool(list_active_data_sources())


def _normalized_step_values(raw_steps: object) -> list[str]:
    """Return unique known step values from persisted JSON evidence."""
    if not isinstance(raw_steps, list):
        return []
    valid_steps = {step.value for step in WizardStep}
    return list(
        dict.fromkeys(step for step in raw_steps if isinstance(step, str) and step in valid_steps)
    )


def _validated_secret(value: str, *, field_name: str) -> str:
    """Validate a bounded credential without exposing it in failures."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > 4096:
        raise ValueError(f"{field_name} must contain 1 to 4096 characters.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{field_name} contains invalid control characters.")
    return normalized


def _validated_http_url(value: str | None) -> str:
    """Validate an optional credential-free HTTP(S) provider endpoint."""
    if value is None or not value.strip():
        return ""
    normalized = value.strip()
    if len(normalized) > 500:
        raise ValueError("Tushare HTTP URL is too long.")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Tushare HTTP URL must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Tushare HTTP URL cannot contain credentials, query, or fragment.")
    return normalized
