"""
ORM Models for Setup Wizard.

存储安装向导的状态和配置。
"""

from django.db import models


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

    def __str__(self):
        status = "已完成" if self.is_completed else "进行中"
        return f"安装向导 - {status}"

    @classmethod
    def get_instance(cls) -> "SetupStateModel":
        """
        获取全局单例实例

        如果不存在则创建一条新记录。
        """
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance
