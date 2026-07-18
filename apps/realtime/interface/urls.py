"""Realtime page URL configuration."""

from django.urls import path
from django.views.generic import RedirectView

app_name = "realtime"

urlpatterns = [
    # Realtime operations live in the governed TUI workbench. Keep the legacy
    # page entry usable instead of exposing an empty URL namespace.
    path(
        "",
        RedirectView.as_view(url="/tui/#/realtime-monitor.alerts", permanent=False),
        name="home",
    ),
]
