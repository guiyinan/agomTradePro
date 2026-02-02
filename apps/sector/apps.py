from django.apps import AppConfig


class SectorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sector'
    verbose_name = '板块分析'

    def ready(self):
        """Import tasks module when app is ready"""
        import apps.sector.application.tasks  # noqa: F401 - Import Celery tasks
