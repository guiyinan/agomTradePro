"""
Decision Rhythm Django App Configuration
"""

from django.apps import AppConfig


class DecisionRhythmConfig(AppConfig):
    """Decision Rhythm 模块配置"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.decision_rhythm"
    verbose_name = "决策频率约束"

    def ready(self):
        """应用启动时初始化"""
        # 导入信号处理
        try:
            from .application import handlers  # noqa
        except ImportError:
            pass
