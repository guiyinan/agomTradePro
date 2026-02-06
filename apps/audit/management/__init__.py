"""Audit App Configuration"""
from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.audit'
    verbose_name = 'Audit Reports'

    def ready(self):
        """Import admin module when app is ready"""
        import apps.audit.interface.admin  # noqa: F401

