from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.account'
    verbose_name = '账户管理'

    def ready(self):
        """
        应用启动时导入信号处理器和 Celery 任务
        """
        import apps.account.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.account.infrastructure.signals  # noqa: F401
