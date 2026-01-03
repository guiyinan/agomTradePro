"""
基金分析模块 - Django App 配置
"""

from django.apps import AppConfig


class FundConfig(AppConfig):
    """基金分析模块配置"""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.fund'
    verbose_name = '基金分析模块'

    def ready(self):
        """应用启动时执行"""
        # 导入信号处理（如果需要）
        pass
