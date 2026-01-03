"""
Asset Analysis App Configuration
"""

from django.apps import AppConfig


class AssetAnalysisConfig(AppConfig):
    """资产分析应用配置"""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.asset_analysis'
    verbose_name = '通用资产分析'
