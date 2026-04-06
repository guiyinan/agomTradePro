"""
Data Center — Page URL Patterns
"""

from django.urls import path
from django.views.generic import RedirectView

from apps.data_center.interface.views import monitor_page, providers_page

urlpatterns = [
    path("", RedirectView.as_view(url="/data-center/providers/", permanent=False)),
    path("providers/", providers_page, name="dc-providers-page"),
    path("monitor/", monitor_page, name="dc-monitor-page"),
]
