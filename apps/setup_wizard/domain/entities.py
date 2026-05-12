"""
Domain entities for Setup Wizard.

安装向导核心实体定义，遵循 DDD 规范，不依赖任何外部框架。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class WizardStep(Enum):
    """安装向导步骤枚举"""

    WELCOME = "welcome"
    ADMIN_PASSWORD = "admin_password"
    AI_PROVIDER = "ai_provider"
    DATA_SOURCE = "data_source"
    COMPLETE = "complete"


class SetupStatus(Enum):
    """系统初始化状态"""

    NOT_INITIALIZED = "not_initialized"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True)
class AdminConfig:
    """管理员配置实体"""

    username: str
    password: str
    email: str | None = None

    def validate_password_strength(self) -> tuple[bool, str]:
        """
        验证密码强度

        Returns:
            (is_valid, message): 验证结果和消息
        """
        if len(self.password) < 8:
            return False, "密码长度至少 8 位"

        has_letter = any(c.isalpha() for c in self.password)
        has_digit = any(c.isdigit() for c in self.password)

        if not has_letter:
            return False, "密码必须包含字母"
        if not has_digit:
            return False, "密码必须包含数字"

        return True, ""


@dataclass(frozen=True)
class AIProviderConfigDTO:
    """AI Provider 配置实体"""

    name: str
    provider_type: str
    base_url: str
    api_key: str
    default_model: str = "gpt-3.5-turbo"
    is_active: bool = True
    priority: int = 10


@dataclass(frozen=True)
class DataSourceConfigDTO:
    """数据源配置实体"""

    tushare_token: str | None = None
    tushare_http_url: str | None = None
    fred_api_key: str | None = None
    akshare_enabled: bool = True


@dataclass(frozen=True)
class SetupProgress:
    """安装进度实体"""

    current_step: WizardStep
    completed_steps: list[WizardStep] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def is_step_completed(self, step: WizardStep) -> bool:
        """检查步骤是否已完成"""
        return step in self.completed_steps

    def get_progress_percentage(self) -> int:
        """获取进度百分比"""
        all_steps = [
            WizardStep.WELCOME,
            WizardStep.ADMIN_PASSWORD,
            WizardStep.AI_PROVIDER,
            WizardStep.DATA_SOURCE,
            WizardStep.COMPLETE,
        ]
        completed_count = len([s for s in all_steps if s in self.completed_steps])
        return int((completed_count / len(all_steps)) * 100)


@dataclass(frozen=True)
class SetupState:
    """安装状态实体"""

    status: SetupStatus
    progress: SetupProgress | None = None
    admin_configured: bool = False
    ai_provider_configured: bool = False
    data_source_configured: bool = False

    def is_first_time_setup(self) -> bool:
        """是否首次安装"""
        return self.status == SetupStatus.NOT_INITIALIZED

    def requires_auth(self) -> bool:
        """是否需要认证才能继续"""
        return self.admin_configured
