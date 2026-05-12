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
        from apps.account.application.config_summary_service import (
            configure_account_config_summary_repository,
            get_account_config_summary_service,
        )
        from apps.account.application.documentation_use_cases import (
            configure_documentation_repository,
        )
        from apps.account.infrastructure.config_summary_repository import (
            DjangoAccountConfigSummaryRepository,
        )
        from apps.account.infrastructure.documentation_repository import (
            DjangoDocumentationRepository,
        )
        from core.integration.runtime_settings import (
            configure_runtime_settings_provider,
        )

        configure_account_config_summary_repository(DjangoAccountConfigSummaryRepository())
        configure_documentation_repository(DjangoDocumentationRepository())
        configure_runtime_settings_provider(get_account_config_summary_service())
