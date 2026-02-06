"""Rotation app configuration"""
from django.apps import AppConfig


class RotationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.rotation'
    verbose_name = '资产轮动'
