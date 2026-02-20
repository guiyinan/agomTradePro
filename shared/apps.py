from django.apps import AppConfig


class SharedConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shared'
    verbose_name = '共享配置'

    def ready(self):
        """应用启动时的初始化"""
        # Domain config initialization moved to apps.signal.apps.SignalConfig
        pass
