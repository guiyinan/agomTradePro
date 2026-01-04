from django.apps import AppConfig


class SharedInterfaceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.shared.interface'
    verbose_name = '共享接口组件'
