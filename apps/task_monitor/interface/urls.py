"""
Task Monitor URL Configuration

URL 路由定义。
"""

from django.urls import path
from apps.task_monitor.interface import views

app_name = "task_monitor"

urlpatterns = [
    # 任务状态
    path("status/<str:task_id>/", views.get_task_status, name="task_status"),
    path("list/", views.list_tasks, name="task_list"),
    path("statistics/", views.get_task_statistics, name="task_statistics"),
    path("dashboard/", views.dashboard, name="dashboard"),

    # Celery 健康检查
    path("celery/health/", views.health_check, name="celery_health"),
]
