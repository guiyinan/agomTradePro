from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.account"
    verbose_name = "账户管理"

    def ready(self):
        """
        应用启动时导入信号处理器和 Celery 任务
        """
        import apps.account.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.account.infrastructure.signals  # noqa: F401
        import apps.account.interface.openapi  # noqa: F401 - Register OpenAPI extensions
        from apps.account.application.config_summary_service import (
            configure_account_config_summary_repository,
        )
        from apps.account.application.documentation_use_cases import (
            configure_documentation_repository,
        )
        from apps.account.application.interface_services import (
            get_active_access_token,
            touch_access_token,
        )
        from apps.account.application.repository_provider import (
            get_account_position_repository,
        )
        from apps.account.infrastructure.config_summary_repository import (
            DjangoAccountConfigSummaryRepository,
        )
        from apps.account.infrastructure.documentation_repository import (
            DjangoDocumentationRepository,
        )
        from core.integration.account_access_registry import (
            register_access_token_provider,
        )
        from core.integration.policy_hedging_registry import (
            register_position_repository_factory,
        )

        configure_account_config_summary_repository(DjangoAccountConfigSummaryRepository())
        configure_documentation_repository(DjangoDocumentationRepository())
        register_access_token_provider(
            reader=get_active_access_token,
            toucher=touch_access_token,
        )
        register_position_repository_factory(get_account_position_repository)
