"""
Repository implementations for Setup Wizard.

实现数据持久化逻辑。
"""

from datetime import UTC, datetime, timezone
from typing import Optional, Protocol

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

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

User = get_user_model()


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

            completed_steps = []
            for step_str in model.completed_steps or []:
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
            model.completed_steps = [s.value for s in state.progress.completed_steps]

            if state.status == SetupStatus.COMPLETED:
                model.completed_at = datetime.now(UTC)

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

        if completed and step not in [WizardStep(s) for s in (model.completed_steps or [])]:
            completed_steps = model.completed_steps or []
            completed_steps.append(step.value)
            model.completed_steps = completed_steps

        model.save(update_fields=["current_step", "completed_steps", "updated_at"])

    def mark_completed(self) -> None:
        """标记安装完成"""
        model = SetupStateModel.get_instance()
        model.is_completed = True
        model.completed_at = datetime.now(UTC)
        model.current_step = WizardStep.COMPLETE.value
        model.save()


class AdminRepository:
    """管理员用户仓储"""

    def has_admin_user(self) -> bool:
        """检查是否存在管理员用户"""
        return User.objects.filter(is_superuser=True).exists()

    def create_admin_user(self, config: AdminConfig) -> User:
        """
        创建管理员用户

        Args:
            config: 管理员配置

        Returns:
            创建的用户对象
        """
        user = User.objects.create_superuser(
            username=config.username,
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
        admin_users = User.objects.filter(is_superuser=True)
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
        model.admin_username = config.username
        model.admin_email = config.email or ""
        model.save(update_fields=["admin_username", "admin_email", "updated_at"])


class AIProviderRepository:
    """AI Provider 配置仓储"""

    def save_config(self, config: AIProviderConfigDTO) -> None:
        """
        保存 AI Provider 配置

        优先使用加密字段 api_key_encrypted 存储，
        仅在加密服务不可用时回退到明文存储。

        Args:
            config: AI Provider 配置
        """
        from apps.ai_provider.infrastructure.models import AIProviderConfig
        from shared.infrastructure.crypto import get_encryption_service

        defaults = {
            "provider_type": config.provider_type,
            "base_url": config.base_url,
            "default_model": config.default_model,
            "is_active": config.is_active,
            "priority": config.priority,
        }

        crypto = get_encryption_service()
        if crypto and config.api_key:
            defaults["api_key_encrypted"] = crypto.encrypt(config.api_key)
            defaults["api_key"] = ""  # Clear deprecated plaintext field
        else:
            defaults["api_key"] = config.api_key

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
        from apps.macro.infrastructure.models import DataSourceConfig

        if config.tushare_token:
            DataSourceConfig.objects.update_or_create(
                source_type="tushare",
                defaults={
                    "api_key": config.tushare_token,
                    "is_active": True,
                },
            )

        if config.fred_api_key:
            DataSourceConfig.objects.update_or_create(
                source_type="fred",
                defaults={
                    "api_key": config.fred_api_key,
                    "is_active": True,
                },
            )

    def has_active_config(self) -> bool:
        """检查是否存在活跃的数据源配置"""
        from apps.macro.infrastructure.models import DataSourceConfig

        return DataSourceConfig.objects.filter(is_active=True).exists()
