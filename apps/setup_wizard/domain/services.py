"""
Domain services for Setup Wizard.

纯业务逻辑，不依赖任何外部框架。
"""

from typing import Optional
from .entities import (
    AdminConfig,
    AIProviderConfigDTO,
    DataSourceConfigDTO,
    SetupProgress,
    SetupState,
    SetupStatus,
    WizardStep,
)


class SetupValidator:
    """安装配置验证器（纯算法）"""

    @staticmethod
    def validate_admin_username(username: str) -> tuple[bool, str]:
        """
        验证管理员用户名

        Args:
            username: 用户名

        Returns:
            (is_valid, message): 验证结果
        """
        if not username or len(username) < 3:
            return False, "用户名长度至少 3 位"

        if not username[0].isalpha():
            return False, "用户名必须以字母开头"

        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
        if not all(c in allowed_chars for c in username):
            return False, "用户名只能包含字母、数字、下划线和连字符"

        return True, ""

    @staticmethod
    def validate_admin_email(email: Optional[str]) -> tuple[bool, str]:
        """
        验证管理员邮箱

        Args:
            email: 邮箱地址

        Returns:
            (is_valid, message): 验证结果
        """
        if not email:
            return True, ""

        if "@" not in email or "." not in email:
            return False, "邮箱格式不正确"

        return True, ""

    @staticmethod
    def validate_ai_provider_config(config: AIProviderConfigDTO) -> tuple[bool, str]:
        """
        验证 AI Provider 配置

        Args:
            config: AI Provider 配置

        Returns:
            (is_valid, message): 验证结果
        """
        if not config.name:
            return False, "配置名称不能为空"

        if not config.base_url:
            return False, "API Base URL 不能为空"

        if not config.api_key:
            return False, "API Key 不能为空"

        if not config.default_model:
            return False, "默认模型不能为空"

        return True, ""


class SetupProgressCalculator:
    """安装进度计算器（纯算法）"""

    @staticmethod
    def get_next_step(current: WizardStep) -> Optional[WizardStep]:
        """
        获取下一步骤

        Args:
            current: 当前步骤

        Returns:
            下一个步骤，如果是最后一步则返回 None
        """
        step_order = [
            WizardStep.WELCOME,
            WizardStep.ADMIN_PASSWORD,
            WizardStep.AI_PROVIDER,
            WizardStep.DATA_SOURCE,
            WizardStep.COMPLETE,
        ]

        try:
            current_index = step_order.index(current)
            if current_index < len(step_order) - 1:
                return step_order[current_index + 1]
            return None
        except ValueError:
            return None

    @staticmethod
    def get_previous_step(current: WizardStep) -> Optional[WizardStep]:
        """
        获取上一步骤

        Args:
            current: 当前步骤

        Returns:
            上一个步骤，如果是第一步则返回 None
        """
        step_order = [
            WizardStep.WELCOME,
            WizardStep.ADMIN_PASSWORD,
            WizardStep.AI_PROVIDER,
            WizardStep.DATA_SOURCE,
            WizardStep.COMPLETE,
        ]

        try:
            current_index = step_order.index(current)
            if current_index > 0:
                return step_order[current_index - 1]
            return None
        except ValueError:
            return None


class PasswordStrengthChecker:
    """密码强度检查器（纯算法）"""

    @staticmethod
    def check_strength(password: str) -> tuple[int, str, list[str]]:
        """
        检查密码强度

        Args:
            password: 密码

        Returns:
            (score, level, suggestions): 分数(0-100)、等级、改进建议
        """
        score = 0
        suggestions = []

        if len(password) >= 8:
            score += 20
        else:
            suggestions.append("密码长度至少 8 位")

        if len(password) >= 12:
            score += 10

        if any(c.islower() for c in password):
            score += 15
        else:
            suggestions.append("建议包含小写字母")

        if any(c.isupper() for c in password):
            score += 15
        else:
            suggestions.append("建议包含大写字母")

        if any(c.isdigit() for c in password):
            score += 15
        else:
            suggestions.append("建议包含数字")

        if any(c in "!@#$%^&*()_+-=[]{}|;:',.<>?" for c in password):
            score += 25
        else:
            suggestions.append("建议包含特殊字符")

        if score >= 80:
            level = "强"
        elif score >= 60:
            level = "中"
        elif score >= 40:
            level = "弱"
        else:
            level = "很弱"

        return score, level, suggestions
