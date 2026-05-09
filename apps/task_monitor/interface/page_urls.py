from django.urls import path

from apps.task_monitor.interface.page_views import scheduler_console_view

app_name = "task_monitor_pages"

urlpatterns = [
    path("", scheduler_console_view, name="scheduler_console"),
]
