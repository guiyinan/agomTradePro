"""Policy App Configuration"""
from django.apps import AppConfig


class PolicyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.policy'
    verbose_name = 'Policy Events'
