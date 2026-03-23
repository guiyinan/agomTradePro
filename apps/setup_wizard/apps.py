"""
Setup Wizard App Configuration.
"""

from django.apps import AppConfig


class SetupWizardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.setup_wizard"
    verbose_name = "安装向导"

    def ready(self):
        """应用启动时执行"""
        pass
