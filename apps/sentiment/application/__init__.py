from django.apps import AppConfig


class SentimentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sentiment'
    verbose_name = '舆情情感分析'

    def ready(self):
        """Import tasks module when app is ready"""
        import apps.sentiment.application.tasks  # noqa: F401 - Import Celery tasks

