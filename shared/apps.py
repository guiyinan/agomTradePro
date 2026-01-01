from django.apps import AppConfig


class SharedConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'shared'
    verbose_name = '共享配置'

    def ready(self):
        """应用启动时初始化配置"""
        # 延迟导入避免循环依赖
        try:
            from .infrastructure.config_init import initialize_domain_config
            initialize_domain_config()
        except Exception:
            # 开发环境或数据库未迁移时可能失败，忽略
            pass
