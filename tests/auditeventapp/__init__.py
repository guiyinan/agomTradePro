from django.apps import AppConfig


class AuditEventTestConfig(AppConfig):
    """Load only the schema-only canonical audit event model."""

    name = "tests.auditeventapp"
    label = "audit"
