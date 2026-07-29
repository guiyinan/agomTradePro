"""
ORM Models for Setup Wizard.

存储安装向导的状态和配置。
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models

from apps.setup_wizard.domain.entities import WizardStep


class SetupStateModel(models.Model):
    """
    安装状态模型

    记录系统是否已完成初始化设置。
    全局单例：系统中只应有一条记录。
    """

    is_completed = models.BooleanField(default=False, help_text="是否已完成初始化")
    admin_username = models.CharField(max_length=150, blank=True, help_text="创建的管理员用户名")
    admin_email = models.EmailField(blank=True, help_text="管理员邮箱")
    ai_provider_configured = models.BooleanField(default=False, help_text="是否已配置 AI Provider")
    data_source_configured = models.BooleanField(default=False, help_text="是否已配置数据源")
    current_step = models.CharField(max_length=50, default="welcome", help_text="当前步骤")
    completed_steps = models.JSONField(default=list, blank=True, help_text="已完成的步骤列表")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True, help_text="完成时间")

    class Meta:
        db_table = "setup_wizard_state"
        verbose_name = "安装向导状态"
        verbose_name_plural = "安装向导状态"

    def __str__(self) -> str:
        status = "已完成" if self.is_completed else "进行中"
        return f"安装向导 - {status}"

    @classmethod
    def get_instance(cls) -> "SetupStateModel":
        """
        获取全局单例实例

        如果不存在则创建一条新记录。
        """
        instance, _ = cls._default_manager.get_or_create(pk=1)
        return instance

    def clean(self) -> None:
        """Reject inconsistent or malformed singleton state evidence."""
        super().clean()
        valid_steps = {step.value for step in WizardStep}
        if self.current_step not in valid_steps:
            raise ValidationError({"current_step": "Unknown setup wizard step."})
        if not isinstance(self.completed_steps, list):
            raise ValidationError({"completed_steps": "Expected a list of setup steps."})
        if any(
            not isinstance(step, str) or step not in valid_steps for step in self.completed_steps
        ):
            raise ValidationError({"completed_steps": "Contains an unknown setup step."})
        if len(set(self.completed_steps)) != len(self.completed_steps):
            raise ValidationError({"completed_steps": "Setup steps must be unique."})
        if self.is_completed:
            if self.current_step != WizardStep.COMPLETE.value:
                raise ValidationError({"current_step": "Completed setup must be at complete."})
            if WizardStep.COMPLETE.value not in self.completed_steps:
                raise ValidationError(
                    {"completed_steps": "Completed setup must include the complete step."}
                )
            if self.completed_at is None:
                raise ValidationError({"completed_at": "Completed setup requires a timestamp."})
        elif self.completed_at is not None:
            raise ValidationError(
                {"completed_at": "Incomplete setup cannot have a completion timestamp."}
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist only the validated singleton setup record."""
        if self.pk not in (None, 1):
            raise ValidationError("Setup state is a singleton with primary key 1.")
        self.pk = 1
        self.full_clean()
        super().save(*args, **kwargs)
