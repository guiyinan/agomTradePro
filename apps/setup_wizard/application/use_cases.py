"""
Application Use Cases for Setup Wizard.

用例编排层，协调 Domain 和 Infrastructure 层。
"""

from dataclasses import dataclass
from typing import Optional

from apps.setup_wizard.domain.entities import (
    AdminConfig,
    AIProviderConfigDTO,
    DataSourceConfigDTO,
    SetupState,
    SetupStatus,
    WizardStep,
)
from apps.setup_wizard.domain.services import (
    PasswordStrengthChecker,
    SetupProgressCalculator,
    SetupValidator,
)
from apps.setup_wizard.infrastructure.repositories import (
    AdminRepository,
    AIProviderRepository,
    DataSourceRepository,
    SetupStateRepository,
)


@dataclass
class CheckSetupStatusResult:
    """检查安装状态结果"""

    is_first_time: bool
    requires_auth: bool
    current_step: WizardStep
    state: SetupState


@dataclass
class SetupAdminResult:
    """设置管理员结果"""

    success: bool
    message: str
    password_strength: tuple[int, str, list[str]]


@dataclass
class SetupAIProviderResult:
    """设置 AI Provider 结果"""

    success: bool
    message: str


class CheckSetupStatusUseCase:
    """检查安装状态用例"""

    def __init__(self):
        self.state_repo = SetupStateRepository()
        self.admin_repo = AdminRepository()

    def execute(self) -> CheckSetupStatusResult:
        """
        执行检查安装状态

        Returns:
            检查结果
        """
        state = self.state_repo.get_state()
        has_admin = self.admin_repo.has_admin_user()

        is_first_time = state.status == SetupStatus.NOT_INITIALIZED and not has_admin
        requires_auth = has_admin

        current_step = state.progress.current_step if state.progress else WizardStep.WELCOME

        return CheckSetupStatusResult(
            is_first_time=is_first_time,
            requires_auth=requires_auth,
            current_step=current_step,
            state=state,
        )


class SetupAdminUseCase:
    """设置管理员用例"""

    def __init__(self):
        self.admin_repo = AdminRepository()
        self.state_repo = SetupStateRepository()
        self.validator = SetupValidator()

    def execute(self, config: AdminConfig) -> SetupAdminResult:
        """
        执行设置管理员

        Args:
            config: 管理员配置

        Returns:
            设置结果
        """
        is_valid, message = self.validator.validate_admin_username(config.username)
        if not is_valid:
            return SetupAdminResult(
                success=False,
                message=message,
                password_strength=(0, "", []),
            )

        is_valid, message = self.validator.validate_admin_email(config.email)
        if not is_valid:
            return SetupAdminResult(
                success=False,
                message=message,
                password_strength=(0, "", []),
            )

        is_valid, message = config.validate_password_strength()
        if not is_valid:
            return SetupAdminResult(
                success=False,
                message=message,
                password_strength=(0, "", []),
            )

        password_strength = PasswordStrengthChecker.check_strength(config.password)

        try:
            self.admin_repo.create_admin_user(config)
            self.admin_repo.set_admin_credentials(config)
            self.state_repo.update_step(WizardStep.ADMIN_PASSWORD, completed=True)

            return SetupAdminResult(
                success=True,
                message="管理员账户创建成功",
                password_strength=password_strength,
            )
        except Exception as e:
            return SetupAdminResult(
                success=False,
                message=f"创建管理员失败: {str(e)}",
                password_strength=password_strength,
            )


class SetupAIProviderUseCase:
    """设置 AI Provider 用例"""

    def __init__(self):
        self.ai_provider_repo = AIProviderRepository()
        self.state_repo = SetupStateRepository()
        self.validator = SetupValidator()

    def execute(self, config: AIProviderConfigDTO | None) -> SetupAIProviderResult:
        """
        执行设置 AI Provider

        Args:
            config: AI Provider 配置（None 表示跳过）

        Returns:
            设置结果
        """
        if config is None:
            self.state_repo.update_step(WizardStep.AI_PROVIDER, completed=True)
            return SetupAIProviderResult(
                success=True,
                message="已跳过 AI Provider 配置，可稍后在系统中配置",
            )

        is_valid, message = self.validator.validate_ai_provider_config(config)
        if not is_valid:
            return SetupAIProviderResult(success=False, message=message)

        try:
            self.ai_provider_repo.save_config(config)
            self.state_repo.update_step(WizardStep.AI_PROVIDER, completed=True)

            return SetupAIProviderResult(
                success=True,
                message=f"AI Provider '{config.name}' 配置成功",
            )
        except Exception as e:
            return SetupAIProviderResult(
                success=False,
                message=f"配置 AI Provider 失败: {str(e)}",
            )


class SetupDataSourceUseCase:
    """设置数据源用例"""

    def __init__(self):
        self.data_source_repo = DataSourceRepository()
        self.state_repo = SetupStateRepository()

    def execute(self, config: DataSourceConfigDTO | None) -> SetupAIProviderResult:
        """
        执行设置数据源

        Args:
            config: 数据源配置（None 表示跳过）

        Returns:
            设置结果
        """
        if config is None:
            self.state_repo.update_step(WizardStep.DATA_SOURCE, completed=True)
            return SetupAIProviderResult(
                success=True,
                message="已跳过数据源配置，可稍后在系统中配置",
            )

        if not config.tushare_token and not config.fred_api_key:
            self.state_repo.update_step(WizardStep.DATA_SOURCE, completed=True)
            return SetupAIProviderResult(
                success=True,
                message="已跳过数据源配置，可稍后在系统中配置",
            )

        try:
            self.data_source_repo.save_config(config)
            self.state_repo.update_step(WizardStep.DATA_SOURCE, completed=True)

            return SetupAIProviderResult(
                success=True,
                message="数据源配置成功",
            )
        except Exception as e:
            return SetupAIProviderResult(
                success=False,
                message=f"配置数据源失败: {str(e)}",
            )


class EnsureSecurityKeysUseCase:
    """确保安全密钥已配置用例"""

    def execute(
        self, *, generate_secret_key: bool = True, generate_encryption_key: bool = True
    ) -> dict[str, bool]:
        """
        检查并自动生成安全密钥（SECRET_KEY / AGOMTRADEPRO_ENCRYPTION_KEY）。

        Returns:
            Dict with generation flags
        """
        from apps.setup_wizard.infrastructure.encryption_setup import ensure_all_keys

        return ensure_all_keys(
            generate_secret_key=generate_secret_key,
            generate_encryption_key=generate_encryption_key,
        )


class CompleteSetupUseCase:
    """完成安装用例"""

    def __init__(self):
        self.state_repo = SetupStateRepository()

    def execute(self) -> None:
        """执行完成安装"""
        self.state_repo.mark_completed()


class VerifyAdminAuthUseCase:
    """验证管理员认证用例"""

    def __init__(self):
        self.admin_repo = AdminRepository()

    def execute(self, password: str) -> bool:
        """
        执行验证管理员密码

        Args:
            password: 管理员密码

        Returns:
            是否验证通过
        """
        return self.admin_repo.verify_admin_password(password)


class GetNextStepUseCase:
    """获取下一步骤用例"""

    def __init__(self):
        self.calculator = SetupProgressCalculator()

    def execute(self, current_step: WizardStep) -> WizardStep | None:
        """
        执行获取下一步骤

        Args:
            current_step: 当前步骤

        Returns:
            下一个步骤
        """
        return self.calculator.get_next_step(current_step)
