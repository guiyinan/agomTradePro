from django.apps import AppConfig


class AuditSystemTestConfig(AppConfig):
    """Load only the system audit schema under the existing audit label."""

    name = "tests.auditsystemapp"
    label = "audit"
