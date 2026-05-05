"""
Data Center — Page URL Patterns
"""

from django.urls import path
from django.views.generic import RedirectView

from apps.data_center.interface.views import (
    governance_page,
    monitor_page,
    providers_page,
    publishers_page,
)

urlpatterns = [
    path("", RedirectView.as_view(url="/data-center/governance/", permanent=False)),
    path("governance/", governance_page, name="dc-governance-page"),
    path("publishers/", publishers_page, name="dc-publishers-page"),
    path("providers/", providers_page, name="dc-providers-page"),
    path("monitor/", monitor_page, name="dc-monitor-page"),
]
