"""
Celery configuration for AgomTradePro project.
"""

import os

from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.development')

app = Celery('agomtradepro')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()
app.autodiscover_tasks(
    lambda: [app_name for app_name in settings.INSTALLED_APPS if app_name.startswith("apps.")],
    related_name='application.tasks',
)

# ========== Prometheus 指标信号处理 ==========
# 导入 Celery 信号处理器，自动记录任务指标
# 必须在 Django setup 之后导入
try:
    from .celery_metrics import *  # noqa: F401, F403
except Exception:
    # 在 worker 启动时可能尚未 setup Django，忽略错误
    pass
