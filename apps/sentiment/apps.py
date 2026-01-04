from django.apps import AppConfig


class SentimentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sentiment'
    verbose_name = '舆情情感分析'
