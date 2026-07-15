"""Policy App Configuration"""

from django.apps import AppConfig


class PolicyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.policy"
    verbose_name = "Policy Events"

    def ready(self) -> None:
        """Import admin and tasks modules when app is ready"""
        import apps.policy.application.tasks  # noqa: F401 - Import Celery tasks
        import apps.policy.interface.admin  # noqa: F401
        from apps.policy.infrastructure.account_gateway import register_policy_account_gateway

        register_policy_account_gateway()
