"""
Django app configuration for share application.
"""
from django.apps import AppConfig


class ShareConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.share'
    verbose_name = '账户分享'
